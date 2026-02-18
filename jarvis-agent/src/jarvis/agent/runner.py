"""
runner.py

Configuración base del agente.
AgentConfig: parámetros comunes a cualquier motor LLM (debug, etc.)
AgentState: historial en memoria → ver state.py
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentConfig:
    """Configuración base del agente."""
    debug: bool = False
