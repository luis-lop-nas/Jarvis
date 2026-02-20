"""
main_panel.py

Panel de control liquid glass — estilo Apple.
"""

from __future__ import annotations

import os
import signal
import threading
import objc
import AppKit
from typing import Optional, Callable

# NSTrackingArea: MouseEnteredAndExited | ActiveAlways
_TRACK = 0x01 | 0x80
_CR    = 26.0   # corner radius global


# ── Iconos bezier ─────────────────────────────────────────────────────────────

def _icon_quit(cx: float, cy: float, alpha: float) -> None:
    """× delgada."""
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
    """Waveform de audio: 5 barras verticales de altura variable."""
    p = AppKit.NSBezierPath.bezierPath()
    p.setLineWidth_(1.6)
    p.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    AppKit.NSColor.colorWithRed_green_blue_alpha_(1, 1, 1, alpha).set()
    for dx, hh in [(-5.5, 2.5), (-2.8, 4.8), (0.0, 6.2), (2.8, 4.8), (5.5, 2.5)]:
        p.moveToPoint_(AppKit.NSMakePoint(cx + dx, cy - hh))
        p.lineToPoint_(AppKit.NSMakePoint(cx + dx, cy + hh))
    p.stroke()


def _icon_text(cx: float, cy: float, alpha: float) -> None:
    """Cursor I-beam de texto."""
    p = AppKit.NSBezierPath.bezierPath()
    p.setLineWidth_(1.3)
    p.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    AppKit.NSColor.colorWithRed_green_blue_alpha_(1, 1, 1, alpha).set()
    # barra vertical
    p.moveToPoint_(AppKit.NSMakePoint(cx,      cy - 5.5))
    p.lineToPoint_(AppKit.NSMakePoint(cx,      cy + 5.5))
    # serif superior
    p.moveToPoint_(AppKit.NSMakePoint(cx - 3.0, cy + 5.5))
    p.lineToPoint_(AppKit.NSMakePoint(cx + 3.0, cy + 5.5))
    # serif inferior
    p.moveToPoint_(AppKit.NSMakePoint(cx - 3.0, cy - 5.5))
    p.lineToPoint_(AppKit.NSMakePoint(cx + 3.0, cy - 5.5))
    p.stroke()


# ── Highlight especular liquid glass ─────────────────────────────────────────

class _GlassOverlay(AppKit.NSView):
    """
    Capa que añade el highlight especular característico del liquid glass:
    un gradiente blanco translúcido en la mitad superior que simula la
    refracción de la luz en el cristal curvado.
    """

    def drawRect_(self, rect) -> None:
        b = self.bounds()
        w = b.size.width
        h = b.size.height

        ctx = AppKit.NSGraphicsContext.currentContext()
        ctx.saveGraphicsState()

        # Clip al contorno redondeado del panel
        pill = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            b, _CR, _CR
        )
        pill.addClip()

        # Gradiente especular: blanco en el borde superior, transparente a mitad
        # angle 90° = de abajo (startingColor) hacia arriba (endingColor)
        spec = AppKit.NSGradient.alloc().initWithStartingColor_endingColor_(
            AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.00),
            AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.20),
        )
        spec.drawInRect_angle_(
            AppKit.NSMakeRect(0, h * 0.42, w, h * 0.58),
            90.0,
        )

        ctx.restoreGraphicsState()

    def isOpaque(self) -> bool:
        return False

    def hitTest_(self, pt):
        return None


# ── Borde exterior ────────────────────────────────────────────────────────────

class _Border(AppKit.NSView):
    """Borde redondeado translúcido. No captura clics."""

    def drawRect_(self, rect) -> None:
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), _CR, _CR
        )
        path.setLineWidth_(1.0)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.30).set()
        path.stroke()

    def isOpaque(self) -> bool:
        return False

    def hitTest_(self, pt):
        return None


# ── Botón píldora glass ───────────────────────────────────────────────────────

class _GlassBtn(AppKit.NSView):
    """Píldora glass con icono bezier, micro-highlight y etiqueta."""

    def initWithFrame_(self, frame):
        self = objc.super(_GlassBtn, self).initWithFrame_(frame)
        if self is None:
            return None
        self._label:     str                = ""
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

    # ── Hover ────────────────────────────────────────────────────────────────

    def updateTrackingAreas(self) -> None:
        objc.super(_GlassBtn, self).updateTrackingAreas()
        for a in list(self.trackingAreas()):
            self.removeTrackingArea_(a)
        self.addTrackingArea_(
            AppKit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(), _TRACK, self, None
            )
        )

    def mouseEntered_(self, event) -> None:
        self._hover = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event) -> None:
        self._hover = False
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event) -> None:
        if self._action:
            self._action()

    def isOpaque(self) -> bool:
        return False

    # ── Dibujo ───────────────────────────────────────────────────────────────

    def drawRect_(self, rect) -> None:
        b  = self.bounds()
        w  = b.size.width
        h  = b.size.height
        cr = h / 2   # fully rounded pill

        # ── Fondo glass base
        pill = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(b, cr, cr)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(
            1.0, 1.0, 1.0, 0.24 if self._hover else 0.10
        ).set()
        pill.fill()

        # ── Micro-highlight glass en mitad superior del botón
        ctx = AppKit.NSGraphicsContext.currentContext()
        ctx.saveGraphicsState()
        pill.addClip()
        hi = AppKit.NSGradient.alloc().initWithStartingColor_endingColor_(
            AppKit.NSColor.colorWithRed_green_blue_alpha_(1, 1, 1, 0.00),
            AppKit.NSColor.colorWithRed_green_blue_alpha_(1, 1, 1, 0.12 if self._hover else 0.07),
        )
        hi.drawInRect_angle_(
            AppKit.NSMakeRect(0, h * 0.5, w, h * 0.5), 90.0
        )
        ctx.restoreGraphicsState()

        # ── Borde
        pill.setLineWidth_(0.75)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(
            1.0, 1.0, 1.0, 0.40 if self._hover else 0.22
        ).set()
        pill.stroke()

        # ── Icono bezier
        if self._draw_icon:
            self._draw_icon(w / 2, h * 0.58, 0.92 if self._hover else 0.72)

        # ── Etiqueta
        lbl_a = {
            AppKit.NSFontAttributeName:
                AppKit.NSFont.systemFontOfSize_weight_(8.0, AppKit.NSFontWeightMedium),
            AppKit.NSForegroundColorAttributeName:
                AppKit.NSColor.colorWithRed_green_blue_alpha_(
                    1.0, 1.0, 1.0, 0.68 if self._hover else 0.44
                ),
        }
        lbl_s = AppKit.NSAttributedString.alloc().initWithString_attributes_(
            self._label, lbl_a
        )
        lsz = lbl_s.size()
        lbl_s.drawAtPoint_(AppKit.NSMakePoint(
            w / 2 - lsz.width / 2,
            h * 0.12 - lsz.height / 2,
        ))


# ── Panel principal ───────────────────────────────────────────────────────────

class MainPanel:
    """
    Panel de control liquid glass — centrado en pantalla.
    Thread-safe: toggle() desde cualquier hilo.
    toggle_on_main() solo desde el hilo principal.
    """

    WIDTH  = 220
    HEIGHT = 72

    def __init__(self, bridge, daemon, chat_panel) -> None:
        self._bridge     = bridge
        self._daemon     = daemon
        self._chat_panel = chat_panel
        self._panel: Optional[AppKit.NSPanel] = None
        self._visible = False

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
        if self._visible:
            self._panel.orderOut_(None)
            self._visible = False
        else:
            self._center()
            self._panel.makeKeyAndOrderFront_(None)
            AppKit.NSApp.activateIgnoringOtherApps_(True)
            self._visible = True

    def _hide(self) -> None:
        if self._panel:
            self._panel.orderOut_(None)
        self._visible = False

    def _center(self) -> None:
        sf = AppKit.NSScreen.mainScreen().frame()
        px = (sf.size.width  - self.WIDTH)  / 2
        py =  sf.size.height * 0.44
        self._panel.setFrameOrigin_(AppKit.NSMakePoint(px, py))

    def _build(self) -> None:
        # ── NSPanel borderless ────────────────────────────────────────────────
        self._panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, self.WIDTH, self.HEIGHT),
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self._panel.setLevel_(1001)
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._panel.setHasShadow_(True)
        self._panel.setMovableByWindowBackground_(True)
        self._panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )

        # ── NSVisualEffectView — dark frosted glass ────────────────────────────
        vfx = AppKit.NSVisualEffectView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        )
        vfx.setMaterial_(13)    # NSVisualEffectMaterialHUDWindow
        vfx.setBlendingMode_(0) # NSVisualEffectBlendingModeBehindWindow
        vfx.setState_(1)        # NSVisualEffectStateActive
        self._panel.setContentView_(vfx)

        # Esquinas redondeadas (DESPUÉS de setContentView_)
        vfx.setWantsLayer_(True)
        vfx.layer().setCornerRadius_(_CR)
        vfx.layer().setMasksToBounds_(True)

        # ── Capas en orden (de fondo a frente) ───────────────────────────────

        # 1. Highlight especular liquid glass
        overlay = _GlassOverlay.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        )
        vfx.addSubview_(overlay)

        # 2. Botones píldora
        PAD   = 12
        GAP   = 8
        BTN_W = (self.WIDTH - 2 * PAD - 2 * GAP) / 3
        BTN_H = self.HEIGHT - 2 * PAD

        configs = [
            ("Quit",  _icon_quit,  self._action_quit),
            ("Voice", _icon_voice, self._action_voice),
            ("Type",  _icon_text,  self._action_text),
        ]
        for i, (lbl, icon_fn, act) in enumerate(configs):
            bx  = PAD + i * (BTN_W + GAP)
            btn = _GlassBtn.alloc().initWithFrame_(
                AppKit.NSMakeRect(bx, PAD, BTN_W, BTN_H)
            )
            btn.configure(lbl, icon_fn, act)
            vfx.addSubview_(btn)

        # 3. Borde exterior (siempre encima)
        border = _Border.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        )
        vfx.addSubview_(border)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _action_quit(self) -> None:
        os.kill(os.getpid(), signal.SIGKILL)

    def _action_voice(self) -> None:
        self._hide()
        threading.Thread(
            target=self._daemon.trigger_voice_input, daemon=True
        ).start()

    def _action_text(self) -> None:
        self._hide()
        threading.Thread(
            target=self._daemon.trigger_text_input, daemon=True
        ).start()
