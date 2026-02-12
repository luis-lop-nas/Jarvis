"""
stt.py

Speech-to-Text (STT) con Whisper local mejorado.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False


@dataclass
class STTConfig:
    sample_rate: int = 16000
    channels: int = 1
    dtype: str = "int16"
    device: Optional[int] = None
    whisper_model: str = "small"  # Cambiado de "base" a "small" para mejor precisión


class STT:
    def __init__(self, cfg: Optional[STTConfig] = None):
        self.cfg = cfg or STTConfig()
        self._whisper_model = None
        
        if WHISPER_AVAILABLE:
            try:
                print(f"Cargando modelo Whisper '{self.cfg.whisper_model}'...")
                self._whisper_model = whisper.load_model(self.cfg.whisper_model)
                print("✓ Modelo Whisper cargado correctamente")
            except Exception as e:
                print(f"⚠ Error cargando Whisper: {e}")
                self._whisper_model = None

    def record_to_wav(self, out_path: Path, *, seconds: float = 5.0) -> Path:
        """Graba audio del micro durante X segundos."""
        out_path = Path(out_path).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"🎤 Grabando {seconds} segundos... ¡HABLA AHORA!")
        
        frames = int(self.cfg.sample_rate * float(seconds))
        audio = sd.rec(
            frames,
            samplerate=self.cfg.sample_rate,
            channels=self.cfg.channels,
            dtype=self.cfg.dtype,
            device=self.cfg.device,
        )
        sd.wait()

        audio_int16 = np.asarray(audio, dtype=np.int16)

        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(self.cfg.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.cfg.sample_rate)
            wf.writeframes(audio_int16.tobytes())

        print(f"✓ Audio guardado")
        return out_path

    def transcribe_wav(self, wav_path: Path) -> str:
        """Transcribe un WAV a texto usando Whisper."""
        wav_path = Path(wav_path).expanduser().resolve()
        if not wav_path.exists():
            raise FileNotFoundError(f"No existe WAV: {wav_path}")

        if not WHISPER_AVAILABLE:
            return "Whisper no está instalado."
        
        if self._whisper_model is None:
            return "Modelo Whisper no cargado."

        try:
            print("🎯 Transcribiendo audio...")
            result = self._whisper_model.transcribe(
                str(wav_path),
                language="es",
                fp16=False,
                initial_prompt="Este es Jarvis, un asistente virtual en español.",
                temperature=0.0,  # Más determinista
                beam_size=5,      # Mejor búsqueda
            )
            
            text = result.get("text", "").strip()
            
            # Si Whisper devuelve vacío o muy corto
            if not text or len(text) < 3:
                return "No he detectado voz clara, intenta de nuevo"
            
            print(f"✓ Transcripción: '{text}'")
            return text
            
        except Exception as e:
            return f"Error en transcripción: {e}"
