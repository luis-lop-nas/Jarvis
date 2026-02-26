from __future__ import annotations

from pathlib import Path

from jarvis.agent.tool_agent import ToolAgent, ToolAgentConfig
from jarvis.tools.registry import ToolRegistry, ToolSpec


def test_tool_execute_passes_verifier(tmp_path: Path) -> None:
    target = tmp_path / "v.txt"

    def _fs(args):
        content = str(args.get("content", ""))
        target.write_text(content, encoding="utf-8")
        return {"action": "write_text", "path": str(target), "bytes": len(content.encode("utf-8"))}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="filesystem",
            description="filesystem",
            fn=_fs,
            schema={"action": "accion", "path": "path"},
        )
    )
    cfg = ToolAgentConfig(
        use_claude=False,
        use_gemini=False,
        use_groq=False,
        verifier_enabled=True,
    )
    agent = ToolAgent(config=cfg, registry=registry)
    out = agent._execute_tool("filesystem", {"action": "write_text", "path": str(target), "content": "hola"})  # noqa: SLF001
    assert out.get("verified") is True
    assert out.get("verify_report", {}).get("status") == "ok"
