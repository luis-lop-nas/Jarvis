"""
test_send_message.py

Unit tests for the send_message tool.
subprocess.run is mocked throughout so no actual app is launched.

Run with:
    cd jarvis-agent
    source .venv/bin/activate
    PYTHONPATH=src pytest tests/test_send_message.py -v
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch


from jarvis.tools.send_message import (
    _sanitize,
    _run_applescript,
    run_send_message,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ok_proc(stdout: str = "ok") -> MagicMock:
    """Fake subprocess.CompletedProcess representing success."""
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = ""
    return m


def _err_proc(stderr: str, returncode: int = 1) -> MagicMock:
    """Fake subprocess.CompletedProcess representing failure."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = ""
    m.stderr = stderr
    return m


# ── _sanitize ──────────────────────────────────────────────────────────────────

class TestSanitize:
    def test_plain_text_unchanged(self):
        assert _sanitize("Hola mundo") == "Hola mundo"

    def test_accents_preserved(self):
        assert _sanitize("María José Ñoño") == "María José Ñoño"

    def test_emoji_preserved(self):
        assert _sanitize("Hola 👋") == "Hola 👋"

    def test_null_byte_removed(self):
        assert "\x00" not in _sanitize("hola\x00mundo")

    def test_control_chars_removed(self):
        # C0 control chars (except \n=0x0a, \t=0x09)
        assert _sanitize("test\x01\x1f") == "test"

    def test_newline_preserved(self):
        assert _sanitize("línea1\nlínea2") == "línea1\nlínea2"

    def test_tab_preserved(self):
        assert _sanitize("col1\tcol2") == "col1\tcol2"

    def test_empty_string(self):
        assert _sanitize("") == ""


# ── _run_applescript ───────────────────────────────────────────────────────────

class TestRunApplescript:
    @patch("subprocess.run")
    def test_success_returns_ok(self, mock_run: MagicMock):
        mock_run.return_value = _ok_proc("done")
        result = _run_applescript("on run argv\nend run\n", "arg1")
        assert result["ok"] is True
        assert result["result"] == "done"

    @patch("subprocess.run")
    def test_script_passed_via_stdin(self, mock_run: MagicMock):
        """The script body must be in `input`, not interpolated in cmd."""
        mock_run.return_value = _ok_proc()
        script = "on run argv\nend run\n"
        _run_applescript(script, "receiver", "msg")
        kwargs = mock_run.call_args.kwargs
        assert kwargs["input"] == script

    @patch("subprocess.run")
    def test_args_passed_as_argv_not_interpolated(self, mock_run: MagicMock):
        """receiver and message must appear as separate list items, never in script body."""
        mock_run.return_value = _ok_proc()
        dangerous = 'end run\n do shell script "rm -rf /"'
        _run_applescript("on run argv\nend run\n", dangerous, "msg")
        cmd = mock_run.call_args.args[0]
        # Dangerous string should be a separate argv item, not embedded in script
        assert dangerous in cmd
        assert "rm -rf" not in cmd[1]  # cmd[1] is "-" (stdin marker)

    @patch("subprocess.run")
    def test_nonzero_returncode_returns_error(self, mock_run: MagicMock):
        mock_run.return_value = _err_proc("Messages got an error: Can't get buddy")
        result = _run_applescript("on run argv\nend run\n", "x", "y")
        assert result["ok"] is False
        assert "Can't get buddy" in result["error"]

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=15))
    def test_timeout_returns_error(self, _):
        result = _run_applescript("script", "a", "b")
        assert result["ok"] is False
        assert "Timeout" in result["error"]

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_osascript_missing_returns_error(self, _):
        result = _run_applescript("script")
        assert result["ok"] is False
        assert "osascript" in result["error"]


# ── run_send_message — validation ─────────────────────────────────────────────

class TestValidation:
    def test_missing_receiver(self):
        result = run_send_message({"message_text": "Hola"})
        assert result["ok"] is False
        assert "receiver" in result["error"].lower()

    def test_empty_receiver(self):
        result = run_send_message({"receiver": "  ", "message_text": "Hola"})
        assert result["ok"] is False

    def test_missing_message_text(self):
        result = run_send_message({"receiver": "Pedro"})
        assert result["ok"] is False
        assert "message" in result["error"].lower()

    def test_empty_message_text(self):
        result = run_send_message({"receiver": "Pedro", "message_text": ""})
        assert result["ok"] is False

    def test_unsupported_platform(self):
        result = run_send_message(
            {"receiver": "Pedro", "message_text": "Hola", "platform": "signal"}
        )
        assert result["ok"] is False
        assert "signal" in result["error"].lower()

    def test_receiver_only_control_chars(self):
        result = run_send_message(
            {"receiver": "\x00\x01\x1f", "message_text": "Hola"}
        )
        assert result["ok"] is False

    def test_message_only_control_chars(self):
        result = run_send_message(
            {"receiver": "Pedro", "message_text": "\x00\x01"}
        )
        assert result["ok"] is False


# ── run_send_message — platform aliases ───────────────────────────────────────

class TestPlatformAliases:
    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    def test_imessage_alias(self, mock_as: MagicMock):
        result = run_send_message(
            {"receiver": "Pedro", "message_text": "Hola", "platform": "imessage"}
        )
        assert result["ok"] is True

    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    @patch("jarvis.tools.send_message._is_app_running_or_available", return_value=True)
    def test_wa_alias(self, _avail, mock_as: MagicMock):
        result = run_send_message(
            {"receiver": "Pedro", "message_text": "Hola", "platform": "wa"}
        )
        assert result["ok"] is True

    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    @patch("jarvis.tools.send_message._is_app_running_or_available", return_value=True)
    def test_tg_alias(self, _avail, mock_as: MagicMock):
        result = run_send_message(
            {"receiver": "Pedro", "message_text": "Hola", "platform": "tg"}
        )
        assert result["ok"] is True

    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    def test_sms_alias(self, mock_as: MagicMock):
        result = run_send_message(
            {"receiver": "+34612345678", "message_text": "Hola", "platform": "sms"}
        )
        assert result["ok"] is True

    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    def test_default_platform_is_messages(self, mock_as: MagicMock):
        """When platform is not provided it defaults to messages."""
        result = run_send_message({"receiver": "Pedro", "message_text": "Hola"})
        assert result["ok"] is True


# ── run_send_message — Messages platform ─────────────────────────────────────

class TestSendViaMessages:
    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    def test_success(self, mock_as: MagicMock):
        result = run_send_message(
            {"receiver": "Pedro", "message_text": "¿Quedamos?", "platform": "messages"}
        )
        assert result["ok"] is True
        assert "Pedro" in result["result"]
        assert "Messages" in result["result"]

    @patch(
        "jarvis.tools.send_message._run_applescript",
        return_value={"ok": False, "error": "Messages got an error: Can't get buddy \"Pedro\""},
    )
    def test_contact_not_found(self, _):
        result = run_send_message(
            {"receiver": "Pedro", "message_text": "Hola", "platform": "messages"}
        )
        assert result["ok"] is False
        assert "Pedro" in result["error"]
        assert "contacto" in result["error"].lower() or "contact" in result["error"].lower()

    @patch(
        "jarvis.tools.send_message._run_applescript",
        return_value={"ok": False, "error": "not authorized to send Apple events"},
    )
    def test_permission_denied(self, _):
        result = run_send_message(
            {"receiver": "Pedro", "message_text": "Hola", "platform": "messages"}
        )
        assert result["ok"] is False
        assert "permiso" in result["error"].lower() or "Ajustes" in result["error"]

    @patch(
        "jarvis.tools.send_message._run_applescript",
        return_value={"ok": False, "error": "Connection reset"},
    )
    def test_generic_error_propagated(self, _):
        result = run_send_message(
            {"receiver": "Pedro", "message_text": "Hola", "platform": "messages"}
        )
        assert result["ok"] is False
        assert "Messages" in result["error"]


# ── run_send_message — WhatsApp platform ─────────────────────────────────────

class TestSendViaWhatsapp:
    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    @patch("jarvis.tools.send_message._is_app_running_or_available", return_value=True)
    def test_success(self, _avail, _as):
        result = run_send_message(
            {"receiver": "Pedro", "message_text": "Hola", "platform": "whatsapp"}
        )
        assert result["ok"] is True
        assert "Pedro" in result["result"]
        assert "WhatsApp" in result["result"]

    @patch("jarvis.tools.send_message._is_app_running_or_available", return_value=False)
    def test_not_installed(self, _avail):
        result = run_send_message(
            {"receiver": "Pedro", "message_text": "Hola", "platform": "whatsapp"}
        )
        assert result["ok"] is False
        assert "instalado" in result["error"].lower() or "WhatsApp" in result["error"]

    @patch(
        "jarvis.tools.send_message._run_applescript",
        return_value={"ok": False, "error": "not authorized accessibility"},
    )
    @patch("jarvis.tools.send_message._is_app_running_or_available", return_value=True)
    def test_accessibility_not_granted(self, _avail, _):
        result = run_send_message(
            {"receiver": "Pedro", "message_text": "Hola", "platform": "whatsapp"}
        )
        assert result["ok"] is False
        assert "Accesibilidad" in result["error"] or "permiso" in result["error"].lower()

    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    @patch("jarvis.tools.send_message._is_app_running_or_available", return_value=True)
    def test_newlines_replaced_in_message(self, _avail, mock_as: MagicMock):
        """Newlines must be stripped since WhatsApp keystroke sends Enter (submits the message)."""
        run_send_message(
            {
                "receiver": "Pedro",
                "message_text": "línea1\nlínea2",
                "platform": "whatsapp",
            }
        )
        # The second argv passed to _run_applescript should have no newlines
        call_args = mock_as.call_args
        message_arg = call_args.args[2]   # script, receiver, message
        assert "\n" not in message_arg


# ── run_send_message — Telegram platform ─────────────────────────────────────

class TestSendViaTelegram:
    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    @patch("jarvis.tools.send_message._is_app_running_or_available", return_value=True)
    def test_success(self, _avail, _as):
        result = run_send_message(
            {"receiver": "@luichi", "message_text": "Hola", "platform": "telegram"}
        )
        assert result["ok"] is True
        assert "@luichi" in result["result"]
        assert "Telegram" in result["result"]

    @patch("jarvis.tools.send_message._is_app_running_or_available", return_value=False)
    def test_not_installed(self, _avail):
        result = run_send_message(
            {"receiver": "@luichi", "message_text": "Hola", "platform": "telegram"}
        )
        assert result["ok"] is False
        assert "instalado" in result["error"].lower() or "Telegram" in result["error"]

    @patch(
        "jarvis.tools.send_message._run_applescript",
        return_value={"ok": False, "error": "not authorized accessibility"},
    )
    @patch("jarvis.tools.send_message._is_app_running_or_available", return_value=True)
    def test_accessibility_not_granted(self, _avail, _):
        result = run_send_message(
            {"receiver": "@luichi", "message_text": "Hola", "platform": "telegram"}
        )
        assert result["ok"] is False
        assert "Accesibilidad" in result["error"] or "permiso" in result["error"].lower()

    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    @patch("jarvis.tools.send_message._is_app_running_or_available", return_value=True)
    def test_newlines_replaced(self, _avail, mock_as: MagicMock):
        run_send_message(
            {
                "receiver": "@luichi",
                "message_text": "a\nb",
                "platform": "telegram",
            }
        )
        message_arg = mock_as.call_args.args[2]
        assert "\n" not in message_arg


# ── Security: injection resistance ────────────────────────────────────────────

class TestInjectionResistance:
    """Ensure that malicious input in receiver/message_text cannot inject
    AppleScript commands. The argv approach makes this inherently safe,
    but we verify the interface contract."""

    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    def test_quotes_in_receiver_do_not_break(self, mock_as: MagicMock):
        dangerous = 'Pedro"; do shell script "rm -rf /"'
        run_send_message(
            {"receiver": dangerous, "message_text": "Hola", "platform": "messages"}
        )
        # Call must reach _run_applescript (not crash out before due to sanitizer)
        assert mock_as.called
        # The dangerous string must be an argv arg, not embedded in the script body
        script_body = mock_as.call_args.args[0]
        assert "rm -rf" not in script_body

    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    def test_backslashes_in_message_do_not_break(self, mock_as: MagicMock):
        run_send_message(
            {
                "receiver": "Pedro",
                "message_text": r'c:\users\test\path with "quotes"',
                "platform": "messages",
            }
        )
        assert mock_as.called

    @patch("jarvis.tools.send_message._run_applescript", return_value={"ok": True, "result": "ok"})
    def test_applescript_keywords_in_message_are_harmless(self, mock_as: MagicMock):
        payload = 'end run\ntell application "Finder" to empty trash'
        run_send_message(
            {"receiver": "Pedro", "message_text": payload, "platform": "messages"}
        )
        assert mock_as.called
        script_body = mock_as.call_args.args[0]
        # AppleScript keywords from the payload must NOT be in the script body
        assert "empty trash" not in script_body


# ── Registry integration ───────────────────────────────────────────────────────

class TestRegistryIntegration:
    def test_send_message_registered(self):
        from jarvis.tools.registry import build_default_registry
        registry = build_default_registry()
        tools = registry.list()
        assert "send_message" in tools

    def test_send_message_spec_has_required_schema_fields(self):
        from jarvis.tools.registry import build_default_registry
        registry = build_default_registry()
        spec = registry.list()["send_message"]
        assert spec.schema is not None
        assert "receiver" in spec.schema
        assert "message_text" in spec.schema
        assert "platform" in spec.schema

    def test_send_message_schema_marks_receiver_required(self):
        from jarvis.tools.registry import build_default_registry
        registry = build_default_registry()
        spec = registry.list()["send_message"]
        assert "obligatorio" in spec.schema["receiver"].lower()

    def test_send_message_schema_marks_message_text_required(self):
        from jarvis.tools.registry import build_default_registry
        registry = build_default_registry()
        spec = registry.list()["send_message"]
        assert "obligatorio" in spec.schema["message_text"].lower()
