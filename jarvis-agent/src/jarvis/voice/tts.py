"""
tts.py

Text-to-Speech (TTS) en macOS.

Implementación inicial:
- Usa el comando nativo `say` de macOS (rápido y sin dependencias).

Más adelante:
- Podemos cambiar a Piper / Coqui para voces más naturales (offline),
  manteniendo la misma interfaz pública.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class TTSConfig:
    """
    Config del TTS.

    voice: nombre de voz de macOS (ej: "Samantha", "Monica", etc). None = default.
    rate: velocidad de habla (words per minute). None = default.
    """
    voice: Optional[str] = None
    rate: Optional[int] = None


class TTS:
    """Motor TTS basado en `say`."""

    def __init__(self, cfg: Optional[TTSConfig] = None):
        self.cfg = cfg or TTSConfig()

    def speak(self, text: str) -> dict:
        """
        Habla el texto usando `say`.

        Devuelve un dict con:
        - command (string)
        - returncode
        - stdout/stderr (normalmente vacíos)
        """
        text = (text or "").strip()
        if not text:
            return {"command": "", "returncode": 0, "stdout": "", "stderr": ""}

        cmd = ["say"]

        if self.cfg.voice:
            cmd += ["-v", self.cfg.voice]

        if self.cfg.rate is not None:
            cmd += ["-r", str(int(self.cfg.rate))]

        # Pasamos el texto como último argumento (sin shell)
        cmd.append(text)

        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)

        return {
            "command": " ".join(shlex.quote(x) for x in cmd),
            "returncode": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
        }