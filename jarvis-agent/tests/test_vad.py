"""
test_vad.py

Tests unitarios para SileroVAD (voice/vad.py).
No requiere onnxruntime real — todo se mockea.

Run with:
    cd jarvis-agent
    source .venv/bin/activate
    PYTHONPATH=src pytest tests/test_vad.py -v
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ── Reset singleton entre tests ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    """Limpia el singleton de SileroVAD antes y después de cada test."""
    from jarvis.voice import vad as vad_module
    vad_module.SileroVAD._instance = None
    yield
    vad_module.SileroVAD._instance = None


# ── Tests: load() ─────────────────────────────────────────────────────────────

class TestSileroVADLoad:
    def test_load_returns_none_when_onnx_missing(self):
        """load() retorna None cuando el ONNX no existe."""
        from jarvis.voice.vad import SileroVAD

        with patch.object(Path, "exists", return_value=False):
            result = SileroVAD.load()

        assert result is None

    def test_load_returns_none_when_onnxruntime_unavailable(self):
        """load() retorna None cuando onnxruntime no está instalado."""
        from jarvis.voice.vad import SileroVAD

        with patch.object(Path, "exists", return_value=True), \
             patch("builtins.__import__", side_effect=ImportError("no onnxruntime")):
            result = SileroVAD.load()

        assert result is None

    def test_singleton_same_instance(self):
        """Dos llamadas a load() devuelven la misma instancia."""
        from jarvis.voice.vad import SileroVAD

        mock_sess = MagicMock()
        mock_ort = MagicMock()
        mock_ort.InferenceSession.return_value = mock_sess

        with patch.object(Path, "exists", return_value=True), \
             patch.dict("sys.modules", {"onnxruntime": mock_ort}):
            inst1 = SileroVAD.load()
            inst2 = SileroVAD.load()

        assert inst1 is inst2
        assert inst1 is not None

    def test_load_creates_ort_session(self):
        """load() llama a ort.InferenceSession con el path correcto."""
        from jarvis.voice.vad import SileroVAD

        mock_ort = MagicMock()
        mock_sess = MagicMock()
        mock_ort.InferenceSession.return_value = mock_sess

        with patch.object(Path, "exists", return_value=True), \
             patch.dict("sys.modules", {"onnxruntime": mock_ort}):
            inst = SileroVAD.load()

        assert inst is not None
        mock_ort.InferenceSession.assert_called_once()
        call_args = mock_ort.InferenceSession.call_args
        assert "silero_vad.onnx" in call_args[0][0]


# ── Tests: reset_states() ────────────────────────────────────────────────────

class TestSileroVADResetStates:
    def _make_vad(self):
        from jarvis.voice.vad import SileroVAD
        mock_ort = MagicMock()
        mock_ort.InferenceSession.return_value = MagicMock()
        with patch.object(Path, "exists", return_value=True), \
             patch.dict("sys.modules", {"onnxruntime": mock_ort}):
            return SileroVAD.load()

    def test_reset_states_zeros(self):
        """reset_states() pone _state a ceros."""
        vad = self._make_vad()
        vad._state = np.ones((2, 1, 128), dtype=np.float32)
        vad.reset_states()
        assert np.all(vad._state == 0.0)

    def test_reset_states_shape(self):
        """_state tiene la forma correcta tras reset."""
        vad = self._make_vad()
        vad.reset_states()
        assert vad._state.shape == (2, 1, 128)
        assert vad._state.dtype == np.float32


# ── Tests: __call__() ────────────────────────────────────────────────────────

class TestSileroVADCall:
    def _make_vad(self):
        from jarvis.voice.vad import SileroVAD
        mock_ort = MagicMock()
        mock_sess = MagicMock()
        mock_ort.InferenceSession.return_value = mock_sess
        with patch.object(Path, "exists", return_value=True), \
             patch.dict("sys.modules", {"onnxruntime": mock_ort}):
            return SileroVAD.load(), mock_sess

    def test_call_returns_float(self):
        """__call__ retorna un float."""
        vad, mock_sess = self._make_vad()
        # Simular salida del modelo: output + state nuevo
        fake_out = np.array([[0.85]], dtype=np.float32)
        fake_state = np.zeros((2, 1, 128), dtype=np.float32)
        mock_sess.run.return_value = [fake_out, fake_state]

        audio = np.zeros(512, dtype=np.float32)
        result = vad(audio, sr=16000)

        assert isinstance(result, float)
        assert result == pytest.approx(0.85)

    def test_call_updates_state(self):
        """__call__ actualiza _state con el nuevo estado del modelo."""
        vad, mock_sess = self._make_vad()
        new_state = np.ones((2, 1, 128), dtype=np.float32) * 0.5
        mock_sess.run.return_value = [np.array([[0.3]]), new_state]

        audio = np.zeros(512, dtype=np.float32)
        vad(audio, sr=16000)

        np.testing.assert_array_equal(vad._state, new_state)

    def test_call_passes_sr_as_int64(self):
        """__call__ pasa sr como np.int64 a la sesión ONNX."""
        vad, mock_sess = self._make_vad()
        mock_sess.run.return_value = [
            np.array([[0.0]]),
            np.zeros((2, 1, 128), dtype=np.float32),
        ]

        audio = np.zeros(512, dtype=np.float32)
        vad(audio, sr=16000)

        _, feed_dict = mock_sess.run.call_args[0], mock_sess.run.call_args[0]
        call_kwargs = mock_sess.run.call_args[0][1]
        assert call_kwargs["sr"].dtype == np.int64
        assert int(call_kwargs["sr"]) == 16000
