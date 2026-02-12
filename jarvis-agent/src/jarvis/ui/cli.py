"""
cli.py

Interfaz CLI con memoria persistente.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

from jarvis.agent.tool_agent import tool_agent_from_settings
from jarvis.memory.store import MemoryStore


console = Console()


def print_welcome() -> None:
    """Imprime banner de bienvenida."""
    console.print(
        Panel(
            "[bold cyan]Jarvis Agent - CLI[/bold cyan]\n"
            "Escribe tu petición o usa /help para ver comandos.",
            title="🤖 Bienvenido",
            border_style="cyan",
        )
    )


def print_help() -> None:
    """Muestra ayuda de comandos."""
    help_text = """
[bold cyan]Comandos disponibles:[/bold cyan]

  /help      - Muestra esta ayuda
  /exit      - Salir de Jarvis
  /quit      - Salir de Jarvis
  /clear     - Limpiar pantalla
  /paths     - Ver rutas del proyecto
  /debug     - Ver estado de debug
  /reset     - Borrar memoria de sesión actual
  /sessions  - Ver sesiones anteriores
  /search    - Buscar en historial: /search <query>
    """
    console.print(Panel(help_text.strip(), border_style="blue"))


def run_cli(settings: Any, paths: Any) -> None:
    """Ejecuta el CLI interactivo con memoria."""
    
    # Inicializar memoria
    memory_store = MemoryStore(paths.db_path)
    
    # Crear agente con memoria
    agent = tool_agent_from_settings(
        settings,
        memory_store=memory_store
    )
    
    # Setup logging
    log_dir = paths.logs_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = log_dir / f"session_{timestamp}.log"
    
    print_welcome()
    
    try:
        while True:
            try:
                user_input = console.input("[bold green]Tú:[/bold green] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Saliendo...[/yellow]")
                break
            
            if not user_input:
                continue
            
            # Comandos especiales
            if user_input.startswith("/"):
                cmd_parts = user_input.split(maxsplit=1)
                cmd = cmd_parts[0].lower()
                
                if cmd in ["/exit", "/quit"]:
                    console.print("[yellow]👋 Hasta luego![/yellow]")
                    break
                
                elif cmd == "/help":
                    print_help()
                    continue
                
                elif cmd == "/clear":
                    console.clear()
                    print_welcome()
                    continue
                
                elif cmd == "/paths":
                    console.print(f"[cyan]Raíz proyecto:[/cyan] {paths.project_root}")
                    console.print(f"[cyan]Data dir:[/cyan] {paths.data_dir}")
                    console.print(f"[cyan]Workspace:[/cyan] {paths.workspace_dir}")
                    console.print(f"[cyan]Logs:[/cyan] {paths.logs_dir}")
                    console.print(f"[cyan]Base de datos:[/cyan] {paths.db_path}")
                    continue
                
                elif cmd == "/debug":
                    console.print(f"[cyan]Debug:[/cyan] {settings.debug}")
                    console.print(f"[cyan]Groq:[/cyan] {settings.use_groq}")
                    console.print(f"[cyan]Sesión ID:[/cyan] {agent.config.session_id}")
                    continue
                
                elif cmd == "/reset":
                    agent.state.clear()
                    console.print("[yellow]✓ Memoria de sesión borrada[/yellow]")
                    continue
                
                elif cmd == "/sessions":
                    sessions = memory_store.get_recent_sessions(limit=10)
                    if not sessions:
                        console.print("[yellow]No hay sesiones guardadas[/yellow]")
                    else:
                        console.print("\n[bold cyan]Sesiones recientes:[/bold cyan]")
                        for s in sessions:
                            console.print(f"  • {s['id'][:8]}... - {s['created_at']} ({s['message_count']} mensajes)")
                    continue
                
                elif cmd == "/search":
                    if len(cmd_parts) < 2:
                        console.print("[yellow]Uso: /search <término>[/yellow]")
                        continue
                    
                    query = cmd_parts[1]
                    results = memory_store.search_messages(query, limit=5)
                    
                    if not results:
                        console.print(f"[yellow]No se encontraron mensajes con '{query}'[/yellow]")
                    else:
                        console.print(f"\n[bold cyan]Resultados para '{query}':[/bold cyan]")
                        for r in results:
                            console.print(f"\n[dim]{r['created_at']}[/dim]")
                            console.print(f"[cyan]{r['role']}:[/cyan] {r['content'][:100]}...")
                    continue
                
                else:
                    console.print(f"[red]Comando desconocido: {cmd}[/red]")
                    console.print("[dim]Usa /help para ver comandos disponibles[/dim]")
                    continue
            
            # Log input
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] USER: {user_input}\n")
            
            # Procesar con agente
            response = agent.run(user_input)
            
            # Mostrar respuesta
            console.print(f"[bold blue]Jarvis:[/bold blue] {response}\n")
            
            # Log response
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] JARVIS: {response}\n")
    
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        if settings.debug:
            import traceback
            traceback.print_exc()
    
    console.print(f"\n[dim]Log guardado en: {log_file}[/dim]")
