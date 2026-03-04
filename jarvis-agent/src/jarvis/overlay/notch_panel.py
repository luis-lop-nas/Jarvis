"""
notch_panel.py

Notch digital animado: pastilla negra que aparece justo donde acaba
el notch físico del MacBook, continuándolo visualmente hacia abajo.

Animaciones por estado (misma paleta que particles/hud):
  idle      — breathing glow cyan/purple
  listening — sine wave verde, amplitud reactiva al nivel de audio
  thinking  — 4 puntos orbitando en amarillo
  acting    — sine wave rosa/rápida, amplitud reactiva
  error     — glow naranja estático

API pública (thread-safe desde el hilo principal vía OverlayBridge):
  panel.set_state("listening")
  panel.set_audio_level(0.7)
  panel.hide() / panel.show()
"""
from __future__ import annotations

import math
from typing import Optional

import AppKit
import objc


# ── Dimensiones ───────────────────────────────────────────────────────────────

_NOTCH_W        = 175.0   # anchura
_DIGITAL_H      =  36.0   # altura visible por debajo del notch físico
_CORNER_R       =   9.0   # radio de las esquinas inferiores
_CORNER_OVERLAP =   6.0   # píxeles que el window sube dentro del notch físico

# ── Paleta de colores por estado (idéntica a particles.py y hud.py) ───────────

_PALETTES: dict[str, tuple[tuple, tuple]] = {
    "idle":      ((0.000, 1.000, 0.878), (0.482, 0.188, 1.000)),
    "listening": ((0.000, 1.000, 0.533), (0.000, 1.000, 0.878)),
    "thinking":  ((1.000, 0.882, 0.000), (1.000, 0.549, 0.000)),
    "acting":    ((1.000, 0.125, 0.376), (0.545, 0.000, 1.000)),
    "error":     ((1.000, 0.400, 0.000), (1.000, 0.200, 0.000)),
}

# Velocidad de avance de phase por frame (a 30 fps)
_PHASE_SPEEDS: dict[str, float] = {
    "idle":      0.012,   # breathing lento
    "listening": 0.060,   # wave media
    "thinking":  0.050,   # dots orbit
    "acting":    0.100,   # wave rápida
    "error":     0.020,   # glow lento
}


# ── Path: top plano, esquinas inferiores redondeadas ─────────────────────────

def _notch_path(x: float, y: float, w: float, h: float, r: float):
    path = AppKit.NSBezierPath.bezierPath()
    path.moveToPoint_(AppKit.NSMakePoint(x, y + h))
    path.lineToPoint_(AppKit.NSMakePoint(x + w, y + h))
    path.lineToPoint_(AppKit.NSMakePoint(x + w, y + r))
    path.appendBezierPathWithArcFromPoint_toPoint_radius_(
        AppKit.NSMakePoint(x + w, y),
        AppKit.NSMakePoint(x + w - r, y),
        r,
    )
    path.lineToPoint_(AppKit.NSMakePoint(x + r, y))
    path.appendBezierPathWithArcFromPoint_toPoint_radius_(
        AppKit.NSMakePoint(x, y),
        AppKit.NSMakePoint(x, y + r),
        r,
    )
    path.closePath()
    return path


# ── NSTimer target ────────────────────────────────────────────────────────────

class _NotchTimerTarget(AppKit.NSObject):
    """Target de NSTimer para el loop de animación del notch."""

    def fire_(self, timer: AppKit.NSTimer) -> None:
        try:
            view = timer.userInfo()
            if view is not None:
                view._anim_tick()
        except Exception:
            pass


# ── NSView animado ────────────────────────────────────────────────────────────

class _NotchView(AppKit.NSView):
    """
    Vista del notch digital. Dibuja el pill negro + animación por estado.
    Todas las propiedades se leen/escriben desde el hilo principal.
    """

    def initWithFrame_(self, frame):
        self = objc.super(_NotchView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._state: str   = "idle"
        self._level: float = 0.3
        self._phase: float = 0.0
        # Timer de animación a 30 fps
        self._anim_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / 30.0, _NotchTimerTarget.new(), "fire:", self, True
        )
        return self

    # ── API interna (llamada desde NotchPanel, hilo principal) ────────────────

    @objc.python_method
    def set_state(self, state: str) -> None:
        self._state = state if state in _PALETTES else "idle"
        self._phase = 0.0

    @objc.python_method
    def set_audio_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))

    @objc.python_method
    def invalidate(self) -> None:
        if self._anim_timer is not None:
            self._anim_timer.invalidate()
            self._anim_timer = None

    # ── Loop de animación (llamado por timer, hilo principal) ─────────────────

    @objc.python_method
    def _anim_tick(self) -> None:
        self._phase += _PHASE_SPEEDS.get(self._state, 0.02)
        self.setNeedsDisplay_(True)

    # ── Dibujo ────────────────────────────────────────────────────────────────

    def isOpaque(self) -> bool:
        return False

    def drawRect_(self, rect) -> None:
        try:
            w     = self.bounds().size.width
            h     = self.bounds().size.height
            state = self._state
            phase = self._phase
            level = self._level

            accent, _ = _PALETTES.get(state, _PALETTES["idle"])
            r1, g1, b1 = accent

            # Limpiar
            AppKit.NSColor.clearColor().set()
            AppKit.NSRectFill(self.bounds())

            # Pill negro
            AppKit.NSColor.blackColor().set()
            pill = _notch_path(0.0, 0.0, w, h, _CORNER_R)
            pill.fill()

            # Borde con glow — breathing en idle, estático en el resto
            if state == "idle":
                border_a = 0.25 + 0.20 * math.sin(phase * math.pi * 2)
            elif state == "error":
                border_a = 0.45 + 0.25 * math.sin(phase * math.pi * 2)
            else:
                border_a = 0.70

            AppKit.NSColor.colorWithRed_green_blue_alpha_(r1, g1, b1, border_a).set()
            pill.setLineWidth_(1.5)
            pill.stroke()

            # Animación interior según estado
            if state in ("listening", "acting"):
                self._draw_wave(w, h, r1, g1, b1, phase, level)
            elif state == "thinking":
                self._draw_thinking_dots(w, h, r1, g1, b1, phase)

        except Exception:
            pass

    @objc.python_method
    def _draw_wave(
        self,
        w: float, h: float,
        r: float, g: float, b: float,
        phase: float, level: float,
    ) -> None:
        """Forma de onda sinusoidal multi-harmónica dentro del pill."""
        cx     = w / 2.0
        cy     = h / 2.0
        wave_w = w - 24.0
        amp    = max(3.5, level * h * 0.38)

        path  = AppKit.NSBezierPath.bezierPath()
        steps = 60
        for i in range(steps + 1):
            t = i / steps
            x = cx - wave_w / 2.0 + t * wave_w
            y = (cy
                 + amp * 0.55 * math.sin(phase         + t * math.pi * 4)
                 + amp * 0.30 * math.sin(phase * 1.73  + t * math.pi * 7)
                 + amp * 0.15 * math.sin(phase * 2.37  + t * math.pi * 11))
            if i == 0:
                path.moveToPoint_(AppKit.NSMakePoint(x, y))
            else:
                path.lineToPoint_(AppKit.NSMakePoint(x, y))

        path.setLineWidth_(1.8)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, 0.85).set()
        path.stroke()

    @objc.python_method
    def _draw_thinking_dots(
        self,
        w: float, h: float,
        r: float, g: float, b: float,
        phase: float,
    ) -> None:
        """4 puntos orbitando elípticamente dentro del pill."""
        cx    = w / 2.0
        cy    = h / 2.0
        rx    = w / 2.0 - 14.0   # radio X de la órbita
        ry    = h / 2.0 - 5.0    # radio Y de la órbita
        dot_r = 2.5
        n     = 4

        for i in range(n):
            angle = phase * 2.0 + i * (2.0 * math.pi / n)
            dot_x = cx + math.cos(angle) * rx
            dot_y = cy + math.sin(angle) * ry
            alpha = 0.40 + 0.60 * (math.sin(phase * 3.0 + i * 1.5) * 0.5 + 0.5)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, alpha).set()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                AppKit.NSMakeRect(dot_x - dot_r, dot_y - dot_r, dot_r * 2, dot_r * 2)
            ).fill()


# ── Clase pública ─────────────────────────────────────────────────────────────

class NotchPanel:
    """
    Ventana flotante con forma de notch animada.

    API (llamar desde hilo principal, vía OverlayBridge):
        panel.set_state("listening")
        panel.set_audio_level(0.7)
        panel.hide() / panel.show()
    """

    def __init__(self) -> None:
        screen = AppKit.NSScreen.mainScreen()
        sf     = screen.frame()
        sw, sh = sf.size.width, sf.size.height

        try:
            notch_h = float(screen.safeAreaInsets().top)
        except Exception:
            notch_h = 32.0

        if notch_h < 8.0:
            # Pantalla sin notch físico → no mostrar nada
            self._window: Optional[AppKit.NSWindow] = None
            self._view:   Optional[_NotchView]      = None
            return

        win_w = _NOTCH_W
        win_h = _DIGITAL_H + _CORNER_OVERLAP
        win_x = (sw - win_w) / 2.0
        win_y = (sh - notch_h) - _DIGITAL_H

        win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(win_x, win_y, win_w, win_h),
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        win.setLevel_(1001)
        win.setOpaque_(False)
        win.setBackgroundColor_(AppKit.NSColor.clearColor())
        win.setIgnoresMouseEvents_(True)
        win.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )
        win.setSharingType_(AppKit.NSWindowSharingNone)

        view = _NotchView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, win_w, win_h)
        )
        win.setContentView_(view)
        win.orderFrontRegardless()

        self._window = win
        self._view   = view

    # ── API pública (hilo principal) ──────────────────────────────────────────

    def set_state(self, state: str) -> None:
        """Cambiar el estado visual. state: idle|listening|thinking|acting|error"""
        if self._view is not None:
            self._view.set_state(state)

    def set_audio_level(self, level: float) -> None:
        """Actualizar amplitud de la wave (0.0–1.0). Solo visible en listening/acting."""
        if self._view is not None:
            self._view.set_audio_level(level)

    def hide(self) -> None:
        if self._window is not None:
            self._window.orderOut_(None)

    def show(self) -> None:
        if self._window is not None:
            self._window.orderFrontRegardless()
