"""
runner.py

Clases base para el agente:
- AgentConfig: configuración del agente (API key, modelo, etc.)
- AgentState: estado en memoria (historial de mensajes)

Estos son los building blocks que usa ToolAgent y otros agentes futuros.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AgentConfig:
    """
    Configuración base del agente.
    
    Parámetros comunes a cualquier agente que use OpenAI:
    - api_key: clave de API de OpenAI
    - model: nombre del modelo (ej: "gpt-4", "gpt-3.5-turbo", "gpt-5.2-codex")
    - org: organización de OpenAI (opcional)
    - project: proyecto de OpenAI (opcional)
    - debug: modo debug (más logs, errores detallados)
    """
    api_key: str = ""
    model: str = "gpt-4"
    org: str = ""
    project: str = ""
    debug: bool = False


@dataclass
class AgentState:
    """
    Estado en memoria del agente (historial de mensajes).
    
    - history: lista de mensajes en formato OpenAI
      [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
    
    Esto es la "memoria corta" de la sesión actual.
    Más adelante lo conectaremos con MemoryStore (SQLite) para persistencia.
    """
    history: List[Dict[str, Any]] = field(default_factory=list)
    
    def add_user(self, content: str) -> None:
        """Añade un mensaje del usuario al historial."""
        self.history.append({"role": "user", "content": content})
    
    def add_assistant(self, content: str) -> None:
        """Añade un mensaje del asistente al historial."""
        self.history.append({"role": "assistant", "content": content})
    
    def add_tool(self, tool_call_id: str, content: str) -> None:
        """Añade un resultado de tool al historial."""
        self.history.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        })
    
    def clear(self) -> None:
        """Borra todo el historial (reset de sesión)."""
        self.history.clear()
    
    def get_messages(self) -> List[Dict[str, Any]]:
        """Devuelve una copia del historial."""
        return list(self.history)