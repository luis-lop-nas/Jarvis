"""
voice_loop.py

Loop de voz de Jarvis.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from jarvis.voice.wake_word import WakeWordConfig, WakeWordListener
from jarvis.voice.stt import STT, STTConfig
from jarvis.voice.tts import TTS, TTSConfig


AgentFn = Callable[[str], str]


@dataclass
class VoiceLoopConfig:
    workspace_dir: str = "data/workspace"
    record_seconds: float = 6.0  # Aumentado a 6 segundos


class VoiceLoop:
    def __init__(
        self,
        *,
        wake_cfg: WakeWordConfig,
        stt_cfg: Optional[STTConfig] = None,
        tts_cfg: Optional[TTSConfig] = None,
        loop_cfg: Optional[VoiceLoopConfig] = None,
    ):
        self.loop_cfg = loop_cfg or VoiceLoopConfig()
        self.workspace = Path(self.loop_cfg.workspace_dir).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.wake = WakeWordListener(wake_cfg)
        self.stt = STT(stt_cfg or STTConfig())
        self.tts = TTS(tts_cfg or TTSConfig())

    def run_forever(self, agent_fn: AgentFn) -> None:
        self.wake.start()
        print("👂 Escuchando wake word...\n")
        
        try:
            while True:
                print("💤 Esperando 'Jarvis'...")
                woke = self.wake.wait_for_wake(timeout_sec=None)
                
                if not woke:
                    continue

                print("✓ Wake word detectada!")
                self.tts.speak("Dime")

                wav_path = self.workspace / "_jarvis_input.wav"
                self.stt.record_to_wav(wav_path, seconds=float(self.loop_cfg.record_seconds))

                text = self.stt.transcribe_wav(wav_path).strip()

                if not text or "no he detectado" in text.lower() or text.startswith("Error"):
                    print(f"⚠ Problema: {text}")
                    self.tts.speak("No te he entendido bien")
                    continue

                print(f"📝 Entendí: {text}\n")
                print("🤔 Procesando...")
                
                response = agent_fn(text)
                print(f"💬 Jarvis: {response}\n")

                self.tts.speak(response)
                print("─" * 60)

        except KeyboardInterrupt:
            print("\n👋 Saliendo...")
        finally:
            self.wake.stop()
