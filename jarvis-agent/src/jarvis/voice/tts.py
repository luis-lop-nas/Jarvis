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
        
        """
stt.py

Speech-to-Text (STT).

Diseño para avanzar sin re-editar:
- grabamos audio del micro a un WAV (siempre útil)
- la transcripción es "pluggable":
    - más adelante: Whisper local (faster-whisper)
    - o API (OpenAI transcriptions)

Por ahora:
- record_to_wav(...) funciona ya
- transcribe_wav(...) deja un mensaje claro si no hay backend configurado
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd


@dataclass
class STTConfig:
    """
    Config de STT.

    sample_rate: frecuencia de muestreo (16000 es estándar para STT)
    channels: 1 (mono)
    dtype: int16 para WAV estándar
    device: índice de dispositivo (None = default)
    """
    sample_rate: int = 16000
    channels: int = 1
    dtype: str = "int16"
    device: Optional[int] = None


class STT:
    """
    Grabador + STT pluggable.

    Nota:
    - Grabar audio bien es la mitad de la batalla.
    - La transcripción la conectaremos en el "update final".
    """

    def __init__(self, cfg: Optional[STTConfig] = None):
        self.cfg = cfg or STTConfig()

    def record_to_wav(self, out_path: Path, *, seconds: float = 4.0) -> Path:
        """
        Graba audio del micro durante X segundos y lo guarda como WAV.

        - out_path: ruta del WAV a crear
        - seconds: duración

        Devuelve el Path del WAV creado.
        """
        out_path = Path(out_path).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Grabación bloqueante: simple y fiable
        frames = int(self.cfg.sample_rate * float(seconds))
        audio = sd.rec(
            frames,
            samplerate=self.cfg.sample_rate,
            channels=self.cfg.channels,
            dtype=self.cfg.dtype,
            device=self.cfg.device,
        )
        sd.wait()

        # sounddevice devuelve numpy array; lo guardamos como WAV PCM16
        # audio shape: (frames, channels)
        audio_int16 = np.asarray(audio, dtype=np.int16)

        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(self.cfg.channels)
            wf.setsampwidth(2)  # 2 bytes = int16
            wf.setframerate(self.cfg.sample_rate)
            wf.writeframes(audio_int16.tobytes())

        return out_path

    def transcribe_wav(self, wav_path: Path) -> str:
        """
        Hook para transcribir un WAV a texto.

        Por ahora NO implementamos backend (para evitar atascarte con deps),
        pero dejamos la interfaz lista.

        En el update final elegimos:
        - Whisper local (faster-whisper)
        - o OpenAI audio transcriptions

        Devuelve texto.
        """
        wav_path = Path(wav_path).expanduser().resolve()
        if not wav_path.exists():
            raise FileNotFoundError(f"No existe WAV: {wav_path}")

        # Placeholder controlado: para que el sistema no “invente” transcripciones.
        return (
            "STT no configurado todavía. "
            f"Audio grabado en: {wav_path}. "
            "En el update final conectamos Whisper/API para transcribir."
        )