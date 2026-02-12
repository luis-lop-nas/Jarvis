"""
store.py

Memoria persistente con SQLite.

Qué hace:
- inicializa la DB si no existe (aplicando schema.sql)
- crea sesiones
- guarda mensajes (user/assistant/tool)
- guarda eventos de tools (args/result)

En el “gran update final” lo conectaremos al agente para:
- persistir historial
- registrar tool calls
- rehidratar contexto al arrancar
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def _now() -> str:
    """Timestamp ISO para SQLite."""
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class MemoryStore:
    db_path: Path
    schema_path: Path

    def connect(self) -> sqlite3.Connection:
        """Abre conexión SQLite (crea carpeta si hace falta)."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Crea tablas si no existen usando schema.sql."""
        schema_sql = self.schema_path.read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.executescript(schema_sql)
            conn.commit()

    def create_session(self) -> str:
        """Crea una sesión nueva y devuelve session_id."""
        session_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                (session_id, _now()),
            )
            conn.commit()
        return session_id

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """Guarda un mensaje en la sesión (role=user/assistant/tool)."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, _now()),
            )
            conn.commit()

    def add_tool_event(
        self,
        session_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_result: Dict[str, Any],
    ) -> None:
        """Guarda un evento de tool (args + result en JSON)."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO tool_events (session_id, tool_name, tool_args, tool_result, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    tool_name,
                    json.dumps(tool_args, ensure_ascii=False),
                    json.dumps(tool_result, ensure_ascii=False),
                    _now(),
                ),
            )
            conn.commit()

    def get_recent_messages(self, session_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """
        Devuelve los últimos N mensajes en orden cronológico (role, content, created_at).
        """
        limit = max(1, min(int(limit), 500))
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()

        # Están en orden inverso, los devolvemos en orden normal
        return [dict(r) for r in reversed(rows)]