"""
tool_agent.py

Agente con Claude Sonnet 4.6 como cerebro principal.
- Claude maneja conversación + tool use nativo (sin Ollama)
- Fallback a Groq si Claude no está configurado
- Fallback a Ollama si ninguno está disponible
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import queue as queue_module
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

import requests
from pydantic import ValidationError

from jarvis.agent.confirm_policy import (
    extract_confirm_token,
    is_affirmative,
    is_confirmation_reply,
    is_negative,
)
from jarvis.agent.dry_run import build_preview, build_summary, infer_risk, is_sensitive
from jarvis.agent.intent_tracker import IntentTracker
from jarvis.agent.prompt_guard import scan_tool_args
from jarvis.agent.pending_actions import PendingActionStore
from jarvis.agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_GROQ
from jarvis.agent.runner import AgentConfig
from jarvis.agent.state import AgentState, truncate_history
from jarvis.agent.verifier import VerifyContext, verify
from jarvis.tools.schemas.base import normalize_tool_output
from jarvis.tools.schemas.errors import build_validation_error_payload
from jarvis.tools.shell_guard import analyze_shell_command
from jarvis.tools.registry import ToolRegistry, build_default_registry

_logger = logging.getLogger(__name__)


Message = Dict[str, Any]

# ── Streaming TTS: helpers de segmentación de frases ─────────────────────────

_RE_SENT_SEP = re.compile(r"(?<=[.!?…])\s+")


def _emit_sentences(
    buffer: str,
    on_sentence: Callable[[str], None],
    first_emitted: List[bool],
    min_chars: int = 50,
) -> str:
    """
    Divide el buffer en frases completas (según separadores .!?…) y llama
    on_sentence() para cada una que esté lista.

    - La primera frase se emite en cuanto termina (sin esperar min_chars).
    - Las siguientes se acumulan hasta alcanzar min_chars antes de emitir.
    - Retorna el fragmento restante (frase incompleta al final del buffer).
    """
    parts = _RE_SENT_SEP.split(buffer)
    if len(parts) <= 1:
        return buffer

    accumulated = ""
    for part in parts[:-1]:
        part = part.strip()
        if not part:
            continue
        accumulated = f"{accumulated} {part}".strip() if accumulated else part
        should_emit = (not first_emitted[0]) or (len(accumulated) >= min_chars)
        if should_emit:
            on_sentence(accumulated)
            first_emitted[0] = True
            accumulated = ""

    remainder = parts[-1]
    if accumulated:
        remainder = (
            f"{accumulated} {remainder}".strip() if remainder.strip() else accumulated
        )
    return remainder


@dataclass
class ToolAgentConfig(AgentConfig):
    max_tool_loops: int = 8
    # Claude (principal)
    use_claude: bool = False
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    # Gemini
    use_gemini: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    # Groq (fallback conversación)
    use_groq: bool = False
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    # Ollama (último fallback)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    # Memoria
    session_id: Optional[str] = None
    enable_memory: bool = True
    # Dry-run
    dry_run_enabled: bool = True
    dry_run_ttl_seconds: int = 120
    dry_run_always_for: List[str] = field(default_factory=list)
    dry_run_max_items_list: int = 20
    dry_run_snippet_chars: int = 300
    # Backward compatibility
    confirm_policy_enabled: bool = True
    confirm_ttl_seconds: int = 120
    confirm_always_for: List[str] = field(default_factory=list)
    # Shell guard
    shell_guard_enabled: bool = True
    shell_guard_mode: str = "strict"
    shell_deny_patterns: List[str] = field(default_factory=list)
    shell_confirm_patterns: List[str] = field(default_factory=list)
    # Verifier
    verifier_enabled: bool = True
    verifier_timeout_ms: int = 1500
    verifier_max_items: int = 50
    verifier_sample_if_over: int = 200
    verifier_strict: bool = False
    # Tool schema validation
    tool_schema_validation_enabled: bool = True
    tool_schema_strict: bool = True
    tool_schema_log_invalid: bool = False
    # PEV Pipeline
    pev_enabled: bool = False
    pev_max_steps: int = 6
    pev_retry_max: int = 1
    pev_state_ttl_seconds: int = 600
    pev_verbose_trace: bool = False


class ToolAgent:
    def __init__(
        self,
        config: ToolAgentConfig,
        registry: Optional[ToolRegistry] = None,
        state: Optional[AgentState] = None,
        memory_store: Optional[Any] = None,
        confirm_context: Optional[Any] = None,
    ):
        self.config = config
        self.registry = registry or build_default_registry()
        self.state = state or AgentState()
        self.memory_store = memory_store
        self._confirm_context = confirm_context or {
            "project_root": Path.cwd(),
            "data_dir": Path.cwd() / "data",
        }
        self._pending_actions = PendingActionStore(ttl_seconds=self.config.dry_run_ttl_seconds)

        if self.memory_store and self.config.enable_memory and not self.config.session_id:
            self.config.session_id = self.memory_store.create_session()
            if self.config.debug:
                print(f"📝 Nueva sesión: {self.config.session_id[:8]}...")

        # Inicializar Claude
        self.claude_client = None
        if self.config.use_claude and self.config.claude_api_key:
            try:
                from anthropic import Anthropic
                self.claude_client = Anthropic(api_key=self.config.claude_api_key)
                print(f"✅ Claude {self.config.claude_model} activado (conversación + tools)")
                if self.memory_store:
                    print("✅ Memoria persistente activada")
            except ImportError:
                print("⚠️ 'anthropic' no instalado. pip install anthropic")

        # Inicializar Gemini
        self.gemini_client = None
        if self.config.use_gemini and self.config.gemini_api_key:
            try:
                from google import genai
                self.gemini_client = genai.Client(api_key=self.config.gemini_api_key)
                if not self.claude_client:
                    print(f"✅ Gemini {self.config.gemini_model} activado")
            except ImportError:
                print("⚠️ 'google-genai' no instalado. pip install google-genai")

        # Inicializar Groq (fallback o STT)
        self.groq_client = None
        if self.config.use_groq and self.config.groq_api_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=self.config.groq_api_key)
                if not self.claude_client:
                    print("✅ Groq activado como LLM principal")
            except ImportError:
                print("⚠️ Librería 'groq' no instalada.")

        # Multi-step intent tracker (shared across all backends)
        self.intent_tracker = IntentTracker()

        # Pre-computar schemas de tools (inmutables durante la vida del agente)
        self._cached_claude_tools = self._tools_for_claude()
        self._cached_ollama_tools = self._tools_for_ollama()
        self._cached_gemini_tools = self._tools_for_gemini() if self.gemini_client else []

    # ------------------------------------------------------------------
    # Memoria
    # ------------------------------------------------------------------

    def _save_message(self, role: str, content: str) -> None:
        if self.memory_store and self.config.enable_memory and self.config.session_id:
            try:
                self.memory_store.add_message(
                    session_id=self.config.session_id,
                    role=role,
                    content=content,
                )
            except Exception as e:
                if self.config.debug:
                    print(f"⚠️ Error guardando mensaje: {e}")

    def _save_tool_event(self, tool_name: str, tool_args: Dict, tool_result: Dict) -> None:
        if self.memory_store and self.config.enable_memory and self.config.session_id:
            try:
                self.memory_store.add_tool_event(
                    session_id=self.config.session_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=tool_result,
                )
            except Exception as e:
                if self.config.debug:
                    print(f"⚠️ Error guardando tool event: {e}")

    def _verify_tool_result(self, tool_name: str, tool_args: Dict[str, Any], tool_out: Dict[str, Any]) -> Dict[str, Any]:
        if not self.config.verifier_enabled:
            return tool_out

        vctx = VerifyContext(
            timeout_ms=self.config.verifier_timeout_ms,
            max_items=self.config.verifier_max_items,
            sample_if_over=self.config.verifier_sample_if_over,
            strict=self.config.verifier_strict,
            turn_id=self.config.session_id,
        )
        report = verify(tool_name, tool_args, tool_out, vctx)
        report_dict = {
            "status": report.status,
            "reason": report.reason,
            "details": report.details,
            "suggested_fix": report.suggested_fix,
            "evidence": report.evidence,
            "retryable": report.retryable,
        }
        critical_tools = {
            "filesystem",
            "shell",
            "calendar",
            "send_email",
            "send_message",
            "download_file",
            "search_and_download",
            "open_app",
            "web_agent",
        }
        status = report.status
        if status == "unknown" and self.config.verifier_strict and tool_name in critical_tools:
            status = "fail"
            report_dict["reason"] = (
                f"{report.reason} (VERIFIER_STRICT=true: unknown tratado como fail)."
            )

        if status == "fail":
            return {
                "ok": False,
                "type": "action_failed",
                "tool": tool_name,
                "verify_report": report_dict,
                "tool_result": tool_out,
            }

        out = tool_out if isinstance(tool_out, dict) else {"result": tool_out}
        out["verify_report"] = report_dict
        out["verified"] = status == "ok"
        return out

    def _validate_tool_input(self, tool_name: str, tool_args: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not self.config.tool_schema_validation_enabled:
            return tool_args, None
        spec = self.registry.get(tool_name)
        if not spec or spec.input_model is None:
            return tool_args, None
        try:
            parsed = spec.input_model.model_validate(tool_args)
            return parsed.model_dump(exclude_none=True), None
        except ValidationError as e:
            return None, build_validation_error_payload(
                tool=tool_name,
                stage="input",
                err=e,
                message="Faltan campos o el formato de entrada es inválido.",
                include_raw=False,
            )

    def _validate_tool_output(self, tool_name: str, raw_output: Any) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        normalized = normalize_tool_output(tool_name, raw_output)
        if not self.config.tool_schema_validation_enabled:
            return normalized, None
        spec = self.registry.get(tool_name)
        if not spec or spec.output_model is None:
            return normalized, None
        try:
            parsed = spec.output_model.model_validate(normalized)
            return parsed.model_dump(exclude_none=True), None
        except ValidationError as e:
            payload = build_validation_error_payload(
                tool=tool_name,
                stage="output",
                err=e,
                message="La tool devolvió un resultado inesperado.",
                raw_output=normalized,
                include_raw=self.config.tool_schema_log_invalid,
            )
            if self.config.tool_schema_strict:
                return None, payload
            normalized["schema_warning"] = payload
            return normalized, None

    def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        # Escanear args en busca de patrones de inyección antes de ejecutar
        inj = scan_tool_args(tool_name, tool_args)
        if inj.detected:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "prompt_guard: %s en tool '%s'", inj.message, tool_name
            )
            if inj.risk_level == "high":
                return {
                    "ok": False,
                    "type": "injection_blocked",
                    "error": (
                        "Petición bloqueada: se detectó un patrón de inyección "
                        "en los argumentos de la tool."
                    ),
                }

        validated_args, input_err = self._validate_tool_input(tool_name, tool_args)
        if input_err is not None:
            return input_err
        args_to_use = validated_args if validated_args is not None else tool_args

        raw_tool_out = self.registry.call(tool_name, args_to_use)
        normalized_out, output_err = self._validate_tool_output(tool_name, raw_tool_out)
        if output_err is not None:
            return output_err

        tool_out = normalized_out if normalized_out is not None else normalize_tool_output(tool_name, raw_tool_out)
        verified_out = self._verify_tool_result(tool_name, args_to_use, tool_out)
        self.intent_tracker.on_tool_executed(tool_name)
        self._save_tool_event(tool_name, args_to_use, verified_out)
        return verified_out

    def _run_tool_calls_parallel(
        self,
        tool_calls: List[Tuple[Optional[str], str, Optional[str]]],
    ) -> List[Tuple[Optional[str], Dict[str, Any]]]:
        """
        Ejecuta una lista de (tc_id, tool_name, args_json) en paralelo si hay >1.
        Devuelve [(tc_id, tool_out), ...] en el mismo orden que la entrada.
        """
        def _run_one(item: Tuple[Optional[str], str, Optional[str]]) -> Tuple[Optional[str], Dict[str, Any]]:
            tc_id, name, args_json = item
            try:
                args = json.loads(args_json or "{}")
            except Exception:
                args = {}
            return tc_id, self._execute_tool(name, args)

        if len(tool_calls) <= 1:
            return [_run_one(tc) for tc in tool_calls]

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
            futures = [pool.submit(_run_one, tc) for tc in tool_calls]
            return [f.result() for f in futures]

    # ------------------------------------------------------------------
    # Dry-run policy
    # ------------------------------------------------------------------

    @property
    def has_pending_confirmation(self) -> bool:
        return self._pending_actions.has_pending()

    def _render_dry_run_prompt(self, payload: Dict[str, Any]) -> str:
        if payload.get("type") == "deny":
            return (
                f"⛔ Bloqueado por seguridad: {payload.get('reason', 'Comando denegado')}\n"
                "Sugerencia: indica una ruta/acción específica y segura para continuar."
            )
        risk = str(payload.get("risk_level") or "medium").upper()
        details = payload.get("details") or {}
        return (
            f"⚠️ {payload.get('summary', 'Acción sensible')}\n"
            f"Motivo: {payload.get('reason', 'Requiere confirmación')}\n"
            f"Riesgo: {risk}\n"
            f"Detalles: {json.dumps(details, ensure_ascii=False)}\n"
            f"Token: {payload.get('confirm_token', '')}\n"
            "Responde 'sí' o 'confirmar <token>' para continuar, "
            "o 'no'/'cancelar' para descartar. ¿Confirmas?"
        )

    def _handle_confirmation_turn(self, user_text: str) -> Optional[str]:
        self._pending_actions.cleanup_expired()
        if not is_confirmation_reply(user_text):
            return None
        if not self._pending_actions.has_pending():
            return "No hay ninguna acción pendiente para confirmar o cancelar."

        token = extract_confirm_token(user_text)

        if is_negative(user_text):
            pending = self._pending_actions.cancel(token)
            if not pending:
                return "No hay ninguna acción pendiente para cancelar."
            return f"Cancelado: {pending.summary}"

        if is_affirmative(user_text):
            pending = self._pending_actions.confirm(token)
            if not pending:
                return "No hay ninguna acción pendiente para confirmar o ya expiró."

            tool_out = self._execute_tool(pending.tool_name, dict(pending.args))
            if tool_out.get("ok", True):
                return f"Hecho: {pending.summary}\nResultado: {json.dumps(tool_out, ensure_ascii=False)}"
            return (
                f"Intenté ejecutar '{pending.tool_name}', pero falló:\n"
                f"{json.dumps(tool_out, ensure_ascii=False)}"
            )
        return None

    def _maybe_build_dry_run(self, tool_name: str, tool_args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        enabled = self.config.dry_run_enabled and self.config.confirm_policy_enabled
        if not enabled:
            return None
        always_for = set(str(t).strip().lower() for t in (self.config.dry_run_always_for or []) if str(t).strip())
        shell_mode = self.config.shell_guard_mode
        shell_deny = self.config.shell_deny_patterns
        shell_confirm = self.config.shell_confirm_patterns
        if tool_name == "shell" and self.config.shell_guard_enabled:
            shell_decision = analyze_shell_command(
                str(tool_args.get("command", "")).strip(),
                cwd=str(tool_args.get("cwd", "") or ""),
                mode=shell_mode,
                deny_patterns=shell_deny,
                confirm_patterns=shell_confirm,
            )
            if shell_decision.decision == "deny":
                return {
                    "type": "deny",
                    "requires_confirmation": False,
                    "risk_level": shell_decision.risk_level,
                    "summary": f"Bloqueado por seguridad: {shell_decision.normalized_command}",
                    "reason": shell_decision.reason,
                    "details": {
                        "command": shell_decision.normalized_command,
                        "cwd": str(tool_args.get("cwd", "") or ""),
                        "rules": shell_decision.matches,
                    },
                    "confirm_token": "",
                }

        if not is_sensitive(
            tool_name,
            tool_args,
            always_for=always_for,
            shell_guard_mode=shell_mode,
            shell_deny_patterns=shell_deny,
            shell_confirm_patterns=shell_confirm,
        ):
            return None

        summary = build_summary(tool_name, tool_args)
        details = build_preview(
            tool_name,
            tool_args,
            max_items=self.config.dry_run_max_items_list,
            snippet_chars=self.config.dry_run_snippet_chars,
            shell_guard_mode=shell_mode,
            shell_deny_patterns=shell_deny,
            shell_confirm_patterns=shell_confirm,
        )
        reason = str(details.get("guard_reason", "")).strip() if tool_name == "shell" else ""
        if not reason:
            reason = "Acción sensible; requiere confirmación explícita."
        risk_level = infer_risk(
            tool_name,
            tool_args,
            shell_guard_mode=shell_mode,
            shell_deny_patterns=shell_deny,
            shell_confirm_patterns=shell_confirm,
        )

        pending = self._pending_actions.put(
            tool_name=tool_name,
            args=tool_args,
            summary=summary,
            reason=reason,
            details=details,
            risk_level=risk_level,
        )
        return {
            "type": "dry_run",
            "requires_confirmation": True,
            "confirm_token": pending.confirm_token,
            "summary": pending.summary,
            "reason": pending.reason,
            "risk_level": pending.risk_level,
            "details": pending.details,
        }

    # ------------------------------------------------------------------
    # Schema de herramientas
    # ------------------------------------------------------------------

    def _tools_for_claude(self) -> List[Dict[str, Any]]:
        """Schema de tools en formato Anthropic."""
        tools: List[Dict[str, Any]] = []

        for name, spec in self.registry.list().items():
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for field_name, desc in (spec.schema or {}).items():
                desc_str = str(desc)
                ftype = "string"
                if "int" in desc_str.lower():
                    ftype = "integer"
                elif "bool" in desc_str.lower():
                    ftype = "boolean"

                properties[field_name] = {
                    "type": ftype,
                    "description": desc_str,
                }

                if "obligatorio" in desc_str.lower():
                    required.append(field_name)

            input_schema: Dict[str, Any] = {
                "type": "object",
                "properties": properties,
            }
            if required:
                input_schema["required"] = required

            tools.append({
                "name": spec.name,
                "description": spec.description,
                "input_schema": input_schema,
            })

        return tools

    @staticmethod
    def _field_type(desc_str: str) -> str:
        """Detecta el tipo JSON de un campo a partir de su descripción."""
        import re
        dl = desc_str.lower()
        # Booleano
        if "bool" in dl:
            return "boolean"
        # Entero — búsqueda por palabra completa para evitar falsos positivos
        # (e.g., "int" dentro de "inteligente")
        _INT_RE = re.compile(
            r"\b(int(eger)?|n[úu]mero|segundos|timeout|top_n|l[íi]mit|"
            r"cantidad|count|d[íi]as?|days?)\b"
        )
        if _INT_RE.search(dl):
            return "integer"
        return "string"

    def _tools_for_ollama(self) -> List[Dict[str, Any]]:
        """Schema de tools en formato OpenAI/Groq/Ollama."""
        tools: List[Dict[str, Any]] = []

        for name, spec in self.registry.list().items():
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for field_name, desc in (spec.schema or {}).items():
                desc_str = str(desc)
                properties[field_name] = {
                    "type": self._field_type(desc_str),
                    "description": desc_str,
                }
                if "obligatorio" in desc_str.lower():
                    required.append(field_name)

            # No incluir "required" vacío — algunos modelos lo usan mal
            params: Dict[str, Any] = {"type": "object"}
            if properties:
                params["properties"] = properties
            if required:
                params["required"] = required

            tools.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": params,
                },
            })

        return tools

    # ------------------------------------------------------------------
    # Historial para Claude (solo user/assistant con content string)
    # ------------------------------------------------------------------

    def _build_claude_messages(self) -> List[Message]:
        """Filtra el historial para Claude (solo user/assistant con texto, truncado)."""
        history = truncate_history(self.state.history, max_messages=20)
        messages: List[Message] = []
        for msg in history:
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                messages.append({"role": role, "content": content})
        return messages

    # ------------------------------------------------------------------
    # Motor Claude
    # ------------------------------------------------------------------

    def _run_with_claude(self, user_text: str) -> str:
        """Claude como cerebro único: conversación + tools nativo."""
        import hashlib
        import json as _json

        messages = self._build_claude_messages()
        tools = self._cached_claude_tools

        _loop_start = time.monotonic()
        _MAX_LOOP_SECONDS = 60.0
        _last_tool_sig: Optional[str] = None

        for loop_count in range(self.config.max_tool_loops):
            # Timeout global del bucle
            if time.monotonic() - _loop_start > _MAX_LOOP_SECONDS:
                text = "Tiempo máximo de procesamiento alcanzado."
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text

            try:
                response = self.claude_client.messages.create(
                    model=self.config.claude_model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    messages=messages,
                )
            except Exception as e:
                err = f"Error Claude API: {e}"
                if self.config.debug:
                    print(f"⚠️ {err}")
                # Intentar fallback a Groq
                if self.groq_client:
                    return self._run_with_groq_simple(user_text)
                self.state.add_assistant(err)
                self._save_message("assistant", err)
                return err

            stop_reason = response.stop_reason

            # Respuesta final (sin tool use)
            if stop_reason == "end_turn":
                text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text += block.text
                text = text.strip() or "No generé respuesta."
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text

            # Claude quiere usar herramientas
            if stop_reason == "tool_use":
                # Añadir respuesta de Claude al historial
                messages.append({"role": "assistant", "content": response.content})

                # Ejecutar todas las herramientas
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_args = block.input

                        if self.config.debug:
                            print(f"🔧 Claude usa: {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:80]})")

                        # Check for missing required params before executing
                        question = self.intent_tracker.check_tool_call(
                            tool_name, tool_args, self.registry
                        )
                        if question:
                            # Params missing — send a synthetic tool_result so Claude
                            # stays in a valid conversation state and asks the user.
                            if self.config.debug:
                                print(f"⏳ Intent pendiente ({tool_name}): {question}")
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({
                                    "ok": False,
                                    "error": (
                                        f"Parámetros obligatorios faltantes. "
                                        f"Pregunta al usuario: {question}"
                                    ),
                                }, ensure_ascii=False),
                            })
                            continue  # don't execute the tool

                        confirm_evt = self._maybe_build_dry_run(tool_name, tool_args)
                        if confirm_evt:
                            text = self._render_dry_run_prompt(confirm_evt)
                            self.state.add_assistant(text)
                            self._save_message("assistant", text)
                            return text

                        tool_out = self._execute_tool(tool_name, tool_args)

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(tool_out, ensure_ascii=False),
                        })

                # Detección de loop: mismos tools con mismos args dos veces seguidas
                _cur_sig = hashlib.md5(
                    _json.dumps(
                        [(b.name, b.input) for b in response.content if b.type == "tool_use"],
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                if _cur_sig == _last_tool_sig:
                    text = "Ciclo detectado: el agente usó las mismas herramientas dos veces seguidas."
                    self.state.add_assistant(text)
                    self._save_message("assistant", text)
                    return text
                _last_tool_sig = _cur_sig

                # Devolver resultados a Claude
                messages.append({"role": "user", "content": tool_results})
                continue

            # stop_reason inesperado → extraer texto si lo hay
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            text = text.strip() or "Respuesta inesperada."
            self.state.add_assistant(text)
            self._save_message("assistant", text)
            return text

        msg = "Límite de iteraciones de herramientas alcanzado."
        self.state.add_assistant(msg)
        self._save_message("assistant", msg)
        return msg

    # ------------------------------------------------------------------
    # Motor Gemini
    # ------------------------------------------------------------------

    def _tools_for_gemini(self) -> List[Any]:
        """Schema de tools en formato Gemini."""
        from google.genai import types

        declarations = []
        for name, spec in self.registry.list().items():
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for field_name, desc in (spec.schema or {}).items():
                desc_str = str(desc)
                if "int" in desc_str.lower():
                    ftype = "INTEGER"
                elif "bool" in desc_str.lower():
                    ftype = "BOOLEAN"
                else:
                    ftype = "STRING"

                properties[field_name] = types.Schema(
                    type=ftype,
                    description=desc_str,
                )
                if "obligatorio" in desc_str.lower():
                    required.append(field_name)

            params = types.Schema(
                type="OBJECT",
                properties=properties,
                required=required if required else [],
            )
            declarations.append(
                types.FunctionDeclaration(
                    name=spec.name,
                    description=spec.description,
                    parameters=params,
                )
            )

        return [types.Tool(function_declarations=declarations)] if declarations else []

    def _run_with_gemini(self, user_text: str) -> str:
        """Gemini como cerebro: conversación + tools nativo."""
        from google.genai import types

        # Construir historial en formato Gemini (truncado)
        contents: List[Any] = []
        for msg in truncate_history(self.state.history, max_messages=20):
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user" and isinstance(content, str) and content.strip():
                contents.append(types.Content(role="user", parts=[types.Part.from_text(content)]))
            elif role == "assistant" and isinstance(content, str) and content.strip():
                contents.append(types.Content(role="model", parts=[types.Part.from_text(content)]))

        tools = self._cached_gemini_tools

        for _ in range(self.config.max_tool_loops):
            try:
                response = self.gemini_client.models.generate_content(
                    model=self.config.gemini_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        tools=tools if tools else None,
                    ),
                )
            except Exception as e:
                err = f"Error Gemini API: {e}"
                if self.config.debug:
                    print(f"⚠️ {err}")
                if self.groq_client:
                    return self._run_with_groq_simple(user_text)
                self.state.add_assistant(err)
                self._save_message("assistant", err)
                return err

            if not response.candidates:
                err = "Gemini no devolvió candidatos (posible filtro de contenido)."
                if self.config.debug:
                    print(f"⚠️ {err}")
                self.state.add_assistant(err)
                self._save_message("assistant", err)
                return err

            candidate = response.candidates[0]
            parts = candidate.content.parts

            # Buscar tool calls
            tool_calls = [p for p in parts if p.function_call is not None]

            if not tool_calls:
                # Respuesta final
                text = "".join(p.text for p in parts if hasattr(p, "text") and p.text).strip()
                text = text or "No generé respuesta."
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text

            # Añadir respuesta del modelo al historial
            contents.append(types.Content(role="model", parts=parts))

            # Ejecutar tools y devolver resultados
            result_parts = []
            for part in tool_calls:
                fc = part.function_call
                tool_args = dict(fc.args) if fc.args else {}

                # Check for missing required params before executing
                question = self.intent_tracker.check_tool_call(
                    fc.name, tool_args, self.registry
                )
                if question:
                    if self.config.debug:
                        print(f"⏳ Intent pendiente ({fc.name}): {question}")
                    self.state.add_assistant(question)
                    self._save_message("assistant", question)
                    return question

                if self.config.debug:
                    print(f"🔧 Gemini usa: {fc.name}({json.dumps(tool_args, ensure_ascii=False)[:80]})")

                confirm_evt = self._maybe_build_dry_run(fc.name, tool_args)
                if confirm_evt:
                    text = self._render_dry_run_prompt(confirm_evt)
                    self.state.add_assistant(text)
                    self._save_message("assistant", text)
                    return text

                tool_out = self._execute_tool(fc.name, tool_args)

                result_parts.append(
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": json.dumps(tool_out, ensure_ascii=False)},
                    )
                )

            contents.append(types.Content(role="user", parts=result_parts))

        msg = "Límite de iteraciones de herramientas alcanzado."
        self.state.add_assistant(msg)
        self._save_message("assistant", msg)
        return msg

    # ------------------------------------------------------------------
    # Motor Groq (fallback)
    # ------------------------------------------------------------------

    def _run_with_groq(self, user_text: str) -> str:
        """Groq con tool calling nativo (mismo formato OpenAI)."""
        # SYSTEM_PROMPT_GROQ: versión compacta sin ejemplos de código Python que
        # confunden al modelo llama sobre el formato de function calling de la API.
        messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT_GROQ}]
        for msg in truncate_history(self.state.history, max_messages=20):
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str):
                messages.append({"role": role, "content": content})

        tools = self._cached_ollama_tools  # formato OpenAI — idéntico al que usa Groq

        for _ in range(self.config.max_tool_loops):
            try:
                response = self.groq_client.chat.completions.create(
                    model=self.config.groq_model,
                    messages=messages,
                    tools=tools if tools else None,
                    tool_choice="auto" if tools else None,
                    parallel_tool_calls=False,
                    max_tokens=2000,
                    temperature=0.7,
                )
            except Exception as e:
                # Si el modelo genera una tool call malformada, reintentar sin tools
                err_str = str(e)
                if "tool_use_failed" in err_str or "tool call validation failed" in err_str:
                    if self.config.debug:
                        print("⚠️ Groq tool_use_failed — reintentando sin tools")
                    return self._run_with_groq_simple(user_text)
                err = f"Error Groq: {e}"
                self.state.add_assistant(err)
                self._save_message("assistant", err)
                return err

            choice = response.choices[0]
            msg_out = choice.message

            # Respuesta final (sin tool calls estructurados)
            if not msg_out.tool_calls:
                text = (msg_out.content or "").strip() or "No generé respuesta."
                # Detectar tool calls en formato texto (<function=...>) que el modelo
                # a veces genera en vez de usar el mecanismo estructurado de la API
                text_calls = self._extract_text_tool_calls(text)
                if text_calls:
                    # Ejecutar las tools y pedir al modelo que reformule con los resultados
                    tool_results_ctx = self._run_text_tool_calls(text_calls)
                    messages.append({"role": "assistant", "content": text})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Resultados de las herramientas:\n{tool_results_ctx}\n\n"
                            "Ahora responde al usuario usando esos resultados. "
                            "No incluyas etiquetas <function=...> en tu respuesta."
                        ),
                    })
                    # Nueva llamada para que el modelo formule la respuesta final
                    try:
                        resp2 = self.groq_client.chat.completions.create(
                            model=self.config.groq_model,
                            messages=messages,
                            max_tokens=2000,
                            temperature=0.7,
                        )
                        text = (resp2.choices[0].message.content or "").strip() or text
                    except Exception:
                        pass  # usar texto original si falla
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text

            # Check for missing required params BEFORE adding tool_calls to messages.
            # For Groq, returning early avoids leaving an orphaned tool_call in history.
            first_question: Optional[str] = None
            confirm_evt: Optional[Dict[str, Any]] = None
            for tc in msg_out.tool_calls:
                _tname = tc.function.name
                try:
                    _targs = json.loads(tc.function.arguments or "{}")
                except Exception:
                    _targs = {}
                _q = self.intent_tracker.check_tool_call(_tname, _targs, self.registry)
                if _q:
                    first_question = _q
                    if self.config.debug:
                        print(f"⏳ Intent pendiente ({_tname}): {_q}")
                    break
                _confirm = self._maybe_build_dry_run(_tname, _targs)
                if _confirm:
                    confirm_evt = _confirm
                    break

            if first_question:
                self.state.add_assistant(first_question)
                self._save_message("assistant", first_question)
                return first_question
            if confirm_evt:
                text = self._render_dry_run_prompt(confirm_evt)
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text

            # All params present — añadir respuesta al historial y ejecutar
            messages.append({
                "role": "assistant",
                "content": msg_out.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg_out.tool_calls
                ],
            })

            # Ejecutar tools (en paralelo si hay más de una)
            _tc_inputs = [(tc.id, tc.function.name, tc.function.arguments) for tc in msg_out.tool_calls]
            if self.config.debug:
                for _, name, args_json in _tc_inputs:
                    print(f"🔧 Groq usa: {name}({(args_json or '')[:80]})")
            for tc_id, tool_out in self._run_tool_calls_parallel(_tc_inputs):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": json.dumps(tool_out, ensure_ascii=False),
                })

        msg = "Límite de iteraciones de herramientas alcanzado."
        self.state.add_assistant(msg)
        self._save_message("assistant", msg)
        return msg

    def _run_with_groq_simple(self, user_text: str) -> str:
        """Groq sin tools — solo usado como fallback de Claude/Gemini en caso de error."""
        messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in truncate_history(self.state.history, max_messages=20):
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str):
                messages.append({"role": role, "content": content})

        try:
            response = self.groq_client.chat.completions.create(
                model=self.config.groq_model,
                messages=messages,
                max_tokens=2000,
                temperature=0.7,
            )
            text = (response.choices[0].message.content or "").strip() or "No generé respuesta."
            self.state.add_assistant(text)
            self._save_message("assistant", text)
            return text
        except Exception as e:
            err = f"Error Groq: {e}"
            self.state.add_assistant(err)
            self._save_message("assistant", err)
            return err

    # ------------------------------------------------------------------
    # Motor Ollama (último fallback)
    # ------------------------------------------------------------------

    def _run_with_ollama(self, user_text: str, use_tools: bool = True) -> str:
        """Ollama local — solo usado si Claude y Groq no están disponibles."""
        messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.state.history)

        if not use_tools:
            try:
                response = requests.post(
                    f"{self.config.ollama_url}/api/chat",
                    json={"model": self.config.ollama_model, "messages": messages, "stream": False},
                    timeout=120,
                )
                response.raise_for_status()
                content = response.json().get("message", {}).get("content", "").strip()
                text = content or "No generé respuesta."
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text
            except Exception as e:
                err = f"Error Ollama: {e}"
                self.state.add_assistant(err)
                self._save_message("assistant", err)
                return err

        tools = self._cached_ollama_tools

        for _ in range(self.config.max_tool_loops):
            try:
                response = requests.post(
                    f"{self.config.ollama_url}/api/chat",
                    json={"model": self.config.ollama_model, "messages": messages, "tools": tools, "stream": False},
                    timeout=120,
                )
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                err = f"Error Ollama: {e}"
                self.state.add_assistant(err)
                self._save_message("assistant", err)
                return err

            msg = data.get("message", {})
            content = msg.get("content", "").strip()
            tool_calls = msg.get("tool_calls", [])

            if not tool_calls:
                text = content or "No generé respuesta."
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text

            # Check for missing required params BEFORE adding tool_calls to messages
            first_question_ollama: Optional[str] = None
            confirm_evt_ollama: Optional[Dict[str, Any]] = None
            for tc in tool_calls:
                _func = tc.get("function", {})
                _tname = _func.get("name", "")
                _targs_raw = _func.get("arguments", {})
                if isinstance(_targs_raw, str):
                    try:
                        _targs = json.loads(_targs_raw)
                    except Exception:
                        _targs = {}
                else:
                    _targs = _targs_raw
                _q = self.intent_tracker.check_tool_call(_tname, _targs, self.registry)
                if _q:
                    first_question_ollama = _q
                    if self.config.debug:
                        print(f"⏳ Intent pendiente ({_tname}): {_q}")
                    break
                _confirm = self._maybe_build_dry_run(_tname, _targs)
                if _confirm:
                    confirm_evt_ollama = _confirm
                    break

            if first_question_ollama:
                self.state.add_assistant(first_question_ollama)
                self._save_message("assistant", first_question_ollama)
                return first_question_ollama
            if confirm_evt_ollama:
                text = self._render_dry_run_prompt(confirm_evt_ollama)
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text

            messages.append({"role": "assistant", "content": content or "", "tool_calls": tool_calls})

            # Construir inputs normalizados para ejecución paralela
            _tc_inputs_ol: List[Tuple[Optional[str], str, Optional[str]]] = []
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                args_raw = func.get("arguments", {})
                args_json = args_raw if isinstance(args_raw, str) else json.dumps(args_raw)
                _tc_inputs_ol.append((None, name, args_json))

            for _, tool_out in self._run_tool_calls_parallel(_tc_inputs_ol):
                messages.append({"role": "tool", "content": json.dumps(tool_out, ensure_ascii=False)})

        msg = "Límite de tool loops alcanzado."
        self.state.add_assistant(msg)
        self._save_message("assistant", msg)
        return msg

    # ------------------------------------------------------------------
    # Punto de entrada principal
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Parser de text-format tool calls (Groq/llama fallback)
    # ------------------------------------------------------------------

    _RE_TEXT_FUNC = re.compile(
        r'<function=(\w+)>(.*?)</function>', re.DOTALL
    )

    def _extract_text_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        """
        Detecta tool calls escritas en texto por el modelo
        (<function=name>{...}</function>) y devuelve lista de {name, args}.
        """
        results = []
        for m in self._RE_TEXT_FUNC.finditer(text):
            name = m.group(1)
            raw = m.group(2).strip()
            try:
                args = json.loads(raw)
            except Exception:
                args = {}
            results.append({"name": name, "args": args})
        return results

    def _run_text_tool_calls(self, calls: List[Dict[str, Any]]) -> str:
        """Ejecuta una lista de text-format tool calls y devuelve resultados como texto."""
        parts: List[str] = []
        for call in calls:
            name = call["name"]
            args = call["args"]
            if self.config.debug:
                print(f"🔧 Groq text-call: {name}({json.dumps(args, ensure_ascii=False)[:80]})")
            try:
                confirm_evt = self._maybe_build_dry_run(name, args)
                if confirm_evt:
                    parts.append(
                        f"[{name}] {json.dumps(confirm_evt, ensure_ascii=False)}"
                    )
                    continue
                out = self._execute_tool(name, args)
                parts.append(f"[{name}] {json.dumps(out, ensure_ascii=False)}")
            except Exception as e:
                parts.append(f"[{name}] Error: {e}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Punto de entrada principal
    # ------------------------------------------------------------------

    def run(self, user_text: str) -> str:
        """Ejecuta petición. Prioridad: Claude > Groq > Ollama."""
        user_text = (user_text or "").strip()
        if not user_text:
            return "Dime qué quieres que haga."

        confirm_reply = self._handle_confirmation_turn(user_text)
        if confirm_reply is not None:
            self.state.add_user(user_text)
            self._save_message("user", user_text)
            self.state.add_assistant(confirm_reply)
            self._save_message("assistant", confirm_reply)
            return confirm_reply

        self.state.add_user(user_text)
        self._save_message("user", user_text)

        # Claude: maneja TODO (conversación + tools) de forma nativa
        if self.claude_client and self.config.use_claude:
            return self._run_with_claude(user_text)

        # Gemini: conversación + tools
        if self.gemini_client and self.config.use_gemini:
            return self._run_with_gemini(user_text)

        # Groq: conversación + tools nativo
        if self.groq_client and self.config.use_groq:
            return self._run_with_groq(user_text)

        # Ollama: fallback local
        return self._run_with_ollama(user_text, use_tools=True)

    # ------------------------------------------------------------------
    # Streaming (Groq)
    # ------------------------------------------------------------------

    async def run_stream(self, user_text: str) -> AsyncGenerator[str, None]:
        """
        Versión streaming de run() para Groq.
        Yield-ea chunks de texto según llegan del LLM.
        Si no hay Groq disponible, hace run() normal y yield-ea todo de golpe.
        """
        user_text = (user_text or "").strip()
        if not user_text:
            yield "Dime qué quieres que haga."
            return

        confirm_reply = self._handle_confirmation_turn(user_text)
        if confirm_reply is not None:
            self.state.add_user(user_text)
            self._save_message("user", user_text)
            self.state.add_assistant(confirm_reply)
            self._save_message("assistant", confirm_reply)
            yield confirm_reply
            return

        self.state.add_user(user_text)
        self._save_message("user", user_text)

        # Claude: no streaming en este modo — fallback síncrono
        if self.claude_client and self.config.use_claude:
            # _run_with_claude ya maneja estado y memoria
            text = await asyncio.to_thread(self._run_with_claude, user_text)
            yield text
            return

        # Groq streaming nativo
        if self.groq_client and self.config.use_groq:
            messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
            for msg in truncate_history(self.state.history, max_messages=20):
                role = msg.get("role")
                content = msg.get("content", "")
                if role in ("user", "assistant") and isinstance(content, str):
                    messages.append({"role": role, "content": content})

            q: queue_module.Queue = queue_module.Queue()

            def _stream_worker() -> None:
                try:
                    response = self.groq_client.chat.completions.create(
                        model=self.config.groq_model,
                        messages=messages,
                        max_tokens=2000,
                        temperature=0.7,
                        stream=True,
                    )
                    for chunk in response:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            q.put(("chunk", delta))
                    q.put(("done", None))
                except Exception as e:
                    q.put(("error", str(e)))

            loop = asyncio.get_event_loop()
            future = loop.run_in_executor(None, _stream_worker)

            full_text = ""
            while True:
                try:
                    kind, data = q.get_nowait()
                except queue_module.Empty:
                    await asyncio.sleep(0.01)
                    continue

                if kind == "done":
                    break
                if kind == "error":
                    yield f"Error Groq: {data}"
                    return
                full_text += data
                yield data

            await future  # asegurar que el thread terminó limpiamente

            full_text = full_text.strip() or "No generé respuesta."
            self.state.add_assistant(full_text)
            self._save_message("assistant", full_text)
            return

        # Fallback: Gemini / Ollama (no streaming)
        # Nota: ya añadimos user al state arriba, no llamar run() completo
        if self.gemini_client and self.config.use_gemini:
            text = await asyncio.to_thread(self._run_with_gemini, user_text)
        else:
            text = await asyncio.to_thread(self._run_with_ollama, user_text, True)
        yield text

    # ------------------------------------------------------------------
    # Streaming TTS: run_sentences — emite frases conforme el LLM genera
    # ------------------------------------------------------------------

    def run_sentences(
        self,
        user_text: str,
        on_sentence: Callable[[str], None],
        interrupt_event: Optional[threading.Event] = None,
    ) -> str:
        """
        Ejecuta el LLM y llama on_sentence(frase) para cada frase completa
        conforme se genera, permitiendo TTS en paralelo.

        Retorna el texto completo al finalizar (para historial/logs).
        Para Claude y Groq usa streaming; para Gemini/Ollama hace run()
        blocking y luego emite las frases de la respuesta completa.
        """
        user_text = (user_text or "").strip()
        if not user_text:
            msg = "Dime qué quieres que haga."
            on_sentence(msg)
            return msg

        confirm_reply = self._handle_confirmation_turn(user_text)
        if confirm_reply is not None:
            self.state.add_user(user_text)
            self._save_message("user", user_text)
            self.state.add_assistant(confirm_reply)
            self._save_message("assistant", confirm_reply)
            on_sentence(confirm_reply)
            return confirm_reply

        self.state.add_user(user_text)
        self._save_message("user", user_text)

        if self.claude_client and self.config.use_claude:
            return self._run_sentences_claude(user_text, on_sentence, interrupt_event)

        if self.groq_client and self.config.use_groq:
            return self._run_sentences_groq(user_text, on_sentence, interrupt_event)

        # Gemini / Ollama: sin streaming propio — emitir frases de respuesta completa
        if self.gemini_client and self.config.use_gemini:
            full = self._run_with_gemini(user_text)
        else:
            full = self._run_with_ollama(user_text, use_tools=True)

        # Emitir frases de la respuesta completa
        first_emitted: List[bool] = [False]
        remainder = _emit_sentences(full, on_sentence, first_emitted)
        if remainder.strip():
            on_sentence(remainder.strip())
        return full

    def _run_sentences_claude(
        self,
        user_text: str,
        on_sentence: Callable[[str], None],
        interrupt_event: Optional[threading.Event],
    ) -> str:
        """
        Claude con streaming: emite frases vía on_sentence conforme llegan tokens.
        Maneja tool use: para cada iteración se re-entra en streaming.
        """
        messages = self._build_claude_messages()
        tools = self._cached_claude_tools
        first_emitted: List[bool] = [False]

        def _interrupted() -> bool:
            return interrupt_event is not None and interrupt_event.is_set()

        for loop_count in range(self.config.max_tool_loops):
            if _interrupted():
                break
            buffer = ""
            try:
                with self.claude_client.messages.stream(
                    model=self.config.claude_model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    messages=messages,
                ) as stream:
                    for text_delta in stream.text_stream:
                        if _interrupted():
                            break
                        buffer += text_delta
                        buffer = _emit_sentences(buffer, on_sentence, first_emitted)
                    final = stream.get_final_message()
            except Exception as e:
                _logger.warning("[sentences:claude] Stream error: %s — fallback blocking", e)
                # Fallback a llamada bloqueante
                return self._run_with_claude(user_text)

            # Frase final restante en buffer
            if buffer.strip() and not _interrupted() and final.stop_reason == "end_turn":
                on_sentence(buffer.strip())

            if final.stop_reason == "end_turn":
                text = ""
                for block in final.content:
                    if hasattr(block, "text"):
                        text += block.text
                text = text.strip() or "No generé respuesta."
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text

            if final.stop_reason == "tool_use":
                # Emitir buffer pre-tool si lo hay
                if buffer.strip() and not _interrupted():
                    on_sentence(buffer.strip())

                # Ejecutar tools (mismo patrón que _run_with_claude)
                messages.append({"role": "assistant", "content": final.content})
                tool_results = []
                for block in final.content:
                    if block.type != "tool_use":
                        continue
                    tool_name = block.name
                    tool_args = block.input

                    if self.config.debug:
                        _logger.debug(
                            "[sentences:claude] tool=%s args=%s",
                            tool_name,
                            json.dumps(tool_args, ensure_ascii=False)[:80],
                        )

                    question = self.intent_tracker.check_tool_call(
                        tool_name, tool_args, self.registry
                    )
                    if question:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({
                                "ok": False,
                                "error": f"Parámetros faltantes. Pregunta: {question}",
                            }, ensure_ascii=False),
                        })
                        continue

                    confirm_evt = self._maybe_build_dry_run(tool_name, tool_args)
                    if confirm_evt:
                        text = self._render_dry_run_prompt(confirm_evt)
                        self.state.add_assistant(text)
                        self._save_message("assistant", text)
                        on_sentence(text)
                        return text

                    tool_out = self._execute_tool(tool_name, tool_args)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(tool_out, ensure_ascii=False),
                    })

                messages.append({"role": "user", "content": tool_results})
                continue  # siguiente iteración → streaming de respuesta post-tool

            # stop_reason inesperado
            if buffer.strip() and not _interrupted():
                on_sentence(buffer.strip())
            text = buffer.strip() or "Respuesta inesperada."
            self.state.add_assistant(text)
            self._save_message("assistant", text)
            return text

        msg = "Límite de iteraciones de herramientas alcanzado."
        self.state.add_assistant(msg)
        self._save_message("assistant", msg)
        return msg

    def _run_sentences_groq(
        self,
        user_text: str,
        on_sentence: Callable[[str], None],
        interrupt_event: Optional[threading.Event],
    ) -> str:
        """
        Groq con streaming progresivo + tool calling completo.

        Flujo por iteración:
          1. Llama a Groq con stream=True incluyendo tools.
          2. Acumula tool_calls del stream (llegan fragmentados) y emite texto.
          3. Si hay tool_calls: ejecuta tools y continúa el loop (sin re-llamar).
          4. Si no hay tool_calls: emite buffer restante, guarda y retorna.
        """
        messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT_GROQ}]
        for msg in truncate_history(self.state.history, max_messages=20):
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str):
                messages.append({"role": role, "content": content})

        tools = self._cached_ollama_tools  # formato OpenAI — idéntico al que usa Groq
        first_emitted: List[bool] = [False]

        def _interrupted() -> bool:
            return interrupt_event is not None and interrupt_event.is_set()

        for _loop in range(self.config.max_tool_loops):
            if _interrupted():
                break

            buffer = ""
            # tool_calls acumulados del stream: idx → {id, name, args}
            tool_acc: dict = {}
            finish_reason: Optional[str] = None

            try:
                stream = self.groq_client.chat.completions.create(
                    model=self.config.groq_model,
                    messages=messages,
                    tools=tools if tools else None,
                    tool_choice="auto" if tools else None,
                    parallel_tool_calls=False,
                    max_tokens=2000,
                    temperature=0.7,
                    stream=True,
                )
                for chunk in stream:
                    if _interrupted():
                        break
                    choice = chunk.choices[0] if chunk.choices else None
                    if choice is None:
                        continue
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason

                    # ── Acumular tool_calls fragmentados ──────────────────────
                    if choice.delta.tool_calls:
                        for tc_delta in choice.delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_acc:
                                tool_acc[idx] = {"id": "", "name": "", "args": ""}
                            if tc_delta.id:
                                tool_acc[idx]["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tool_acc[idx]["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    tool_acc[idx]["args"] += tc_delta.function.arguments

                    # ── Emitir texto progresivo ───────────────────────────────
                    delta = choice.delta.content
                    if delta:
                        buffer += delta
                        buffer = _emit_sentences(buffer, on_sentence, first_emitted)

            except Exception as e:
                _logger.warning("[sentences:groq] Stream error: %s — fallback blocking", e)
                full = self._run_with_groq(user_text)
                if not first_emitted[0]:
                    rem = _emit_sentences(full, on_sentence, first_emitted)
                    if rem.strip():
                        on_sentence(rem.strip())
                return full

            # ── Sin tool calls: respuesta final de texto ──────────────────────
            if not tool_acc:
                if buffer.strip() and not _interrupted():
                    on_sentence(buffer.strip())
                full_text = buffer.strip() or "No generé respuesta."
                self.state.add_assistant(full_text)
                self._save_message("assistant", full_text)
                return full_text

            # ── Con tool calls: verificar params y ejecutar ───────────────────
            tool_calls_list = [tool_acc[i] for i in sorted(tool_acc.keys())]

            first_question: Optional[str] = None
            confirm_evt: Optional[Dict[str, Any]] = None
            for tc in tool_calls_list:
                try:
                    _args = json.loads(tc["args"] or "{}")
                except Exception:
                    _args = {}
                _q = self.intent_tracker.check_tool_call(tc["name"], _args, self.registry)
                if _q:
                    first_question = _q
                    break
                _confirm = self._maybe_build_dry_run(tc["name"], _args)
                if _confirm:
                    confirm_evt = _confirm
                    break

            if first_question:
                self.state.add_assistant(first_question)
                self._save_message("assistant", first_question)
                on_sentence(first_question)
                return first_question
            if confirm_evt:
                text = self._render_dry_run_prompt(confirm_evt)
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                on_sentence(text)
                return text

            # Añadir turno asistente con tool_calls al historial local
            messages.append({
                "role": "assistant",
                "content": buffer or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["args"]},
                    }
                    for tc in tool_calls_list
                ],
            })

            # Ejecutar tools (en paralelo si hay más de una)
            _tc_inputs_sg = [(tc["id"], tc["name"], tc["args"]) for tc in tool_calls_list]
            if self.config.debug:
                for _, name, args_json in _tc_inputs_sg:
                    _logger.debug("[sentences:groq] tool=%s args=%s", name, (args_json or "")[:80])
            for tc_id, tool_out in self._run_tool_calls_parallel(_tc_inputs_sg):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": json.dumps(tool_out, ensure_ascii=False),
                })
            # Siguiente iteración: el LLM genera la respuesta final con los resultados

        msg = "Límite de iteraciones de herramientas alcanzado."
        self.state.add_assistant(msg)
        self._save_message("assistant", msg)
        return msg


def tool_agent_from_settings(
    settings: Any,
    registry: Optional[ToolRegistry] = None,
    memory_store: Optional[Any] = None,
    paths: Optional[Any] = None,
):
    """Construye ToolAgent desde Settings."""
    def _parse_list(raw: Any) -> List[str]:
        if isinstance(raw, str):
            return [x.strip() for x in raw.split(",") if x.strip()]
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        return []

    always_for = _parse_list(getattr(settings, "dry_run_always_for", []))
    shell_deny_patterns = _parse_list(getattr(settings, "shell_deny_patterns", []))
    shell_confirm_patterns = _parse_list(getattr(settings, "shell_confirm_patterns", []))

    cfg = ToolAgentConfig(
        # Claude
        use_claude=bool(getattr(settings, "use_claude", False)),
        claude_api_key=getattr(settings, "anthropic_api_key", ""),
        claude_model=getattr(settings, "anthropic_model", "claude-sonnet-4-6"),
        # Gemini
        use_gemini=bool(getattr(settings, "use_gemini", False)),
        gemini_api_key=getattr(settings, "gemini_api_key", ""),
        gemini_model=getattr(settings, "gemini_model", "gemini-2.0-flash"),
        # Groq
        use_groq=bool(getattr(settings, "use_groq", False)),
        groq_api_key=getattr(settings, "groq_api_key", ""),
        groq_model=getattr(settings, "groq_model", "llama-3.3-70b-versatile"),
        # Ollama
        ollama_model=getattr(settings, "ollama_model", "llama3.2:3b"),
        # General
        debug=bool(getattr(settings, "debug", False)),
        max_tool_loops=8,
        enable_memory=True,
        dry_run_enabled=bool(getattr(settings, "dry_run_enabled", True)),
        dry_run_ttl_seconds=int(getattr(settings, "dry_run_ttl_seconds", 120)),
        dry_run_always_for=always_for,
        dry_run_max_items_list=int(getattr(settings, "dry_run_max_items_list", 20)),
        dry_run_snippet_chars=int(getattr(settings, "dry_run_snippet_chars", 300)),
        # Compatibilidad con config anterior
        confirm_policy_enabled=bool(getattr(settings, "confirm_policy_enabled", True)),
        confirm_ttl_seconds=int(getattr(settings, "confirm_ttl_seconds", 120)),
        confirm_always_for=_parse_list(getattr(settings, "confirm_always_for", [])),
        shell_guard_enabled=bool(getattr(settings, "shell_guard_enabled", True)),
        shell_guard_mode=str(getattr(settings, "shell_guard_mode", "strict")),
        shell_deny_patterns=shell_deny_patterns,
        shell_confirm_patterns=shell_confirm_patterns,
        verifier_enabled=bool(getattr(settings, "verifier_enabled", True)),
        verifier_timeout_ms=int(getattr(settings, "verifier_timeout_ms", 1500)),
        verifier_max_items=int(getattr(settings, "verifier_max_items", 50)),
        verifier_sample_if_over=int(getattr(settings, "verifier_sample_if_over", 200)),
        verifier_strict=bool(getattr(settings, "verifier_strict", False)),
        tool_schema_validation_enabled=bool(getattr(settings, "tool_schema_validation_enabled", True)),
        tool_schema_strict=bool(getattr(settings, "tool_schema_strict", True)),
        tool_schema_log_invalid=bool(getattr(settings, "tool_schema_log_invalid", False)),
        pev_enabled=bool(getattr(settings, "pev_enabled", False)),
        pev_max_steps=int(getattr(settings, "pev_max_steps", 6)),
        pev_retry_max=int(getattr(settings, "pev_retry_max", 1)),
        pev_state_ttl_seconds=int(getattr(settings, "pev_state_ttl_seconds", 600)),
        pev_verbose_trace=bool(getattr(settings, "pev_verbose_trace", False)),
    )
    confirm_context = {
        "project_root": getattr(paths, "project_root", Path.cwd()),
        "data_dir": getattr(paths, "data_dir", Path.cwd() / "data"),
    }
    if cfg.pev_enabled:
        from jarvis.agent.pev_agent import PEVAgent  # lazy import — evita circular
        return PEVAgent(cfg, registry=registry, memory_store=memory_store,
                        confirm_context=confirm_context)
    return ToolAgent(
        cfg,
        registry=registry,
        memory_store=memory_store,
        confirm_context=confirm_context,
    )
