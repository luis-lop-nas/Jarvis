"""
registry.py

Registro centralizado de herramientas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass
class ToolSpec:
    """Especificación de una herramienta."""
    name: str
    description: str
    fn: Callable[..., Dict[str, Any]]
    schema: Optional[Dict[str, str]] = None


class ToolRegistry:
    """Registro de herramientas disponibles."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """Registra una herramienta."""
        self._tools[spec.name] = spec

    def list(self) -> Dict[str, ToolSpec]:
        """Lista todas las herramientas."""
        return self._tools.copy()

    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta una herramienta por nombre."""
        spec = self._tools.get(name)
        if not spec:
            return {"ok": False, "error": f"Tool desconocida: {name}"}

        try:
            return spec.fn(args)
        except TypeError as e:
            return {"ok": False, "error": f"Argumentos inválidos: {e}"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def build_default_registry() -> ToolRegistry:
    """Construye el registro por defecto con todas las herramientas."""
    from jarvis.tools import (
        filesystem,
        open_app,
        run_code,
        shell,
        web_search,
        spotify,
        calendar,
        email,
        vision,
    )

    registry = ToolRegistry()

    # 1. Shell
    registry.register(
        ToolSpec(
            name="shell",
            description="Ejecuta un comando de shell (macOS/Linux). Útil para comandos del sistema, git, npm, etc.",
            fn=shell.run_shell,
            schema={
                "command": "Comando a ejecutar (obligatorio)",
                "cwd": "Directorio de trabajo (opcional)",
                "timeout_sec": "Timeout en segundos (opcional, default 30)",
                "allow_dangerous": "Permitir comandos peligrosos (bool, opcional)",
            },
        )
    )

    # 2. Filesystem
    registry.register(
        ToolSpec(
            name="filesystem",
            description="Opera sobre archivos en el workspace. Acciones: write_text, read_text, list_dir, mkdir, exists, delete",
            fn=filesystem.run_filesystem,
            schema={
                "action": "Acción a realizar: write_text, read_text, list_dir, mkdir, exists, delete (obligatorio)",
                "path": "Ruta relativa al workspace (obligatorio)",
                "content": "Contenido (para write_text)",
                "recursive": "Recursivo (bool, para delete/mkdir)",
            },
        )
    )

    # 3. Open App
    registry.register(
        ToolSpec(
            name="open_app",
            description="Abre aplicaciones, URLs o archivos en macOS usando el comando 'open'",
            fn=open_app.run_open_app,
            schema={
                "app": "Nombre de la aplicación (ej: Spotify, Safari)",
                "target": "URL o ruta de archivo a abrir",
                "wait": "Esperar a que la app termine (bool)",
                "new_instance": "Abrir nueva instancia (bool)",
            },
        )
    )

    # 4. Run Code
    registry.register(
        ToolSpec(
            name="run_code",
            description="Ejecuta código Python o Node.js en sandbox Docker aislado",
            fn=run_code.run_code,
            schema={
                "language": "Lenguaje: 'python' o 'node' (obligatorio)",
                "code": "Código a ejecutar (snippet)",
                "file": "Ruta a archivo de código (alternativa a 'code')",
                "timeout_sec": "Timeout en segundos (opcional, default 30)",
            },
        )
    )

    # 5. Web Search
    registry.register(
        ToolSpec(
            name="web_search",
            description="Busca información en internet usando DuckDuckGo",
            fn=web_search.run_web_search,
            schema={
                "query": "Término de búsqueda (obligatorio)",
                "limit": "Número de resultados (opcional, default 5, max 10)",
            },
        )
    )

    # 6. Spotify
    registry.register(
        ToolSpec(
            name="spotify",
            description="Controla Spotify: play, pause, next, previous, status, volume_up, volume_down",
            fn=spotify.spotify_control,
            schema={
                "action": "Acción: play, pause, next, previous, status, volume_up, volume_down (obligatorio)",
            },
        )
    )

    # 7. Calendar
    registry.register(
        ToolSpec(
            name="calendar",
            description="Consulta el calendario de macOS: today, tomorrow, week, create (recordatorio)",
            fn=calendar.calendar_query,
            schema={
                "action": "Acción: today, tomorrow, week, create (obligatorio)",
                "query": "Texto para búsqueda o título del recordatorio (para 'create')",
            },
        )
    )

    # 8. Email
    registry.register(
        ToolSpec(
            name="send_email",
            description="Envía emails usando Mail.app de macOS",
            fn=email.send_email,
            schema={
                "to": "Destinatario (email, obligatorio)",
                "subject": "Asunto del email (obligatorio)",
                "body": "Cuerpo del mensaje",
                "action": "send o draft (opcional, default send)",
            },
        )
    )

    # 9. Vision (NUEVO)
    registry.register(
        ToolSpec(
            name="vision",
            description="Analiza lo que hay en pantalla. Puede describir, responder preguntas, o leer texto (OCR)",
            fn=vision.vision_command,
            schema={
                "action": "describe, answer, read, context (obligatorio)",
                "question": "Pregunta sobre la pantalla (para action='answer')",
                "capture_mode": "full o window (opcional, default full)",
            },
        )
    )

    return registry
