"""
tests/test_memory_store.py

Tests unitarios para MemoryStore (SQLite + WAL + thread-local).
No requiere ningún hardware especial.
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.memory.store import MemoryStore


# ─────────────────────────────────────────────────────────────────────────────
# Fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    db = tmp_path / "test_jarvis.db"
    s = MemoryStore(db)
    yield s
    s.close()


# ─────────────────────────────────────────────────────────────────────────────
# Creación y sesiones
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateSession:
    def test_returns_uuid(self, store: MemoryStore):
        sid = store.create_session()
        assert len(sid) == 36  # UUID4 estándar
        uuid.UUID(sid)  # no lanza

    def test_multiple_sessions_unique(self, store: MemoryStore):
        ids = [store.create_session() for _ in range(5)]
        assert len(set(ids)) == 5


# ─────────────────────────────────────────────────────────────────────────────
# add_message / get_session_messages
# ─────────────────────────────────────────────────────────────────────────────

class TestMessages:
    def test_add_and_get(self, store: MemoryStore):
        sid = store.create_session()
        store.add_message(sid, "user", "Hola")
        store.add_message(sid, "assistant", "Hola a ti")

        msgs = store.get_session_messages(sid)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hola"
        assert msgs[1]["role"] == "assistant"

    def test_empty_session(self, store: MemoryStore):
        sid = store.create_session()
        assert store.get_session_messages(sid) == []

    def test_messages_ordered_by_time(self, store: MemoryStore):
        sid = store.create_session()
        for i in range(5):
            store.add_message(sid, "user", f"Mensaje {i}")
        msgs = store.get_session_messages(sid)
        contents = [m["content"] for m in msgs]
        assert contents == [f"Mensaje {i}" for i in range(5)]


# ─────────────────────────────────────────────────────────────────────────────
# search_messages
# ─────────────────────────────────────────────────────────────────────────────

class TestSearch:
    def test_search_finds_match(self, store: MemoryStore):
        sid = store.create_session()
        store.add_message(sid, "user", "El clima en Madrid hoy")
        store.add_message(sid, "user", "Recuérdame comprar leche")

        results = store.search_messages("Madrid")
        assert len(results) == 1
        assert "Madrid" in results[0]["content"]

    def test_search_no_match(self, store: MemoryStore):
        sid = store.create_session()
        store.add_message(sid, "user", "Hola mundo")

        results = store.search_messages("Python")
        assert results == []

    def test_search_case_insensitive_via_like(self, store: MemoryStore):
        """LIKE en SQLite es case-insensitive para ASCII."""
        sid = store.create_session()
        store.add_message(sid, "user", "madrid capital")
        results = store.search_messages("MADRID")
        assert len(results) == 1


# ─────────────────────────────────────────────────────────────────────────────
# get_recent_sessions
# ─────────────────────────────────────────────────────────────────────────────

class TestRecentSessions:
    def test_returns_sessions(self, store: MemoryStore):
        for _ in range(3):
            sid = store.create_session()
            store.add_message(sid, "user", "msg")
        sessions = store.get_recent_sessions(limit=10)
        assert len(sessions) == 3

    def test_limit_respected(self, store: MemoryStore):
        for _ in range(5):
            store.create_session()
        sessions = store.get_recent_sessions(limit=2)
        assert len(sessions) == 2

    def test_message_count_in_session(self, store: MemoryStore):
        sid = store.create_session()
        for i in range(4):
            store.add_message(sid, "user", f"msg {i}")
        sessions = store.get_recent_sessions()
        target = next(s for s in sessions if s["id"] == sid)
        assert target["message_count"] == 4


# ─────────────────────────────────────────────────────────────────────────────
# WAL mode
# ─────────────────────────────────────────────────────────────────────────────

class TestWALMode:
    def test_wal_mode_enabled(self, store: MemoryStore):
        conn = store._get_conn()
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"


# ─────────────────────────────────────────────────────────────────────────────
# Escritura concurrente (10 threads)
# ─────────────────────────────────────────────────────────────────────────────

class TestConcurrentWrites:
    def test_no_corruption(self, tmp_path: Path):
        db = tmp_path / "concurrent.db"
        store = MemoryStore(db)
        errors: list[Exception] = []
        sessions_created: list[str] = []
        lock = threading.Lock()

        def worker():
            try:
                sid = store.create_session()
                with lock:
                    sessions_created.append(sid)
                for i in range(5):
                    store.add_message(sid, "user", f"mensaje {i} de {sid[:8]}")
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errores en threads: {errors}"
        # Cada thread creó 1 sesión
        assert len(sessions_created) == 10
        # Cada sesión tiene 5 mensajes
        for sid in sessions_created:
            msgs = store.get_session_messages(sid)
            assert len(msgs) == 5

        store.close()


# ─────────────────────────────────────────────────────────────────────────────
# VACUUM cada 100 writes
# ─────────────────────────────────────────────────────────────────────────────

class TestVacuumAutomatic:
    def test_vacuum_called_on_100th_write(self, store: MemoryStore):
        vacuum_calls: list[int] = []
        original_execute = store._get_conn().execute

        with patch.object(store, "_get_conn") as mock_get_conn:
            mock_conn = mock_get_conn.return_value
            # Simular execute normal, pero capturar VACUUM
            def fake_execute(sql, *args, **kwargs):
                if "VACUUM" in sql.upper():
                    vacuum_calls.append(1)
                return original_execute(sql, *args, **kwargs)
            mock_conn.execute = fake_execute
            mock_conn.commit = lambda: None

            # Simular _write_count justo antes de 100
            store._write_count = 99
            store._increment_write()

        assert len(vacuum_calls) >= 1, "VACUUM no se llamó en la escritura 100"

    def test_vacuum_not_called_before_100(self, store: MemoryStore):
        vacuum_calls: list[int] = []
        original_execute = store._get_conn().execute

        with patch.object(store, "_get_conn") as mock_get_conn:
            mock_conn = mock_get_conn.return_value

            def fake_execute(sql, *args, **kwargs):
                if "VACUUM" in sql.upper():
                    vacuum_calls.append(1)
                return original_execute(sql, *args, **kwargs)
            mock_conn.execute = fake_execute
            mock_conn.commit = lambda: None

            # Solo 50 escrituras
            for _ in range(50):
                store._increment_write()

        assert len(vacuum_calls) == 0, "VACUUM se llamó antes de 100 escrituras"


# ─────────────────────────────────────────────────────────────────────────────
# add_tool_event
# ─────────────────────────────────────────────────────────────────────────────

class TestToolEvent:
    def test_add_tool_event(self, store: MemoryStore):
        sid = store.create_session()
        store.add_tool_event(
            sid,
            tool_name="shell",
            tool_args={"command": "ls"},
            tool_result={"output": "file1.txt\nfile2.txt", "returncode": 0},
        )
        # No lanza — el evento se ha registrado
        sessions = store.get_recent_sessions()
        assert any(s["id"] == sid for s in sessions)


# ─────────────────────────────────────────────────────────────────────────────
# close / db_path
# ─────────────────────────────────────────────────────────────────────────────

class TestClose:
    def test_close_no_error(self, store: MemoryStore):
        store.close()  # no debe lanzar

    def test_db_path_alias(self, store: MemoryStore):
        assert store.db_path == store._db_path
