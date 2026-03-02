"""
hand_pointer.py

Controla el cursor del ratón usando la posición y gesto de la mano detectada.

Gestos:
  OPEN_PALM  → cursor sigue la palma   (hover)
  PINCH      → botón izquierdo pulsado (arrastre de ventanas)
  V_SIGN     → clic derecho
  FIST       → suelta el botón / pausa el control
  THUMB_UP   → scroll arriba
  THUMB_DOWN → scroll abajo

Uso:
    pointer = HandPointer()
    # en el bucle de captura, con landmarks y gesture del HandLandmarker:
    state_label = pointer.update(landmarks, gesture_event)
"""
from __future__ import annotations

from typing import Any, Optional


class HandPointer:
    """
    Transforma posición de mano (landmark wrist) + gesto en eventos de ratón macOS.

    Internamente usa Quartz.CGEventCreateMouseEvent para mover el cursor y
    simular clics sin depender de AppleScript ni de permisos de Accesibilidad extra.
    """

    # ── Parámetros ajustables ─────────────────────────────────────────────────
    ALPHA       = 0.25   # suavizado EMA (0=fijo, 1=sin suavizado)
    SENSITIVITY = 1.6    # amplificación del movimiento de la mano
    SCROLL_TICKS = 8     # "clics" de rueda por gesto

    def __init__(self) -> None:
        self._smooth_x: float = 0.5
        self._smooth_y: float = 0.5
        self._btn_down: bool  = False
        self._sw, self._sh    = self._screen_size()

    # ── API pública ───────────────────────────────────────────────────────────

    def update(self, landmarks: Any, gesture_event: Any) -> str:
        """
        Actualiza el puntero con los landmarks y gesto actuales.

        landmarks    — lista de NormalizedLandmark (de HandLandmarker Tasks API)
                       o secuencia de objetos con .x .y .z
        gesture_event — GestureEvent o None

        Devuelve un label de estado para mostrar en el monitor:
        "HOVER" | "DRAG" | "RCLICK" | "SCROLL↑" | "SCROLL↓" | "LIBRE" | ""
        """
        if landmarks is None or gesture_event is None:
            if self._btn_down:
                self._mouse_up(self._smooth_pos())
            return ""

        try:
            from jarvis.vision.gesture_controller import GestureEvent
        except ImportError:
            return ""

        # ── Actualizar posición suavizada (muñeca = landmark 0) ───────────
        wrist = landmarks[0]
        self._smooth_x = self.ALPHA * wrist.x + (1 - self.ALPHA) * self._smooth_x
        self._smooth_y = self.ALPHA * wrist.y + (1 - self.ALPHA) * self._smooth_y
        pos = self._smooth_pos()

        # ── Despachar por gesto ───────────────────────────────────────────
        if gesture_event == GestureEvent.OPEN_PALM:
            if self._btn_down:
                self._mouse_up(pos)
            self._mouse_move(pos)
            return "HOVER"

        elif gesture_event == GestureEvent.PINCH:
            if not self._btn_down:
                self._mouse_down(pos)
            else:
                self._mouse_drag(pos)
            return "DRAG"

        elif gesture_event == GestureEvent.V_SIGN:
            if self._btn_down:
                self._mouse_up(pos)
            self._right_click(pos)
            return "RCLICK"

        elif gesture_event == GestureEvent.THUMB_UP:
            if self._btn_down:
                self._mouse_up(pos)
            self._scroll(self.SCROLL_TICKS)
            return "SCROLL↑"

        elif gesture_event == GestureEvent.THUMB_DOWN:
            if self._btn_down:
                self._mouse_up(pos)
            self._scroll(-self.SCROLL_TICKS)
            return "SCROLL↓"

        elif gesture_event == GestureEvent.FIST:
            if self._btn_down:
                self._mouse_up(pos)
            return "LIBRE"

        return ""

    # ── Posición de pantalla ──────────────────────────────────────────────────

    def _smooth_pos(self) -> tuple[int, int]:
        """Convierte coordenadas normalizadas [0,1] a píxeles de pantalla."""
        half_sw = self._sw / 2
        half_sh = self._sh / 2
        sx = int(self._smooth_x * self._sw * self.SENSITIVITY - (self.SENSITIVITY - 1) * half_sw)
        sy = int(self._smooth_y * self._sh * self.SENSITIVITY - (self.SENSITIVITY - 1) * half_sh)
        sx = max(0, min(self._sw - 1, sx))
        sy = max(0, min(self._sh - 1, sy))
        return sx, sy

    @staticmethod
    def _screen_size() -> tuple[int, int]:
        try:
            import Quartz
            d = Quartz.CGMainDisplayID()
            return Quartz.CGDisplayPixelsWide(d), Quartz.CGDisplayPixelsHigh(d)
        except Exception:
            return 1470, 956

    # ── Eventos de ratón (Quartz) ─────────────────────────────────────────────

    @staticmethod
    def _cg_point(pos: tuple[int, int]):
        import Quartz
        return Quartz.CGPoint(pos[0], pos[1])

    def _post(self, event_type: int, pos: tuple[int, int], btn: int = 0) -> None:
        try:
            import Quartz
            p = self._cg_point(pos)
            e = Quartz.CGEventCreateMouseEvent(None, event_type, p, btn)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
        except Exception:
            pass

    def _mouse_move(self, pos: tuple[int, int]) -> None:
        import Quartz
        self._post(Quartz.kCGEventMouseMoved, pos, Quartz.kCGMouseButtonLeft)

    def _mouse_down(self, pos: tuple[int, int]) -> None:
        import Quartz
        self._post(Quartz.kCGEventLeftMouseDown, pos, Quartz.kCGMouseButtonLeft)
        self._btn_down = True

    def _mouse_drag(self, pos: tuple[int, int]) -> None:
        import Quartz
        self._post(Quartz.kCGEventLeftMouseDragged, pos, Quartz.kCGMouseButtonLeft)

    def _mouse_up(self, pos: tuple[int, int]) -> None:
        import Quartz
        self._post(Quartz.kCGEventLeftMouseUp, pos, Quartz.kCGMouseButtonLeft)
        self._btn_down = False

    def _right_click(self, pos: tuple[int, int]) -> None:
        import Quartz
        self._post(Quartz.kCGEventRightMouseDown, pos, Quartz.kCGMouseButtonRight)
        self._post(Quartz.kCGEventRightMouseUp,   pos, Quartz.kCGMouseButtonRight)

    def _scroll(self, ticks: int) -> None:
        try:
            import Quartz
            e = Quartz.CGEventCreateScrollWheelEvent(
                None,
                Quartz.kCGScrollEventUnitLine,
                1,
                ticks,
            )
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
        except Exception:
            pass
