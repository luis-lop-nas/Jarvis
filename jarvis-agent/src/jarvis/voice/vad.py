"""
vad.py

SileroVAD: wrapper mínimo de Silero VAD usando onnxruntime directamente.
No requiere torchaudio ni torch.hub. Usa el ONNX cacheado en ~/.cache/torch/hub/.
Singleton: se instancia una vez y se reutiliza.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np


class SileroVAD:
    """
    Wrapper mínimo de Silero VAD usando onnxruntime directamente.
    No requiere torchaudio ni torch.hub. Usa el ONNX cacheado en ~/.cache/torch/hub/.
    Singleton: se instancia una vez y se reutiliza en todas las grabaciones.
    """

    _ONNX_PATH = (
        Path.home() / ".cache/torch/hub/snakers4_silero-vad_master"
        / "src/silero_vad/data/silero_vad.onnx"
    )
    _instance: Optional["SileroVAD"] = None

    def __init__(self) -> None:
        import onnxruntime as ort
        self._sess = ort.InferenceSession(
            str(self._ONNX_PATH),
            providers=["CPUExecutionProvider"],
        )
        self.reset_states()

    def reset_states(self) -> None:
        """Resetea el estado LSTM del modelo."""
        # state: shape (2, batch=1, 128) — estado LSTM del modelo
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

    def __call__(self, audio_float32: np.ndarray, sr: int = 16000) -> float:
        """audio_float32: shape (512,) float32 [-1,1]. Retorna probabilidad de voz [0,1]."""
        x = audio_float32.reshape(1, -1)
        outs = self._sess.run(None, {
            "input": x,
            "state": self._state,
            "sr":    np.array(sr, dtype=np.int64)
        })
        # outs[0] = output (1,1), outs[1] = stateN actualizado
        self._state = outs[1]
        return float(outs[0][0, 0])

    @classmethod
    def load(cls) -> Optional["SileroVAD"]:
        """Carga Silero VAD. Singleton: devuelve instancia existente si ya cargó."""
        if cls._instance is not None:
            return cls._instance
        try:
            if not cls._ONNX_PATH.exists():
                raise FileNotFoundError(f"ONNX no encontrado: {cls._ONNX_PATH}")
            cls._instance = cls()
            print("✅ Silero VAD cargado (ONNX, sin torchaudio)")
            return cls._instance
        except Exception as e:
            print(f"⚠️ Silero VAD no disponible ({e}). Usando VAD por RMS.")
            return None
