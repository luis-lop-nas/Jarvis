from __future__ import annotations

import queue
from unittest.mock import MagicMock

from jarvis.overlay.daemon import JarvisDaemon


def _make_daemon_stub() -> JarvisDaemon:
    daemon = JarvisDaemon.__new__(JarvisDaemon)
    daemon._trigger_queue = queue.Queue()
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
    daemon._handle_gesture_event("interrupt")
    daemon.interrupt.assert_called_once()


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
    daemon._handle_gesture_event("confirm")
    daemon._handle_gesture_event("yes")
    daemon._handle_gesture_event("no")

    daemon.submit_text.assert_any_call("sí, confirmo")
    daemon.submit_text.assert_any_call("sí")
    daemon.submit_text.assert_any_call("no, cancela")
