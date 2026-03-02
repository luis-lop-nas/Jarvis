"""
notch_panel.py

Notch digital: pastilla negra que aparece justo donde acaba
el notch físico del MacBook, continuándolo visualmente hacia abajo.

Top plano (se funde con el notch físico), esquinas inferiores redondeadas.
Negro puro, sin bordes ni efectos.
"""
from __future__ import annotations

import AppKit
import objc


# ── Dimensiones ───────────────────────────────────────────────────────────────

_NOTCH_W        = 175.0   # anchura
_DIGITAL_H      =  36.0   # altura visible por debajo del notch físico
_CORNER_R       =   9.0   # radio de las esquinas inferiores
_CORNER_OVERLAP =   6.0   # píxeles que el window sube dentro del notch físico
                           # para tapar los huecos en las esquinas superiores


# ── Path: top plano, esquinas inferiores redondeadas ─────────────────────────

def _notch_path(x: float, y: float, w: float, h: float, r: float):
    path = AppKit.NSBezierPath.bezierPath()
    path.moveToPoint_(AppKit.NSMakePoint(x, y + h))           # top-left (recto)
    path.lineToPoint_(AppKit.NSMakePoint(x + w, y + h))       # top-right (recto)
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


# ── NSView ────────────────────────────────────────────────────────────────────

class _NotchView(AppKit.NSView):

    def initWithFrame_(self, frame):
        self = objc.super(_NotchView, self).initWithFrame_(frame)
        return self

    def isOpaque(self):
        return False

    def drawRect_(self, rect):
        try:
            AppKit.NSColor.clearColor().set()
            AppKit.NSRectFill(self.bounds())
            w = self.bounds().size.width
            h = self.bounds().size.height
            AppKit.NSColor.blackColor().set()
            _notch_path(0.0, 0.0, w, h, _CORNER_R).fill()
        except Exception:
            pass


# ── Clase pública ─────────────────────────────────────────────────────────────

class NotchPanel:
    """
    Ventana flotante con forma de notch que aparece justo donde acaba
    el notch físico del MacBook.

    API:
        panel = NotchPanel()
        panel.set_state("listening")   # reservado para futuro uso
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
            self._window = None
            self._view   = None
            return

        win_w = _NOTCH_W
        # Extender el window hacia arriba (_CORNER_OVERLAP pts) dentro del notch físico
        # para que el edge recto del digital tape los huecos en media luna de las esquinas.
        # El notch físico es negro → la superposición es invisible.
        win_h = _DIGITAL_H + _CORNER_OVERLAP
        win_x = (sw - win_w) / 2.0
        win_y = (sh - notch_h) - _DIGITAL_H   # bottom visual del notch digital sin cambios

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

    # ── API pública ───────────────────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        pass   # reservado para futuro uso

    def set_audio_level(self, level: float) -> None:
        pass   # reservado para futuro uso

    def hide(self) -> None:
        if self._window:
            self._window.orderOut_(None)

    def show(self) -> None:
        if self._window:
            self._window.orderFrontRegardless()
