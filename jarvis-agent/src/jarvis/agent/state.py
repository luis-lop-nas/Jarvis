"""
state.py

Estado y helpers del agente:
- AgentState: historial de mensajes en memoria (memoria corta)
- truncate_history: recorta el historial para no saturar el contexto
- count_tokens_estimate: estimación rápida de tokens
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Estado en memoria
# ---------------------------------------------------------------------------

@dataclass
class AgentState:
    """Historial de mensajes en memoria para la sesión actual."""

    history: List[Dict[str, Any]] = field(default_factory=list)

    def add_user(self, content: str) -> None:
        self.history.append({"role": "user", "content": content})

    def add_assistant(self, content: str) -> None:
        self.history.append({"role": "assistant", "content": content})

    def add_tool(self, tool_call_id: str, content: str) -> None:
        self.history.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })

    def clear(self) -> None:
        self.history.clear()

    def get_messages(self) -> List[Dict[str, Any]]:
        return list(self.history)


# ---------------------------------------------------------------------------
# Helpers de contexto
# ---------------------------------------------------------------------------

def truncate_history(
    history: List[Dict[str, Any]],
    max_messages: int = 20,
) -> List[Dict[str, Any]]:
    """
    Devuelve los últimos max_messages mensajes.
    Si hay system prompt al inicio, lo preserva siempre.
    """
    if len(history) <= max_messages:
        return history

    if history and history[0].get("role") == "system":
        return [history[0]] + history[-(max_messages - 1):]

    return history[-max_messages:]


def count_tokens_estimate(messages: List[Dict[str, Any]]) -> int:
    """Estimación rápida de tokens (~4 chars = 1 token)."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content)
        if "tool_calls" in msg:
            total += len(str(msg["tool_calls"]))
    return total // 4


def format_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")
