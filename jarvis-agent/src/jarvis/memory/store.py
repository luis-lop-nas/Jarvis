"""
store.py

Gestión de memoria persistente en SQLite.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class MemoryStore:
    """Store de memoria persistente con conexiones thread-local y WAL mode."""

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()   # conexión per-thread
        self._lock = threading.Lock()      # solo para contador VACUUM
        self._write_count = 0
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Devuelve (creando si no existe) la conexión SQLite del thread actual."""
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(str(self._db_path), check_same_thread=True)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        """Inicializa la base de datos con el schema."""
        schema_path = Path(__file__).parent / "schema.sql"
        conn = self._get_conn()
        with open(schema_path, 'r') as f:
            conn.executescript(f.read())
        conn.commit()

    def _increment_write(self) -> None:
        """Incrementa el contador de escrituras; ejecuta VACUUM cada 100."""
        with self._lock:
            self._write_count += 1
            do_vacuum = (self._write_count % 100 == 0)
        if do_vacuum:
            try:
                self._get_conn().execute("VACUUM")
            except Exception:
                pass

    # ── Public API ───────────────────────────────────────────────────────────

    def create_session(self) -> str:
        """Crea una nueva sesión y retorna su ID."""
        session_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO sessions (id, created_at) VALUES (?, ?)",
            (session_id, timestamp),
        )
        conn.commit()
        self._increment_write()
        return session_id

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """Añade un mensaje a la sesión."""
        timestamp = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO messages (session_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, role, content, timestamp),
        )
        conn.commit()
        self._increment_write()

    def add_tool_event(
        self,
        session_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_result: Dict[str, Any],
    ) -> None:
        """Registra un evento de uso de herramienta."""
        timestamp = datetime.now().isoformat()
        conn = self._get_conn()
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
                timestamp,
            ),
        )
        conn.commit()
        self._increment_write()

    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Obtiene todos los mensajes de una sesión."""
        cursor = self._get_conn().execute(
            """
            SELECT role, content, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_recent_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Obtiene las sesiones más recientes."""
        cursor = self._get_conn().execute(
            """
            SELECT s.id, s.created_at, COUNT(m.id) as message_count
            FROM sessions s
            LEFT JOIN messages m ON s.id = m.session_id
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def search_messages(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Busca mensajes que contengan el query."""
        cursor = self._get_conn().execute(
            """
            SELECT m.session_id, m.role, m.content, m.created_at
            FROM messages m
            WHERE m.content LIKE ?
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            (f"%{query}%", limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        """Cierra la conexión del thread actual (si existe)."""
        if hasattr(self._local, "conn"):
            try:
                self._local.conn.close()
            except Exception:
                pass
            del self._local.conn

    # Alias de compatibilidad hacia atrás
    @property
    def db_path(self) -> Path:
        return self._db_path
