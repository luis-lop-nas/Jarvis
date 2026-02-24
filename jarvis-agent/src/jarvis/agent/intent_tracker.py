"""
intent_tracker.py

Multi-step intent resolution across conversation turns.

When the LLM detects an action request with incomplete parameters,
this tracker:
  1. Intercepts tool calls with missing required params
  2. Generates natural questions for each missing param
  3. Tracks collected params across turns
  4. Injects collected context into subsequent user prompts
  5. Signals the daemon to use an extended follow-up window (30 s vs 6 s)

Two detection paths:
  A) Structural — LLM calls a tool with missing required params:
     intercepted before execution; a question is returned to the user.
  B) Conversational — LLM response ends with a question (no tool call yet):
     detected from response text; follow-up window is extended.

Both paths make ``is_pending()`` return True, signalling the daemon to:
  - Use a 30 s follow-up window instead of the default 6 s
  - Inject collected-params context into the next user message
  - Show a status line in the HUD
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.tools.registry import ToolRegistry


# ── Human-readable questions for common tool params ───────────────────────────

_TOOL_PARAM_QUESTIONS: Dict[str, Dict[str, str]] = {
    "send_email": {
        "to": "¿A quién quieres enviarlo?",
        "subject": "¿Cuál es el asunto?",
        "body": "¿Qué quieres decir en el mensaje?",
    },
    "open_app": {
        "app": "¿Qué aplicación quieres abrir?",
        "target": "¿Qué archivo o URL quieres abrir?",
    },
    "web_search": {
        "query": "¿Qué quieres buscar?",
    },
    "download_file": {
        "url": "¿Cuál es la URL del archivo a descargar?",
    },
    "search_and_download": {
        "query": "¿Qué quieres buscar y descargar?",
    },
    "run_code": {
        "language": "¿En qué lenguaje? ¿Python o Node.js?",
        "code": "¿Cuál es el código que quieres ejecutar?",
    },
    "shell": {
        "command": "¿Qué comando quieres ejecutar?",
    },
    "weather": {
        "city": "¿De qué ciudad quieres ver el tiempo?",
    },
    "filesystem": {
        "action": "¿Qué acción: leer, escribir, listar, borrar o renombrar?",
        "path": "¿Cuál es la ruta del archivo o carpeta?",
    },
    "calendar": {
        "action": "¿Qué quieres hacer: ver hoy, mañana, la semana, o crear un evento?",
    },
    "spotify": {
        "action": "¿Qué quieres hacer con Spotify: play, pausa, siguiente o anterior?",
    },
    "vision": {
        "action": "¿Qué quieres hacer con la pantalla: describir, responder, leer o contexto?",
    },
    "knowledge": {
        "action": "¿Qué quieres hacer: buscar, añadir, listar o eliminar?",
    },
    "system_info": {
        "action": "¿Qué información quieres: CPU, RAM, disco, batería, red o procesos?",
    },
    "code_assistant": {
        "task": "¿Qué código quieres que genere?",
    },
}

_GENERIC_PARAM_QUESTIONS: Dict[str, str] = {
    "to": "¿Para quién?",
    "subject": "¿Cuál es el asunto?",
    "body": "¿Cuál es el contenido?",
    "query": "¿Qué quieres buscar?",
    "command": "¿Qué comando?",
    "url": "¿Cuál es la URL?",
    "path": "¿Cuál es la ruta?",
    "content": "¿Cuál es el contenido?",
    "app": "¿Qué aplicación?",
    "city": "¿Qué ciudad?",
    "action": "¿Qué acción quieres realizar?",
    "task": "¿Cuál es la tarea?",
    "code": "¿Cuál es el código?",
    "language": "¿En qué lenguaje?",
}


# ── Data ──────────────────────────────────────────────────────────────────────

@dataclass
class PendingIntent:
    """Active parameter-collection state for a specific tool."""

    tool_name: str
    required_params: List[str]
    collected: Dict[str, Any] = field(default_factory=dict)
    current_param: Optional[str] = None  # param currently being asked for

    @property
    def missing(self) -> List[str]:
        """Params that are still needed."""
        return [
            p for p in self.required_params
            if not self.collected.get(p) or str(self.collected[p]).strip() == ""
        ]

    @property
    def is_complete(self) -> bool:
        return len(self.missing) == 0


# ── IntentTracker ─────────────────────────────────────────────────────────────

class IntentTracker:
    """
    Session-level tracker for multi-step intent resolution.

    Usage in the agent loop (tool_agent.py):
        question = self.intent_tracker.check_tool_call(name, args, registry)
        if question:
            # params missing — return question to user, don't execute yet
            return question
        tool_out = self.registry.call(name, args)
        self.intent_tracker.on_tool_executed(name)

    Usage in the daemon (_process_text):
        # Before calling agent.run():
        self.agent.intent_tracker.check_user_cancel(text)
        intent_ctx = self.agent.intent_tracker.get_context_injection()
        # After agent.run():
        self.agent.intent_tracker.analyze_llm_response(response)
        # In _try_followup:
        timeout = self.agent.intent_tracker.get_followup_timeout(default)
    """

    # Extended follow-up when collecting params
    COLLECTING_TIMEOUT_S: float = 30.0

    # Detect if a response ends with a question
    _RE_ENDS_QUESTION = re.compile(r"[?]\s*$")

    # Detect cancel intent from user
    _RE_CANCEL = re.compile(
        r"\b(cancela?r?|olvida?r?lo?|deja?r?lo?|no\s+importa|"
        r"abort[ae]?r?|nada|deja\s+estar)\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self._pending: Optional[PendingIntent] = None
        # True when LLM asked a question without calling a tool
        self._dialog_mode: bool = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def is_pending(self) -> bool:
        """True when actively collecting parameters."""
        return self._pending is not None or self._dialog_mode

    def get_followup_timeout(self, default: float = 6.0) -> float:
        """Returns the follow-up window to use. Extended when collecting params."""
        return self.COLLECTING_TIMEOUT_S if self.is_pending() else default

    def get_status_text(self) -> Optional[str]:
        """Short text for HUD display during collection."""
        if self._pending:
            missing_str = ", ".join(self._pending.missing[:3])
            return f"⚙ Completando: {self._pending.tool_name} — falta: {missing_str}"
        if self._dialog_mode:
            return "⚙ Esperando tu respuesta..."
        return None

    def get_context_injection(self) -> Optional[str]:
        """
        Returns a context string to prepend to the next user message so the
        LLM remembers which tool it was targeting and what params it has so far.
        Returns None when no structural pending intent exists.
        """
        if not self._pending:
            return None
        p = self._pending
        collected_parts = [
            f"{k}={repr(v)}"
            for k, v in p.collected.items()
            if v and str(v).strip()
        ]
        collected_str = ", ".join(collected_parts) or "ninguno aún"
        missing_str = ", ".join(p.missing)
        return (
            f"[Intent pendiente: herramienta={p.tool_name} | "
            f"parámetros ya recopilados: {collected_str} | "
            f"parámetros que faltan: {missing_str}]"
        )

    def check_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        registry: "ToolRegistry",
    ) -> Optional[str]:
        """
        Called BEFORE executing a tool in the agent loop.

        Returns:
            None  → all required params present; proceed with execution.
            str   → natural-language question for the user; do NOT execute yet.

        When returning a question, the caller should return that question as the
        assistant response and let the daemon handle the next user turn.
        """
        spec = registry.list().get(tool_name)
        if not spec or not spec.schema:
            return None

        required = self._required_params(spec)
        if not required:
            return None

        # Merge previously collected params with the new call's args
        merged: Dict[str, Any] = {}
        if self._pending and self._pending.tool_name == tool_name:
            merged.update(self._pending.collected)
        merged.update({
            k: v for k, v in args.items()
            if v is not None and str(v).strip() != ""
        })

        missing = [
            p for p in required
            if not merged.get(p) or str(merged[p]).strip() == ""
        ]

        if not missing:
            # All required params present — clear any pending intent for this tool
            if self._pending and self._pending.tool_name == tool_name:
                self._pending = None
            self._dialog_mode = False
            return None  # proceed with execution

        # Update or create pending intent
        if self._pending and self._pending.tool_name == tool_name:
            self._pending.collected.update(merged)
            self._pending.current_param = missing[0]
        else:
            self._pending = PendingIntent(
                tool_name=tool_name,
                required_params=required,
                collected=merged,
                current_param=missing[0],
            )
        self._dialog_mode = False  # structural detection takes priority
        return self._make_question(tool_name, missing[0], spec)

    def analyze_llm_response(self, response: str) -> None:
        """
        Called AFTER agent.run() returns.
        Detects conversational param-collection mode: the LLM asked a question
        back to the user instead of (or before) calling a tool.
        """
        clean = response.strip()
        if self._RE_ENDS_QUESTION.search(clean):
            # LLM asked a question → enter dialog mode unless structural pending exists
            if not self._pending:
                self._dialog_mode = True
        else:
            # LLM gave a statement → intent is resolved (or was never active)
            if not self._pending:
                self._dialog_mode = False

    def check_user_cancel(self, user_text: str) -> bool:
        """
        Returns True if the user wants to cancel any pending intent.
        Clears state when True so subsequent processing runs without context.
        Input is normalised (accent marks stripped) before matching so that
        e.g. "olvídalo" and "déjalo" are detected reliably.
        """
        normalized = self._strip_accents(user_text)
        if self._RE_CANCEL.search(normalized):
            self.cancel()
            return True
        return False

    def on_tool_executed(self, tool_name: str) -> None:
        """Called after a tool is successfully executed. Clears matching intent."""
        if self._pending and self._pending.tool_name == tool_name:
            self._pending = None
        self._dialog_mode = False

    def cancel(self) -> None:
        """Cancels any active pending intent."""
        self._pending = None
        self._dialog_mode = False

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _strip_accents(text: str) -> str:
        """Remove combining accent marks so regex \b works on Spanish words."""
        return "".join(
            c for c in unicodedata.normalize("NFD", text)
            if unicodedata.category(c) != "Mn"
        )

    @staticmethod
    def _required_params(spec: Any) -> List[str]:
        """Extracts required param names from a ToolSpec."""
        return [
            fname
            for fname, desc in (spec.schema or {}).items()
            if "obligatorio" in str(desc).lower()
        ]

    @classmethod
    def _make_question(cls, tool_name: str, param: str, spec: Any) -> str:
        """Generates a natural question for a missing required param."""
        # Tool-specific question
        tool_qs = _TOOL_PARAM_QUESTIONS.get(tool_name, {})
        if param in tool_qs:
            return tool_qs[param]
        # Generic by param name
        if param in _GENERIC_PARAM_QUESTIONS:
            return _GENERIC_PARAM_QUESTIONS[param]
        # Fallback: derive from schema description
        if spec and spec.schema and param in spec.schema:
            desc = str(spec.schema[param])
            desc_clean = re.sub(
                r"\s*\(obligatorio\)", "", desc, flags=re.IGNORECASE
            ).strip()
            return f"¿{desc_clean.capitalize()}?"
        return f"¿Puedes especificar '{param}'?"
