"""
test_gesture_controller.py

Tests unitarios para gesture_controller.py.
No requiere cámara, MediaPipe ni OpenCV — todo se mockea.

Run with:
    cd jarvis-agent
    source .venv/bin/activate
    PYTHONPATH=src pytest tests/test_gesture_controller.py -v
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List
from unittest.mock import MagicMock, call, patch

import pytest

from jarvis.vision.gesture_controller import (
    GestureConfig,
    GestureController,
    GestureEvent,
    detect_gesture,
    fingers_up,
    pinch_distance,
    build_gesture_controller,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

@dataclass
class _LM:
    """Landmark mock con x, y, z."""
    x: float = 0.5
    y: float = 0.5
    z: float = 0.0


def _make_landmarks(**overrides) -> List[_LM]:
    """Crea lista de 21 landmarks. Posición base: mano neutra, todo doblado."""
    lm = [_LM() for _ in range(21)]
    # Muñeca
    lm[0] = _LM(x=0.5, y=0.8, z=0.0)

    # Pulgar (CMC→TIP a lo largo del eje X, no extendido por defecto)
    lm[1] = _LM(x=0.60, y=0.75, z=0.0)  # THUMB_CMC
    lm[2] = _LM(x=0.65, y=0.72, z=0.0)  # THUMB_MCP
    lm[3] = _LM(x=0.68, y=0.70, z=0.0)  # THUMB_IP
    lm[4] = _LM(x=0.70, y=0.68, z=0.0)  # THUMB_TIP (no extendido para Right)

    # Índice (doblado: tip.y > pip.y)
    lm[5] = _LM(x=0.50, y=0.60, z=0.0)  # INDEX_MCP
    lm[6] = _LM(x=0.50, y=0.55, z=0.0)  # INDEX_PIP
    lm[7] = _LM(x=0.50, y=0.58, z=0.0)  # INDEX_DIP
    lm[8] = _LM(x=0.50, y=0.62, z=0.0)  # INDEX_TIP  (tip > pip → doblado)

    # Medio (doblado)
    lm[9]  = _LM(x=0.50, y=0.60, z=0.0)  # MIDDLE_MCP
    lm[10] = _LM(x=0.50, y=0.55, z=0.0)  # MIDDLE_PIP
    lm[11] = _LM(x=0.50, y=0.58, z=0.0)  # MIDDLE_DIP
    lm[12] = _LM(x=0.50, y=0.62, z=0.0)  # MIDDLE_TIP

    # Anular (doblado)
    lm[13] = _LM(x=0.50, y=0.60, z=0.0)  # RING_MCP
    lm[14] = _LM(x=0.50, y=0.55, z=0.0)  # RING_PIP
    lm[15] = _LM(x=0.50, y=0.58, z=0.0)  # RING_DIP
    lm[16] = _LM(x=0.50, y=0.62, z=0.0)  # RING_TIP

    # Meñique (doblado)
    lm[17] = _LM(x=0.50, y=0.60, z=0.0)  # PINKY_MCP
    lm[18] = _LM(x=0.50, y=0.55, z=0.0)  # PINKY_PIP
    lm[19] = _LM(x=0.50, y=0.58, z=0.0)  # PINKY_DIP
    lm[20] = _LM(x=0.50, y=0.62, z=0.0)  # PINKY_TIP

    for k, v in overrides.items():
        idx, attr = k.rsplit("_", 1)
        slot = int(idx.lstrip("lm"))
        setattr(lm[slot], attr, v)
    return lm


def _extend_finger(lm: List[_LM], tip_i: int, pip_i: int) -> List[_LM]:
    """Coloca tip.y claramente por encima de pip.y (dedo extendido)."""
    lm[tip_i].y = lm[pip_i].y - 0.15  # tip más arriba que pip
    return lm


def _fold_finger(lm: List[_LM], tip_i: int, pip_i: int) -> List[_LM]:
    """Coloca tip.y claramente por debajo de pip.y (dedo doblado)."""
    lm[tip_i].y = lm[pip_i].y + 0.10
    return lm


# ── Gestos fijos que usamos en múltiples tests ───────────────────────────────

def _make_fist() -> List[_LM]:
    """Todos los dedos doblados (puño)."""
    lm = _make_landmarks()
    for tip, pip in [(8, 6), (12, 10), (16, 14), (20, 18)]:
        _fold_finger(lm, tip, pip)
    # Pulgar no extendido (tip.x > ip.x para Right)
    lm[4].x = lm[3].x + 0.02
    return lm


def _make_open_palm() -> List[_LM]:
    """Todos los dedos extendidos (palma abierta)."""
    lm = _make_landmarks()
    for tip, pip in [(8, 6), (12, 10), (16, 14), (20, 18)]:
        _extend_finger(lm, tip, pip)
    # Pulgar extendido para mano derecha: tip.x < ip.x
    lm[3].x = 0.68
    lm[4].x = 0.60  # tip.x < ip.x
    return lm


def _make_v_sign() -> List[_LM]:
    """Índice y medio extendidos, anular y meñique doblados."""
    lm = _make_fist()
    _extend_finger(lm, 8, 6)
    _extend_finger(lm, 12, 10)
    return lm


def _make_thumb_up() -> List[_LM]:
    """Solo pulgar extendido, apuntando hacia arriba."""
    lm = _make_fist()
    # Pulgar extendido para Right: tip.x < ip.x
    lm[3].x = 0.68
    lm[4].x = 0.60
    # Pulgar apuntando arriba: tip.y << cmc.y
    lm[1].y = 0.75  # CMC
    lm[4].y = 0.55  # TIP significativamente más arriba
    return lm


def _make_thumb_down() -> List[_LM]:
    """Solo pulgar extendido, apuntando hacia abajo."""
    lm = _make_fist()
    lm[3].x = 0.68
    lm[4].x = 0.60
    # Pulgar apuntando abajo: tip.y >> cmc.y
    lm[1].y = 0.55  # CMC
    lm[4].y = 0.75  # TIP significativamente más abajo
    return lm


def _make_pinch(dist: float = 0.03) -> List[_LM]:
    """Pinch: pulgar tip e índice tip muy juntos."""
    lm = _make_fist()
    lm[4].x = 0.50
    lm[4].y = 0.50
    lm[8].x = 0.50 + dist
    lm[8].y = 0.50
    return lm


# ── fingers_up ───────────────────────────────────────────────────────────────

class TestFingersUp:
    def test_fist_all_down(self):
        lm = _make_fist()
        result = fingers_up(lm, "Right")
        # Al menos los 4 dedos (índice..meñique) doblados
        assert result[1] is False  # index
        assert result[2] is False  # middle
        assert result[3] is False  # ring
        assert result[4] is False  # pinky

    def test_open_palm_all_up(self):
        lm = _make_open_palm()
        result = fingers_up(lm, "Right")
        assert result[0] is True   # thumb
        assert result[1] is True   # index
        assert result[2] is True   # middle
        assert result[3] is True   # ring
        assert result[4] is True   # pinky

    def test_index_only(self):
        lm = _make_fist()
        _extend_finger(lm, 8, 6)
        result = fingers_up(lm, "Right")
        assert result[1] is True
        assert result[2] is False
        assert result[3] is False
        assert result[4] is False

    def test_v_sign_index_middle(self):
        lm = _make_v_sign()
        result = fingers_up(lm, "Right")
        assert result[1] is True
        assert result[2] is True
        assert result[3] is False
        assert result[4] is False

    def test_thumb_right_extended(self):
        lm = _make_landmarks()
        lm[3].x = 0.68  # IP
        lm[4].x = 0.60  # TIP < IP → extendido para Right
        result = fingers_up(lm, "Right")
        assert result[0] is True

    def test_thumb_right_not_extended(self):
        lm = _make_landmarks()
        lm[3].x = 0.68
        lm[4].x = 0.72  # TIP > IP → doblado para Right
        result = fingers_up(lm, "Right")
        assert result[0] is False

    def test_thumb_left_extended(self):
        lm = _make_landmarks()
        lm[3].x = 0.32
        lm[4].x = 0.40  # TIP > IP → extendido para Left
        result = fingers_up(lm, "Left")
        assert result[0] is True

    def test_returns_5_booleans(self):
        lm = _make_landmarks()
        result = fingers_up(lm, "Right")
        assert len(result) == 5
        assert all(isinstance(v, bool) for v in result)


# ── pinch_distance ────────────────────────────────────────────────────────────

class TestPinchDistance:
    def test_zero_distance(self):
        lm = _make_landmarks()
        lm[4].x = lm[8].x = 0.5
        lm[4].y = lm[8].y = 0.5
        assert pinch_distance(lm) == pytest.approx(0.0, abs=1e-9)

    def test_small_distance(self):
        lm = _make_pinch(dist=0.03)
        assert pinch_distance(lm) == pytest.approx(0.03, abs=1e-4)

    def test_large_distance(self):
        lm = _make_landmarks()
        lm[4].x, lm[4].y = 0.0, 0.0
        lm[8].x, lm[8].y = 1.0, 1.0
        import math
        assert pinch_distance(lm) == pytest.approx(math.sqrt(2), abs=1e-6)

    def test_threshold_boundary(self):
        """Distancia justo en el umbral."""
        lm = _make_pinch(dist=0.06)
        assert pinch_distance(lm) == pytest.approx(0.06, abs=1e-4)


# ── detect_gesture ────────────────────────────────────────────────────────────

class TestDetectGesture:
    def test_fist(self):
        assert detect_gesture(_make_fist(), "Right") == GestureEvent.FIST

    def test_open_palm(self):
        assert detect_gesture(_make_open_palm(), "Right") == GestureEvent.OPEN_PALM

    def test_v_sign(self):
        assert detect_gesture(_make_v_sign(), "Right") == GestureEvent.V_SIGN

    def test_thumb_up(self):
        assert detect_gesture(_make_thumb_up(), "Right") == GestureEvent.THUMB_UP

    def test_thumb_down(self):
        assert detect_gesture(_make_thumb_down(), "Right") == GestureEvent.THUMB_DOWN

    def test_pinch_below_threshold(self):
        lm = _make_pinch(dist=0.03)
        assert detect_gesture(lm, "Right", pinch_threshold=0.06) == GestureEvent.PINCH

    def test_pinch_above_threshold_not_pinch(self):
        """Distancia mayor que threshold → no es pinch."""
        lm = _make_pinch(dist=0.15)
        result = detect_gesture(lm, "Right", pinch_threshold=0.06)
        # No puede ser pinch pero puede ser otro gesto
        assert result != GestureEvent.PINCH

    def test_pinch_takes_priority(self):
        """Pinch se detecta incluso con dedos en otras posiciones."""
        lm = _make_open_palm()
        # Acercar pulgar e índice
        lm[4].x, lm[4].y = 0.5, 0.5
        lm[8].x, lm[8].y = 0.52, 0.5
        assert detect_gesture(lm, "Right", pinch_threshold=0.06) == GestureEvent.PINCH

    def test_no_clear_gesture_returns_none(self):
        """Posición ambigua → None."""
        lm = _make_fist()
        # Extender solo el anular (gesto inusual → None)
        _extend_finger(lm, 16, 14)
        result = detect_gesture(lm, "Right")
        assert result is None

    def test_thumb_horizontal_returns_none(self):
        """Pulgar horizontal (sin span vertical suficiente) → None."""
        lm = _make_fist()
        lm[1].y = 0.60  # CMC
        lm[4].y = 0.61  # TIP casi mismo nivel → span < 0.06
        # Pulgar extendido horizontalmente
        lm[3].x = 0.68
        lm[4].x = 0.60
        result = detect_gesture(lm, "Right")
        # Con span pequeño, no clasifica como THUMB_UP ni THUMB_DOWN
        assert result != GestureEvent.THUMB_UP
        assert result != GestureEvent.THUMB_DOWN


# ── GestureConfig ─────────────────────────────────────────────────────────────

class TestGestureConfig:
    def test_defaults(self):
        cfg = GestureConfig()
        assert cfg.enabled is False
        assert cfg.cooldown_sec == pytest.approx(1.5)
        assert cfg.debug is False
        assert cfg.camera_index == 0
        assert cfg.stable_frames == 5

    def test_custom_values(self):
        cfg = GestureConfig(enabled=True, cooldown_sec=2.0, debug=True, camera_index=1)
        assert cfg.enabled is True
        assert cfg.cooldown_sec == pytest.approx(2.0)
        assert cfg.debug is True
        assert cfg.camera_index == 1


# ── GestureController ─────────────────────────────────────────────────────────

def _make_controller(**kwargs) -> GestureController:
    """Crea un GestureController con callbacks mockeados."""
    cfg = GestureConfig(enabled=True, cooldown_sec=0.1, stable_frames=1)
    defaults = {k: MagicMock() for k in
                ["on_interrupt", "on_pause", "on_resume",
                 "on_confirm", "on_voice", "on_yes", "on_no"]}
    defaults.update(kwargs)
    return GestureController(cfg=cfg, **defaults)


class TestGestureControllerDispatch:
    """Tests del método _dispatch directamente (sin cámara)."""

    def test_fist_calls_interrupt(self):
        ctrl = _make_controller()
        ctrl._dispatch(GestureEvent.FIST)
        ctrl._on_interrupt.assert_called_once()

    def test_open_palm_first_calls_pause(self):
        ctrl = _make_controller()
        assert ctrl.is_paused is False
        ctrl._dispatch(GestureEvent.OPEN_PALM)
        ctrl._on_pause.assert_called_once()
        ctrl._on_resume.assert_not_called()
        assert ctrl.is_paused is True

    def test_open_palm_second_calls_resume(self):
        ctrl = _make_controller()
        ctrl._dispatch(GestureEvent.OPEN_PALM)  # pause
        ctrl._dispatch(GestureEvent.OPEN_PALM)  # resume
        ctrl._on_pause.assert_called_once()
        ctrl._on_resume.assert_called_once()
        assert ctrl.is_paused is False

    def test_open_palm_toggle_sequence(self):
        ctrl = _make_controller()
        ctrl._dispatch(GestureEvent.OPEN_PALM)
        assert ctrl.is_paused is True
        ctrl._dispatch(GestureEvent.OPEN_PALM)
        assert ctrl.is_paused is False
        ctrl._dispatch(GestureEvent.OPEN_PALM)
        assert ctrl.is_paused is True

    def test_pinch_calls_confirm(self):
        ctrl = _make_controller()
        ctrl._dispatch(GestureEvent.PINCH)
        ctrl._on_confirm.assert_called_once()

    def test_v_sign_calls_voice(self):
        ctrl = _make_controller()
        ctrl._dispatch(GestureEvent.V_SIGN)
        ctrl._on_voice.assert_called_once()

    def test_thumb_up_calls_yes(self):
        ctrl = _make_controller()
        ctrl._dispatch(GestureEvent.THUMB_UP)
        ctrl._on_yes.assert_called_once()

    def test_thumb_down_calls_no(self):
        ctrl = _make_controller()
        ctrl._dispatch(GestureEvent.THUMB_DOWN)
        ctrl._on_no.assert_called_once()

    def test_callback_exception_does_not_propagate(self):
        """Excepción en un callback no debe tumbar el controlador."""
        ctrl = _make_controller()
        ctrl._on_interrupt.side_effect = RuntimeError("boom")
        # No debe lanzar excepción
        ctrl._dispatch(GestureEvent.FIST)

    def test_callbacks_not_called_without_dispatch(self):
        ctrl = _make_controller()
        ctrl._on_interrupt.assert_not_called()
        ctrl._on_voice.assert_not_called()


# ── Cooldown ──────────────────────────────────────────────────────────────────

class TestCooldown:
    def test_cooldown_prevents_second_trigger(self):
        """Dos gestos rápidos → solo el primero dispara."""
        cfg = GestureConfig(enabled=True, cooldown_sec=2.0, stable_frames=1)
        on_interrupt = MagicMock()
        ctrl = GestureController(cfg=cfg, on_interrupt=on_interrupt)

        ctrl._last_trigger_time = 0.0

        # Primer gesto → debe disparar
        ctrl._update_stable(GestureEvent.FIST)
        on_interrupt.assert_called_once()

        # Inmediatamente después → cooldown activo, no dispara
        ctrl._update_stable(GestureEvent.FIST)
        assert on_interrupt.call_count == 1

    def test_cooldown_allows_after_wait(self):
        """Tras esperar el cooldown, el gesto vuelve a disparar."""
        cfg = GestureConfig(enabled=True, cooldown_sec=0.05, stable_frames=1)
        on_fist = MagicMock()
        ctrl = GestureController(cfg=cfg, on_interrupt=on_fist)

        ctrl._update_stable(GestureEvent.FIST)
        assert on_fist.call_count == 1

        time.sleep(0.1)  # esperar más que el cooldown
        ctrl._update_stable(GestureEvent.FIST)
        assert on_fist.call_count == 2

    def test_none_gesture_resets_stable_count(self):
        """None limpia el contador de estabilidad."""
        cfg = GestureConfig(enabled=True, cooldown_sec=5.0, stable_frames=3)
        on_fist = MagicMock()
        ctrl = GestureController(cfg=cfg, on_interrupt=on_fist)

        ctrl._update_stable(GestureEvent.FIST)   # frame 1
        ctrl._update_stable(GestureEvent.FIST)   # frame 2
        ctrl._update_stable(None)                 # reset
        ctrl._update_stable(GestureEvent.FIST)   # frame 1 de nuevo
        ctrl._update_stable(GestureEvent.FIST)   # frame 2
        # stable_frames=3 → aún no debería haber disparado
        on_fist.assert_not_called()

    def test_stable_frames_required(self):
        """Solo dispara después de N frames consecutivos."""
        cfg = GestureConfig(enabled=True, cooldown_sec=0.0, stable_frames=4)
        on_confirm = MagicMock()
        ctrl = GestureController(cfg=cfg, on_confirm=on_confirm)

        for _ in range(3):
            ctrl._update_stable(GestureEvent.PINCH)

        on_confirm.assert_not_called()

        ctrl._update_stable(GestureEvent.PINCH)  # frame 4
        on_confirm.assert_called_once()

    def test_different_gestures_reset_counter(self):
        """Cambiar gesto entre frames reinicia el contador."""
        cfg = GestureConfig(enabled=True, cooldown_sec=0.0, stable_frames=3)
        on_fist = MagicMock()
        ctrl = GestureController(cfg=cfg, on_interrupt=on_fist)

        ctrl._update_stable(GestureEvent.FIST)
        ctrl._update_stable(GestureEvent.FIST)
        ctrl._update_stable(GestureEvent.OPEN_PALM)  # gesto diferente → reset
        ctrl._update_stable(GestureEvent.FIST)
        ctrl._update_stable(GestureEvent.FIST)
        # Solo 2 frames de FIST tras el reset → no dispara
        on_fist.assert_not_called()


# ── start / stop ─────────────────────────────────────────────────────────────

class TestStartStop:
    def test_start_disabled_does_nothing(self):
        """Si cfg.enabled=False, start() no lanza ningún thread."""
        cfg = GestureConfig(enabled=False)
        ctrl = GestureController(cfg=cfg)
        ctrl.start()
        assert ctrl._thread is None
        assert ctrl._running is False

    def test_stop_sets_running_false(self):
        ctrl = _make_controller()
        ctrl._running = True
        ctrl.stop()
        assert ctrl._running is False

    def test_start_enabled_launches_thread(self):
        """Con enabled=True, start() lanza un thread daemon."""
        cfg = GestureConfig(enabled=True, stable_frames=1, cooldown_sec=0.1)
        ctrl = GestureController(cfg=cfg)

        # Mockear _loop para que no intente abrir la cámara
        with patch.object(ctrl, "_loop"):
            ctrl.start()
            assert ctrl._running is True
            assert ctrl._thread is not None
            assert ctrl._thread.daemon is True
            ctrl.stop()

    def test_is_paused_initial_false(self):
        ctrl = _make_controller()
        assert ctrl.is_paused is False


# ── build_gesture_controller ──────────────────────────────────────────────────

class TestBuildGestureController:
    def _make_settings(self, enabled=True, **kwargs):
        s = MagicMock()
        s.use_gestures = enabled
        s.gesture_cooldown = kwargs.get("gesture_cooldown", 1.5)
        s.gesture_debug = kwargs.get("gesture_debug", False)
        s.gesture_camera_index = kwargs.get("gesture_camera_index", 0)
        return s

    def _make_daemon(self):
        d = MagicMock()
        d.enqueue_gesture_event = None
        d.interrupt = MagicMock()
        d.pause_gesture = MagicMock()
        d.resume_gesture = MagicMock()
        d.trigger_voice_input = MagicMock()
        d.submit_text = MagicMock()
        return d

    def test_returns_none_when_disabled(self):
        settings = self._make_settings(enabled=False)
        result = build_gesture_controller(settings, self._make_daemon())
        assert result is None

    def test_returns_controller_when_enabled(self):
        settings = self._make_settings(enabled=True)
        result = build_gesture_controller(settings, self._make_daemon())
        assert isinstance(result, GestureController)

    def test_config_propagated(self):
        settings = self._make_settings(enabled=True, gesture_cooldown=2.5,
                                        gesture_debug=True, gesture_camera_index=1)
        ctrl = build_gesture_controller(settings, self._make_daemon())
        assert ctrl.cfg.cooldown_sec == pytest.approx(2.5)
        assert ctrl.cfg.debug is True
        assert ctrl.cfg.camera_index == 1

    def test_interrupt_callback_calls_daemon(self):
        daemon = self._make_daemon()
        settings = self._make_settings()
        ctrl = build_gesture_controller(settings, daemon)
        ctrl._dispatch(GestureEvent.FIST)
        daemon.interrupt.assert_called_once()

    def test_pause_callback_calls_daemon(self):
        daemon = self._make_daemon()
        settings = self._make_settings()
        ctrl = build_gesture_controller(settings, daemon)
        ctrl._dispatch(GestureEvent.OPEN_PALM)
        daemon.pause_gesture.assert_called_once()

    def test_resume_callback_calls_daemon(self):
        daemon = self._make_daemon()
        settings = self._make_settings()
        ctrl = build_gesture_controller(settings, daemon)
        ctrl._dispatch(GestureEvent.OPEN_PALM)  # pause
        ctrl._dispatch(GestureEvent.OPEN_PALM)  # resume
        daemon.resume_gesture.assert_called_once()

    def test_voice_callback_calls_daemon(self):
        daemon = self._make_daemon()
        settings = self._make_settings()
        ctrl = build_gesture_controller(settings, daemon)
        ctrl._dispatch(GestureEvent.V_SIGN)
        daemon.trigger_voice_input.assert_called_once()

    def test_confirm_sends_text(self):
        daemon = self._make_daemon()
        settings = self._make_settings()
        ctrl = build_gesture_controller(settings, daemon)
        ctrl._dispatch(GestureEvent.PINCH)
        daemon.submit_text.assert_called_once_with("sí, confirmo")

    def test_yes_sends_text(self):
        daemon = self._make_daemon()
        settings = self._make_settings()
        ctrl = build_gesture_controller(settings, daemon)
        ctrl._dispatch(GestureEvent.THUMB_UP)
        daemon.submit_text.assert_called_with("sí")

    def test_no_sends_text(self):
        daemon = self._make_daemon()
        settings = self._make_settings()
        ctrl = build_gesture_controller(settings, daemon)
        ctrl._dispatch(GestureEvent.THUMB_DOWN)
        daemon.submit_text.assert_called_with("no, cancela")

    def test_daemon_without_interrupt_method(self):
        """Daemon sin método interrupt → sin crash."""
        daemon = MagicMock(spec=[])  # sin atributos
        settings = self._make_settings()
        ctrl = build_gesture_controller(settings, daemon)
        assert ctrl is not None
        # _dispatch no debe lanzar aunque el callback sea no-op
        ctrl._dispatch(GestureEvent.FIST)

    def test_uses_trigger_queue_when_available(self):
        daemon = MagicMock()
        daemon.enqueue_gesture_event = MagicMock()
        settings = self._make_settings()
        ctrl = build_gesture_controller(settings, daemon)

        ctrl._dispatch(GestureEvent.FIST)
        ctrl._dispatch(GestureEvent.OPEN_PALM)
        ctrl._dispatch(GestureEvent.OPEN_PALM)
        ctrl._dispatch(GestureEvent.PINCH)
        ctrl._dispatch(GestureEvent.V_SIGN)
        ctrl._dispatch(GestureEvent.THUMB_UP)
        ctrl._dispatch(GestureEvent.THUMB_DOWN)

        daemon.enqueue_gesture_event.assert_has_calls(
            [
                call("interrupt"),
                call("pause"),
                call("resume"),
                call("confirm"),
                call("voice"),
                call("yes"),
                call("no"),
            ],
            any_order=False,
        )

    def test_queue_mode_does_not_call_legacy_methods(self):
        daemon = MagicMock()
        daemon.enqueue_gesture_event = MagicMock()
        daemon.interrupt = MagicMock()
        daemon.pause_gesture = MagicMock()
        daemon.resume_gesture = MagicMock()
        daemon.trigger_voice_input = MagicMock()
        daemon.submit_text = MagicMock()
        settings = self._make_settings()
        ctrl = build_gesture_controller(settings, daemon)

        ctrl._dispatch(GestureEvent.FIST)
        ctrl._dispatch(GestureEvent.PINCH)

        daemon.enqueue_gesture_event.assert_has_calls([call("interrupt"), call("confirm")])
        daemon.interrupt.assert_not_called()
        daemon.submit_text.assert_not_called()
