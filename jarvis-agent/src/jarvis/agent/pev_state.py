"""
pev_state.py

Thread-safe store for PEV RunState objects with TTL expiry.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from jarvis.agent.pev_models import RunState


class RunStateStore:
    def __init__(self, ttl_seconds: int = 600) -> None:
        self._ttl = ttl_seconds
        self._store: Dict[str, RunState] = {}
        self._lock = threading.Lock()

    def put(self, key: str, state: RunState) -> None:
        state.updated_at = time.time()
        with self._lock:
            self._store[key] = state
            self._cleanup_expired_unsafe()

    def get(self, key: str) -> Optional[RunState]:
        with self._lock:
            self._cleanup_expired_unsafe()
            return self._store.get(key)

    def clear(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def cleanup_expired(self) -> None:
        with self._lock:
            self._cleanup_expired_unsafe()

    def _cleanup_expired_unsafe(self) -> None:
        """Llamado solo con el lock ya adquirido."""
        now = time.time()
        expired = [k for k, s in self._store.items() if now - s.updated_at > self._ttl]
        for k in expired:
            del self._store[k]
