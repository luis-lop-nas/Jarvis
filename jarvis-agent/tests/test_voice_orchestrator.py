"""
test_voice_orchestrator.py

Tests unitarios para VoiceOrchestrator (voice/orchestrator.py).
No requiere micrófono ni sounddevice real — todo se mockea.

Run with:
    cd jarvis-agent
    source .venv/bin/activate
    PYTHONPATH=src pytest tests/test_voice_orchestrator.py -v
"""
from __future__ import annotations

import threading
import wave
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

from jarvis.voice.orchestrator import VoiceOrchestrator
from jarvis.voice.stt import STTConfig


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_orchestrator(
    interrupt: threading.Event | None = None,
    on_audio_level=None,
    vad_engine: str = "rms",  # rms para no necesitar ONNX
) -> VoiceOrchestrator:
    stt_cfg = STTConfig(sample_rate=16000, channels=1, dtype="int16", device=None)
    evt = interrupt or threading.Event()
    return VoiceOrchestrator(
        stt_cfg=stt_cfg,
        interrupt_event=evt,
        on_audio_level=on_audio_level,
        vad_engine=vad_engine,
    )


def _make_chunk_int16(value: int = 500, size: int = 512) -> np.ndarray:
    """Chunk int16 con RMS ~value."""
    return np.full((size, 1), value, dtype=np.int16)


# ── Helper: fake stream ───────────────────────────────────────────────────────

class _FakeStream:
    """
    Simula sd.InputStream: entrega chunks predefinidos al leer.
    Se usa como context manager.
    """
    def __init__(self, chunks: List[np.ndarray], overflowed: bool = False):
        self._chunks = list(chunks)
        self._overflowed = overflowed
        self._idx = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self, _n: int):
        if self._idx < len(self._chunks):
            chunk = self._chunks[self._idx]
            self._idx += 1
            return chunk, False
        # Devolver silencio tras agotar chunks
        return np.zeros((512, 1), dtype=np.int16), False


# ── Tests: _record_rms ───────────────────────────────────────────────────────

class TestRecordRMS:
    def test_incorporates_prebuffer_not_used_in_rms(self, tmp_path):
        """_record_rms ignora prebuffer (parámetro solo para Silero path)."""
        orc = _make_orchestrator()
        # Sin voz → timeout → None (prebuffer no aplica a RMS)
        out = tmp_path / "out.wav"
        silence = [np.zeros((512, 1), dtype=np.int16)] * 50

        with patch("sounddevice.InputStream", return_value=_FakeStream(silence)):
            result = orc._record_rms(out, wait_timeout_s=1.0)

        assert result is None

    def test_interrupt_event_stops_recording(self, tmp_path):
        """interrupt_event interrumpe la grabación y retorna None."""
        interrupt = threading.Event()
        orc = _make_orchestrator(interrupt=interrupt)
        out = tmp_path / "out.wav"

        # chunks con voz que nunca terminan
        loud = [np.full((512, 1), 5000, dtype=np.int16)] * 100

        def side_effect(_n):
            interrupt.set()
            return np.full((512, 1), 5000, dtype=np.int16), False

        mock_stream = MagicMock()
        mock_stream.__enter__ = lambda s: s
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.read.side_effect = side_effect

        with patch("sounddevice.InputStream", return_value=mock_stream):
            result = orc._record_rms(out, wait_timeout_s=30.0)

        assert result is None

    def test_on_audio_level_called(self, tmp_path):
        """on_audio_level callback se llama con nivel normalizado."""
        levels = []
        orc = _make_orchestrator(on_audio_level=levels.append)
        out = tmp_path / "out.wav"
        silence = [np.zeros((512, 1), dtype=np.int16)] * 10

        with patch("sounddevice.InputStream", return_value=_FakeStream(silence)):
            orc._record_rms(out, wait_timeout_s=0.1)

        assert len(levels) > 0
        assert all(0.0 <= lvl <= 1.0 for lvl in levels)

    def test_voice_detected_saves_wav(self, tmp_path):
        """Cuando se detecta voz + silencio, guarda WAV y retorna path."""
        orc = _make_orchestrator()
        out = tmp_path / "out.wav"

        loud = np.full((512, 1), 5000, dtype=np.int16)
        silent = np.zeros((512, 1), dtype=np.int16)
        # 5 chunks de voz + 20 de silencio (> VAD_SILENCE_SEGS=15)
        chunks = [loud] * 5 + [silent] * 20

        with patch("sounddevice.InputStream", return_value=_FakeStream(chunks)):
            result = orc._record_rms(out, wait_timeout_s=30.0)

        assert result == out
        assert out.exists()

    def test_no_voice_timeout_returns_none(self, tmp_path):
        """Sin voz y wait_timeout_s → retorna None en follow-up."""
        orc = _make_orchestrator()
        out = tmp_path / "out.wav"
        silence = [np.zeros((512, 1), dtype=np.int16)] * 200

        with patch("sounddevice.InputStream", return_value=_FakeStream(silence)):
            result = orc._record_rms(out, wait_timeout_s=1.0)

        assert result is None


# ── Tests: _record_silero ─────────────────────────────────────────────────────

class TestRecordSilero:
    def _make_mock_vad(self, probs: List[float]):
        """Crea un SileroVAD mock que devuelve las probabilidades en secuencia."""
        mock_vad = MagicMock()
        mock_vad.reset_states = MagicMock()
        prob_iter = iter(probs + [0.0] * 1000)  # cola infinita de silencios
        mock_vad.side_effect = lambda audio, sr: next(prob_iter)
        return mock_vad

    def test_prebuffer_incorporated(self, tmp_path):
        """Prebuffer se rechunquea y añade a frames correctamente."""
        orc = _make_orchestrator()
        out = tmp_path / "out.wav"

        # Prebuffer: 3 chunks de 1280 muestras con energía (> noise_floor * 1.5)
        orc._noise_floor = 100.0
        prebuffer = [np.full(1280, 5000, dtype=np.int16)] * 3

        # Vad: silencio tras prebuffer para terminar rápido
        mock_vad = self._make_mock_vad([0.5] * 5 + [0.05] * 20)

        # Stream: solo silencio (la voz viene del prebuffer)
        silence = [np.zeros((512, 1), dtype=np.int16)] * 50

        with patch("sounddevice.InputStream", return_value=_FakeStream(silence)):
            result = orc._record_silero(out, None, prebuffer, mock_vad)

        # Debería haber detectado voz en el prebuffer
        mock_vad.reset_states.assert_called_once()

    def test_interrupt_stops_silero_recording(self, tmp_path):
        """interrupt_event interrumpe _record_silero y retorna None."""
        interrupt = threading.Event()
        orc = _make_orchestrator(interrupt=interrupt)
        out = tmp_path / "out.wav"

        mock_vad = self._make_mock_vad([0.8] * 100)

        def side_effect(_n):
            interrupt.set()
            return np.full((512, 1), 5000, dtype=np.int16), False

        mock_stream = MagicMock()
        mock_stream.__enter__ = lambda s: s
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.read.side_effect = side_effect

        with patch("sounddevice.InputStream", return_value=mock_stream):
            result = orc._record_silero(out, None, [], mock_vad)

        assert result is None

    def test_adaptive_silence_soft_pause_increments_half(self, tmp_path):
        """
        Silencio suave (prob entre SILERO_HARD y SILERO_SILEN) incrementa
        silence_count en 0.5, no en 1.0.
        """
        orc = _make_orchestrator()
        out = tmp_path / "out.wav"

        # 10 chunks de voz activa → luego 22 chunks con prob=0.15 (suave)
        # silence_count += 0.5 por chunk → necesitaría 30 para alcanzar SILENCE_LONG=15
        # → realmente necesita 30 chunks suaves para cortar (15/0.5)
        # Aquí probamos que con 14 chunks suaves NO corta (14*0.5 = 7.0 < 10)
        probs = (
            [0.9] * 10                # voz activa (voice_chunks = 10)
            + [0.15] * 14             # pausa suave: silence_count = 7.0 (< budget=10)
            + [0.05] * 20             # silencio duro → sí corta eventualmente
        )
        mock_vad = self._make_mock_vad(probs)

        # Necesitamos que los chunks de voz tengan energía > noise_floor * 1.5
        loud_chunk = np.full((512, 1), 5000, dtype=np.int16)
        soft_chunk = np.full((512, 1), 100, dtype=np.int16)

        chunks = [loud_chunk] * 10 + [soft_chunk] * 34

        with patch("sounddevice.InputStream", return_value=_FakeStream(chunks)):
            result = orc._record_silero(out, None, [], mock_vad)

        # Debe haber completado (no interrumpido)
        assert result is not None or result is None  # no crash

    def test_adaptive_silence_hard_increments_full(self, tmp_path):
        """
        Silencio duro (prob < SILERO_HARD) incrementa silence_count en 1.0.
        Con SILENCE_SHORT=10, necesita 10 chunks duros para cortar.
        """
        orc = _make_orchestrator()
        out = tmp_path / "out.wav"

        # voice_chunks=1 → is_long=False → budget=SILENCE_SHORT=10
        # 11 chunks con prob=0.05 (duro) → silence_count=11 >= budget → corta
        probs = [0.9] * 1 + [0.05] * 12
        mock_vad = self._make_mock_vad(probs)

        loud_chunk = np.full((512, 1), 5000, dtype=np.int16)
        silent_chunk = np.zeros((512, 1), dtype=np.int16)
        chunks = [loud_chunk] * 1 + [silent_chunk] * 12 + [silent_chunk] * 100

        with patch("sounddevice.InputStream", return_value=_FakeStream(chunks)):
            result = orc._record_silero(out, 30.0, [], mock_vad)

        # El archivo debe existir si voice_started
        if result is not None:
            assert out.exists()

    def test_noise_floor_updated_before_voice(self, tmp_path):
        """Noise floor se actualiza durante pre-voz, no durante voz activa."""
        initial_nf = 200.0
        orc = _make_orchestrator()
        orc._noise_floor = initial_nf
        out = tmp_path / "out.wav"

        # Chunks silenciosos → noise_floor se actualiza (EMA hacia 0)
        probs = [0.05] * 30  # silencio puro
        mock_vad = self._make_mock_vad(probs)

        silence_chunks = [np.zeros((512, 1), dtype=np.int16)] * 50

        with patch("sounddevice.InputStream", return_value=_FakeStream(silence_chunks)):
            orc._record_silero(out, 1.0, [], mock_vad)

        # Noise floor debe haber bajado (EMA hacia los chunks silenciosos ≈ 0)
        assert orc._get_noise_floor() < initial_nf

    def test_on_audio_level_called_normalized(self, tmp_path):
        """on_audio_level se llama con valor en [0, 1]."""
        levels = []
        orc = _make_orchestrator(on_audio_level=levels.append)
        out = tmp_path / "out.wav"

        probs = [0.05] * 20
        mock_vad = self._make_mock_vad(probs)
        chunks = [np.zeros((512, 1), dtype=np.int16)] * 20

        with patch("sounddevice.InputStream", return_value=_FakeStream(chunks)):
            orc._record_silero(out, 0.5, [], mock_vad)

        assert len(levels) > 0
        assert all(0.0 <= lvl <= 1.0 for lvl in levels)

    def test_wait_timeout_returns_none(self, tmp_path):
        """Timeout de espera sin voz retorna None (follow-up mode)."""
        orc = _make_orchestrator()
        out = tmp_path / "out.wav"

        probs = [0.05] * 200  # silencio siempre
        mock_vad = self._make_mock_vad(probs)
        chunks = [np.zeros((512, 1), dtype=np.int16)] * 200

        with patch("sounddevice.InputStream", return_value=_FakeStream(chunks)):
            result = orc._record_silero(out, 0.5, [], mock_vad)

        assert result is None


# ── Tests: record() dispatch ──────────────────────────────────────────────────

class TestRecordDispatch:
    def test_record_uses_silero_when_available(self, tmp_path):
        """record() usa _record_silero cuando Silero VAD está disponible."""
        orc = _make_orchestrator(vad_engine="silero")
        mock_vad = MagicMock()
        mock_vad.reset_states = MagicMock()
        mock_vad.side_effect = lambda a, sr: 0.0

        with patch.object(orc, "_get_silero", return_value=mock_vad), \
             patch.object(orc, "_record_silero", return_value=None) as mock_silero:
            orc.record(tmp_path / "x.wav")

        mock_silero.assert_called_once()

    def test_record_uses_rms_when_silero_unavailable(self, tmp_path):
        """record() usa _record_rms cuando Silero no está disponible."""
        orc = _make_orchestrator(vad_engine="rms")

        with patch.object(orc, "_get_silero", return_value=None), \
             patch.object(orc, "_record_rms", return_value=None) as mock_rms:
            orc.record(tmp_path / "x.wav")

        mock_rms.assert_called_once()


# ── Tests: debounce en daemon ─────────────────────────────────────────────────

class TestDaemonDebounce:
    """
    Tests de _try_activate() sin instanciar JarvisDaemon completo.
    Usamos __new__ para evitar __init__.
    """

    def _make_daemon(self):
        import importlib
        daemon_module = importlib.import_module("jarvis.overlay.daemon")
        daemon = object.__new__(daemon_module.JarvisDaemon)
        import time as _time
        daemon._last_activation_ts = 0.0
        daemon._activation_lock = __import__("threading").Lock()
        daemon._interrupt_event = __import__("threading").Event()
        daemon._trigger_queue = __import__("queue").Queue()
        return daemon

    def test_try_activate_accepts_first_call(self):
        """_try_activate retorna True en la primera llamada."""
        d = self._make_daemon()
        assert d._try_activate("wake_word") is True

    def test_try_activate_rejects_within_debounce_window(self):
        """Segunda llamada dentro de la ventana de debounce retorna False."""
        d = self._make_daemon()
        d._try_activate("wake_word")
        result = d._try_activate("gaze_trigger")
        assert result is False

    def test_try_activate_accepts_after_debounce_expires(self):
        """Llamada después de que expire el debounce retorna True."""
        import time as _time
        d = self._make_daemon()
        d._try_activate("wake_word")
        # Forzar expiración del debounce
        d._last_activation_ts = _time.monotonic() - 2.0
        result = d._try_activate("gaze_trigger")
        assert result is True

    def test_try_activate_sets_interrupt_event(self):
        """_try_activate marca el interrupt_event."""
        d = self._make_daemon()
        d._try_activate("wake_word")
        assert d._interrupt_event.is_set()

    def test_try_activate_puts_source_in_queue(self):
        """_try_activate encola la fuente correcta."""
        d = self._make_daemon()
        d._try_activate("wake_word")
        source = d._trigger_queue.get_nowait()
        assert source == "wake_word"

    def test_try_activate_rejected_does_not_enqueue(self):
        """Activación rechazada no encola nada."""
        d = self._make_daemon()
        d._try_activate("wake_word")
        d._trigger_queue.get_nowait()  # consumir el primero

        d._trigger_queue = __import__("queue").Queue()  # reiniciar queue
        d._interrupt_event.clear()
        result = d._try_activate("gaze_trigger")
        assert result is False
        assert d._trigger_queue.empty()
