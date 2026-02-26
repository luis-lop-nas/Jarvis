"""
circuit_breaker.py

Circuit breaker para llamadas al LLM en el daemon.

Estados:
  CLOSED  → funcionando normalmente (acepta llamadas)
  OPEN    → en espera tras N fallos consecutivos (rechaza llamadas)
  HALF    → probando una llamada tras el cooldown (si falla → OPEN de nuevo)

Uso:
    cb = LLMCircuitBreaker(failure_threshold=3, recovery_timeout=30.0)

    if not cb.allow_call():
        return "Servicio LLM temporalmente no disponible, reintentando en breve."

    try:
        result = llm.call(...)
        cb.record_success()
    except Exception as e:
        cb.record_failure()
        raise
"""
from __future__ import annotations

import threading
import time
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class _State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF = "half_open"


class LLMCircuitBreaker:
    """
    Circuit breaker thread-safe para el LLM del daemon.

    Parámetros
    ----------
    failure_threshold : int
        Número de fallos consecutivos antes de abrir el circuito (default 3).
    recovery_timeout : float
        Segundos en estado OPEN antes de intentar medio-apertura (default 30).
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ) -> None:
        self._threshold = failure_threshold
        self._timeout = recovery_timeout
        self._state = _State.CLOSED
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._lock = threading.Lock()

    # ── API pública ───────────────────────────────────────────────────────────

    def allow_call(self) -> bool:
        """
        Retorna True si se permite realizar la llamada al LLM.
        Transiciona de OPEN a HALF_OPEN si el cooldown expiró.
        """
        with self._lock:
            if self._state == _State.CLOSED:
                return True

            if self._state == _State.OPEN:
                elapsed = time.time() - (self._opened_at or 0.0)
                if elapsed >= self._timeout:
                    self._state = _State.HALF
                    logger.info(
                        "[CircuitBreaker] OPEN → HALF_OPEN tras %.0fs de espera", elapsed
                    )
                    return True
                remaining = self._timeout - elapsed
                logger.debug(
                    "[CircuitBreaker] OPEN — bloqueando llamada LLM (%.0fs restantes)", remaining
                )
                return False

            # HALF_OPEN: permitir exactamente una llamada de prueba
            return True

    def record_success(self) -> None:
        """Registra una llamada exitosa. Cierra el circuito si estaba abierto."""
        with self._lock:
            if self._state != _State.CLOSED:
                logger.info(
                    "[CircuitBreaker] Llamada exitosa — %s → CLOSED", self._state.value
                )
            self._failures = 0
            self._opened_at = None
            self._state = _State.CLOSED

    def record_failure(self) -> None:
        """
        Registra un fallo. Si se alcanza el umbral, abre el circuito.
        En HALF_OPEN, cualquier fallo vuelve a OPEN.
        """
        with self._lock:
            self._failures += 1
            if self._state == _State.HALF or self._failures >= self._threshold:
                self._state = _State.OPEN
                self._opened_at = time.time()
                logger.warning(
                    "[CircuitBreaker] %d fallos consecutivos → OPEN (cooldown %.0fs)",
                    self._failures,
                    self._timeout,
                )
            else:
                logger.debug(
                    "[CircuitBreaker] Fallo %d/%d", self._failures, self._threshold
                )

    @property
    def state(self) -> str:
        """Estado actual como string: 'closed' | 'open' | 'half_open'."""
        with self._lock:
            return self._state.value

    @property
    def failures(self) -> int:
        with self._lock:
            return self._failures

    def reset(self) -> None:
        """Fuerza el circuito a CLOSED. Solo para tests/admin."""
        with self._lock:
            self._state = _State.CLOSED
            self._failures = 0
            self._opened_at = None
