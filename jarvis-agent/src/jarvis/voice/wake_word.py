"""
wake_word.py

Detección de palabra de activación ("Hey Jarvis") usando Porcupine (Picovoice).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import pvporcupine
from pvrecorder import PvRecorder


@dataclass
class WakeWordConfig:
    access_key: str
    keyword: str = "jarvis"
    sensitivity: float = 0.6
    device_index: Optional[int] = None


class WakeWordListener:
    def __init__(self, cfg: WakeWordConfig):
        self.cfg = cfg
        self._porcupine = None
        self._recorder = None

    def start(self) -> None:
        if not self.cfg.access_key:
            raise ValueError("Falta PORCUPINE_ACCESS_KEY (WakeWordConfig.access_key).")

        # Crear motor Porcupine
        self._porcupine = pvporcupine.create(
            access_key=self.cfg.access_key,
            keywords=[self.cfg.keyword],
            sensitivities=[float(self.cfg.sensitivity)],
        )

        # Si no se especificó device_index, buscar el micrófono del Mac
        device_index = self.cfg.device_index
        if device_index is None:
            devices = PvRecorder.get_available_devices()
            for i, device in enumerate(devices):
                if "MacBook" in device or "Mac" in device:
                    device_index = i
                    print(f"🎤 Usando micrófono: {device}")
                    break
            
            # Si no encuentra "MacBook", usar el primero disponible
            if device_index is None and len(devices) > 0:
                device_index = 0
                print(f"🎤 Usando micrófono por defecto: {devices[0]}")

        # Crear grabador
        self._recorder = PvRecorder(
            device_index=device_index,
            frame_length=self._porcupine.frame_length,
        )
        self._recorder.start()

    def stop(self) -> None:
        if self._recorder is not None:
            try:
                self._recorder.stop()
            except Exception:
                pass
            try:
                self._recorder.delete()
            except Exception:
                pass
            self._recorder = None

        if self._porcupine is not None:
            try:
                self._porcupine.delete()
            except Exception:
                pass
            self._porcupine = None

    def wait_for_wake(self, *, timeout_sec: Optional[float] = None) -> bool:
        if self._porcupine is None or self._recorder is None:
            raise RuntimeError("WakeWordListener no está iniciado. Llama start() primero.")

        t0 = time.time()
        while True:
            if timeout_sec is not None and (time.time() - t0) > timeout_sec:
                return False

            pcm = self._recorder.read()
            kw_index = self._porcupine.process(pcm)
            if kw_index >= 0:
                return True
