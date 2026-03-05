"""
tests/test_config_validation.py

Tests unitarios para la validación de settings en config.py.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from jarvis.config import Settings


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_settings(**kwargs) -> Settings:
    """Crea un Settings con todos los campos opcionales mínimos."""
    defaults = {
        "USE_CLAUDE": "false",
        "USE_GEMINI": "false",
        "USE_GROQ": "false",
    }
    defaults.update(kwargs)
    return Settings(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# wake_word_sensitivity — clampado a [0.0, 1.0]
# ─────────────────────────────────────────────────────────────────────────────

class TestWakeWordSensitivity:
    def test_clamped_high(self):
        s = make_settings(WAKE_WORD_SENSITIVITY="2.5")
        assert s.wake_word_sensitivity == 1.0

    def test_clamped_low(self):
        s = make_settings(WAKE_WORD_SENSITIVITY="-0.5")
        assert s.wake_word_sensitivity == 0.0

    def test_valid_middle(self):
        s = make_settings(WAKE_WORD_SENSITIVITY="0.7")
        assert s.wake_word_sensitivity == pytest.approx(0.7)

    def test_valid_zero(self):
        s = make_settings(WAKE_WORD_SENSITIVITY="0.0")
        assert s.wake_word_sensitivity == 0.0

    def test_valid_one(self):
        s = make_settings(WAKE_WORD_SENSITIVITY="1.0")
        assert s.wake_word_sensitivity == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# kokoro_speed — clampado a [0.5, 2.0]
# ─────────────────────────────────────────────────────────────────────────────

class TestKokoroSpeed:
    def test_clamped_too_fast(self):
        s = make_settings(KOKORO_SPEED="5.0")
        assert s.kokoro_speed == 2.0

    def test_clamped_too_slow(self):
        s = make_settings(KOKORO_SPEED="0.1")
        assert s.kokoro_speed == 0.5

    def test_valid_default(self):
        s = make_settings()
        assert s.kokoro_speed == pytest.approx(1.0)

    def test_valid_boundaries(self):
        s = make_settings(KOKORO_SPEED="0.5")
        assert s.kokoro_speed == pytest.approx(0.5)
        s2 = make_settings(KOKORO_SPEED="2.0")
        assert s2.kokoro_speed == pytest.approx(2.0)


# ─────────────────────────────────────────────────────────────────────────────
# gesture_cooldown — clampado a [0.1, 30.0]
# ─────────────────────────────────────────────────────────────────────────────

class TestGestureCooldown:
    def test_clamped_negative(self):
        s = make_settings(GESTURE_COOLDOWN="-1.0")
        assert s.gesture_cooldown == pytest.approx(0.1)

    def test_clamped_zero(self):
        s = make_settings(GESTURE_COOLDOWN="0.0")
        assert s.gesture_cooldown == pytest.approx(0.1)

    def test_clamped_too_large(self):
        s = make_settings(GESTURE_COOLDOWN="100.0")
        assert s.gesture_cooldown == pytest.approx(30.0)

    def test_valid(self):
        s = make_settings(GESTURE_COOLDOWN="2.5")
        assert s.gesture_cooldown == pytest.approx(2.5)


# ─────────────────────────────────────────────────────────────────────────────
# vad_silence_ms — clampado a [50, 3000]
# ─────────────────────────────────────────────────────────────────────────────

class TestVadSilenceMs:
    def test_clamped_low(self):
        s = make_settings(VAD_SILENCE_MS="10")
        assert s.vad_silence_ms == 50

    def test_clamped_high(self):
        s = make_settings(VAD_SILENCE_MS="9999")
        assert s.vad_silence_ms == 3000

    def test_valid_default(self):
        s = make_settings()
        assert s.vad_silence_ms == 350


# ─────────────────────────────────────────────────────────────────────────────
# camera_context_interval_s — clampado a [0.5, 60.0]
# ─────────────────────────────────────────────────────────────────────────────

class TestCameraContextInterval:
    def test_clamped_low(self):
        s = make_settings(CAMERA_CONTEXT_INTERVAL="0.1")
        assert s.camera_context_interval_s == pytest.approx(0.5)

    def test_clamped_high(self):
        s = make_settings(CAMERA_CONTEXT_INTERVAL="999.0")
        assert s.camera_context_interval_s == pytest.approx(60.0)

    def test_valid(self):
        s = make_settings(CAMERA_CONTEXT_INTERVAL="10.0")
        assert s.camera_context_interval_s == pytest.approx(10.0)


# ─────────────────────────────────────────────────────────────────────────────
# Literal types — deben lanzar ValidationError con valores inválidos
# ─────────────────────────────────────────────────────────────────────────────

class TestLiteralTypes:
    def test_tts_engine_invalid_raises(self):
        with pytest.raises(ValidationError):
            make_settings(TTS_ENGINE="invalid_engine")

    def test_tts_engine_valid(self):
        for engine in ("kokoro", "piper", "macos", "elevenlabs"):
            s = make_settings(TTS_ENGINE=engine)
            assert s.tts_engine == engine

    def test_stt_engine_invalid_raises(self):
        with pytest.raises(ValidationError):
            make_settings(STT_ENGINE="azure")

    def test_stt_engine_valid(self):
        for engine in ("groq", "local"):
            s = make_settings(STT_ENGINE=engine)
            assert s.stt_engine == engine

    def test_shell_guard_mode_invalid_raises(self):
        with pytest.raises(ValidationError):
            make_settings(SHELL_GUARD_MODE="ultrastrict")

    def test_shell_guard_mode_valid(self):
        for mode in ("strict", "permissive", "custom"):
            s = make_settings(SHELL_GUARD_MODE=mode)
            assert s.shell_guard_mode == mode

    def test_vad_engine_invalid_raises(self):
        with pytest.raises(ValidationError):
            make_settings(VAD_ENGINE="tensorflow")

    def test_vad_engine_valid(self):
        for engine in ("silero", "rms"):
            s = make_settings(VAD_ENGINE=engine)
            assert s.vad_engine == engine


# ─────────────────────────────────────────────────────────────────────────────
# Validación cross-field: API keys faltantes no crashean
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossFieldValidation:
    def test_claude_no_key_no_crash(self):
        """USE_CLAUDE=true sin ANTHROPIC_API_KEY → solo warning, no excepción."""
        s = make_settings(USE_CLAUDE="true", ANTHROPIC_API_KEY="")
        assert s.use_claude is True
        assert s.anthropic_api_key == ""

    def test_groq_no_key_no_crash(self):
        """USE_GROQ=true sin GROQ_API_KEY → solo warning, no excepción."""
        s = make_settings(USE_GROQ="true", GROQ_API_KEY="")
        assert s.use_groq is True
        assert s.groq_api_key == ""

    def test_valid_settings_no_error(self):
        """Settings completamente válido no lanza."""
        s = make_settings(
            USE_CLAUDE="true",
            ANTHROPIC_API_KEY="sk-ant-test",
            USE_GROQ="false",
        )
        assert s.use_claude is True
        assert s.anthropic_api_key == "sk-ant-test"
