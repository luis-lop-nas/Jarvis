"""
test_intent_tracker.py

Unit tests for the multi-step intent resolution system.

Run with:
    cd jarvis-agent
    source .venv/bin/activate
    PYTHONPATH=src pytest tests/test_intent_tracker.py -v
"""

from __future__ import annotations

import pytest

from jarvis.agent.intent_tracker import IntentTracker, PendingIntent
from jarvis.tools.registry import ToolRegistry, ToolSpec


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_email_registry() -> ToolRegistry:
    """Registry with send_email: 'to' and 'subject' are required, 'body' is not."""
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="send_email",
        description="Envía emails",
        fn=lambda args: {"ok": True},
        schema={
            "to": "Destinatario (obligatorio)",
            "subject": "Asunto (obligatorio)",
            "body": "Cuerpo del mensaje",          # NOT required
        },
    ))
    return registry


def _make_weather_registry() -> ToolRegistry:
    """Registry with weather: 'city' is required, 'days' is not."""
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="weather",
        description="Tiempo",
        fn=lambda args: {"ok": True},
        schema={
            "city": "Ciudad (obligatorio)",
            "days": "Días de pronóstico (opcional)",
        },
    ))
    return registry


def _make_no_required_registry() -> ToolRegistry:
    """Registry with open_app: no required params."""
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="open_app",
        description="Abre app",
        fn=lambda args: {"ok": True},
        schema={
            "app": "Nombre de la app",
            "target": "URL o archivo",
        },
    ))
    return registry


def _make_empty_schema_registry() -> ToolRegistry:
    """Registry with a tool that has no schema at all."""
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="spotify",
        description="Control Spotify",
        fn=lambda args: {"ok": True},
        schema=None,
    ))
    return registry


# ── PendingIntent properties ───────────────────────────────────────────────────

class TestPendingIntentProperties:
    def test_missing_computed_correctly(self):
        intent = PendingIntent(
            tool_name="send_email",
            required_params=["to", "subject"],
            collected={"to": "pedro@test.com"},
        )
        assert intent.missing == ["subject"]
        assert not intent.is_complete

    def test_is_complete_when_all_collected(self):
        intent = PendingIntent(
            tool_name="send_email",
            required_params=["to", "subject"],
            collected={"to": "pedro@test.com", "subject": "Hola"},
        )
        assert intent.missing == []
        assert intent.is_complete

    def test_whitespace_only_counts_as_missing(self):
        intent = PendingIntent(
            tool_name="send_email",
            required_params=["to"],
            collected={"to": "   "},
        )
        assert "to" in intent.missing

    def test_none_value_counts_as_missing(self):
        intent = PendingIntent(
            tool_name="send_email",
            required_params=["to"],
            collected={"to": None},
        )
        assert "to" in intent.missing

    def test_empty_string_counts_as_missing(self):
        intent = PendingIntent(
            tool_name="send_email",
            required_params=["to"],
            collected={"to": ""},
        )
        assert "to" in intent.missing


# ── check_tool_call ────────────────────────────────────────────────────────────

class TestCheckToolCall:
    def test_all_required_present_returns_none(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        result = tracker.check_tool_call(
            "send_email", {"to": "x@x.com", "subject": "Hola"}, registry
        )
        assert result is None

    def test_missing_required_returns_question_string(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        result = tracker.check_tool_call("send_email", {}, registry)
        assert isinstance(result, str)
        assert "?" in result

    def test_question_for_missing_to(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        # to is missing; subject provided
        result = tracker.check_tool_call("send_email", {"subject": "Hola"}, registry)
        assert result is not None
        assert "quién" in result.lower() or "para" in result.lower()

    def test_question_for_missing_subject(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        # subject is missing; to provided
        result = tracker.check_tool_call("send_email", {"to": "x@x.com"}, registry)
        assert result is not None
        assert "asunto" in result.lower()

    def test_optional_param_missing_is_ok(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        # body is NOT required
        result = tracker.check_tool_call(
            "send_email", {"to": "x@x.com", "subject": "Hola"}, registry
        )
        assert result is None

    def test_no_schema_returns_none(self):
        tracker = IntentTracker()
        registry = _make_empty_schema_registry()
        result = tracker.check_tool_call("spotify", {}, registry)
        assert result is None

    def test_no_required_params_returns_none(self):
        tracker = IntentTracker()
        registry = _make_no_required_registry()
        result = tracker.check_tool_call("open_app", {}, registry)
        assert result is None

    def test_unknown_tool_returns_none(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        result = tracker.check_tool_call("unknown_tool", {}, registry)
        assert result is None

    def test_sets_pending_on_missing_params(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        tracker.check_tool_call("send_email", {}, registry)
        assert tracker.is_pending()
        assert tracker._pending is not None
        assert tracker._pending.tool_name == "send_email"

    def test_clears_pending_when_all_present(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        # First call: missing params
        tracker.check_tool_call("send_email", {}, registry)
        assert tracker.is_pending()
        # Second call: all params present
        result = tracker.check_tool_call(
            "send_email", {"to": "x@x.com", "subject": "Hola"}, registry
        )
        assert result is None
        assert not tracker.is_pending()

    def test_accumulates_params_across_calls(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        # First call: only 'to' provided, 'subject' still missing
        q1 = tracker.check_tool_call("send_email", {"to": "x@x.com"}, registry)
        assert q1 is not None
        assert tracker._pending.collected.get("to") == "x@x.com"
        # Second call: 'subject' now provided (merged with previously collected 'to')
        q2 = tracker.check_tool_call("send_email", {"subject": "Hola"}, registry)
        assert q2 is None
        assert not tracker.is_pending()

    def test_switches_pending_to_different_tool(self):
        tracker = IntentTracker()
        email_reg = _make_email_registry()
        weather_reg = _make_weather_registry()
        # Collect for email
        tracker.check_tool_call("send_email", {}, email_reg)
        assert tracker._pending.tool_name == "send_email"
        # Now a different tool starts — pending switches
        tracker.check_tool_call("weather", {}, weather_reg)
        assert tracker._pending.tool_name == "weather"

    def test_weather_city_required(self):
        tracker = IntentTracker()
        registry = _make_weather_registry()
        q = tracker.check_tool_call("weather", {}, registry)
        assert q is not None
        assert "ciudad" in q.lower() or "city" in q.lower()

    def test_weather_city_present_returns_none(self):
        tracker = IntentTracker()
        registry = _make_weather_registry()
        result = tracker.check_tool_call("weather", {"city": "Madrid"}, registry)
        assert result is None


# ── analyze_llm_response ───────────────────────────────────────────────────────

class TestAnalyzeLLMResponse:
    def test_question_sets_dialog_mode(self):
        tracker = IntentTracker()
        tracker.analyze_llm_response("¿A quién quieres enviarlo?")
        assert tracker._dialog_mode
        assert tracker.is_pending()

    def test_statement_does_not_set_dialog_mode(self):
        tracker = IntentTracker()
        tracker.analyze_llm_response("He enviado el email correctamente.")
        assert not tracker._dialog_mode
        assert not tracker.is_pending()

    def test_statement_clears_existing_dialog_mode(self):
        tracker = IntentTracker()
        tracker._dialog_mode = True
        tracker.analyze_llm_response("Listo, done.")
        assert not tracker._dialog_mode

    def test_question_does_not_override_structural_pending(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        tracker.check_tool_call("send_email", {}, registry)   # sets _pending
        assert tracker._pending is not None
        assert not tracker._dialog_mode   # structural mode, not dialog
        # A question response should NOT set dialog mode when structural pending exists
        tracker.analyze_llm_response("¿A quién quieres enviarlo?")
        assert tracker._pending is not None  # structural pending preserved
        assert not tracker._dialog_mode      # dialog mode not set

    def test_multiline_response_ending_with_question(self):
        tracker = IntentTracker()
        tracker.analyze_llm_response(
            "Entendido. Puedo enviar el email.\n¿A quién va dirigido?"
        )
        assert tracker._dialog_mode

    def test_trailing_whitespace_does_not_block_detection(self):
        tracker = IntentTracker()
        tracker.analyze_llm_response("¿Cuál es el asunto?   ")
        assert tracker._dialog_mode


# ── get_context_injection ──────────────────────────────────────────────────────

class TestGetContextInjection:
    def test_returns_none_when_idle(self):
        tracker = IntentTracker()
        assert tracker.get_context_injection() is None

    def test_returns_none_for_dialog_mode_only(self):
        tracker = IntentTracker()
        tracker._dialog_mode = True
        # Dialog mode alone has no collected params to inject
        assert tracker.get_context_injection() is None

    def test_returns_context_when_pending(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        tracker.check_tool_call("send_email", {"to": "pedro@test.com"}, registry)
        ctx = tracker.get_context_injection()
        assert ctx is not None
        assert "send_email" in ctx
        assert "pedro@test.com" in ctx
        assert "subject" in ctx  # still missing

    def test_context_includes_all_missing_params(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        tracker.check_tool_call("send_email", {}, registry)
        ctx = tracker.get_context_injection()
        assert "to" in ctx
        assert "subject" in ctx

    def test_context_shows_ninguno_when_nothing_collected(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        tracker.check_tool_call("send_email", {}, registry)
        ctx = tracker.get_context_injection()
        assert "ninguno" in ctx


# ── get_followup_timeout ───────────────────────────────────────────────────────

class TestGetFollowupTimeout:
    def test_default_when_idle(self):
        tracker = IntentTracker()
        assert tracker.get_followup_timeout(default=6.0) == 6.0

    def test_extended_when_structural_pending(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        tracker.check_tool_call("send_email", {}, registry)
        assert tracker.get_followup_timeout(default=6.0) == IntentTracker.COLLECTING_TIMEOUT_S

    def test_extended_when_dialog_mode(self):
        tracker = IntentTracker()
        tracker._dialog_mode = True
        assert tracker.get_followup_timeout(default=6.0) == IntentTracker.COLLECTING_TIMEOUT_S

    def test_custom_default_respected(self):
        tracker = IntentTracker()
        assert tracker.get_followup_timeout(default=10.0) == 10.0


# ── on_tool_executed ───────────────────────────────────────────────────────────

class TestOnToolExecuted:
    def test_clears_matching_pending(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        tracker.check_tool_call("send_email", {}, registry)
        assert tracker.is_pending()
        tracker.on_tool_executed("send_email")
        assert not tracker.is_pending()
        assert tracker._pending is None

    def test_does_not_clear_different_tool_pending(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        tracker.check_tool_call("send_email", {}, registry)
        tracker.on_tool_executed("web_search")  # different tool
        assert tracker.is_pending()             # send_email still pending

    def test_clears_dialog_mode(self):
        tracker = IntentTracker()
        tracker._dialog_mode = True
        tracker.on_tool_executed("any_tool")
        assert not tracker._dialog_mode


# ── cancel ─────────────────────────────────────────────────────────────────────

class TestCancel:
    def test_clears_structural_pending(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        tracker.check_tool_call("send_email", {}, registry)
        tracker.cancel()
        assert tracker._pending is None
        assert not tracker.is_pending()

    def test_clears_dialog_mode(self):
        tracker = IntentTracker()
        tracker._dialog_mode = True
        tracker.cancel()
        assert not tracker._dialog_mode
        assert not tracker.is_pending()


# ── check_user_cancel ──────────────────────────────────────────────────────────

class TestCheckUserCancel:
    @pytest.mark.parametrize("text", [
        "cancela",
        "cancela eso",
        "cancelar",
        "olvídalo",
        "no importa",
        "déjalo",
        "déjalo estar",
        "CANCELA",
        "Cancela esto por favor",
    ])
    def test_detects_cancel_phrases(self, text: str):
        tracker = IntentTracker()
        tracker._dialog_mode = True
        result = tracker.check_user_cancel(text)
        assert result is True
        assert not tracker.is_pending()

    @pytest.mark.parametrize("text", [
        "pedro@example.com",
        "el asunto es reunión",
        "Madrid",
        "ls -la",
        "hola",
    ])
    def test_normal_input_not_cancel(self, text: str):
        tracker = IntentTracker()
        tracker._dialog_mode = True
        result = tracker.check_user_cancel(text)
        assert result is False
        assert tracker.is_pending()  # still pending

    def test_cancel_clears_structural_pending(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        tracker.check_tool_call("send_email", {}, registry)
        tracker.check_user_cancel("cancela esto")
        assert tracker._pending is None


# ── get_status_text ────────────────────────────────────────────────────────────

class TestGetStatusText:
    def test_none_when_idle(self):
        tracker = IntentTracker()
        assert tracker.get_status_text() is None

    def test_shows_tool_name_when_pending(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        tracker.check_tool_call("send_email", {}, registry)
        status = tracker.get_status_text()
        assert status is not None
        assert "send_email" in status

    def test_shows_missing_params_when_pending(self):
        tracker = IntentTracker()
        registry = _make_email_registry()
        tracker.check_tool_call("send_email", {}, registry)
        status = tracker.get_status_text()
        assert "to" in status or "subject" in status

    def test_shows_waiting_text_in_dialog_mode(self):
        tracker = IntentTracker()
        tracker._dialog_mode = True
        status = tracker.get_status_text()
        assert status is not None
        assert len(status) > 0


# ── Integration: full multi-step param collection flow ────────────────────────

class TestMultiStepFlow:
    def test_full_email_collection_flow(self):
        """Simulate: user asks to send email → tool called twice with
        progressive params → executes on second call when all present."""
        tracker = IntentTracker()
        registry = _make_email_registry()

        # Turn 1: user says "send email", LLM calls tool with empty params
        q1 = tracker.check_tool_call("send_email", {}, registry)
        assert q1 is not None  # asks for 'to'
        assert tracker.is_pending()
        assert tracker._pending.tool_name == "send_email"

        # LLM responded with a question
        tracker.analyze_llm_response(q1)
        assert tracker.is_pending()

        # Turn 2: user says "to pedro", LLM calls tool with to= but missing subject
        q2 = tracker.check_tool_call(
            "send_email", {"to": "pedro@example.com"}, registry
        )
        assert q2 is not None  # asks for 'subject'
        assert "asunto" in q2.lower()
        assert tracker._pending.collected["to"] == "pedro@example.com"

        # Turn 3: user says "subject is meeting", LLM calls tool with both
        q3 = tracker.check_tool_call(
            "send_email", {"subject": "Reunión"}, registry
        )
        assert q3 is None  # all required params now present
        assert not tracker.is_pending()

    def test_context_injection_grows_as_params_collected(self):
        tracker = IntentTracker()
        registry = _make_email_registry()

        tracker.check_tool_call("send_email", {}, registry)
        ctx1 = tracker.get_context_injection()
        assert "ninguno" in ctx1

        tracker.check_tool_call("send_email", {"to": "pedro@example.com"}, registry)
        ctx2 = tracker.get_context_injection()
        assert "pedro@example.com" in ctx2
        assert "ninguno" not in ctx2

    def test_followup_timeout_extended_during_collection(self):
        tracker = IntentTracker()
        registry = _make_email_registry()

        assert tracker.get_followup_timeout(default=6.0) == 6.0  # idle
        tracker.check_tool_call("send_email", {}, registry)
        assert tracker.get_followup_timeout(default=6.0) == 30.0  # collecting

        # After completing the intent
        tracker.check_tool_call(
            "send_email", {"to": "x@x.com", "subject": "Hola"}, registry
        )
        assert tracker.get_followup_timeout(default=6.0) == 6.0  # back to default
