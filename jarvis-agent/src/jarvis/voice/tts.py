"""
tts.py

Text-to-Speech con Piper (voz neural natural).
"""

from __future__ import annotations

import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class TTSConfig:
    engine: str = "piper"
    voice_model: Optional[str] = None
    voice: Optional[str] = None
    rate: Optional[int] = None


class TTS:
    def __init__(self, cfg: Optional[TTSConfig] = None):
        self.cfg = cfg or TTSConfig()
        
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

        if self.cfg.engine == "piper" and self.cfg.voice_model:
            return self._speak_piper(text)
        else:
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
            
            # Reproducir con afplay
            play = subprocess.run(
                ["afplay", wav_path],
                capture_output=True,
            )
            
            # Limpiar
            Path(wav_path).unlink(missing_ok=True)
            
            return {
                "command": "piper → afplay",
                "returncode": play.returncode,
                "stdout": "",
                "stderr": "",
            }
            
        except Exception as e:
            print(f"⚠️ Error Piper: {e}. Usando macOS 'say'")
            return self._speak_macos(text)

    def _speak_macos(self, text: str) -> dict:
        """Fallback a macOS 'say'."""
        cmd = ["say"]
        if self.cfg.voice:
            cmd += ["-v", self.cfg.voice]
        if self.cfg.rate is not None:
            cmd += ["-r", str(int(self.cfg.rate))]
        cmd.append(text)

        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)

        return {
            "command": " ".join(shlex.quote(x) for x in cmd),
            "returncode": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
        }
