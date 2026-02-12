"""
wake_word.py

Detección de palabra de activación ("Hey Jarvis") usando Porcupine (Picovoice).

Qué hace:
- Inicializa Porcupine con una keyword (por defecto "jarvis")
- Lee audio del micrófono usando PvRecorder
- Devuelve cuando detecta la keyword

Requisitos:
- pvporcupine
- pvrecorder
- Una PORCUPINE_ACCESS_KEY válida en tu .env

Notas:
- Porcupine detecta la keyword, pero NO transcribe. Solo "despierta" a Jarvis.
- La frase completa "hey jarvis" no es siempre una keyword exacta; normalmente la keyword es "jarvis".
  Luego el STT (speech-to-text) transcribirá lo que digas después de despertarlo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import pvporcupine
from pvrecorder import PvRecorder


@dataclass
class WakeWordConfig:
    """
    Config de wake word.

    access_key: clave de Picovoice
    keyword: keyword de Porcupine (por defecto "jarvis")
    sensitivity: 0..1 (más alto = más sensible pero más falsos positivos)
    device_index: micrófono a usar (None = default)
    """
    access_key: str
    keyword: str = "jarvis"
    sensitivity: float = 0.6
    device_index: Optional[int] = None


class WakeWordListener:
    """
    Listener de wake word.

    Uso típico:
        listener = WakeWordListener(cfg)
        listener.start()
        listener.wait_for_wake()
        listener.stop()
    """

    def __init__(self, cfg: WakeWordConfig):
        self.cfg = cfg
        self._porcupine = None
        self._recorder = None

    def start(self) -> None:
        """Inicializa Porcupine y el grabador del micro."""
        if not self.cfg.access_key:
            raise ValueError("Falta PORCUPINE_ACCESS_KEY (WakeWordConfig.access_key).")

        # Crear motor Porcupine
        # Keyword predefinida: "jarvis" suele estar disponible como built-in.
        # Si quisieras custom keyword, aquí se usaría keyword_paths.
        self._porcupine = pvporcupine.create(
            access_key=self.cfg.access_key,
            keywords=[self.cfg.keyword],
            sensitivities=[float(self.cfg.sensitivity)],
        )

        # Crear grabador
        self._recorder = PvRecorder(
            device_index=self.cfg.device_index,
            frame_length=self._porcupine.frame_length,
        )
        self._recorder.start()

    def stop(self) -> None:
        """Para el micro y libera recursos."""
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
        """
        Bloquea hasta detectar la keyword o hasta timeout.

        Returns:
          True si detectó wake word
          False si hizo timeout
        """
        if self._porcupine is None or self._recorder is None:
            raise RuntimeError("WakeWordListener no está iniciado. Llama start() primero.")

        t0 = time.time()
        while True:
            if timeout_sec is not None and (time.time() - t0) > timeout_sec:
                return False

            pcm = self._recorder.read()
            # process devuelve index >= 0 si detecta keyword
            kw_index = self._porcupine.process(pcm)
            if kw_index >= 0:
                return True