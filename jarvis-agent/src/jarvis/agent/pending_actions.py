from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class PendingAction:
    confirm_token: str
    tool_name: str
    args: Dict[str, Any]
    created_at: float
    expires_at: float
    summary: str
    reason: str
    details: Dict[str, Any]
    risk_level: str


class PendingActionStore:
    def __init__(self, ttl_seconds: int = 120) -> None:
        self.ttl_seconds = max(1, int(ttl_seconds))
        self._pending: Dict[str, PendingAction] = {}

    def cleanup_expired(self) -> None:
        now = time.time()
        expired = [t for t, p in self._pending.items() if p.expires_at <= now]
        for token in expired:
            self._pending.pop(token, None)

    def put(
        self,
        *,
        tool_name: str,
        args: Dict[str, Any],
        summary: str,
        reason: str,
        details: Dict[str, Any],
        risk_level: str,
    ) -> PendingAction:
        self.cleanup_expired()
        now = time.time()
        token = uuid.uuid4().hex[:12]
        pending = PendingAction(
            confirm_token=token,
            tool_name=tool_name,
            args=dict(args),
            created_at=now,
            expires_at=now + self.ttl_seconds,
            summary=summary,
            reason=reason,
            details=details,
            risk_level=risk_level,
        )
        self._pending[token] = pending
        return pending

    def get_latest(self) -> Optional[PendingAction]:
        self.cleanup_expired()
        if not self._pending:
            return None
        return sorted(self._pending.values(), key=lambda p: p.created_at)[-1]

    def get(self, token: str) -> Optional[PendingAction]:
        self.cleanup_expired()
        return self._pending.get(token)

    def confirm(self, token: Optional[str] = None) -> Optional[PendingAction]:
        self.cleanup_expired()
        if token:
            return self._pending.pop(token, None)
        latest = self.get_latest()
        if not latest:
            return None
        return self._pending.pop(latest.confirm_token, None)

    def cancel(self, token: Optional[str] = None) -> Optional[PendingAction]:
        return self.confirm(token)

    def has_pending(self) -> bool:
        self.cleanup_expired()
        return bool(self._pending)
