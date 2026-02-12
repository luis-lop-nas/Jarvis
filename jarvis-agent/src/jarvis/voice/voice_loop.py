"""
voice_loop.py

Loop de voz de Jarvis.

No lo conectamos todavía al arranque (main.py) para no re-editar continuamente.
Aquí solo dejamos el loop listo y reutilizable.

Flujo:
1) wait_for_wake()  -> Porcupine detecta "jarvis"
2) record_to_wav()  -> grabamos audio del micro
3) transcribe_wav() -> STT (por ahora placeholder)
4) agent(text)      -> llamamos al "cerebro" (lo pasas como callback)
5) tts.speak(resp)  -> respuesta hablada

Más adelante:
- grabación "hasta silencio" en vez de segundos fijos
- STT real (Whisper local o API)
- streaming de respuesta / interrupciones
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
    """
    Config del loop de voz.

    workspace_dir: dónde guardar wav temporales (usamos workspace para mantenerlo controlado)
    record_seconds: duración de grabación tras wake word
    """
    workspace_dir: str = "data/workspace"
    record_seconds: float = 4.0


class VoiceLoop:
    """
    Loop de voz. Se crea con:
    - WakeWordListener
    - STT (grabación + transcripción)
    - TTS (voz)

    El agente se pasa como callback `agent_fn(text)->response`.
    """

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
        """
        Arranca el loop infinito:
        - espera wake word
        - graba
        - transcribe
        - llama agente
        - habla respuesta
        """
        self.wake.start()
        try:
            while True:
                # 1) Esperar "jarvis"
                woke = self.wake.wait_for_wake(timeout_sec=None)
                if not woke:
                    continue

                # Feedback rápido (opcional): una frase corta
                # Para no molestar, puedes comentar esta línea.
                self.tts.speak("Sí")

                # 2) Grabar audio tras despertar
                wav_path = self.workspace / "_jarvis_input.wav"
                self.stt.record_to_wav(wav_path, seconds=float(self.loop_cfg.record_seconds))

                # 3) Transcribir (ahora placeholder)
                text = self.stt.transcribe_wav(wav_path).strip()

                # Si el STT aún no está configurado, lo decimos y seguimos
                if text.startswith("STT no configurado"):
                    self.tts.speak("Todavía no tengo transcripción configurada.")
                    continue

                # 4) Llamar al agente
                response = agent_fn(text)

                # 5) Hablar respuesta
                # (si es muy largo, luego lo troceamos; por ahora tal cual)
                self.tts.speak(response)

        except KeyboardInterrupt:
            # Salida limpia
            pass
        finally:
            self.wake.stop()