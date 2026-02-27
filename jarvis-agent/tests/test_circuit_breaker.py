"""
tests/test_circuit_breaker.py

Tests unitarios para LLMCircuitBreaker.
"""
from __future__ import annotations

import time


from jarvis.agent.circuit_breaker import LLMCircuitBreaker


class TestCircuitBreakerClosed:
    def test_allows_calls_when_closed(self):
        cb = LLMCircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
        assert cb.allow_call() is True

    def test_initial_state_is_closed(self):
        cb = LLMCircuitBreaker()
        assert cb.state == "closed"

    def test_success_keeps_closed(self):
        cb = LLMCircuitBreaker()
        cb.record_success()
        assert cb.state == "closed"

    def test_single_failure_stays_closed(self):
        cb = LLMCircuitBreaker(failure_threshold=3)
        cb.record_failure()
        assert cb.state == "closed"
        assert cb.failures == 1

    def test_two_failures_stay_closed(self):
        cb = LLMCircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"


class TestCircuitBreakerOpens:
    def test_opens_after_threshold_failures(self):
        cb = LLMCircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"

    def test_blocks_calls_when_open(self):
        cb = LLMCircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.allow_call() is False

    def test_success_resets_failure_count(self):
        cb = LLMCircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failures == 0
        assert cb.state == "closed"

    def test_success_after_failures_prevents_open(self):
        cb = LLMCircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        # Solo 1 fallo tras el reset → sigue closed
        assert cb.state == "closed"


class TestCircuitBreakerRecovery:
    def test_transitions_to_half_open_after_timeout(self):
        cb = LLMCircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == "open"
        time.sleep(0.02)
        assert cb.allow_call() is True
        assert cb.state == "half_open"

    def test_success_in_half_open_closes_circuit(self):
        cb = LLMCircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        cb.allow_call()  # → half_open
        cb.record_success()
        assert cb.state == "closed"

    def test_failure_in_half_open_reopens_circuit(self):
        cb = LLMCircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        cb.allow_call()  # → half_open
        cb.record_failure()
        assert cb.state == "open"

    def test_still_blocked_before_timeout(self):
        cb = LLMCircuitBreaker(failure_threshold=1, recovery_timeout=100.0)
        cb.record_failure()
        assert cb.allow_call() is False

    def test_reset_force_closes(self):
        cb = LLMCircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == "open"
        cb.reset()
        assert cb.state == "closed"
        assert cb.failures == 0
        assert cb.allow_call() is True


class TestCircuitBreakerThreadSafety:
    def test_concurrent_failures_dont_exceed_state(self):
        """Múltiples threads registrando fallos no deben corromper el estado."""
        import threading
        cb = LLMCircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
        errors: list = []

        def _fail():
            try:
                cb.record_failure()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_fail) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert cb.state in ("closed", "open")
