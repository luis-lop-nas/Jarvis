"""
stt.py

Speech-to-Text con dos motores:
- "groq"  → Groq Whisper API (whisper-large-v3-turbo) — rápido, preciso, usa API ya configurada
- "local" → Whisper local                              — sin conexión, más lento
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
    engine: str = "groq"                        # "groq" | "local"
    sample_rate: int = 16000
    channels: int = 1
    dtype: str = "int16"
    device: Optional[int] = None
    language: str = "es"                        # idioma para transcripción
    # Groq
    groq_api_key: str = ""
    groq_model: str = "whisper-large-v3-turbo"
    # Local Whisper (fallback)
    whisper_model: str = "small"


class STT:
    def __init__(self, cfg: Optional[STTConfig] = None):
        self.cfg = cfg or STTConfig()
        self._whisper_model = None
        self._groq_client = None

        if self.cfg.engine == "groq":
            self._init_groq()
        else:
            self._init_local_whisper()

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def _init_groq(self) -> None:
        if not self.cfg.groq_api_key:
            print("⚠ GROQ_API_KEY no configurada. Usando Whisper local como fallback.")
            self.cfg.engine = "local"
            self._init_local_whisper()
            return
        try:
            from groq import Groq
            self._groq_client = Groq(api_key=self.cfg.groq_api_key)
            print(f"✓ STT: Groq Whisper API ({self.cfg.groq_model})")
        except ImportError:
            print("⚠ groq no instalado. Usando Whisper local.")
            self.cfg.engine = "local"
            self._init_local_whisper()

    def _init_local_whisper(self) -> None:
        try:
            import whisper
            print(f"Cargando modelo Whisper local '{self.cfg.whisper_model}'...")
            self._whisper_model = whisper.load_model(self.cfg.whisper_model)
            print("✓ STT: Whisper local cargado")
        except ImportError:
            print("⚠ whisper no instalado. Instala con: pip install openai-whisper")
        except Exception as e:
            print(f"⚠ Error cargando Whisper local: {e}")

    # ------------------------------------------------------------------
    # Grabación
    # ------------------------------------------------------------------

    def record_to_wav(self, out_path: Path, *, seconds: float = 5.0) -> Path:
        """Graba audio del micrófono durante X segundos."""
        out_path = Path(out_path).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"🎤 Grabando {seconds}s... ¡HABLA AHORA!")

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

        print("✓ Audio guardado")
        return out_path

    # ------------------------------------------------------------------
    # Transcripción
    # ------------------------------------------------------------------

    def transcribe_wav(self, wav_path: Path) -> str:
        """Transcribe un WAV a texto usando el motor configurado."""
        wav_path = Path(wav_path).expanduser().resolve()
        if not wav_path.exists():
            raise FileNotFoundError(f"No existe WAV: {wav_path}")

        if self.cfg.engine == "groq" and self._groq_client:
            return self._transcribe_groq(wav_path)
        else:
            return self._transcribe_local(wav_path)

    def _transcribe_groq(self, wav_path: Path) -> str:
        """Transcribe usando Groq Whisper API."""
        try:
            print("🎯 Transcribiendo con Groq Whisper...")
            with open(wav_path, "rb") as f:
                result = self._groq_client.audio.transcriptions.create(
                    file=(wav_path.name, f.read()),
                    model=self.cfg.groq_model,
                    language=self.cfg.language,
                    response_format="text",
                )
            text = (result or "").strip()
            if not text:
                return "No he detectado voz clara, intenta de nuevo"
            print(f"✓ Transcripción: '{text}'")
            return text
        except Exception as e:
            print(f"⚠ Error Groq STT: {e}. Intentando Whisper local...")
            return self._transcribe_local(wav_path)

    def _transcribe_local(self, wav_path: Path) -> str:
        """Transcribe usando Whisper local."""
        if self._whisper_model is None:
            return "Whisper local no disponible."
        try:
            print("🎯 Transcribiendo con Whisper local...")
            result = self._whisper_model.transcribe(
                str(wav_path),
                language=self.cfg.language,
                fp16=False,
                initial_prompt="Este es Jarvis, un asistente virtual en español.",
                temperature=0.0,
                beam_size=5,
            )
            text = result.get("text", "").strip()
            if not text:
                return "No he detectado voz clara, intenta de nuevo"
            print(f"✓ Transcripción: '{text}'")
            return text
        except Exception as e:
            return f"Error en transcripción: {e}"
