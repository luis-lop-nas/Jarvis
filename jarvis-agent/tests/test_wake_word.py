from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from jarvis.voice.wake_word import OpenWakeWordListener, WakeWordConfig


def _listener(**kwargs) -> OpenWakeWordListener:
    base = dict(
        sensitivity=0.5,
        oww_min_rms=100.0,
        oww_min_consecutive_hits=2,
        oww_activation_cooldown_sec=1.5,
        oww_score_ema_alpha=1.0,  # simplifica test: sin suavizado
    )
    base.update(kwargs)
    cfg = WakeWordConfig(**base)
    return OpenWakeWordListener(cfg)


def test_requires_consecutive_hits():
    listener = _listener()
    with patch("time.monotonic", side_effect=[10.0, 10.1]):
        assert listener._update_detection_state(score=0.7, rms=200.0) is False
        assert listener._update_detection_state(score=0.8, rms=200.0) is True


def test_low_rms_never_triggers():
    listener = _listener()
    with patch("time.monotonic", side_effect=[10.0, 10.1, 10.2]):
        assert listener._update_detection_state(score=0.9, rms=20.0) is False
        assert listener._update_detection_state(score=0.9, rms=20.0) is False
        assert listener._update_detection_state(score=0.9, rms=20.0) is False


def test_cooldown_blocks_retrigger():
    listener = _listener()
    with patch("time.monotonic", side_effect=[10.0, 10.1, 10.2, 12.0, 12.1]):
        # primer trigger
        assert listener._update_detection_state(score=0.7, rms=200.0) is False
        assert listener._update_detection_state(score=0.7, rms=200.0) is True
        # en cooldown, no dispara
        assert listener._update_detection_state(score=0.9, rms=200.0) is False
        # pasado cooldown, vuelve a disparar con 2 hits
        assert listener._update_detection_state(score=0.9, rms=200.0) is False
        assert listener._update_detection_state(score=0.9, rms=200.0) is True


def test_single_hit_mode_triggers_immediately():
    listener = _listener(oww_min_consecutive_hits=1)
    with patch("time.monotonic", return_value=10.0):
        assert listener._update_detection_state(score=0.6, rms=200.0) is True


def test_resolve_input_device_falls_back_when_default_is_invalid():
    listener = _listener()
    fake_devices = [
        {"name": "Output only", "max_input_channels": 0},
        {"name": "Mic", "max_input_channels": 1},
    ]
    fake_default = SimpleNamespace(device=[-1, -1])

    with (
        patch("jarvis.voice.wake_word.sd.default", fake_default),
        patch("jarvis.voice.wake_word.sd.query_devices", side_effect=[fake_devices]),
    ):
        assert listener._resolve_input_device() == 1


def test_resolve_input_device_raises_when_no_input_devices_exist():
    listener = _listener()
    fake_default = SimpleNamespace(device=[-1, -1])

    with (
        patch("jarvis.voice.wake_word.sd.default", fake_default),
        patch("jarvis.voice.wake_word.sd.query_devices", return_value=[{"name": "Output", "max_input_channels": 0}]),
    ):
        try:
            listener._resolve_input_device()
        except RuntimeError as exc:
            assert "No encontré ningún dispositivo de entrada" in str(exc)
        else:
            raise AssertionError("Esperaba RuntimeError cuando no hay dispositivos de entrada")
