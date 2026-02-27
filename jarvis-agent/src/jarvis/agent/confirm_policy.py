from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


_YES_RE = re.compile(
    r"\b(si|sí|confirm(ar|o)?|ok|dale|hazlo|adelante|procede|continue|yes)\b",
    re.IGNORECASE,
)
_NO_RE = re.compile(
    r"\b(no|cancel(ar|a)?|deten|par(a|ar)|abort|deny|rechaza|olvidalo|olvídalo)\b",
    re.IGNORECASE,
)

_SHELL_DANGEROUS_RE = re.compile(
    r"(^|\s)(sudo|rm\s+-[^\n]*r|rm\s+-[^\n]*f|rm\s+-rf|chmod|chown|kill|pkill|killall|dd\s+if=|mkfs|diskutil\s+erase|shutdown|reboot)(\s|$)",
    re.IGNORECASE,
)
_SHELL_WILDCARD_RE = re.compile(r"(\*|\?|\[[^\]]+\])")
_EXECUTABLE_EXTS = {
    ".app",
    ".pkg",
    ".dmg",
    ".sh",
    ".command",
    ".run",
    ".exe",
    ".msi",
    ".bat",
    ".zsh",
    ".bash",
}


@dataclass(frozen=True)
class ConfirmContext:
    project_root: Path
    data_dir: Path
    now_ts: float = field(default_factory=time.time)
    always_for: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ConfirmDecision:
    requires_confirmation: bool
    risk_level: str
    reason: str
    summary: str
    preview: Optional[Dict[str, Any]] = None
    confirm_token: str = ""


@dataclass
class PendingConfirmation:
    confirm_token: str
    tool_name: str
    args: Dict[str, Any]
    created_at: float
    expires_at: float
    summary: str
    reason: str
    risk_level: str
    preview: Optional[Dict[str, Any]] = None


class ConfirmStore:
    def __init__(self, ttl_seconds: int = 120) -> None:
        self.ttl_seconds = max(1, int(ttl_seconds))
        self._pending: Dict[str, PendingConfirmation] = {}

    def cleanup_expired(self) -> None:
        now = time.time()
        expired = [t for t, p in self._pending.items() if p.expires_at <= now]
        for token in expired:
            self._pending.pop(token, None)

    def put(
        self,
        *,
        tool_name: str,
        args: Dict[str, Any],
        summary: str,
        reason: str,
        risk_level: str,
        preview: Optional[Dict[str, Any]] = None,
    ) -> PendingConfirmation:
        self.cleanup_expired()
        now = time.time()
        token = uuid.uuid4().hex[:12]
        pending = PendingConfirmation(
            confirm_token=token,
            tool_name=tool_name,
            args=dict(args),
            created_at=now,
            expires_at=now + self.ttl_seconds,
            summary=summary,
            reason=reason,
            risk_level=risk_level,
            preview=preview,
        )
        self._pending[token] = pending
        return pending

    def get(self, token: str) -> Optional[PendingConfirmation]:
        self.cleanup_expired()
        return self._pending.get(token)

    def pop(self, token: str) -> Optional[PendingConfirmation]:
        self.cleanup_expired()
        return self._pending.pop(token, None)

    def latest(self) -> Optional[PendingConfirmation]:
        self.cleanup_expired()
        if not self._pending:
            return None
        return sorted(self._pending.values(), key=lambda p: p.created_at)[-1]

    def pop_latest(self) -> Optional[PendingConfirmation]:
        latest = self.latest()
        if not latest:
            return None
        return self._pending.pop(latest.confirm_token, None)

    def has_pending(self) -> bool:
        self.cleanup_expired()
        return bool(self._pending)


def is_confirmation_reply(text: str) -> bool:
    normalized = _first_user_segment(text).strip()
    return bool(_YES_RE.search(normalized) or _NO_RE.search(normalized))


def is_affirmative(text: str) -> bool:
    return bool(_YES_RE.search(_first_user_segment(text)))


def is_negative(text: str) -> bool:
    return bool(_NO_RE.search(_first_user_segment(text)))


def extract_confirm_token(text: str) -> Optional[str]:
    normalized = _first_user_segment(text).strip()
    m = re.search(r"\b([a-f0-9]{12})\b", normalized, re.IGNORECASE)
    return m.group(1).lower() if m else None


def evaluate(tool_name: str, args: Dict[str, Any], context: ConfirmContext) -> ConfirmDecision:
    tool = (tool_name or "").strip().lower()
    if tool in context.always_for:
        summary, preview = _generic_summary(tool, args)
        return ConfirmDecision(
            requires_confirmation=True,
            risk_level="high",
            reason="Tool marcada en CONFIRM_ALWAYS_FOR.",
            summary=summary,
            preview=preview,
        )

    if tool == "send_email":
        preview = {
            "to": str(args.get("to", ""))[:160],
            "subject": str(args.get("subject", ""))[:200],
            "body_preview": _truncate(str(args.get("body", "")), 160),
            "action": str(args.get("action", "send")),
        }
        return ConfirmDecision(
            requires_confirmation=True,
            risk_level="high",
            reason="Enviar email impacta a terceros y no es reversible.",
            summary=f"Enviar email a {preview['to']} con asunto '{preview['subject']}'.",
            preview=preview,
        )

    if tool == "send_message":
        preview = {
            "receiver": str(args.get("receiver", ""))[:160],
            "platform": str(args.get("platform", "messages"))[:40],
            "message_preview": _truncate(str(args.get("message_text", "")), 160),
        }
        return ConfirmDecision(
            requires_confirmation=True,
            risk_level="high",
            reason="Enviar mensajes impacta a terceros y no es reversible.",
            summary=f"Enviar mensaje a {preview['receiver']} por {preview['platform']}.",
            preview=preview,
        )

    if tool == "calendar":
        action = str(args.get("action", "")).strip().lower()
        sensitive = action in {"create", "create_event", "update", "edit", "delete", "remove"}
        if sensitive:
            preview = {
                "action": action,
                "title": str(args.get("query", ""))[:180],
                "date": str(args.get("date", ""))[:40],
                "time": str(args.get("time", ""))[:20],
                "duration_minutes": args.get("duration_minutes"),
            }
            return ConfirmDecision(
                requires_confirmation=True,
                risk_level="medium",
                reason="Cambiar calendario crea/modifica/elimina eventos.",
                summary=f"Modificar calendario con acción '{action}'.",
                preview=preview,
            )
        return _allow()

    if tool == "filesystem":
        action = str(args.get("action", "")).strip().lower()
        path = str(args.get("path", "")).strip()
        destination = str(args.get("destination", "")).strip()
        recursive = bool(args.get("recursive"))
        patterns = args.get("patterns")
        has_wildcard = _has_wildcards(path) or _has_wildcards(destination)
        mass = recursive or has_wildcard or isinstance(patterns, list)
        sensitive_action = action in {"delete", "move", "rename"}
        if sensitive_action or mass:
            risk = "high" if action == "delete" or mass else "medium"
            preview = {
                "action": action,
                "path": _truncate(path, 240),
                "destination": _truncate(destination, 240),
                "recursive": recursive,
                "mass_operation": mass,
            }
            return ConfirmDecision(
                requires_confirmation=True,
                risk_level=risk,
                reason="Operación de archivos potencialmente destructiva o masiva.",
                summary=f"Filesystem '{action}' sobre '{path or '<sin ruta>'}'.",
                preview=preview,
            )
        return _allow()

    if tool == "shell":
        command = str(args.get("command", "")).strip()
        dangerous = bool(_SHELL_DANGEROUS_RE.search(command))
        mass = bool(_SHELL_WILDCARD_RE.search(command))
        if dangerous or mass:
            preview = {"command": _truncate(command, 300)}
            return ConfirmDecision(
                requires_confirmation=True,
                risk_level="high",
                reason="Comando shell peligroso o potencialmente destructivo.",
                summary=f"Ejecutar comando shell sensible: {preview['command']}",
                preview=preview,
            )
        return _allow()

    if tool == "web_agent":
        task = str(args.get("task", "")).strip()
        url = str(args.get("url", "")).strip()
        force_sensitive = bool(args.get("force_sensitive", False))
        read_only = _is_web_read_only(task)
        if force_sensitive or not read_only:
            preview = {"task": _truncate(task, 260), "url": _truncate(url, 240)}
            return ConfirmDecision(
                requires_confirmation=True,
                risk_level="medium",
                reason="web_agent puede hacer clicks/inputs/submit en sitios web.",
                summary=f"Ejecutar web_agent para: {preview['task']}",
                preview=preview,
            )
        return _allow(summary=f"web_agent en modo lectura: {task}")

    if tool in {"download_file", "search_and_download"}:
        destination = str(args.get("destination", "")).strip()
        filename = str(args.get("filename", "")).strip()
        url = str(args.get("url", "")).strip()
        ext = Path(filename or url).suffix.lower()
        writes_outside_data = False
        if destination:
            try:
                dest_path = Path(destination).expanduser().resolve()
                data_dir = context.data_dir.expanduser().resolve()
                writes_outside_data = not _is_relative_to(dest_path, data_dir)
            except Exception:
                writes_outside_data = True
        if writes_outside_data or ext in _EXECUTABLE_EXTS:
            preview = {
                "url": _truncate(url, 240),
                "destination": _truncate(destination, 240),
                "filename": _truncate(filename, 120),
                "extension": ext,
            }
            reason = (
                "Descarga ejecutable."
                if ext in _EXECUTABLE_EXTS
                else "Descarga escribirá fuera de data/."
            )
            return ConfirmDecision(
                requires_confirmation=True,
                risk_level="medium",
                reason=reason,
                summary=f"Descargar archivo ({ext or 'sin extensión'}) en '{destination or 'ruta por defecto'}'.",
                preview=preview,
            )
        return _allow()

    return _allow()


def _allow(summary: str = "") -> ConfirmDecision:
    return ConfirmDecision(
        requires_confirmation=False,
        risk_level="low",
        reason="No requiere confirmación.",
        summary=summary or "Acción permitida sin confirmación.",
        preview=None,
    )


def _generic_summary(tool_name: str, args: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    return (
        f"Ejecutar tool '{tool_name}' con confirmación obligatoria.",
        {"tool_name": tool_name, "args_preview": _truncate(str(args), 300)},
    )


def _truncate(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[: max(0, n - 3)] + "..."


def _has_wildcards(path: str) -> bool:
    return any(ch in (path or "") for ch in ("*", "?", "[", "]"))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_web_read_only(task: str) -> bool:
    t = (task or "").lower()
    action_words = [
        "click",
        "rellena",
        "rellenar",
        "fill",
        "submit",
        "compr",
        "buy",
        "login",
        "iniciar sesión",
        "escribe",
        "type",
        "publica",
        "post",
    ]
    readonly_words = [
        "leer",
        "read",
        "resum",
        "summary",
        "extract",
        "extrae",
        "analiza",
        "describe",
        "ver",
        "consulta",
        "buscar informacion",
    ]
    has_action = any(w in t for w in action_words)
    has_readonly = any(w in t for w in readonly_words)
    return has_readonly and not has_action


def _first_user_segment(text: str) -> str:
    first = (text or "").splitlines()[0].strip()
    return first
