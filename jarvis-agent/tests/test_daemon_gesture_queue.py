from __future__ import annotations

import queue
from unittest.mock import MagicMock

from jarvis.overlay.daemon import JarvisDaemon


def _make_daemon_stub() -> JarvisDaemon:
    daemon = JarvisDaemon.__new__(JarvisDaemon)
    daemon._trigger_queue = queue.Queue()
    daemon._is_recording = False
    daemon.tts = MagicMock()
    daemon.tts.is_speaking = False
    daemon.agent = MagicMock()
    daemon.agent.has_pending_confirmation.return_value = False
    daemon.agent.intent_tracker = MagicMock()
    daemon.agent.intent_tracker.is_pending.return_value = False
    daemon.interrupt = MagicMock()
    daemon.pause_gesture = MagicMock()
    daemon.resume_gesture = MagicMock()
    daemon.trigger_voice_input = MagicMock()
    daemon.submit_text = MagicMock()
    return daemon


def test_enqueue_gesture_event_puts_item_in_queue():
    daemon = _make_daemon_stub()
    daemon.enqueue_gesture_event("interrupt")
    assert daemon._trigger_queue.get_nowait() == ("gesture", "interrupt")


def test_handle_gesture_event_interrupt():
    daemon = _make_daemon_stub()
    daemon.tts.is_speaking = True
    daemon._handle_gesture_event("interrupt")
    daemon.interrupt.assert_called_once()


def test_handle_gesture_event_interrupt_ignored_when_idle():
    daemon = _make_daemon_stub()
    daemon._handle_gesture_event("interrupt")
    daemon.interrupt.assert_not_called()


def test_handle_gesture_event_pause_resume_voice():
    daemon = _make_daemon_stub()
    daemon._handle_gesture_event("pause")
    daemon._handle_gesture_event("resume")
    daemon._handle_gesture_event("voice")

    daemon.pause_gesture.assert_called_once()
    daemon.resume_gesture.assert_called_once()
    daemon.trigger_voice_input.assert_called_once()


def test_handle_gesture_event_text_actions():
    daemon = _make_daemon_stub()
    daemon.agent.has_pending_confirmation.return_value = True
    daemon._handle_gesture_event("confirm")
    daemon._handle_gesture_event("yes")
    daemon._handle_gesture_event("no")

    daemon.submit_text.assert_any_call("sí, confirmo")
    daemon.submit_text.assert_any_call("sí")
    daemon.submit_text.assert_any_call("no, cancela")


def test_handle_gesture_event_text_actions_without_pending_are_ignored():
    daemon = _make_daemon_stub()
    daemon._handle_gesture_event("confirm")
    daemon._handle_gesture_event("yes")
    daemon._handle_gesture_event("no")
    daemon.submit_text.assert_not_called()
