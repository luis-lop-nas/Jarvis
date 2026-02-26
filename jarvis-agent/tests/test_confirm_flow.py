from __future__ import annotations

import time
from pathlib import Path

from jarvis.agent.tool_agent import ToolAgent, ToolAgentConfig
from jarvis.tools.registry import ToolRegistry, ToolSpec


def _build_agent(tmp_path: Path) -> tuple[ToolAgent, dict]:
    calls = {"count": 0}

    def _send_email(args):
        calls["count"] += 1
        return {"ok": True, "result": f"sent to {args.get('to', '')}"}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="send_email",
            description="send email",
            fn=_send_email,
            schema={
                "to": "Destinatario (obligatorio)",
                "subject": "Asunto (obligatorio)",
            },
        )
    )
    cfg = ToolAgentConfig(
        use_claude=False,
        use_gemini=False,
        use_groq=False,
        dry_run_enabled=True,
        dry_run_ttl_seconds=120,
        dry_run_always_for=["send_email"],
    )
    agent = ToolAgent(
        config=cfg,
        registry=registry,
        confirm_context={"project_root": tmp_path, "data_dir": tmp_path / "data"},
    )
    return agent, calls


def test_send_email_returns_dry_run_and_no_execute_first_turn(tmp_path: Path) -> None:
    agent, calls = _build_agent(tmp_path)
    evt = agent._maybe_build_dry_run(  # noqa: SLF001
        "send_email",
        {"to": "ana@example.com", "subject": "hola"},
    )
    assert evt is not None
    assert evt["type"] == "dry_run"
    assert evt["requires_confirmation"] is True
    assert calls["count"] == 0


def test_confirm_yes_executes_pending_action(tmp_path: Path) -> None:
    agent, calls = _build_agent(tmp_path)
    evt = agent._maybe_build_dry_run(  # noqa: SLF001
        "send_email",
        {"to": "ana@example.com", "subject": "hola"},
    )
    assert evt is not None
    out = agent.run("sí")
    assert "Hecho" in out
    assert calls["count"] == 1


def test_confirm_no_discards_pending_action(tmp_path: Path) -> None:
    agent, calls = _build_agent(tmp_path)
    evt = agent._maybe_build_dry_run(  # noqa: SLF001
        "send_email",
        {"to": "ana@example.com", "subject": "hola"},
    )
    assert evt is not None
    out = agent.run("no")
    assert "Cancelado" in out
    assert calls["count"] == 0


def test_confirm_expired_pending_not_executed(tmp_path: Path) -> None:
    agent, calls = _build_agent(tmp_path)
    agent.config.dry_run_ttl_seconds = 1
    agent._pending_actions.ttl_seconds = 1  # noqa: SLF001
    evt = agent._maybe_build_dry_run(  # noqa: SLF001
        "send_email",
        {"to": "ana@example.com", "subject": "hola"},
    )
    assert evt is not None
    time.sleep(1.1)
    out = agent.run("sí")
    assert "no hay ninguna acción pendiente" in out.lower()
    assert calls["count"] == 0
