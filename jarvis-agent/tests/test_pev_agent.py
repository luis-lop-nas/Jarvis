"""
tests/test_pev_agent.py

Tests unitarios para el pipeline PEV (Planner → Executor → Verifier).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from jarvis.agent.pev_agent import PEVAgent
from jarvis.agent.pev_models import Plan, PlanStep, RunState, StepResult
from jarvis.agent.pev_state import RunStateStore
from jarvis.agent.tool_agent import ToolAgent, ToolAgentConfig, tool_agent_from_settings
from jarvis.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_cfg(**kwargs) -> ToolAgentConfig:
    defaults = dict(
        use_claude=False,
        use_gemini=False,
        use_groq=False,
        pev_enabled=True,
        pev_max_steps=6,
        pev_retry_max=1,
        verifier_enabled=False,
        tool_schema_validation_enabled=False,
        dry_run_enabled=False,
        confirm_policy_enabled=False,
    )
    defaults.update(kwargs)
    return ToolAgentConfig(**defaults)


def make_pev(registry=None, **kwargs) -> PEVAgent:
    return PEVAgent(config=make_cfg(**kwargs), registry=registry or ToolRegistry())


def _make_plan(steps=None, goal="test") -> Plan:
    return Plan(goal=goal, steps=steps or [])


def _step(sid="s1", tool_name="shell", action="run", **kwargs) -> PlanStep:
    return PlanStep(id=sid, tool_name=tool_name, action=action, **kwargs)


# ---------------------------------------------------------------------------
# 1. Plan JSON válido → modelo correcto
# ---------------------------------------------------------------------------

def test_plan_valid_json():
    raw = json.dumps({
        "goal": "buscar y mostrar hora",
        "steps": [
            {"id": "s1", "tool_name": "datetime", "action": "obtener hora", "args": {}}
        ],
    })
    agent = make_pev()
    plan = agent._parse_plan(raw)
    assert plan is not None
    assert plan.goal == "buscar y mostrar hora"
    assert len(plan.steps) == 1
    assert plan.steps[0].id == "s1"
    assert plan.steps[0].tool_name == "datetime"


# ---------------------------------------------------------------------------
# 2. JSON sin `steps` → ValidationError → _parse_plan retorna None
# ---------------------------------------------------------------------------

def test_plan_invalid_schema():
    raw = json.dumps({"goal": "algo"})  # falta 'steps'
    agent = make_pev()
    plan = agent._parse_plan(raw)
    assert plan is None


# ---------------------------------------------------------------------------
# 3. JSON malformado → _parse_plan retorna None
# ---------------------------------------------------------------------------

def test_plan_parsing_fallback():
    agent = make_pev()
    plan = agent._parse_plan("esto no es json {{{")
    assert plan is None


# ---------------------------------------------------------------------------
# 4. Plan con step sensible → pausa, tool NO llamada
# ---------------------------------------------------------------------------

def test_executor_pauses_for_sensitive_step():
    agent = make_pev(dry_run_enabled=True, confirm_policy_enabled=True)
    step = _step("s1", tool_name="send_email", action="Enviar correo", sensitive=True)
    plan = _make_plan([step])
    state = RunState(run_id="abc", session_key="default", plan=plan)

    with patch.object(agent._tool_agent, "_execute_tool") as mock_exec:
        result = agent._execute_plan(state)

    mock_exec.assert_not_called()
    assert "confirmación" in result.lower() or "procedo" in result.lower()


# ---------------------------------------------------------------------------
# 5. RunState con pending_confirmation → "sí" → tool llamada
# ---------------------------------------------------------------------------

def test_resume_after_affirmative():
    agent = make_pev()
    step = _step("s1", tool_name="datetime", action="ver hora")
    plan = _make_plan([step])
    state = RunState(
        run_id="abc", session_key="default", plan=plan,
        pending_confirmation_step="s1",
        pending_args={},
        current_step_idx=0,
    )
    agent._state_store.put("default", state)

    fake_output = {"ok": True, "data": {"time": "12:00"}}
    with patch.object(agent._tool_agent, "_execute_tool", return_value=fake_output):
        result = agent._resume("sí", agent._state_store.get("default"))

    assert result  # alguna respuesta generada (síntesis o fallback)


# ---------------------------------------------------------------------------
# 6. RunState con pending_confirmation → "no" → cancelado
# ---------------------------------------------------------------------------

def test_resume_after_negative():
    agent = make_pev()
    step = _step("s1", tool_name="send_email", action="enviar email")
    plan = _make_plan([step])
    state = RunState(
        run_id="abc", session_key="default", plan=plan,
        pending_confirmation_step="s1",
        pending_args={},
        current_step_idx=0,
    )
    agent._state_store.put("default", state)

    result = agent._resume("no", agent._state_store.get("default"))
    assert "cancelado" in result.lower()
    assert agent._state_store.get("default") is None


# ---------------------------------------------------------------------------
# 7. Step con requires_user_input=True → retorna pregunta
# ---------------------------------------------------------------------------

def test_ask_user_step_pauses():
    agent = make_pev()
    step = PlanStep(
        id="s1", tool_name=None,
        action="¿Cuál es tu nombre?",
        requires_user_input=True,
    )
    plan = _make_plan([step])
    state = RunState(run_id="abc", session_key="default", plan=plan)

    result = agent._execute_plan(state)

    assert "nombre" in result.lower() or result == step.action
    # Estado guardado con pending_user_input_step
    saved = agent._state_store.get("default")
    assert saved is not None
    assert saved.pending_user_input_step == "s1"


# ---------------------------------------------------------------------------
# 8. RunState con pending_user_input → user responde → continúa
# ---------------------------------------------------------------------------

def test_ask_user_step_resumes():
    agent = make_pev()
    ask_step = PlanStep(
        id="s1", tool_name=None, action="¿Cuál es tu nombre?",
        requires_user_input=True,
    )
    exec_step = _step("s2", tool_name="datetime", action="mostrar hora",
                       depends_on=[])
    plan = _make_plan([ask_step, exec_step])
    state = RunState(
        run_id="abc", session_key="default", plan=plan,
        pending_user_input_step="s1",
        current_step_idx=0,
    )
    agent._state_store.put("default", state)

    fake_output = {"ok": True}
    with patch.object(agent._tool_agent, "_execute_tool", return_value=fake_output):
        result = agent._resume("Luis", agent._state_store.get("default"))

    assert result  # plan continuó y sintetizó algo


# ---------------------------------------------------------------------------
# 9. Happy path — filesystem (tmp_path)
# ---------------------------------------------------------------------------

def test_happy_path_filesystem(tmp_path):
    registry = ToolRegistry()
    agent = make_pev(registry=registry)

    fake_out = {"ok": True, "written": str(tmp_path / "test.txt")}

    with patch.object(agent._tool_agent, "_execute_tool", return_value=fake_out) as mock_exec:
        step = _step("s1", tool_name="filesystem", action="escribir archivo",
                     args={"action": "write", "path": str(tmp_path / "test.txt"), "content": "hola"})
        plan = _make_plan([step])
        state = RunState(run_id="r1", session_key="default", plan=plan)
        result = agent._execute_plan(state)

    mock_exec.assert_called_once()
    assert result  # síntesis o fallback retornado


# ---------------------------------------------------------------------------
# 10. Plan con más steps que max → truncado
# ---------------------------------------------------------------------------

def test_max_steps_truncated():
    agent = make_pev(pev_max_steps=3)
    raw = json.dumps({
        "goal": "muchos pasos",
        "steps": [
            {"id": f"s{i}", "tool_name": "datetime", "action": f"paso {i}", "args": {}}
            for i in range(10)
        ],
    })
    plan = agent._parse_plan(raw)
    assert plan is not None
    assert len(plan.steps) == 3


# ---------------------------------------------------------------------------
# 11. Tool falla (retryable) → llamada 2 veces
# ---------------------------------------------------------------------------

def test_retry_on_retryable_failure():
    agent = make_pev(pev_retry_max=1)
    step = _step("s1", tool_name="web_search", action="buscar algo", args={"query": "test"})

    call_count = 0
    fake_ok = {"ok": True, "results": []}

    from jarvis.agent.verifier import VerifyReport

    def _fake_execute(tool_name, args):
        nonlocal call_count
        call_count += 1
        return {"ok": False, "error": "timeout"}

    with patch.object(agent._tool_agent, "_execute_tool", side_effect=_fake_execute):
        with patch("jarvis.agent.pev_agent.verify") as mock_verify:
            mock_verify.return_value = VerifyReport(
                status="fail", reason="timeout", retryable=True
            )
            result = agent._execute_with_retry(step, {"query": "test"}, "run1")

    assert call_count == 2  # intento 0 + retry 1
    assert result.status == "fail"


# ---------------------------------------------------------------------------
# 12. Tool falla ambos intentos → devuelve error, no bucle
# ---------------------------------------------------------------------------

def test_no_loop_after_max_retry():
    agent = make_pev(pev_retry_max=1)
    step = _step("s1", tool_name="web_search", action="buscar")

    from jarvis.agent.verifier import VerifyReport

    with patch.object(agent._tool_agent, "_execute_tool", return_value={"ok": False}):
        with patch("jarvis.agent.pev_agent.verify") as mock_verify:
            mock_verify.return_value = VerifyReport(
                status="fail", reason="error", retryable=True
            )
            result = agent._execute_with_retry(step, {}, "run1")

    assert result.status == "fail"
    assert mock_verify.call_count == 2  # retry_max=1 → 2 intentos total


# ---------------------------------------------------------------------------
# 13. pev_enabled=False → tool_agent_from_settings retorna ToolAgent
# ---------------------------------------------------------------------------

def test_pev_disabled_returns_tool_agent():
    settings = MagicMock()
    settings.pev_enabled = False
    settings.use_claude = False
    settings.use_gemini = False
    settings.use_groq = False
    settings.anthropic_api_key = ""
    settings.anthropic_model = "claude-sonnet-4-6"
    settings.gemini_api_key = ""
    settings.gemini_model = "gemini-2.0-flash"
    settings.groq_api_key = ""
    settings.groq_model = "llama-3.3-70b-versatile"
    settings.ollama_model = "llama3.2:3b"
    settings.debug = False
    settings.dry_run_enabled = False
    settings.dry_run_ttl_seconds = 120
    settings.dry_run_always_for = []
    settings.dry_run_max_items_list = 20
    settings.dry_run_snippet_chars = 300
    settings.confirm_policy_enabled = False
    settings.confirm_ttl_seconds = 120
    settings.confirm_always_for = []
    settings.shell_guard_enabled = False
    settings.shell_guard_mode = "strict"
    settings.shell_deny_patterns = []
    settings.shell_confirm_patterns = []
    settings.verifier_enabled = False
    settings.verifier_timeout_ms = 1500
    settings.verifier_max_items = 50
    settings.verifier_sample_if_over = 200
    settings.verifier_strict = False
    settings.tool_schema_validation_enabled = False
    settings.tool_schema_strict = False
    settings.tool_schema_log_invalid = False
    settings.pev_max_steps = 6
    settings.pev_retry_max = 1
    settings.pev_state_ttl_seconds = 600
    settings.pev_verbose_trace = False

    agent = tool_agent_from_settings(settings)
    assert isinstance(agent, ToolAgent)
    assert not isinstance(agent, PEVAgent)


# ---------------------------------------------------------------------------
# 14. pev_enabled=True → tool_agent_from_settings retorna PEVAgent
# ---------------------------------------------------------------------------

def test_pev_enabled_returns_pev_agent():
    settings = MagicMock()
    settings.pev_enabled = True
    settings.use_claude = False
    settings.use_gemini = False
    settings.use_groq = False
    settings.anthropic_api_key = ""
    settings.anthropic_model = "claude-sonnet-4-6"
    settings.gemini_api_key = ""
    settings.gemini_model = "gemini-2.0-flash"
    settings.groq_api_key = ""
    settings.groq_model = "llama-3.3-70b-versatile"
    settings.ollama_model = "llama3.2:3b"
    settings.debug = False
    settings.dry_run_enabled = False
    settings.dry_run_ttl_seconds = 120
    settings.dry_run_always_for = []
    settings.dry_run_max_items_list = 20
    settings.dry_run_snippet_chars = 300
    settings.confirm_policy_enabled = False
    settings.confirm_ttl_seconds = 120
    settings.confirm_always_for = []
    settings.shell_guard_enabled = False
    settings.shell_guard_mode = "strict"
    settings.shell_deny_patterns = []
    settings.shell_confirm_patterns = []
    settings.verifier_enabled = False
    settings.verifier_timeout_ms = 1500
    settings.verifier_max_items = 50
    settings.verifier_sample_if_over = 200
    settings.verifier_strict = False
    settings.tool_schema_validation_enabled = False
    settings.tool_schema_strict = False
    settings.tool_schema_log_invalid = False
    settings.pev_max_steps = 6
    settings.pev_retry_max = 1
    settings.pev_state_ttl_seconds = 600
    settings.pev_verbose_trace = False

    agent = tool_agent_from_settings(settings)
    assert isinstance(agent, PEVAgent)


# ---------------------------------------------------------------------------
# 15. Plan vacío → fallback a ToolAgent.run()
# ---------------------------------------------------------------------------

def test_empty_plan_falls_back_to_tool_agent():
    agent = make_pev()

    with patch.object(agent, "_plan", return_value=_make_plan([])):
        with patch.object(agent._tool_agent, "run", return_value="respuesta fallback") as mock_run:
            result = agent.run("hola")

    mock_run.assert_called_once()
    assert result == "respuesta fallback"


# ---------------------------------------------------------------------------
# 16. depends_on: s2 depende de s1 que falló → s2 skipped
# ---------------------------------------------------------------------------

def test_depends_on_skipped_if_dep_failed():
    agent = make_pev()
    s1 = _step("s1", tool_name="datetime", action="paso 1")
    s2 = _step("s2", tool_name="datetime", action="paso 2", depends_on=["s1"])
    plan = _make_plan([s1, s2])
    state = RunState(run_id="r1", session_key="default", plan=plan)

    # Simular que s1 ya falló (non-retryable) → _execute_plan lo vería cuando llega a s2
    # Para testear _execute_with_retry + fail directo:
    from jarvis.agent.verifier import VerifyReport

    call_count = 0

    def _fake_exec(tool_name, args):
        nonlocal call_count
        call_count += 1
        return {"ok": False, "error": "fallo s1"}

    with patch.object(agent._tool_agent, "_execute_tool", side_effect=_fake_exec):
        with patch("jarvis.agent.pev_agent.verify") as mock_verify:
            mock_verify.return_value = VerifyReport(
                status="fail", reason="fallo", retryable=False
            )
            result = agent._execute_plan(state)

    # s1 falla → plan se detiene con mensaje de error
    assert "s1" in result.lower() or "no pude" in result.lower() or "paso 1" in result.lower()
    # s2 nunca debería haberse intentado (plan se detiene en s1)
    assert call_count == 1


# ---------------------------------------------------------------------------
# 17. Sustitución de args entre pasos: {{s1.data.result}}
# ---------------------------------------------------------------------------

def test_arg_substitution():
    agent = make_pev()
    step_results = {
        "s1": StepResult(
            step_id="s1", status="ok",
            output={"data": {"result": "valor_resuelto"}},
        )
    }
    args = {"query": "{{s1.data.result}}", "literal": "sin cambio"}
    resolved = agent._substitute(args, step_results)
    assert resolved["query"] == "valor_resuelto"
    assert resolved["literal"] == "sin cambio"


# ---------------------------------------------------------------------------
# 18. intent_tracker delega al _tool_agent
# ---------------------------------------------------------------------------

def test_intent_tracker_delegates():
    agent = make_pev()
    assert agent.intent_tracker is agent._tool_agent.intent_tracker
