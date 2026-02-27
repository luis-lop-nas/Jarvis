"""
main_panel.py

Panel de control dark glass — esquina inferior derecha.
Estética "cloud entity": fondo oscuro #080810, esquinas biseladas,
bordes y hover en cyan #00ffe0, tipografía SF Mono.

Se desliza desde fuera de pantalla (derecha) con ease-out quint + fade.
Thread-safe: toggle() desde cualquier hilo.
"""

from __future__ import annotations

import logging
import math
import os
import signal
import objc
import AppKit
from typing import Optional, Callable

_log = logging.getLogger(__name__)

# Zona de tracking: MouseEnteredAndExited | ActiveAlways
_TRACK = 0x01 | 0x80

_CUT   = 10.0    # px de bisel (chamfer) en esquinas top-right y bottom-left
_BG    = (0.030, 0.030, 0.070)    # fondo oscuro
_CYAN  = (0.000, 1.000, 0.878)    # cyan acento

_MARGIN_X = 20
_MARGIN_Y = 40
_DUR_SHOW = 0.34
_DUR_HIDE = 0.22


# ── Helper: path biselado ─────────────────────────────────────────────────────

def _chamfer_path(x: float, y: float, w: float, h: float, cut: float = _CUT):
    """NSBezierPath con esquinas top-right y bottom-left biseladas."""
    path = AppKit.NSBezierPath.bezierPath()
    path.moveToPoint_(AppKit.NSMakePoint(x, y + h))
    path.lineToPoint_(AppKit.NSMakePoint(x + w - cut, y + h))
    path.lineToPoint_(AppKit.NSMakePoint(x + w, y + h - cut))
    path.lineToPoint_(AppKit.NSMakePoint(x + w, y))
    path.lineToPoint_(AppKit.NSMakePoint(x + cut, y))
    path.lineToPoint_(AppKit.NSMakePoint(x, y + cut))
    path.closePath()
    return path


# ── Iconos bezier ─────────────────────────────────────────────────────────────

def _icon_quit(cx: float, cy: float, alpha: float) -> None:
    p = AppKit.NSBezierPath.bezierPath()
    p.setLineWidth_(1.4)
    p.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    AppKit.NSColor.colorWithRed_green_blue_alpha_(1, 1, 1, alpha).set()
    s = 4.5
    p.moveToPoint_(AppKit.NSMakePoint(cx - s, cy - s))
    p.lineToPoint_(AppKit.NSMakePoint(cx + s, cy + s))
    p.moveToPoint_(AppKit.NSMakePoint(cx + s, cy - s))
    p.lineToPoint_(AppKit.NSMakePoint(cx - s, cy + s))
    p.stroke()


def _icon_voice(cx: float, cy: float, alpha: float) -> None:
    p = AppKit.NSBezierPath.bezierPath()
    p.setLineWidth_(1.6)
    p.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    AppKit.NSColor.colorWithRed_green_blue_alpha_(1, 1, 1, alpha).set()
    for dx, hh in [(-5.5, 2.5), (-2.8, 4.8), (0.0, 6.2), (2.8, 4.8), (5.5, 2.5)]:
        p.moveToPoint_(AppKit.NSMakePoint(cx + dx, cy - hh))
        p.lineToPoint_(AppKit.NSMakePoint(cx + dx, cy + hh))
    p.stroke()


def _icon_text(cx: float, cy: float, alpha: float) -> None:
    p = AppKit.NSBezierPath.bezierPath()
    p.setLineWidth_(1.3)
    p.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    AppKit.NSColor.colorWithRed_green_blue_alpha_(1, 1, 1, alpha).set()
    p.moveToPoint_(AppKit.NSMakePoint(cx,      cy - 5.5))
    p.lineToPoint_(AppKit.NSMakePoint(cx,      cy + 5.5))
    p.moveToPoint_(AppKit.NSMakePoint(cx - 3.0, cy + 5.5))
    p.lineToPoint_(AppKit.NSMakePoint(cx + 3.0, cy + 5.5))
    p.moveToPoint_(AppKit.NSMakePoint(cx - 3.0, cy - 5.5))
    p.lineToPoint_(AppKit.NSMakePoint(cx + 3.0, cy - 5.5))
    p.stroke()


# ── Fondo biselado del panel ─────────────────────────────────────────────────

class _DarkPanelBg(AppKit.NSView):
    """Fondo oscuro con esquinas biseladas + borde blanco tenue → cyan al hover."""

    def initWithFrame_(self, frame):
        self = objc.super(_DarkPanelBg, self).initWithFrame_(frame)
        if self is None:
            return None
        self._hover = False
        return self

    @objc.python_method
    def set_hover(self, val: bool) -> None:
        if self._hover != val:
            self._hover = val
            self.setNeedsDisplay_(True)

    def drawRect_(self, rect) -> None:
        try:
            b  = self.bounds()
            bx = b.origin.x
            by = b.origin.y
            bw = b.size.width
            bh = b.size.height

            path = _chamfer_path(bx, by, bw, bh)

            # Fondo
            r, g, b_ = _BG
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b_, 0.93).set()
            path.fill()

            # Borde: blanco tenue → cyan al hover
            path.setLineWidth_(1.0)
            if self._hover:
                AppKit.NSColor.colorWithRed_green_blue_alpha_(*_CYAN, 0.50).set()
            else:
                AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.12).set()
            path.stroke()
        except Exception:
            _log.error("[_DarkPanelBg] drawRect_ error (no fatal)", exc_info=True)

    def isOpaque(self) -> bool:
        return False

    def hitTest_(self, pt):
        return None   # click-through total


# ── Botón dark con esquinas biseladas ────────────────────────────────────────

class _DarkBtn(AppKit.NSView):
    """Botón píldora oscuro con icono bezier, etiqueta SF Mono y hover cyan."""

    def initWithFrame_(self, frame):
        self = objc.super(_DarkBtn, self).initWithFrame_(frame)
        if self is None:
            return None
        self._label:     str                = ''
        self._draw_icon: Optional[Callable] = None
        self._action:    Optional[Callable] = None
        self._hover:     bool               = False
        return self

    @objc.python_method
    def configure(self, label: str, draw_icon: Callable, action: Callable) -> None:
        self._label     = label
        self._draw_icon = draw_icon
        self._action    = action
        self.setNeedsDisplay_(True)

    def updateTrackingAreas(self) -> None:
        objc.super(_DarkBtn, self).updateTrackingAreas()
        for a in list(self.trackingAreas()):
            self.removeTrackingArea_(a)
        self.addTrackingArea_(
            AppKit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(), _TRACK, self, None
            )
        )

    def acceptsFirstMouse_(self, event) -> bool: return True
    def isOpaque(self)                -> bool:   return False

    def mouseEntered_(self, event) -> None:
        self._hover = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event) -> None:
        self._hover = False
        self.setNeedsDisplay_(True)

    def mouseDown_(self, event) -> None:
        pass   # captura para que mouseUp_ llegue aquí

    def mouseUp_(self, event) -> None:
        if self._action:
            self._action()

    def drawRect_(self, rect) -> None:
        try:
            b  = self.bounds()
            bx = b.origin.x
            by = b.origin.y
            bw = b.size.width
            bh = b.size.height

            path = _chamfer_path(bx, by, bw, bh, cut=5.0)

            # Fondo
            if self._hover:
                AppKit.NSColor.colorWithRed_green_blue_alpha_(*_CYAN, 0.10).set()
            else:
                AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.04).set()
            path.fill()

            # Borde
            path.setLineWidth_(0.8)
            if self._hover:
                AppKit.NSColor.colorWithRed_green_blue_alpha_(*_CYAN, 0.55).set()
            else:
                AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.12).set()
            path.stroke()

            # Icono bezier (centrado horizontalmente, parte superior)
            if self._draw_icon:
                icon_alpha = 0.90 if self._hover else 0.60
                self._draw_icon(bw / 2, bh * 0.58, icon_alpha)

            # Etiqueta monospace
            lbl_font = (
                AppKit.NSFont.fontWithName_size_('SF Mono', 7.5) or
                AppKit.NSFont.fontWithName_size_('Menlo', 7.5) or
                AppKit.NSFont.monospacedSystemFontOfSize_weight_(7.5, AppKit.NSFontWeightBold)
            )
            if self._hover:
                lbl_color = AppKit.NSColor.colorWithRed_green_blue_alpha_(*_CYAN, 0.95)
            else:
                lbl_color = AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.35)

            lbl_a = {
                AppKit.NSFontAttributeName: lbl_font,
                AppKit.NSForegroundColorAttributeName: lbl_color,
            }
            lbl_s = AppKit.NSAttributedString.alloc().initWithString_attributes_(
                self._label, lbl_a
            )
            lsz = lbl_s.size()
            lbl_s.drawAtPoint_(AppKit.NSMakePoint(
                bw / 2 - lsz.width / 2,
                bh * 0.14,
            ))
        except Exception:
            _log.error("[_DarkBtn] drawRect_ error (no fatal)", exc_info=True)


# ── Botón × cierre ────────────────────────────────────────────────────────────

class _DarkCloseBtn(AppKit.NSView):
    """Círculo oscuro con × que aparece al hover sobre el panel."""

    SIZE = 19.4

    def initWithFrame_(self, frame):
        self = objc.super(_DarkCloseBtn, self).initWithFrame_(frame)
        if self is None:
            return None
        self._action = None
        self._hover  = False
        self.setAlphaValue_(0.0)
        return self

    @objc.python_method
    def configure(self, action: Callable) -> None:
        self._action = action

    def updateTrackingAreas(self) -> None:
        objc.super(_DarkCloseBtn, self).updateTrackingAreas()
        for a in list(self.trackingAreas()):
            self.removeTrackingArea_(a)
        self.addTrackingArea_(
            AppKit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(), _TRACK, self, None
            )
        )

    def acceptsFirstMouse_(self, event) -> bool: return True
    def isOpaque(self)                -> bool:   return False

    def mouseEntered_(self, event) -> None:
        self._hover = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event) -> None:
        self._hover = False
        self.setNeedsDisplay_(True)

    def mouseDown_(self, event) -> None: pass

    def mouseUp_(self, event) -> None:
        if self._action:
            self._action()

    def drawRect_(self, rect) -> None:
        try:
            b  = self.bounds()
            cx = b.size.width  / 2
            cy = b.size.height / 2

            circle = AppKit.NSBezierPath.bezierPathWithOvalInRect_(b)
            # fondo oscuro
            AppKit.NSColor.colorWithRed_green_blue_alpha_(0.03, 0.03, 0.07, 0.90).set()
            circle.fill()
            # borde
            circle.setLineWidth_(0.8)
            if self._hover:
                AppKit.NSColor.colorWithRed_green_blue_alpha_(*_CYAN, 0.80).set()
            else:
                AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.25).set()
            circle.stroke()

            # ×
            p = AppKit.NSBezierPath.bezierPath()
            p.setLineWidth_(1.2)
            p.setLineCapStyle_(AppKit.NSLineCapStyleRound)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(
                1, 1, 1, 0.90 if self._hover else 0.50
            ).set()
            s = 2.8
            p.moveToPoint_(AppKit.NSMakePoint(cx - s, cy - s))
            p.lineToPoint_(AppKit.NSMakePoint(cx + s, cy + s))
            p.moveToPoint_(AppKit.NSMakePoint(cx + s, cy - s))
            p.lineToPoint_(AppKit.NSMakePoint(cx - s, cy + s))
            p.stroke()
        except Exception:
            _log.error("[_DarkCloseBtn] drawRect_ error (no fatal)", exc_info=True)


# ── Detector hover del panel completo ────────────────────────────────────────

class _PanelHoverTracker(AppKit.NSView):
    """View click-through que detecta entrada/salida del cursor sobre el panel."""

    def initWithFrame_(self, frame):
        self = objc.super(_PanelHoverTracker, self).initWithFrame_(frame)
        if self is None:
            return None
        self._close_btn = None
        self._bg        = None
        return self

    @objc.python_method
    def configure(self, close_btn, bg) -> None:
        self._close_btn = close_btn
        self._bg        = bg

    def updateTrackingAreas(self) -> None:
        objc.super(_PanelHoverTracker, self).updateTrackingAreas()
        for a in list(self.trackingAreas()):
            self.removeTrackingArea_(a)
        self.addTrackingArea_(
            AppKit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(), _TRACK, self, None
            )
        )

    def mouseEntered_(self, event) -> None:
        if self._close_btn:
            AppKit.NSAnimationContext.runAnimationGroup_completionHandler_(
                lambda ctx: (ctx.setDuration_(0.15),
                             self._close_btn.animator().setAlphaValue_(1.0)),
                None,
            )
        if self._bg:
            self._bg.set_hover(True)

    def mouseExited_(self, event) -> None:
        if self._close_btn:
            AppKit.NSAnimationContext.runAnimationGroup_completionHandler_(
                lambda ctx: (ctx.setDuration_(0.10),
                             self._close_btn.animator().setAlphaValue_(0.0)),
                None,
            )
        if self._bg:
            self._bg.set_hover(False)

    def isOpaque(self) -> bool: return False
    def hitTest_(self, pt):     return None
    def drawRect_(self, rect):  pass


# ── Animador ease-out quint ───────────────────────────────────────────────────

class _PanelAnimator(AppKit.NSObject):
    """Anima posición X y alpha de un NSPanel a 60 fps (ease-out quint)."""

    def init(self):
        self = objc.super(_PanelAnimator, self).init()
        if self is None:
            return None
        self._panel    = None
        self._from_x   = 0.0
        self._to_x     = 0.0
        self._y        = 0.0
        self._progress = 0.0
        self._step     = 0.0
        self._fade_in  = True
        self._timer    = None
        self._on_done  = None
        return self

    @objc.python_method
    def start(self, panel, from_x: float, to_x: float, y: float,
              duration: float, fade_in: bool, on_done=None) -> None:
        self._cancel_timer()
        self._panel    = panel
        self._from_x   = from_x
        self._to_x     = to_x
        self._y        = y
        self._progress = 0.0
        self._step     = (1.0 / 60.0) / max(duration, 0.01)
        self._fade_in  = fade_in
        self._on_done  = on_done

        self._timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / 60.0, self, 'animTick:', None, True
        )

    @objc.python_method
    def cancel(self) -> None:
        self._cancel_timer()

    @objc.python_method
    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def animTick_(self, timer) -> None:
        try:
            self._progress = min(1.0, self._progress + self._step)

            # ease-out quint: 1 - (1-p)^5
            inv = 1.0 - self._progress
            t   = 1.0 - inv * inv * inv * inv * inv

            x     = self._from_x + (self._to_x - self._from_x) * t
            alpha = t if self._fade_in else (1.0 - t)

            if self._panel is not None:
                self._panel.setFrameOrigin_(AppKit.NSMakePoint(x, self._y))
                self._panel.setAlphaValue_(alpha)

            if self._progress >= 1.0:
                timer.invalidate()
                self._timer = None
                cb = self._on_done
                self._on_done = None
                if cb is not None:
                    cb()
        except Exception:
            _log.error("[_PanelAnimator] animTick_ error (no fatal)", exc_info=True)
            try:
                timer.invalidate()
            except Exception:
                pass


# ── Panel principal ───────────────────────────────────────────────────────────

class MainPanel:
    """
    Panel de control dark glass — esquina inferior derecha.
    Desliza desde la derecha (ease-out quint + fade).
    Thread-safe: toggle() desde cualquier hilo.
    """

    WIDTH  = 220
    HEIGHT = 72

    def __init__(self, bridge, daemon, chat_panel) -> None:
        self._bridge     = bridge
        self._daemon     = daemon
        self._chat_panel = chat_panel
        self._panel: Optional[AppKit.NSPanel] = None
        self._animator: Optional[_PanelAnimator] = None
        self._visible   = False
        self._animating = False

    @objc.python_method
    def _positions(self):
        CS      = _DarkCloseBtn.SIZE
        OV      = CS / 2
        sf      = AppKit.NSScreen.mainScreen().frame()
        final_x = sf.size.width - self.WIDTH - _MARGIN_X - OV
        final_y = _MARGIN_Y
        off_x   = sf.size.width + 40
        return final_x, final_y, off_x

    # ── API pública ───────────────────────────────────────────────────────────

    def toggle(self) -> None:
        self._bridge.run_on_main_thread(self._do_toggle)

    def toggle_on_main(self) -> None:
        self._do_toggle()

    def toggle_near(self, orb_x: float = 0, orb_y: float = 0,
                    screen_h: float = 0) -> None:
        self.toggle()

    def toggle_near_on_main(self, orb_x: float = 0, orb_y: float = 0,
                             screen_h: float = 0) -> None:
        self.toggle_on_main()

    # ── Hilo principal ────────────────────────────────────────────────────────

    def _do_toggle(self) -> None:
        if self._panel is None:
            self._build()

        if self._animating:
            return

        final_x, final_y, offscreen_x = self._positions()

        if self._visible:
            self._visible   = False
            self._animating = True
            self._animator.start(
                self._panel,
                from_x   = final_x,
                to_x     = offscreen_x,
                y        = final_y,
                duration = _DUR_HIDE,
                fade_in  = False,
                on_done  = self._on_hide_done,
            )
        else:
            self._visible   = True
            self._animating = True
            self._panel.setAlphaValue_(0.0)
            self._panel.setFrameOrigin_(AppKit.NSMakePoint(offscreen_x, final_y))
            self._panel.makeKeyAndOrderFront_(None)
            AppKit.NSApp.activateIgnoringOtherApps_(True)
            self._animator.start(
                self._panel,
                from_x   = offscreen_x,
                to_x     = final_x,
                y        = final_y,
                duration = _DUR_SHOW,
                fade_in  = True,
                on_done  = self._on_show_done,
            )

    def _on_show_done(self) -> None:
        self._animating = False

    def _on_hide_done(self) -> None:
        if self._panel:
            self._panel.orderOut_(None)
        self._animating = False

    def _hide(self) -> None:
        if self._animator:
            self._animator.cancel()
        if self._panel:
            self._panel.orderOut_(None)
        self._visible   = False
        self._animating = False

    def _build(self) -> None:
        self._animator = _PanelAnimator.alloc().init()

        CS      = _DarkCloseBtn.SIZE
        OV      = CS / 2
        panel_w = self.WIDTH  + OV
        panel_h = self.HEIGHT + OV

        self._panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, panel_w, panel_h),
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self._panel.setLevel_(1001)
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._panel.setHasShadow_(True)
        self._panel.setMovableByWindowBackground_(True)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )

        # Content wrapper
        content = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, panel_w, panel_h)
        )
        self._panel.setContentView_(content)

        # Fondo biselado oscuro (desplazado OV para dejar espacio al botón ×)
        bg = _DarkPanelBg.alloc().initWithFrame_(
            AppKit.NSMakeRect(OV, 0, self.WIDTH, self.HEIGHT)
        )
        content.addSubview_(bg)

        # Botones
        PAD   = 12
        GAP   = 8
        BTN_W = (self.WIDTH - 2 * PAD - 2 * GAP) / 3
        BTN_H = self.HEIGHT - 2 * PAD

        configs = [
            ('QUIT',  _icon_quit,  self._action_quit),
            ('VOICE', _icon_voice, self._action_voice),
            ('TYPE',  _icon_text,  self._action_text),
        ]
        for i, (lbl, icon_fn, act) in enumerate(configs):
            bx  = PAD + i * (BTN_W + GAP)
            btn = _DarkBtn.alloc().initWithFrame_(
                AppKit.NSMakeRect(bx, PAD, BTN_W, BTN_H)
            )
            btn.configure(lbl, icon_fn, act)
            bg.addSubview_(btn)

        # Tracker hover (detecta entrada/salida del panel completo)
        tracker = _PanelHoverTracker.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        )
        bg.addSubview_(tracker)

        # Botón × (sobresale por la esquina superior-izquierda del panel)
        K = _CUT * (1.0 - 1.0 / math.sqrt(2.0))
        close_btn = _DarkCloseBtn.alloc().initWithFrame_(
            AppKit.NSMakeRect(K, self.HEIGHT - K - CS / 2, CS, CS)
        )
        close_btn.configure(self._action_close)
        content.addSubview_(close_btn)

        tracker.configure(close_btn, bg)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _action_close(self) -> None:
        self._hide()

    def _action_quit(self) -> None:
        os.kill(os.getpid(), signal.SIGKILL)

    def _action_voice(self) -> None:
        self._hide()
        self._daemon.trigger_voice_input()

    def _action_text(self) -> None:
        popup = self._daemon._text_popup
        popup._already_shown = True
        self._hide()
        popup._show()
        self._daemon.trigger_text_input()
