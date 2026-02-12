"""
cli.py

Interfaz de terminal (CLI) para Jarvis.

Qué hace:
- Bucle interactivo tipo chat
- Comandos básicos (/help, /exit, /clear, /paths, /debug, /reset)
- Logging a archivo por sesión (data/logs/session_....log)
- Conecta con el agente con herramientas (ToolAgent):
  - El modelo puede pedir ejecutar tools (por ahora: shell)
  - Jarvis ejecuta la tool y devuelve el resultado al modelo
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from jarvis.agent.tool_agent import tool_agent_from_settings


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
                    "  [cyan]/reset[/cyan]    - borra la memoria de sesión del agente (historial)",
                    "",
                    "[b]Uso:[/b]",
                    "  Escribe una petición normal y Jarvis responderá.",
                    "  Si hace falta, llamará tools (shell, filesystem, run_code, etc.) para ejecutar acciones.",
                    "",
                    "[b]Ejemplos:[/b]",
                    "  - 'Haz un ls de la carpeta actual'",
                    "  - 'Crea una carpeta llamada test y dime qué hay dentro'",
                    "  - 'Busca información sobre Python en la web'",
                    "  - 'Escribe un script que calcule los primeros 10 números de Fibonacci'",
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
    agent: Any,
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

    if cmd == "/reset":
        # Borra el historial en memoria (memoria corta de sesión)
        try:
            agent.state.clear()
            console.print("[green]Memoria de sesión borrada.[/green]")
        except Exception:
            console.print("[yellow]No se pudo borrar la memoria (estado no disponible).[/yellow]")
        return True

    console.print("[red]Comando no reconocido.[/red] Usa /help.")
    return True


# ---------------------------
# Bucle principal del CLI
# ---------------------------

def run_cli(*, settings: Any, paths: Any) -> None:
    """
    Arranca el bucle interactivo de la terminal.

    - settings: objeto Settings de config.py
    - paths: objeto Paths de config.py
    """
    console = Console()

    # Creamos el agente con tools una vez por sesión.
    # El registry ya tiene todas las tools registradas.
    agent = tool_agent_from_settings(settings)

    # Log de sesión
    log_path = _make_session_log_path(paths.logs_dir)
    _safe_write_line(log_path, f"=== Sesión iniciada: {_timestamp()} ===")

    # Banner de bienvenida
    console.print(
        Panel(
            "[b]Jarvis Agent[/b] - CLI\n"
            "Escribe tu petición o usa [cyan]/help[/cyan] para ver comandos.",
            title="🤖 Bienvenido",
            border_style="cyan",
        )
    )

    # Bucle principal
    while True:
        try:
            # Prompt
            user_input = Prompt.ask("\n[bold cyan]Tú[/bold cyan]").strip()

            if not user_input:
                continue

            # Log de entrada
            _safe_write_line(log_path, f"[{_timestamp()}] USER: {user_input}")

            # Comandos internos
            if user_input.startswith("/"):
                should_continue = _handle_command(
                    user_input,
                    console=console,
                    settings=settings,
                    paths=paths,
                    agent=agent,
                )
                if not should_continue:
                    break
                continue

            # Llamada al agente
            console.print("\n[bold magenta]Jarvis[/bold magenta]: ", end="")
            
            try:
                response = agent.run(user_input)
                console.print(response)
                
                # Log de respuesta
                _safe_write_line(log_path, f"[{_timestamp()}] ASSISTANT: {response}")
                
            except Exception as e:
                error_msg = f"Error: {type(e).__name__}: {e}"
                console.print(f"[red]{error_msg}[/red]")
                _safe_write_line(log_path, f"[{_timestamp()}] ERROR: {error_msg}")
                
                if settings.debug:
                    import traceback
                    console.print(traceback.format_exc())

        except KeyboardInterrupt:
            console.print("\n[yellow]Saliendo...[/yellow]")
            break
        except EOFError:
            console.print("\n[yellow]Saliendo...[/yellow]")
            break

    # Log de cierre
    _safe_write_line(log_path, f"=== Sesión finalizada: {_timestamp()} ===")
    console.print("\n[green]¡Hasta luego![/green]\n")