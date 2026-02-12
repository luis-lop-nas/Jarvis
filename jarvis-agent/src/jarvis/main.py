"""
main.py

Entry point del proyecto.

Responsabilidades:
- Cargar settings desde .env
- Preparar rutas (data/logs/workspace)
- Lanzar la interfaz principal (por ahora CLI)
- Dejar preparado el "switch" para modo voz (lo añadiremos justo después)

Este archivo NO debe tener lógica de "agente" ni tools.
Solo arranca y delega.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from jarvis.config import load_settings


def build_arg_parser() -> argparse.ArgumentParser:
    """
    Define argumentos de línea de comandos.
    Esto nos permite arrancar Jarvis de distintas formas sin tocar el código.

    Ejemplos futuros:
      jarvis --voice
      jarvis --no-voice
      jarvis --debug
    """
    p = argparse.ArgumentParser(prog="jarvis", description="Jarvis Agent (CLI + Voice)")
    p.add_argument(
        "--voice",
        action="store_true",
        help="Activa modo voz + wake word (lo implementaremos en próximos pasos).",
    )
    p.add_argument(
        "--no-voice",
        action="store_true",
        help="Fuerza modo solo-CLI (ignora voz incluso si está configurada).",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Activa modo debug (override de DEBUG=1).",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    """
    Función principal que se ejecuta cuando llamas `jarvis`.

    Devuelve un exit code:
      0 = OK
      !=0 = error
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # 1) Cargamos settings + paths (crea carpetas necesarias)
    settings, paths = load_settings()

    # 2) Override de debug por CLI (útil para probar sin tocar .env)
    if args.debug:
        # Pydantic Settings en runtime: hacemos un override simple
        # (para producción podríamos construir Settings de otra forma,
        # pero ahora queremos simple y transparente)
        settings.debug = True  # type: ignore[attr-defined]

    # 3) Decidimos el modo de interfaz
    #    - Si el usuario fuerza --no-voice => CLI
    #    - Si pide --voice => voz (aún no implementado)
    #    - Por defecto => CLI (por ahora)
    use_voice = False
    if args.no_voice:
        use_voice = False
    elif args.voice:
        use_voice = True

    # 4) Importamos aquí (lazy import) para que la carga inicial sea rápida
    #    y para evitar import cycles.
    from jarvis.ui.cli import run_cli

    if use_voice:
        # Todavía no lo implementamos, pero dejamos el "hueco" ya claro.
        # En el siguiente paso crearemos un "voice_loop" que:
        # - espera "hey jarvis"
        # - graba voz
        # - transcribe
        # - manda el texto al agente
        # - responde por TTS
        print("Modo voz aún no implementado. Arrancando en modo CLI por ahora.\n")

    # 5) Lanzamos la CLI (bucle interactivo)
    run_cli(settings=settings, paths=paths)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())