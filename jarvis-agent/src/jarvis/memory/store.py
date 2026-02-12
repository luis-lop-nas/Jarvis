"""
store.py

Gestión de memoria persistente en SQLite.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class MemoryStore:
    """Store de memoria persistente."""
    
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self) -> None:
        """Inicializa la base de datos con el schema."""
        schema_path = Path(__file__).parent / "schema.sql"
        
        with sqlite3.connect(self.db_path) as conn:
            with open(schema_path, 'r') as f:
                conn.executescript(f.read())
            conn.commit()
    
    def create_session(self) -> str:
        """Crea una nueva sesión y retorna su ID."""
        session_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                (session_id, timestamp)
            )
            conn.commit()
        
        return session_id
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """Añade un mensaje a la sesión."""
        timestamp = datetime.now().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, timestamp)
            )
            conn.commit()
    
    def add_tool_event(
        self,
        session_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_result: Dict[str, Any],
    ) -> None:
        """Registra un evento de uso de herramienta."""
        timestamp = datetime.now().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tool_events 
                (session_id, tool_name, tool_args, tool_result, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    tool_name,
                    json.dumps(tool_args),
                    json.dumps(tool_result),
                    timestamp
                )
            )
            conn.commit()
    
    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Obtiene todos los mensajes de una sesión."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT role, content, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (session_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def get_recent_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Obtiene las sesiones más recientes."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT s.id, s.created_at, COUNT(m.id) as message_count
                FROM sessions s
                LEFT JOIN messages m ON s.id = m.session_id
                GROUP BY s.id
                ORDER BY s.created_at DESC
                LIMIT ?
                """,
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def search_messages(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Busca mensajes que contengan el query."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT m.session_id, m.role, m.content, m.created_at
                FROM messages m
                WHERE m.content LIKE ?
                ORDER BY m.created_at DESC
                LIMIT ?
                """,
                (f"%{query}%", limit)
            )
            return [dict(row) for row in cursor.fetchall()]
