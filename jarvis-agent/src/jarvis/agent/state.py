"""
state.py

Gestión de estado avanzada del agente.

Por ahora AgentState en runner.py es suficiente para la memoria en RAM.
Este archivo lo usaremos más adelante para:
- Conectar memoria persistente (SQLite)
- Gestionar contexto largo (resumir historial viejo)
- Tracking de tareas pendientes
- Estado de herramientas activas

De momento dejamos helpers útiles para cuando los necesitemos.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime


def truncate_history(
    history: List[Dict[str, Any]], 
    max_messages: int = 20
) -> List[Dict[str, Any]]:
    """
    Trunca el historial manteniendo solo los últimos N mensajes.
    
    Útil para evitar que el contexto crezca infinitamente.
    Siempre mantiene el system prompt si existe.
    """
    if len(history) <= max_messages:
        return history
    
    # Si hay system prompt al inicio, lo preservamos
    if history and history[0].get("role") == "system":
        return [history[0]] + history[-(max_messages - 1):]
    
    return history[-max_messages:]


def count_tokens_estimate(messages: List[Dict[str, Any]]) -> int:
    """
    Estimación aproximada de tokens (regla: ~4 chars = 1 token).
    
    Para control real de tokens, usar tiktoken.
    Esto es solo una aproximación rápida.
    """
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        # Si hay tool_calls u otros campos, también los contamos
        if "tool_calls" in msg:
            total_chars += len(str(msg["tool_calls"]))
    
    return total_chars // 4


def format_timestamp() -> str:
    """Timestamp para logging/debugging."""
    return datetime.now().isoformat(timespec="seconds")


class SessionContext:
    """
    Contexto de sesión (wrapper sobre AgentState con metadata).
    
    Útil para tracking de:
    - Cuándo empezó la sesión
    - Cuántas interacciones ha habido
    - Qué tools se han usado
    
    De momento es opcional, pero lo dejamos listo.
    """
    
    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or f"session_{format_timestamp()}"
        self.started_at = format_timestamp()
        self.interaction_count = 0
        self.tools_used: List[str] = []
    
    def record_interaction(self) -> None:
        """Incrementa contador de interacciones."""
        self.interaction_count += 1
    
    def record_tool_use(self, tool_name: str) -> None:
        """Registra que se usó una tool."""
        if tool_name not in self.tools_used:
            self.tools_used.append(tool_name)
    
    def get_stats(self) -> Dict[str, Any]:
        """Devuelve estadísticas de la sesión."""
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "interactions": self.interaction_count,
            "tools_used": self.tools_used,
        }