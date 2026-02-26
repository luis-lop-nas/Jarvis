from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from jarvis.agent.tool_agent import ToolAgent, ToolAgentConfig
from jarvis.tools.registry import ToolRegistry, ToolSpec, build_default_registry


class _InModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


class _OutModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    data: dict
    message: str | None = None
    error: dict | None = None
    meta: dict | None = None


def _agent_with_registry(registry: ToolRegistry) -> ToolAgent:
    cfg = ToolAgentConfig(
        use_claude=False,
        use_gemini=False,
        use_groq=False,
        verifier_enabled=False,
        tool_schema_validation_enabled=True,
        tool_schema_strict=True,
    )
    return ToolAgent(config=cfg, registry=registry)


def test_input_invalid_blocks_execution() -> None:
    calls = {"count": 0}

    def _fn(args):
        calls["count"] += 1
        return {"ok": True, "data": {"echo": args["value"]}}

    reg = ToolRegistry()
    reg.register(ToolSpec(name="mock", description="mock", fn=_fn, input_model=_InModel, output_model=_OutModel))
    agent = _agent_with_registry(reg)
    out = agent._execute_tool("mock", {"value": "x"})  # noqa: SLF001
    assert out["type"] == "tool_validation_error"
    assert out["stage"] == "input"
    assert calls["count"] == 0


def test_output_invalid_reported() -> None:
    def _fn(args):
        return {"ok": True}  # falta data

    reg = ToolRegistry()
    reg.register(ToolSpec(name="mock", description="mock", fn=_fn, input_model=_InModel, output_model=_OutModel))
    agent = _agent_with_registry(reg)
    out = agent._execute_tool("mock", {"value": 1})  # noqa: SLF001
    assert out["type"] == "tool_validation_error"
    assert out["stage"] == "output"


def test_spot_check_filesystem_valid(tmp_path: Path) -> None:
    reg = build_default_registry()
    agent = _agent_with_registry(reg)
    safe_dir = Path.cwd() / ".pytest_schema_tmp"
    safe_dir.mkdir(parents=True, exist_ok=True)
    target = safe_dir / "x.txt"
    out = agent._execute_tool(  # noqa: SLF001
        "filesystem",
        {"action": "write_text", "path": str(target), "content": "hola"},
    )
    assert out.get("ok") is True
    assert target.exists()


def test_spot_check_shell_invalid_input() -> None:
    reg = build_default_registry()
    agent = _agent_with_registry(reg)
    out = agent._execute_tool("shell", {"cwd": "/tmp"})  # noqa: SLF001
    assert out["type"] == "tool_validation_error"
    assert out["stage"] == "input"


def test_spot_check_calendar_invalid_input() -> None:
    reg = build_default_registry()
    agent = _agent_with_registry(reg)
    out = agent._execute_tool("calendar", {"query": "x"})  # noqa: SLF001
    assert out["type"] == "tool_validation_error"
    assert out["stage"] == "input"


def test_spot_check_send_email_invalid_input() -> None:
    reg = build_default_registry()
    agent = _agent_with_registry(reg)
    out = agent._execute_tool("send_email", {"subject": "x"})  # noqa: SLF001
    assert out["type"] == "tool_validation_error"
    assert out["stage"] == "input"


def test_spot_check_download_file_invalid_input() -> None:
    reg = build_default_registry()
    agent = _agent_with_registry(reg)
    out = agent._execute_tool("download_file", {"url": "not-a-url"})  # noqa: SLF001
    assert out["type"] == "tool_validation_error"
    assert out["stage"] == "input"
