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
        code_assistant,
        knowledge,
        organize_files,
        download_file,
        system_info,
        datetime_tool,
        weather,
    )

    registry = ToolRegistry()

    # 1. Shell
    registry.register(
        ToolSpec(
            name="shell",
            description="Ejecuta un comando de shell (macOS/Linux)",
            fn=shell.run_shell,
            schema={
                "command": "Comando a ejecutar (obligatorio)",
                "cwd": "Directorio de trabajo (opcional)",
                "timeout_sec": "Timeout en segundos (opcional)",
                "allow_dangerous": "Permitir comandos peligrosos (bool, opcional)",
            },
        )
    )

    # 2. Filesystem
    registry.register(
        ToolSpec(
            name="filesystem",
            description="Opera sobre archivos: write_text, read_text, list_dir, mkdir, exists, delete, rename, move, copy. Puede trabajar en todo el sistema del usuario.",
            fn=filesystem.run_filesystem,
            schema={
                "action": "write_text, read_text, list_dir, mkdir, exists, delete, rename, move, copy (obligatorio)",
                "path": "Ruta del archivo/carpeta (puede ser absoluta, ej: ~/Desktop/archivo.txt)",
                "content": "Contenido (para write_text)",
                "new_name": "Nuevo nombre (para rename)",
                "destination": "Ruta de destino (para move/copy)",
                "recursive": "Recursivo (bool, para delete/copy)",
            },
        )
    )

    # 3. Open App
    registry.register(
        ToolSpec(
            name="open_app",
            description="Abre aplicaciones, URLs o archivos en macOS",
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
            description="Ejecuta código Python o Node.js en sandbox Docker",
            fn=run_code.run_code,
            schema={
                "language": "python o node (obligatorio)",
                "code": "Código a ejecutar",
                "file": "Ruta a archivo de código",
                "timeout_sec": "Timeout en segundos (opcional)",
            },
        )
    )

    # 5. Web Search
    registry.register(
        ToolSpec(
            name="web_search",
            description="Busca información en internet",
            fn=web_search.run_web_search,
            schema={
                "query": "Término de búsqueda (obligatorio)",
                "limit": "Número de resultados (opcional, max 10)",
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
                "action": "play, pause, next, previous, status, volume_up, volume_down (obligatorio)",
            },
        )
    )

    # 7. Calendar
    registry.register(
        ToolSpec(
            name="calendar",
            description="Consulta calendario: today, tomorrow, week, create (recordatorio)",
            fn=calendar.calendar_query,
            schema={
                "action": "today, tomorrow, week, create (obligatorio)",
                "query": "Título del recordatorio (para create)",
            },
        )
    )

    # 8. Email
    registry.register(
        ToolSpec(
            name="send_email",
            description="Envía emails usando Mail.app",
            fn=email.send_email,
            schema={
                "to": "Destinatario (obligatorio)",
                "subject": "Asunto (obligatorio)",
                "body": "Cuerpo del mensaje",
                "action": "send o draft (opcional)",
            },
        )
    )

    # 9. Vision
    registry.register(
        ToolSpec(
            name="vision",
            description="Analiza pantalla: describe, answer, read (OCR), context",
            fn=vision.vision_command,
            schema={
                "action": "describe, answer, read, context (obligatorio)",
                "question": "Pregunta sobre la pantalla (para answer)",
                "capture_mode": "full o window (opcional)",
            },
        )
    )

    # 10. Code Assistant
    registry.register(
        ToolSpec(
            name="code_assistant",
            description="Genera o edita código. Abre automáticamente en VS Code.",
            fn=code_assistant.code_assistant,
            schema={
                "task": "Descripción de lo que debe programar (obligatorio)",
                "language": "Lenguaje de programación (python, javascript, etc.)",
                "file_path": "Ruta del archivo (opcional, se genera auto)",
                "open_vscode": "Abrir en VS Code (bool, default true)",
            },
        )
    )

    # 11. Knowledge Base
    registry.register(
        ToolSpec(
            name="knowledge",
            description="Gestiona base de conocimiento: search (buscar info), add (añadir doc), add_code (añadir código), add_tutorial (añadir tutorial), list (listar), delete, stats",
            fn=knowledge.knowledge_tool,
            schema={
                "action": "search, add, add_code, add_tutorial, list, delete, stats (obligatorio)",
                "query": "Consulta de búsqueda (para search)",
                "content": "Contenido a guardar (para add/add_code/add_tutorial)",
                "title": "Título o descripción",
                "language": "Lenguaje (para add_code, default python)",
                "category": "Categoría (para add_tutorial)",
                "tags": "Tags separados por comas (para add_code)",
                "doc_id": "ID del documento (para delete)",
                "n_results": "Número de resultados (para search, default 3)",
            },
        )
    )

    # 12. Organize Files
    registry.register(
        ToolSpec(
            name="organize_files",
            description="Organiza archivos automáticamente por tipo, fecha o de forma inteligente. Mueve archivos a carpetas apropiadas sin preguntar.",
            fn=organize_files.run_organize_files,
            schema={
                "source_dir": "Directorio a organizar (ej: ~/Downloads)",
                "dest_dir": "Directorio base destino (ej: ~/ organiza en ~/Documents, ~/Pictures, etc.)",
                "mode": "by_type (por extensión), by_date (por fecha), smart (inteligente, default)",
                "dry_run": "Solo simular sin mover (bool, default false)",
                "recursive": "Buscar en subdirectorios (bool, default false)",
                "patterns": "Lista de patrones glob (ej: ['*.pdf', '*.jpg'])",
            },
        )
    )

    # 13. Download File (NUEVO)
    registry.register(
        ToolSpec(
            name="download_file",
            description="Descarga archivos de internet. Se organiza automáticamente por tipo en la carpeta correcta.",
            fn=download_file.run_download_file,
            schema={
                "url": "URL del archivo a descargar (obligatorio)",
                "filename": "Nombre del archivo (opcional, se detecta auto)",
                "destination": "Directorio destino (opcional, se organiza auto)",
                "organize": "Organizar por tipo automáticamente (bool, default true)",
                "timeout": "Timeout en segundos (default 60)",
            },
        )
    )

    # 14. Search and Download
    registry.register(
        ToolSpec(
            name="search_and_download",
            description="Busca un archivo en internet y lo descarga automáticamente. Ej: 'Python tutorial PDF', 'React logo PNG'",
            fn=download_file.search_and_download,
            schema={
                "query": "Búsqueda del archivo (obligatorio)",
                "file_type": "Tipo de archivo (ej: pdf, png, mp3, etc.)",
                "organize": "Organizar automáticamente (bool, default true)",
            },
        )
    )

    # 15. System Info
    registry.register(
        ToolSpec(
            name="system_info",
            description="Monitorización del sistema: CPU, RAM, disco, batería, red, procesos activos, tiempo de actividad",
            fn=system_info.run_system_info,
            schema={
                "action": "cpu, ram, disk, battery, network, processes, uptime, all (obligatorio)",
                "top_n": "Número de procesos a mostrar (para processes, default 10)",
            },
        )
    )

    # 16. DateTime
    registry.register(
        ToolSpec(
            name="datetime",
            description="Fecha y hora actual con zona horaria, día de la semana, número de semana, etc.",
            fn=datetime_tool.run_datetime,
            schema={
                "format": "full (todo), time (solo hora), date (solo fecha), timestamp (unix). Default: full",
            },
        )
    )

    # 17. Weather
    registry.register(
        ToolSpec(
            name="weather",
            description="Clima actual y pronóstico de cualquier ciudad (temperatura, humedad, viento, descripción). Sin API key.",
            fn=weather.run_weather,
            schema={
                "city": "Ciudad (obligatorio, ej: Madrid, Barcelona, New York)",
                "days": "Días de pronóstico adicionales (0-2, default 0 = solo hoy)",
            },
        )
    )

    return registry
