"""
main.py

Entry point del proyecto.
"""

from __future__ import annotations

import argparse
from typing import Optional

from jarvis.config import load_settings


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarvis", description="Jarvis Agent (CLI + Voice)")
    p.add_argument(
        "--voice",
        action="store_true",
        help="Activa modo voz + wake word.",
    )
    p.add_argument(
        "--no-voice",
        action="store_true",
        help="Fuerza modo solo-CLI.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Activa modo debug.",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    settings, paths = load_settings()

    if args.debug:
        settings.debug = True  # type: ignore[attr-defined]

    use_voice = False
    if args.no_voice:
        use_voice = False
    elif args.voice:
        use_voice = True

    if use_voice:
        # Modo voz activado
        from jarvis.voice.voice_loop import VoiceLoop
        from jarvis.voice.wake_word import WakeWordConfig
        from jarvis.voice.stt import STTConfig
        from jarvis.voice.tts import TTSConfig
        from jarvis.agent.tool_agent import tool_agent_from_settings

        # Crear agente
        agent = tool_agent_from_settings(settings)

        # Configurar voice loop
        wake_cfg = WakeWordConfig(
            access_key=settings.porcupine_access_key,
            keyword=settings.wake_word,
            sensitivity=0.6,
        )
        
        stt_cfg = STTConfig()
        tts_cfg = TTSConfig()

        voice_loop = VoiceLoop(
            wake_cfg=wake_cfg,
            stt_cfg=stt_cfg,
            tts_cfg=tts_cfg,
        )

        print("🎤 Modo voz activado. Di 'Jarvis' para activar...")
        print("Presiona Ctrl+C para salir.\n")

        # Función que conecta el agente
        def agent_fn(text: str) -> str:
            return agent.run(text)

        # Arrancar loop de voz
        voice_loop.run_forever(agent_fn)
    else:
        # Modo CLI
        from jarvis.ui.cli import run_cli
        run_cli(settings=settings, paths=paths)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
