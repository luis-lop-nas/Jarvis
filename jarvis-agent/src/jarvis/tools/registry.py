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
    Crea un registry con las tools base registradas.

    Por ahora solo registramos:
    - shell: ejecutar comandos del sistema (macOS)

    En próximos pasos añadimos:
    - open_app
    - filesystem
    - run_code (Docker)
    - web_search
    """
    reg = ToolRegistry()

    reg.register(
        ToolSpec(
            name="shell",
            description=(
                "Ejecuta comandos en la terminal (macOS). "
                "Devuelve stdout/stderr/returncode. "
                "Usa para automatizar tareas del sistema."
            ),
            schema={
                "command": "str (obligatorio)",
                "cwd": "str (opcional)",
                "timeout_sec": "int (opcional, default 30)",
                "env": "dict (opcional)",
                "allow_dangerous": "bool (opcional, default False)",
                "shell": "bool (opcional, default True)",
            },
            fn=run_shell,
        )
    )

    return reg