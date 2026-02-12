"""
cli.py

Interfaz de terminal (CLI) para Jarvis.

Objetivo V1:
- Tener un bucle interactivo sólido (tipo chat)
- Comandos básicos para inspección y depuración
- Logging a archivo (para trazas y futura memoria)
- Punto único donde, más adelante, conectaremos:
    - Agente (GPT-5 Codex)
    - Tools (run_code, web_search, open_app, etc.)
    - Voz (cuando el wake word dispare una "consulta")

Este módulo NO debe contener lógica de tools ni del modelo.
Solo UI y enrutado básico.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt


# ---------------------------
# Helpers de logging simple
# ---------------------------

def _timestamp() -> str:
    """Timestamp legible para logs."""
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_write_line(path: Path, line: str) -> None:
    """
    Escribe una línea en un archivo (append).
    Si algo falla, no queremos tumbar la app por el log.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # Silencioso a propósito: logging nunca debe romper la app.
        pass


def _make_session_log_path(logs_dir: Path) -> Path:
    """
    Crea un nombre de archivo único por sesión.
    Ejemplo: data/logs/session_2026-02-12_13-30-01.log
    """
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return logs_dir / f"session_{stamp}.log"


# ---------------------------
# Comandos internos del CLI
# ---------------------------

def _print_help(console: Console) -> None:
    """Muestra ayuda rápida de comandos."""
    console.print(
        Panel(
            "\n".join(
                [
                    "[b]Comandos:[/b]",
                    "  [cyan]/help[/cyan]     - muestra esta ayuda",
                    "  [cyan]/exit[/cyan]     - salir",
                    "  [cyan]/clear[/cyan]    - limpiar pantalla",
                    "  [cyan]/paths[/cyan]    - ver rutas del proyecto (data/logs/workspace/db)",
                    "  [cyan]/debug[/cyan]    - ver estado de debug",
                    "",
                    "[b]Uso:[/b]",
                    "  Escribe una petición normal y Jarvis responderá.",
                    "  (De momento responde en modo placeholder; luego lo conectamos al agente GPT-5 Codex).",
                ]
            ),
            title="Jarvis CLI",
        )
    )


def _handle_command(
    cmd: str,
    *,
    console: Console,
    settings: Any,
    paths: Any,
) -> bool:
    """
    Maneja comandos internos.

    Devuelve:
      True  => seguir en el bucle
      False => salir del bucle
    """
    cmd = cmd.strip().lower()

    if cmd in ("/exit", "/quit"):
        console.print("[yellow]Saliendo...[/yellow]")
        return False

    if cmd == "/help":
        _print_help(console)
        return True

    if cmd == "/clear":
        console.clear()
        return True

    if cmd == "/paths":
        # paths es el dataclass Paths (config.py)
        text = "\n".join(
            [
                f"[b]project_root[/b]: {paths.project_root}",
                f"[b]data_dir[/b]:     {paths.data_dir}",
                f"[b]logs_dir[/b]:     {paths.logs_dir}",
                f"[b]workspace_dir[/b]:{paths.workspace_dir}",
                f"[b]db_path[/b]:      {paths.db_path}",
            ]
        )
        console.print(Panel(text, title="Paths"))
        return True

    if cmd == "/debug":
        console.print(Panel(f"debug = {getattr(settings, 'debug', False)}", title="Debug"))
        return True

    console.print("[red]Comando no reconocido.[/red] Usa /help.")
    return True


# ---------------------------
# Respuesta placeholder (por ahora)
# ---------------------------

def _placeholder_response(user_text: str) -> str:
    """
    Mientras aún no conectamos el agente (GPT-5 Codex), devolvemos una respuesta simple.

    En el siguiente paso, este método se sustituirá por algo tipo:
      response = agent.run(user_text)
    """
    user_text = user_text.strip()
    if not user_text:
        return "No he recibido nada. Prueba a escribir una petición."
    return (
        "🛠️ (placeholder) He recibido: "
        f"'{user_text}'.\n"
        "Cuando conectemos el agente, aquí decidiré acciones (tools) y te responderé."
    )


# ---------------------------
# Bucle principal del CLI
# ---------------------------

def run_cli(*, settings: Any, paths: Any) -> None:
    """
    Arranca el bucle interactivo de la terminal.

    - settings: objeto Settings de config.py
    - paths: objeto Paths de config.py

    Este método no devuelve nada: controla la sesión CLI.
    """
    console = Console()

    # Archivo de log por sesión
    session_log = _make_session_log_path(paths.logs_dir)

    # Mensaje de bienvenida
    console.print(
        Panel(
            "\n".join(
                [
                    "[b]Jarvis Agent[/b] (V1)",
                    "",
                    "✅ CLI listo. Próximo paso: conectar agente GPT-5 Codex + tools.",
                    "💡 Escribe [cyan]/help[/cyan] para ver comandos.",
                ]
            ),
            title="Bienvenido",
        )
    )

    _safe_write_line(session_log, f"[{_timestamp()}] Session started")

    # Bucle principal
    while True:
        try:
            user_text = Prompt.ask("[bold cyan]Tú[/bold cyan]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Interrumpido. Saliendo...[/yellow]")
            break

        # Log de entrada
        _safe_write_line(session_log, f"[{_timestamp()}] USER: {user_text}")

        # Si es comando (/algo), lo gestionamos
        if user_text.startswith("/"):
            keep_running = _handle_command(user_text, console=console, settings=settings, paths=paths)
            if not keep_running:
                break
            continue

        # Respuesta (por ahora placeholder)
        jarvis_text = _placeholder_response(user_text)

        # Mostrar
        console.print(Panel(jarvis_text, title="Jarvis"))

        # Log de salida
        _safe_write_line(session_log, f"[{_timestamp()}] JARVIS: {jarvis_text}")

    _safe_write_line(session_log, f"[{_timestamp()}] Session ended")