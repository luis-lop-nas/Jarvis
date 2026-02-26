from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from jarvis.tools.shell_guard import analyze_shell_command


_SECRET_KEYS = ("key", "token", "password", "secret", "api")


def is_sensitive(
    tool_name: str,
    args: Dict[str, Any],
    *,
    always_for: set[str] | None = None,
    shell_guard_mode: str = "strict",
    shell_deny_patterns: List[str] | None = None,
    shell_confirm_patterns: List[str] | None = None,
) -> bool:
    tool = (tool_name or "").strip().lower()
    if always_for and tool in always_for:
        return True

    if tool in {"send_email", "send_message"}:
        return True

    if tool == "calendar":
        action = str(args.get("action", "")).strip().lower()
        return action in {"create", "create_event", "update", "edit", "delete", "remove"}

    if tool == "filesystem":
        action = str(args.get("action", "")).strip().lower()
        path = str(args.get("path", "")).strip()
        destination = str(args.get("destination", "")).strip()
        recursive = bool(args.get("recursive"))
        mass = recursive or _has_wildcards(path) or _has_wildcards(destination)
        return action in {"delete", "move", "rename", "copy"} or mass

    if tool == "shell":
        decision = analyze_shell_command(
            str(args.get("command", "")).strip(),
            cwd=str(args.get("cwd", "") or ""),
            mode=shell_guard_mode,
            deny_patterns=shell_deny_patterns,
            confirm_patterns=shell_confirm_patterns,
        )
        return decision.decision in {"confirm", "deny"}

    if tool == "web_agent":
        task = str(args.get("task", "")).strip()
        force_sensitive = bool(args.get("force_sensitive", False))
        return force_sensitive or not _is_web_read_only(task)

    return False


def infer_risk(
    tool_name: str,
    args: Dict[str, Any],
    *,
    shell_guard_mode: str = "strict",
    shell_deny_patterns: List[str] | None = None,
    shell_confirm_patterns: List[str] | None = None,
) -> str:
    tool = (tool_name or "").strip().lower()
    if tool in {"send_email", "send_message"}:
        return "high"

    if tool == "shell":
        decision = analyze_shell_command(
            str(args.get("command", "")).strip(),
            cwd=str(args.get("cwd", "") or ""),
            mode=shell_guard_mode,
            deny_patterns=shell_deny_patterns,
            confirm_patterns=shell_confirm_patterns,
        )
        return decision.risk_level

    if tool == "filesystem":
        action = str(args.get("action", "")).strip().lower()
        path = str(args.get("path", "")).strip()
        destination = str(args.get("destination", "")).strip()
        recursive = bool(args.get("recursive"))
        mass = recursive or _has_wildcards(path) or _has_wildcards(destination)
        if action == "delete" or mass:
            return "high"
        return "medium"

    if tool in {"calendar", "web_agent"}:
        return "medium"

    return "low"


def build_summary(tool_name: str, args: Dict[str, Any]) -> str:
    tool = (tool_name or "").strip().lower()
    if tool == "send_email":
        to = _safe_text(args.get("to", ""))
        subject = _safe_text(args.get("subject", ""))
        return f"Voy a enviar un email a '{to}' con asunto '{subject}'."
    if tool == "send_message":
        receiver = _safe_text(args.get("receiver", ""))
        return f"Voy a enviar un mensaje a '{receiver}'."
    if tool == "calendar":
        action = _safe_text(args.get("action", "create"))
        title = _safe_text(args.get("query", "evento"))
        return f"Voy a {action} una entrada de calendario: '{title}'."
    if tool == "filesystem":
        action = _safe_text(args.get("action", "operate"))
        path = _safe_text(args.get("path", ""))
        return f"Voy a ejecutar filesystem '{action}' sobre '{path}'."
    if tool == "shell":
        cmd = _safe_text(args.get("command", ""))
        return f"Voy a ejecutar este comando shell: {cmd}"
    if tool == "web_agent":
        task = _safe_text(args.get("task", ""))
        return f"Voy a ejecutar web_agent en modo acción para: {task}"
    return f"Voy a ejecutar la tool '{tool_name}'."


def build_preview(
    tool_name: str,
    args: Dict[str, Any],
    *,
    max_items: int = 20,
    snippet_chars: int = 300,
    shell_guard_mode: str = "strict",
    shell_deny_patterns: List[str] | None = None,
    shell_confirm_patterns: List[str] | None = None,
) -> Dict[str, Any]:
    tool = (tool_name or "").strip().lower()
    if tool == "send_email":
        return {
            "to": _safe_text(args.get("to", "")),
            "cc": _safe_text(args.get("cc", "")),
            "bcc": _safe_text(args.get("bcc", "")),
            "subject": _safe_text(args.get("subject", "")),
            "body_snippet": _truncate(_safe_text(args.get("body", "")), snippet_chars),
            "action": _safe_text(args.get("action", "send")),
        }

    if tool == "send_message":
        return {
            "receiver": _safe_text(args.get("receiver", "")),
            "platform": _safe_text(args.get("platform", "messages")),
            "message_snippet": _truncate(_safe_text(args.get("message_text", "")), snippet_chars),
        }

    if tool == "calendar":
        return {
            "action": _safe_text(args.get("action", "")),
            "title": _safe_text(args.get("query", "")),
            "date": _safe_text(args.get("date", "")),
            "time": _safe_text(args.get("time", "")),
            "duration_minutes": args.get("duration_minutes"),
            "calendar": _safe_text(args.get("calendar", "")),
            "attendees": _safe_text(args.get("attendees", "")),
            "notes_snippet": _truncate(_safe_text(args.get("notes", "")), snippet_chars),
        }

    if tool == "filesystem":
        action = _safe_text(args.get("action", ""))
        path = _safe_text(args.get("path", ""))
        destination = _safe_text(args.get("destination", ""))
        paths = args.get("paths")
        if isinstance(paths, list):
            safe_paths = [_safe_text(p) for p in paths]
            listed: List[str] = safe_paths[:max_items]
            return {
                "operation": action,
                "paths": listed,
                "paths_count": len(safe_paths),
                "destination": destination,
            }
        return {
            "operation": action,
            "path": path,
            "destination": destination,
            "recursive": bool(args.get("recursive")),
        }

    if tool == "shell":
        cmd = _safe_text(args.get("command", ""))
        decision = analyze_shell_command(
            cmd,
            cwd=str(args.get("cwd", "") or ""),
            mode=shell_guard_mode,
            deny_patterns=shell_deny_patterns,
            confirm_patterns=shell_confirm_patterns,
        )
        return {
            "command": cmd,
            "cwd": _safe_text(args.get("cwd", "")),
            "has_pipe": "|" in cmd,
            "has_redirect": any(tok in cmd for tok in (">", ">>", "<")),
            "guard_decision": decision.decision,
            "guard_reason": decision.reason,
            "rules": decision.matches,
        }

    if tool == "web_agent":
        return {
            "task": _safe_text(args.get("task", "")),
            "url": _safe_text(args.get("url", "")),
            "headless": bool(args.get("headless", False)),
            "force_sensitive": bool(args.get("force_sensitive", False)),
            "mode": "read_only" if _is_web_read_only(str(args.get("task", ""))) else "action",
        }

    return _mask_dict(args, snippet_chars=snippet_chars)


def _safe_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    lower = text.lower()
    if any(k in lower for k in _SECRET_KEYS):
        return "[REDACTED]"
    return text


def _mask_dict(data: Dict[str, Any], *, snippet_chars: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in data.items():
        kl = str(k).lower()
        if any(sk in kl for sk in _SECRET_KEYS):
            out[str(k)] = "[REDACTED]"
            continue
        if isinstance(v, (dict, list)):
            out[str(k)] = _truncate(str(v), snippet_chars)
        else:
            out[str(k)] = _truncate(_safe_text(v), snippet_chars)
    return out


def _has_wildcards(path: str) -> bool:
    return any(ch in (path or "") for ch in ("*", "?", "[", "]"))


def _truncate(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[: max(0, n - 3)] + "..."


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
