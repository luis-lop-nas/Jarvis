"""
hud.py

Panel HUD flotante estilo "cloud entity / glitch art".

Aparece centrado en la parte inferior de la pantalla cuando Jarvis responde.

Características:
  - Fondo oscuro #080810 con bordes en color acento (cambia con el estado)
  - Esquinas biseladas (chamfer): top-right y bottom-left cortadas 14px
  - Header [JARVIS CORE] con punto pulsante animado
  - Texto monoespaciado con efecto typewriter + cursor █ parpadeante
  - Click-through — no captura eventos de ratón
  - Visible en todos los Spaces
  - Fade-out automático FADE_DELAY segundos tras terminar el TTS
  - Thread-safe — todas las APIs públicas se pueden llamar desde cualquier thread
"""

from __future__ import annotations

import logging
from typing import Optional

import AppKit
import objc

_log = logging.getLogger(__name__)


_CHAMFER = 14.0    # px de corte en esquinas top-right y bottom-left
_BG      = (0.030, 0.030, 0.070, 0.96)   # fondo negro azulado


# ── Helper: path con esquinas biseladas ─────────────────────────────────────
# Corta top-right y bottom-left (estilo clip-path del demo HTML)

def _chamfer_path(x: float, y: float, w: float, h: float, cut: float = _CHAMFER):
    """
    NSBezierPath con esquinas top-right y bottom-left biseladas.
    Coordenadas macOS: origen bottom-left.
    """
    path = AppKit.NSBezierPath.bezierPath()
    # top-left (sharp) → top-right chamfer start
    path.moveToPoint_(AppKit.NSMakePoint(x, y + h))
    path.lineToPoint_(AppKit.NSMakePoint(x + w - cut, y + h))   # top
    path.lineToPoint_(AppKit.NSMakePoint(x + w, y + h - cut))   # top-right cut
    # bottom-right (sharp)
    path.lineToPoint_(AppKit.NSMakePoint(x + w, y))
    # bottom-left chamfer
    path.lineToPoint_(AppKit.NSMakePoint(x + cut, y))            # bottom
    path.lineToPoint_(AppKit.NSMakePoint(x, y + cut))            # bottom-left cut
    path.closePath()
    return path


# ── Vista de fondo biselado ───────────────────────────────────────────────────

class _HUDBg(AppKit.NSView):
    """Fondo oscuro con esquinas biseladas y borde en color acento."""

    def initWithFrame_(self, frame):
        self = objc.super(_HUDBg, self).initWithFrame_(frame)
        if self is None:
            return None
        self._accent = (0.35, 1.0, 0.42)   # verde terminal por defecto
        return self

    @objc.python_method
    def set_accent(self, r: float, g: float, b: float) -> None:
        self._accent = (r, g, b)
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect) -> None:
        try:
            b  = self.bounds()
            bx = b.origin.x
            by = b.origin.y
            bw = b.size.width
            bh = b.size.height

            path = _chamfer_path(bx, by, bw, bh)

            # Fondo oscuro
            AppKit.NSColor.colorWithRed_green_blue_alpha_(*_BG).set()
            path.fill()

            # Borde en color acento
            path.setLineWidth_(1.5)
            ar, ag, ab = self._accent
            AppKit.NSColor.colorWithRed_green_blue_alpha_(ar, ag, ab, 0.65).set()
            path.stroke()
        except Exception:
            _log.error("[_HUDBg] drawRect_ error (no fatal)", exc_info=True)

    def isOpaque(self) -> bool:
        return False


# ── Target de NSTimer para fade-out ─────────────────────────────────────────

class _HUDTimerTarget(AppKit.NSObject):
    def fire_(self, timer: AppKit.NSTimer) -> None:
        try:
            hud = timer.userInfo()
            if hud is not None:
                hud._close()
        except Exception:
            pass


# ── Target de NSTimer para el dot pulsante ───────────────────────────────────

class _DotTimerTarget(AppKit.NSObject):
    def fire_(self, timer: AppKit.NSTimer) -> None:
        try:
            field = timer.userInfo()
            if field is not None:
                field._pulse_tick()
        except Exception:
            pass


# ── Target de NSTimer para el cursor parpadeante ─────────────────────────────

class _CursorTimerTarget(AppKit.NSObject):
    def fire_(self, timer: AppKit.NSTimer) -> None:
        try:
            hud = timer.userInfo()
            if hud is not None:
                hud._cursor_tick()
        except Exception:
            pass


# ── Target de NSTimer para el typewriter ─────────────────────────────────────

class _TypeTimerTarget(AppKit.NSObject):
    def fire_(self, timer: AppKit.NSTimer) -> None:
        try:
            hud = timer.userInfo()
            if hud is not None:
                hud._type_tick()
        except Exception:
            pass


# ── Dot pulsante ─────────────────────────────────────────────────────────────

class _PulsingDot(AppKit.NSView):
    """Círculo pequeño que pulsa en opacidad para indicar actividad."""

    def initWithFrame_(self, frame):
        self = objc.super(_PulsingDot, self).initWithFrame_(frame)
        if self is None:
            return None
        self._alpha   = 1.0
        self._dir     = -1
        self._accent  = (0.0, 1.0, 0.878)
        # timer de pulso a 20fps
        self._timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / 20.0, _DotTimerTarget.new(), 'fire:', self, True,
        )
        return self

    @objc.python_method
    def _pulse_tick(self) -> None:
        self._alpha += self._dir * 0.07
        if self._alpha <= 0.20:
            self._alpha = 0.20
            self._dir   = 1
        elif self._alpha >= 1.0:
            self._alpha = 1.0
            self._dir   = -1
        self.setNeedsDisplay_(True)

    @objc.python_method
    def set_accent(self, r: float, g: float, b: float) -> None:
        self._accent = (r, g, b)
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect) -> None:
        try:
            b  = self.bounds()
            cx = b.size.width  / 2
            cy = b.size.height / 2
            rr = min(cx, cy)
            ar, ag, ab = self._accent
            AppKit.NSColor.colorWithRed_green_blue_alpha_(ar, ag, ab, self._alpha).set()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                AppKit.NSMakeRect(cx - rr, cy - rr, rr * 2, rr * 2)
            ).fill()
        except Exception:
            _log.error("[_PulsingDot] drawRect_ error (no fatal)", exc_info=True)

    def isOpaque(self) -> bool:
        return False

    def invalidate(self) -> None:
        if self._timer:
            self._timer.invalidate()
            self._timer = None


# ── HUD principal ─────────────────────────────────────────────────────────────

class JarvisHUD:
    """
    Panel flotante que muestra la respuesta de Jarvis con estética cloud entity.

    Uso (desde cualquier thread):
        hud.show_text("Enseguida, señor.")
        hud.schedule_hide()   # desaparece tras FADE_DELAY segundos
        hud.hide()            # inmediato
        hud.set_accent_color(r, g, b)  # sincronizar con estado del orb
    """

    WIDTH      = 600
    PADDING_X  = 18
    PADDING_Y  = 13
    Y_OFFSET   = 120.0
    FADE_DELAY = 3.5
    TYPE_SPEED = 0.018    # segundos por carácter del typewriter

    def __init__(self, bridge) -> None:
        self._bridge  = bridge
        self._window: Optional[AppKit.NSPanel] = None
        self._bg:     Optional[_HUDBg]         = None
        self._dot:    Optional[_PulsingDot]    = None
        self._label:  Optional[AppKit.NSTextField] = None

        self._accent = (0.35, 1.0, 0.42)   # verde terminal por defecto

        # estado del typewriter
        self._full_text   = ''
        self._shown_chars = 0
        self._type_timer: Optional[AppKit.NSTimer] = None

        # cursor parpadeante
        self._cursor_on    = True
        self._cursor_timer: Optional[AppKit.NSTimer] = None

        # timer fade-out
        self._timer: Optional[AppKit.NSTimer] = None

    # ── API pública (thread-safe) ─────────────────────────────────────────────

    def show_text(self, text: str) -> None:
        """Muestra texto en el HUD con efecto typewriter. Thread-safe."""
        self._bridge.run_on_main_thread(lambda: self._show(text))

    def schedule_hide(self) -> None:
        """Oculta el HUD tras FADE_DELAY segundos. Thread-safe."""
        self._bridge.run_on_main_thread(self._start_fade_timer)

    def hide(self) -> None:
        """Oculta el HUD inmediatamente. Thread-safe."""
        self._bridge.run_on_main_thread(self._close)

    def set_accent_color(self, r: float, g: float, b: float) -> None:
        """Actualiza el color de borde/acento. Thread-safe."""
        self._bridge.run_on_main_thread(lambda: self._apply_accent(r, g, b))

    # ── Hilo principal ────────────────────────────────────────────────────────

    def _apply_accent(self, r: float, g: float, b: float) -> None:
        self._accent = (r, g, b)
        if self._bg is not None:
            self._bg.set_accent(r, g, b)
        if self._dot is not None:
            self._dot.set_accent(r, g, b)

    def _show(self, text: str) -> None:
        self._cancel_fade_timer()
        self._cancel_type_timer()
        if self._window is None:
            self._build_window()
        self._start_typewriter(text)
        self._window.orderFront_(None)

    def _build_window(self) -> None:
        screen = AppKit.NSScreen.mainScreen()
        sf     = screen.frame()
        sw     = sf.size.width
        h      = self._calc_height('A')

        x     = (sw - self.WIDTH) / 2
        frame = AppKit.NSMakeRect(x, self.Y_OFFSET, self.WIDTH, h)

        self._window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self._window.setLevel_(AppKit.NSFloatingWindowLevel + 5)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._window.setHasShadow_(True)
        self._window.setIgnoresMouseEvents_(True)
        self._window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )

        # Fondo biselado
        self._bg = _HUDBg.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, self.WIDTH, h)
        )
        ar, ag, ab = self._accent
        self._bg.set_accent(ar, ag, ab)
        self._window.setContentView_(self._bg)

        # Header: dot + [JARVIS CORE]
        _DOT_SIZE = 6
        _HEADER_Y = h - 22

        self._dot = _PulsingDot.alloc().initWithFrame_(
            AppKit.NSMakeRect(self.PADDING_X, _HEADER_Y + 1, _DOT_SIZE, _DOT_SIZE)
        )
        self._dot.set_accent(ar, ag, ab)
        self._bg.addSubview_(self._dot)

        header_lbl = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(self.PADDING_X + _DOT_SIZE + 6, _HEADER_Y - 1,
                              200, 14)
        )
        header_lbl.setStringValue_('[JARVIS CORE]')
        header_lbl.setBezeled_(False)
        header_lbl.setDrawsBackground_(False)
        header_lbl.setEditable_(False)
        header_lbl.setSelectable_(False)
        header_lbl.setFont_(
            AppKit.NSFont.fontWithName_size_('Monaco', 9.0) or
            AppKit.NSFont.monospacedSystemFontOfSize_weight_(9.0, AppKit.NSFontWeightBold)
        )
        header_lbl.setTextColor_(
            AppKit.NSColor.colorWithRed_green_blue_alpha_(ar, ag, ab, 0.70)
        )
        self._bg.addSubview_(header_lbl)
        self._header_lbl = header_lbl

        # Label de texto principal
        txt_font = (
            AppKit.NSFont.fontWithName_size_('Monaco', 11.0) or
            AppKit.NSFont.fontWithName_size_('Menlo', 11.0) or
            AppKit.NSFont.monospacedSystemFontOfSize_weight_(11.0, AppKit.NSFontWeightRegular)
        )
        lx = self.PADDING_X
        lw = self.WIDTH - lx - self.PADDING_X
        lh = max(20, h - self.PADDING_Y * 2 - 22)
        self._label = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(lx, self.PADDING_Y, lw, lh)
        )
        self._label.setStringValue_('')
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setFont_(txt_font)
        self._label.setTextColor_(
            AppKit.NSColor.colorWithRed_green_blue_alpha_(0.78, 1.0, 0.80, 0.92)
        )
        self._label.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        self._label.setMaximumNumberOfLines_(6)
        self._bg.addSubview_(self._label)

        # Timer cursor parpadeante (0.65s)
        self._cursor_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.65, _CursorTimerTarget.new(), 'fire:', self, True,
        )

    # ── Typewriter ────────────────────────────────────────────────────────────

    def _start_typewriter(self, text: str) -> None:
        self._full_text   = text
        self._shown_chars = 0
        self._cancel_type_timer()
        self._type_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            self.TYPE_SPEED, _TypeTimerTarget.new(), 'fire:', self, True,
        )

    def _type_tick(self) -> None:
        """Mostrar un carácter más del texto."""
        if self._shown_chars >= len(self._full_text):
            self._cancel_type_timer()
            self._update_display()
            return
        self._shown_chars += 1
        self._update_display()

    def _cursor_tick(self) -> None:
        """Alternar visibilidad del cursor █."""
        self._cursor_on = not self._cursor_on
        self._update_display()

    def _update_display(self) -> None:
        """Actualizar el label con el texto mostrado + cursor."""
        if self._label is None:
            return
        visible = self._full_text[:self._shown_chars]
        # Cursor: solo mostrar si typewriter terminó
        if self._shown_chars >= len(self._full_text):
            cursor = ' █' if self._cursor_on else '  '
        else:
            cursor = ''
        self._label.setStringValue_(visible + cursor)
        self._resize_to_text(visible or 'A')

    def _resize_to_text(self, text: str) -> None:
        if self._window is None or self._bg is None:
            return
        h  = self._calc_height(text)
        screen = AppKit.NSScreen.mainScreen()
        sf     = screen.frame()
        sw     = sf.size.width
        x      = (sw - self.WIDTH) / 2

        self._window.setFrame_display_(
            AppKit.NSMakeRect(x, self.Y_OFFSET, self.WIDTH, h), False
        )
        self._bg.setFrame_(AppKit.NSMakeRect(0, 0, self.WIDTH, h))
        self._bg.setNeedsDisplay_(True)

        # Reposicionar header y label
        _HEADER_Y = h - 22
        if self._dot is not None:
            self._dot.setFrame_(
                AppKit.NSMakeRect(self.PADDING_X, _HEADER_Y + 1, 6, 6)
            )
        if hasattr(self, '_header_lbl') and self._header_lbl is not None:
            self._header_lbl.setFrame_(
                AppKit.NSMakeRect(self.PADDING_X + 12, _HEADER_Y - 1, 200, 14)
            )
        lh = max(20, h - self.PADDING_Y * 2 - 22)
        self._label.setFrame_(
            AppKit.NSMakeRect(self.PADDING_X, self.PADDING_Y,
                              self.WIDTH - self.PADDING_X * 2, lh)
        )

    def _calc_height(self, text: str) -> float:
        label_width    = self.WIDTH - self.PADDING_X * 2
        chars_per_line = label_width / 7.6         # ~7.6px por carácter a 11pt Mono
        lines          = max(1.0, len(text) / max(1.0, chars_per_line))
        return max(58.0, round(lines + 0.9) * 20 + self.PADDING_Y * 2 + 22)

    # ── Timer fade-out ────────────────────────────────────────────────────────

    def _start_fade_timer(self) -> None:
        self._cancel_fade_timer()
        self._timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            self.FADE_DELAY, _HUDTimerTarget.new(), 'fire:', self, False,
        )

    def _cancel_fade_timer(self) -> None:
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def _cancel_type_timer(self) -> None:
        if self._type_timer is not None:
            self._type_timer.invalidate()
            self._type_timer = None

    def _close(self) -> None:
        self._cancel_fade_timer()
        self._cancel_type_timer()
        if self._window is not None:
            self._window.orderOut_(None)
