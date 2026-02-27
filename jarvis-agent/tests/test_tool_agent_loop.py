"""
tests/test_tool_agent_loop.py

Tests unitarios para la detección de loops y timeout global en ToolAgent._run_with_claude.
La API de Anthropic se mockea completamente — no se requiere API key real.
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jarvis.agent.tool_agent import ToolAgent, ToolAgentConfig
from jarvis.agent.state import AgentState


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_agent() -> ToolAgent:
    cfg = ToolAgentConfig(
        use_claude=True,
        claude_api_key="sk-ant-mock",
        max_tool_loops=8,
        dry_run_enabled=False,
        shell_guard_enabled=False,
        verifier_enabled=False,
        tool_schema_validation_enabled=False,
    )
    agent = ToolAgent(config=cfg)
    # Inyectar mock del cliente Claude
    agent.claude_client = MagicMock()
    agent.state = AgentState()
    agent.state.add_user("hola")
    return agent


def _text_response(text: str):
    """Simula una respuesta final de Claude (end_turn)."""
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(stop_reason="end_turn", content=[block])


def _tool_response(tool_name: str, tool_input: dict, tool_id: str = "tu_001"):
    """Simula una respuesta tool_use de Claude."""
    block = SimpleNamespace(
        type="tool_use",
        id=tool_id,
        name=tool_name,
        input=tool_input,
    )
    return SimpleNamespace(stop_reason="tool_use", content=[block])


# ─────────────────────────────────────────────────────────────────────────────
# Detección de loop — mismo tool dos veces seguidas
# ─────────────────────────────────────────────────────────────────────────────

class TestLoopDetection:
    def test_loop_detection_same_tool_twice(self):
        """El agente debe detectar el loop y retornar mensaje de ciclo."""
        agent = make_agent()

        # Primera llamada → tool_use con shell
        # Segunda llamada → mismo tool_use (loop!)
        tool_resp = _tool_response("shell", {"command": "ls"}, "tu_001")
        agent.claude_client.messages.create.return_value = tool_resp

        # Mock del registry para que el tool devuelva algo
        mock_tool_fn = MagicMock(return_value={"output": "file.txt", "returncode": 0})
        agent.registry._tools = {
            "shell": MagicMock(fn=mock_tool_fn, name="shell", schema={})
        }

        # Patch _execute_tool para no necesitar tools reales
        with patch.object(agent, "_execute_tool", return_value={"output": "ok"}):
            result = agent._run_with_claude("haz algo")

        assert "ciclo" in result.lower() or "mismas herramientas" in result.lower()

    def test_loop_detection_different_tools_no_break(self):
        """Tools distintos NO deben activar la detección de loop."""
        agent = make_agent()

        responses = [
            _tool_response("shell", {"command": "ls"}, "tu_001"),
            _tool_response("datetime", {}, "tu_002"),
            _text_response("Listo."),
        ]
        agent.claude_client.messages.create.side_effect = responses

        with patch.object(agent, "_execute_tool", return_value={"output": "ok"}):
            result = agent._run_with_claude("¿qué hora es?")

        # No debe detectar loop — debe llegar a la respuesta final
        assert "Listo." in result
        assert "ciclo" not in result.lower()

    def test_loop_detection_same_tool_different_args_no_break(self):
        """El mismo tool con args diferentes NO debe activar la detección."""
        agent = make_agent()

        responses = [
            _tool_response("shell", {"command": "ls"}, "tu_001"),
            _tool_response("shell", {"command": "pwd"}, "tu_002"),  # distintos args
            _text_response("Correcto."),
        ]
        agent.claude_client.messages.create.side_effect = responses

        with patch.object(agent, "_execute_tool", return_value={"output": "ok"}):
            result = agent._run_with_claude("muéstrame archivos y directorio")

        assert "Correcto." in result
        assert "ciclo" not in result.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Timeout global de 60 segundos
# ─────────────────────────────────────────────────────────────────────────────

class TestGlobalTimeout:
    def test_timeout_respected(self):
        """El bucle debe salir cuando se supera _MAX_LOOP_SECONDS."""
        agent = make_agent()

        call_count = 0

        def slow_create(**kwargs):
            nonlocal call_count
            call_count += 1
            # Primera llamada OK → tool_use
            return _tool_response("shell", {"command": f"cmd{call_count}"}, f"tu_{call_count:03d}")

        agent.claude_client.messages.create.side_effect = slow_create

        # Parchear time.monotonic para simular que ha pasado > 60s desde el segundo loop
        original_monotonic = time.monotonic
        call_index = [0]

        def fake_monotonic():
            call_index[0] += 1
            # Las primeras llamadas devuelven tiempo normal
            # Después del primer loop, simular que han pasado 65s
            if call_index[0] <= 2:
                return original_monotonic()
            return original_monotonic() + 65.0

        with patch.object(agent, "_execute_tool", return_value={"output": "ok"}):
            with patch("jarvis.agent.tool_agent.time") as mock_time:
                mock_time.monotonic = fake_monotonic
                result = agent._run_with_claude("haz algo")

        assert "máximo" in result.lower() or "tiempo" in result.lower()

    def test_max_loops_still_works(self):
        """8 iteraciones distintas (sin loop) completan normalmente."""
        agent = make_agent()

        # 7 tool calls diferentes + 1 respuesta final
        responses = [
            _tool_response(f"shell", {"command": f"cmd{i}"}, f"tu_{i:03d}")
            for i in range(7)
        ] + [_text_response("Todo completado.")]

        agent.claude_client.messages.create.side_effect = responses

        with patch.object(agent, "_execute_tool", return_value={"output": "ok"}):
            result = agent._run_with_claude("ejecuta varios comandos")

        assert "Todo completado." in result


# ─────────────────────────────────────────────────────────────────────────────
# Límite de iteraciones (max_tool_loops)
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxLoops:
    def test_max_loops_message(self):
        """Si se alcanzan las 8 iteraciones sin respuesta final → mensaje de límite."""
        agent = make_agent()
        agent.config.max_tool_loops = 3  # reducir para el test

        # Siempre responde tool_use con args distintos (sin loop, pero sin fin)
        call_count = [0]

        def always_tool(**kwargs):
            call_count[0] += 1
            return _tool_response("shell", {"command": f"cmd{call_count[0]}"}, f"tu_{call_count[0]}")

        agent.claude_client.messages.create.side_effect = always_tool

        with patch.object(agent, "_execute_tool", return_value={"output": "ok"}):
            result = agent._run_with_claude("loop infinito")

        assert "límite" in result.lower() or "iteraciones" in result.lower()
