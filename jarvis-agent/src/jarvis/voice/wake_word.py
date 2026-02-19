"""
wake_word.py

Detección de wake word con dos motores:
- "openwakeword"  → Open source, sin API key, modelos preentrenados
- "porcupine"     → Picovoice Porcupine (requiere API key)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import sounddevice as sd


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

@dataclass
class WakeWordConfig:
    engine: str = "openwakeword"        # "openwakeword" | "porcupine"
    sensitivity: float = 0.5
    device_index: Optional[int] = None
    # OpenWakeWord
    oww_model: str = "hey_jarvis"       # modelo preentrenado a usar
    # Porcupine (solo si engine="porcupine")
    access_key: str = ""
    keyword: str = "jarvis"


# ---------------------------------------------------------------------------
# Motor: OpenWakeWord (libre, sin API key)
# ---------------------------------------------------------------------------

class OpenWakeWordListener:
    """
    Detecta la wake word usando openwakeword (https://github.com/dscripka/openWakeWord).
    Procesa chunks de 1280 samples a 16kHz (~80ms por chunk).
    """

    CHUNK_SAMPLES = 1280
    SAMPLE_RATE = 16000

    def __init__(self, cfg: WakeWordConfig):
        self.cfg = cfg
        self._stream: Optional[sd.InputStream] = None
        self._model = None

    def start(self) -> None:
        try:
            from openwakeword.model import Model
            from openwakeword.utils import download_models
            print(f"📥 Cargando OpenWakeWord modelo '{self.cfg.oww_model}'...")
            # Descarga modelos si no existen todavía (primera ejecución)
            download_models()
            self._model = Model(
                wakeword_models=[self.cfg.oww_model],
                inference_framework="onnx",
            )
            print(f"✓ Wake word: OpenWakeWord '{self.cfg.oww_model}'")
        except ImportError:
            raise RuntimeError(
                "openwakeword no instalado. Instala con: pip install openwakeword"
            )

        self._stream = sd.InputStream(
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=self.CHUNK_SAMPLES,
            device=self.cfg.device_index,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def wait_for_wake(self, *, timeout_sec: Optional[float] = None) -> bool:
        if self._model is None or self._stream is None:
            raise RuntimeError("OpenWakeWordListener no iniciado. Llama start() primero.")

        t0 = time.time()
        while True:
            if timeout_sec is not None and (time.time() - t0) > timeout_sec:
                return False

            try:
                audio_chunk, overflowed = self._stream.read(self.CHUNK_SAMPLES)
            except Exception:
                time.sleep(0.01)
                continue

            if overflowed:
                continue

            audio_flat = audio_chunk.flatten()
            prediction = self._model.predict(audio_flat)

            for score in prediction.values():
                if score >= 0.05:   # mostrar activaciones notables para debug
                    print(f"  [wake] score={score:.3f} (umbral={self.cfg.sensitivity:.2f})")
                if score >= self.cfg.sensitivity:
                    return True


# ---------------------------------------------------------------------------
# Motor: Porcupine (Picovoice) — mantiene compatibilidad
# ---------------------------------------------------------------------------

class PorcupineListener:
    """Wrapper sobre pvporcupine (requiere PORCUPINE_ACCESS_KEY)."""

    def __init__(self, cfg: WakeWordConfig):
        self.cfg = cfg
        self._porcupine = None
        self._recorder = None

    def start(self) -> None:
        if not self.cfg.access_key:
            raise ValueError("Falta access_key para Porcupine.")

        import pvporcupine
        from pvrecorder import PvRecorder

        self._porcupine = pvporcupine.create(
            access_key=self.cfg.access_key,
            keywords=[self.cfg.keyword],
            sensitivities=[float(self.cfg.sensitivity)],
        )

        device_index = self.cfg.device_index
        if device_index is None:
            devices = PvRecorder.get_available_devices()
            for i, device in enumerate(devices):
                if "MacBook" in device or "Mac" in device:
                    device_index = i
                    print(f"🎤 Porcupine usando: {device}")
                    break
            if device_index is None and devices:
                device_index = 0
                print(f"🎤 Porcupine usando: {devices[0]}")

        from pvrecorder import PvRecorder
        self._recorder = PvRecorder(
            device_index=device_index,
            frame_length=self._porcupine.frame_length,
        )
        self._recorder.start()
        print(f"✓ Wake word: Porcupine '{self.cfg.keyword}'")

    def stop(self) -> None:
        for obj in (self._recorder, self._porcupine):
            if obj is not None:
                try:
                    obj.stop()
                except Exception:
                    pass
                try:
                    obj.delete()
                except Exception:
                    pass
        self._recorder = None
        self._porcupine = None

    def wait_for_wake(self, *, timeout_sec: Optional[float] = None) -> bool:
        if self._porcupine is None or self._recorder is None:
            raise RuntimeError("PorcupineListener no iniciado. Llama start() primero.")

        t0 = time.time()
        while True:
            if timeout_sec is not None and (time.time() - t0) > timeout_sec:
                return False
            pcm = self._recorder.read()
            if self._porcupine.process(pcm) >= 0:
                return True


# ---------------------------------------------------------------------------
# Alias público para compatibilidad con voice_loop.py existente
# ---------------------------------------------------------------------------

class WakeWordListener:
    """
    Fachada que selecciona el motor según WakeWordConfig.engine.
    Interfaz idéntica: start(), stop(), wait_for_wake().
    """

    def __init__(self, cfg: WakeWordConfig):
        self.cfg = cfg
        if cfg.engine == "porcupine":
            self._impl = PorcupineListener(cfg)
        else:
            self._impl = OpenWakeWordListener(cfg)

    def start(self) -> None:
        self._impl.start()

    def stop(self) -> None:
        self._impl.stop()

    def wait_for_wake(self, *, timeout_sec: Optional[float] = None) -> bool:
        return self._impl.wait_for_wake(timeout_sec=timeout_sec)
