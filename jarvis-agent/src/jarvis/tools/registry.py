"""
registry.py

Registro de herramientas (tools) disponibles para Jarvis.

Idea:
- Cada herramienta es una función Python que recibe un dict (args) y devuelve un dict (result).
- Las tools se registran con:
    - name: nombre corto (ej: "shell", "open_app", "run_code")
    - description: para que el agente sepa cuándo usarla
    - schema: contrato simple de parámetros esperados (documentación/validación ligera)

Más adelante:
- Este registro servirá para exponer tools al modelo (tool-calling),
  ejecutar la tool elegida, y devolver el resultado al modelo para que continúe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from jarvis.tools.shell import run_shell
from jarvis.tools.filesystem import run_filesystem
from jarvis.tools.open_app import run_open_app
from jarvis.tools.run_code import run_code
from jarvis.tools.web_search import run_web_search


# Tipo estándar de tool:
# - args: dict con parámetros
# - returns: dict con resultado
ToolFn = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    """
    Especificación de una tool.

    name: nombre único (clave en el registry)
    description: texto breve que explica qué hace
    schema: dict simple con "fields" esperados (para documentar parámetros)
    fn: función que ejecuta la tool
    """
    name: str
    description: str
    schema: Dict[str, Any]
    fn: ToolFn


class ToolRegistry:
    """
    Registro de herramientas.

    Permite:
    - register(...) para añadir tools
    - list() para inspeccionar
    - call(name, args) para ejecutar una tool
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """Registra una tool. Error si el nombre ya existe."""
        name = spec.name.strip()
        if not name:
            raise ValueError("ToolSpec.name no puede estar vacío.")
        if name in self._tools:
            raise ValueError(f"La tool '{name}' ya está registrada.")
        self._tools[name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        """Devuelve una tool si existe, o None si no existe."""
        return self._tools.get(name)

    def list(self) -> Dict[str, ToolSpec]:
        """Devuelve un dict {name: ToolSpec} de todas las tools registradas."""
        return dict(self._tools)

    def call(self, name: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Ejecuta una tool por nombre.

        Convención de retorno:
        - {"ok": True, "result": {...}}
        - {"ok": False, "error": "..."}
        """
        args = args or {}
        spec = self._tools.get(name)
        if not spec:
            return {"ok": False, "error": f"Tool no encontrada: '{name}'"}

        try:
            result = spec.fn(args)
            return {"ok": True, "result": result}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def build_default_registry() -> ToolRegistry:
    """
    Crea un registry con todas las tools disponibles registradas.

    Tools registradas:
    1. shell: ejecutar comandos del sistema (macOS)
    2. filesystem: leer/escribir archivos en workspace
    3. open_app: abrir aplicaciones en macOS
    4. run_code: ejecutar código Python/Node en sandbox Docker
    5. web_search: buscar información en la web
    """
    reg = ToolRegistry()

    # 1) SHELL
    reg.register(
        ToolSpec(
            name="shell",
            description=(
                "Ejecuta comandos en la terminal (macOS). "
                "Devuelve stdout/stderr/returncode. "
                "Usa para automatizar tareas del sistema, git, npm, etc."
            ),
            schema={
                "command": "str (obligatorio) - comando a ejecutar",
                "cwd": "str (opcional) - directorio de trabajo",
                "timeout_sec": "int (opcional, default 30) - timeout en segundos",
                "env": "dict (opcional) - variables de entorno extra",
                "allow_dangerous": "bool (opcional, default False) - permite comandos destructivos",
                "shell": "bool (opcional, default True) - ejecutar como shell",
            },
            fn=run_shell,
        )
    )

    # 2) FILESYSTEM
    reg.register(
        ToolSpec(
            name="filesystem",
            description=(
                "Operaciones de archivos dentro del workspace (data/workspace/). "
                "Acciones: write_text, read_text, list_dir, mkdir, exists, delete. "
                "Usa para crear, leer, modificar archivos de forma segura."
            ),
            schema={
                "action": "str (obligatorio) - write_text|read_text|list_dir|mkdir|exists|delete",
                "path": "str (según action) - ruta relativa dentro del workspace",
                "content": "str (solo write_text) - contenido a escribir",
                "root_dir": "str (opcional, default 'data/workspace') - directorio raíz",
                "recursive": "bool (solo delete, opcional) - borrar recursivo",
            },
            fn=run_filesystem,
        )
    )

    # 3) OPEN_APP
    reg.register(
        ToolSpec(
            name="open_app",
            description=(
                "Abre aplicaciones, URLs o archivos en macOS usando el comando 'open'. "
                "Ejemplos: abrir Spotify, Visual Studio Code, URLs, archivos."
            ),
            schema={
                "app": "str (opcional) - nombre de la aplicación (ej: 'Spotify', 'Visual Studio Code')",
                "target": "str (opcional) - URL o ruta de archivo",
                "wait": "bool (opcional, default False) - esperar a que termine",
                "new_instance": "bool (opcional, default False) - nueva instancia",
                "args": "list[str] (opcional) - argumentos extra para la app",
            },
            fn=run_open_app,
        )
    )

    # 4) RUN_CODE
    reg.register(
        ToolSpec(
            name="run_code",
            description=(
                "Ejecuta código Python o Node.js en un sandbox Docker aislado. "
                "Monta el workspace y devuelve stdout/stderr. "
                "Usa para ejecutar scripts, probar código, análisis de datos."
            ),
            schema={
                "language": "str (obligatorio) - 'python' o 'node'",
                "code": "str (opcional) - snippet de código a ejecutar",
                "file": "str (opcional) - ruta relativa del archivo en workspace",
                "workspace_dir": "str (opcional, default 'data/workspace')",
                "timeout_sec": "int (opcional, default 30)",
                "image": "str (opcional) - override imagen docker",
                "extra_args": "list[str] (opcional) - argumentos para el script",
            },
            fn=run_code,
        )
    )

    # 5) WEB_SEARCH
    reg.register(
        ToolSpec(
            name="web_search",
            description=(
                "Busca información en la web usando DuckDuckGo. "
                "Devuelve título, URL y snippet de los resultados. "
                "Usa para buscar información actualizada, noticias, tutoriales."
            ),
            schema={
                "query": "str (obligatorio) - consulta de búsqueda",
                "limit": "int (opcional, default 5, max 10) - número de resultados",
            },
            fn=run_web_search,
        )
    )

    return reg