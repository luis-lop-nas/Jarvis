from __future__ import annotations

import time

from jarvis.agent.dry_run import build_preview, infer_risk, is_sensitive
from jarvis.agent.pending_actions import PendingActionStore


def test_shell_dangerous_is_high_risk() -> None:
    args = {"command": "rm -rf /"}
    assert is_sensitive("shell", args) is True
    assert infer_risk("shell", args) == "high"


def test_web_agent_read_only_not_sensitive() -> None:
    args = {"task": "lee esta pagina y resume el contenido"}
    assert is_sensitive("web_agent", args) is False


def test_send_email_preview_has_expected_fields() -> None:
    preview = build_preview(
        "send_email",
        {
            "to": "ana@example.com",
            "cc": "cc@example.com",
            "bcc": "bcc@example.com",
            "subject": "Hola",
            "body": "Contenido largo",
        },
    )
    assert "to" in preview
    assert "cc" in preview
    assert "bcc" in preview
    assert "subject" in preview
    assert "body_snippet" in preview


def test_pending_action_expiration() -> None:
    store = PendingActionStore(ttl_seconds=1)
    pending = store.put(
        tool_name="send_email",
        args={"to": "x@example.com"},
        summary="Enviar email",
        reason="sensible",
        details={"to": "x@example.com"},
        risk_level="high",
    )
    assert store.get(pending.confirm_token) is not None
    time.sleep(1.1)
    assert store.get(pending.confirm_token) is None
