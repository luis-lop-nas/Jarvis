"""
tts.py

Text-to-Speech con múltiples engines:
- ElevenLabs (voz personalizada de alta calidad)
- Piper (voz neural local)
- macOS 'say' (fallback)
"""

from __future__ import annotations

import shlex
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class TTSConfig:
    engine: str = "elevenlabs"  # elevenlabs, piper, macos
    voice_model: Optional[str] = None
    voice: Optional[str] = None
    rate: Optional[int] = None
    # ElevenLabs
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None
    elevenlabs_model: str = "eleven_multilingual_v2"


class TTS:
    def __init__(self, cfg: Optional[TTSConfig] = None):
        self.cfg = cfg or TTSConfig()

        # Estado del proceso de reproducción actual
        self._current_proc: Optional[subprocess.Popen] = None
        self._speech_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Auto-configurar según disponibilidad
        if self.cfg.engine == "elevenlabs":
            if not self.cfg.elevenlabs_api_key or not self.cfg.elevenlabs_voice_id:
                print("⚠️ ElevenLabs no configurado. Intentando Piper...")
                self.cfg.engine = "piper"

        if self.cfg.engine == "piper" and not self.cfg.voice_model:
            default_voice = Path("data/voices/es_ES-davefx-medium.onnx")
            if default_voice.exists():
                self.cfg.voice_model = str(default_voice)
            else:
                print("⚠️ Voz Piper no encontrada. Usando macOS 'say'")
                self.cfg.engine = "macos"

    def speak(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            return {"command": "", "returncode": 0, "stdout": "", "stderr": ""}

        if self.cfg.engine == "elevenlabs":
            return self._speak_elevenlabs(text)
        elif self.cfg.engine == "piper" and self.cfg.voice_model:
            return self._speak_piper(text)
        else:
            return self._speak_macos(text)

    def _speak_elevenlabs(self, text: str) -> dict:
        """Habla usando ElevenLabs TTS (SDK v2.x)."""
        try:
            from elevenlabs.types import VoiceSettings
            from elevenlabs.client import ElevenLabs

            client = ElevenLabs(api_key=self.cfg.elevenlabs_api_key)

            # Generar audio como stream de chunks MP3
            audio_iter = client.text_to_speech.convert(
                voice_id=self.cfg.elevenlabs_voice_id,
                text=text,
                model_id=self.cfg.elevenlabs_model,
                output_format="mp3_44100_128",
                voice_settings=VoiceSettings(
                    stability=0.5,
                    similarity_boost=0.75,
                    style=0.0,
                    use_speaker_boost=True,
                ),
            )

            # Escribir en archivo temporal y reproducir con afplay (interruptible)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                mp3_path = f.name
                for chunk in audio_iter:
                    if self._stop_event.is_set():
                        break
                    f.write(chunk)

            if self._stop_event.is_set():
                Path(mp3_path).unlink(missing_ok=True)
                return {"command": "elevenlabs", "returncode": 0, "stdout": "stopped", "stderr": ""}

            proc = subprocess.Popen(
                ["afplay", mp3_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._current_proc = proc
            proc.wait()
            self._current_proc = None
            Path(mp3_path).unlink(missing_ok=True)

            return {
                "command": "elevenlabs → afplay",
                "returncode": proc.returncode,
                "stdout": "",
                "stderr": "",
            }

        except ImportError:
            print("⚠️ elevenlabs no instalado. Instala con: pip install elevenlabs")
            return self._speak_macos(text)
        except Exception as e:
            print(f"⚠️ Error ElevenLabs: {e}. Usando fallback...")
            return self._speak_macos(text)

    def _speak_piper(self, text: str) -> dict:
        """Habla usando Piper TTS."""
        try:
            # Crear archivo temporal para el WAV
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                wav_path = tmp.name
            
            # Ejecutar piper con echo | piper
            piper_cmd = f'echo {shlex.quote(text)} | piper --model {shlex.quote(self.cfg.voice_model)} --output_file {shlex.quote(wav_path)}'
            
            process = subprocess.run(
                piper_cmd,
                shell=True,
                capture_output=True,
                timeout=30,
            )
            
            if process.returncode != 0:
                print(f"⚠️ Error Piper: {process.stderr.decode()}")
                Path(wav_path).unlink(missing_ok=True)
                return self._speak_macos(text)
            
            # Reproducir con afplay (interruptible)
            proc = subprocess.Popen(
                ["afplay", wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._current_proc = proc
            proc.wait()
            self._current_proc = None

            Path(wav_path).unlink(missing_ok=True)

            return {
                "command": "piper → afplay",
                "returncode": proc.returncode,
                "stdout": "",
                "stderr": "",
            }
            
        except Exception as e:
            print(f"⚠️ Error Piper: {e}. Usando macOS 'say'")
            return self._speak_macos(text)

    # ── API no-bloqueante ──────────────────────────────────────────────────────

    def speak_nonblocking(self, text: str) -> None:
        """Inicia TTS en background sin bloquear. Usa stop() para interrumpir."""
        self.stop()
        self._stop_event.clear()
        self._speech_thread = threading.Thread(
            target=self.speak, args=(text,), daemon=True
        )
        self._speech_thread.start()

    def stop(self) -> None:
        """Para el TTS inmediatamente."""
        self._stop_event.set()
        proc = self._current_proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
            self._current_proc = None
        # Parar sounddevice (usado por ElevenLabs)
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        t = self._speech_thread
        if t is not None and t.is_alive():
            t.join(timeout=0.3)
        self._speech_thread = None

    def wait(self) -> None:
        """Espera a que termine el TTS actual."""
        t = self._speech_thread
        if t is not None and t.is_alive():
            t.join()

    @property
    def is_speaking(self) -> bool:
        """True si el TTS está reproduciendo audio."""
        t = self._speech_thread
        return t is not None and t.is_alive()

    def _speak_macos(self, text: str) -> dict:
        """Fallback a macOS 'say'."""
        cmd = ["say"]
        if self.cfg.voice:
            cmd += ["-v", self.cfg.voice]
        if self.cfg.rate is not None:
            cmd += ["-r", str(int(self.cfg.rate))]
        cmd.append(text)

        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._current_proc = proc
        proc.wait()
        self._current_proc = None

        return {
            "command": " ".join(shlex.quote(x) for x in cmd),
            "returncode": proc.returncode,
            "stdout": "",
            "stderr": "",
        }
