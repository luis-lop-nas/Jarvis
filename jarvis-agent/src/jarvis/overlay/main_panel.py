"""
main_panel.py

Panel principal flotante de Jarvis.
Se muestra automáticamente al arrancar y al hacer clic en el orb.

Tres botones:
  ⏻  Salir  — termina Jarvis
  🎤 Voz    — inicia grabación de voz
  💬 Chat   — muestra/oculta el panel de chat
"""

from __future__ import annotations

import threading
import objc
import AppKit
from typing import Optional, Callable

# Bitmask de NSTrackingArea: MouseEnteredAndExited | ActiveAlways
_TRACK_OPTS = 0x01 | 0x80


# ── Fondo redondeado del panel ────────────────────────────────────────────────

class _PanelBG(AppKit.NSView):
    """Fondo oscuro semitransparente con borde azul y esquinas redondeadas."""

    def drawRect_(self, rect) -> None:
        b    = self.bounds()
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(b, 18.0, 18.0)

        # Fondo oscuro
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.05, 0.05, 0.10, 0.93).set()
        path.fill()

        # Borde azul-blanco
        path.setLineWidth_(1.2)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.45, 0.72, 1.0, 0.55).set()
        path.stroke()

    def isOpaque(self) -> bool:
        return False


# ── Botón circular ────────────────────────────────────────────────────────────

class _IconBtn(AppKit.NSView):
    """Vista circular con emoji + hover glow."""

    def initWithFrame_(self, frame):
        self = objc.super(_IconBtn, self).initWithFrame_(frame)
        if self is None:
            return None
        self._icon:   str                = "●"
        self._bg:     tuple              = (0.2, 0.5, 1.0, 0.6)
        self._action: Optional[Callable] = None
        self._hover:  bool               = False
        return self

    def configure(self, icon: str, color: tuple, action: Callable) -> None:
        self._icon   = icon
        self._bg     = color
        self._action = action
        self.setNeedsDisplay_(True)

    # ── Tracking hover ────────────────────────────────────────────────────────

    def updateTrackingAreas(self) -> None:
        objc.super(_IconBtn, self).updateTrackingAreas()
        for area in list(self.trackingAreas()):
            self.removeTrackingArea_(area)
        ta = AppKit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(), _TRACK_OPTS, self, None
        )
        self.addTrackingArea_(ta)

    def mouseEntered_(self, event) -> None:
        self._hover = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event) -> None:
        self._hover = False
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event) -> None:
        if self._action is not None:
            self._action()

    # ── Dibujo ────────────────────────────────────────────────────────────────

    def isOpaque(self) -> bool:
        return False

    def drawRect_(self, rect) -> None:
        b  = self.bounds()
        cx = b.size.width  / 2
        cy = b.size.height / 2
        r  = min(cx, cy) - 2.0

        rr, gg, bb, aa = self._bg
        aa_draw = min(1.0, aa + 0.22) if self._hover else aa

        # Círculo de fondo
        path = AppKit.NSBezierPath.bezierPath()
        path.appendBezierPathWithOvalInRect_(
            AppKit.NSMakeRect(cx - r, cy - r, r * 2, r * 2)
        )
        AppKit.NSColor.colorWithRed_green_blue_alpha_(rr, gg, bb, aa_draw).set()
        path.fill()

        # Borde
        path.setLineWidth_(1.0)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.30 if self._hover else 0.18).set()
        path.stroke()

        # Destello especular
        sx, sy, sr = cx - r * 0.25, cy + r * 0.28, r * 0.20
        sp = AppKit.NSBezierPath.bezierPath()
        sp.appendBezierPathWithOvalInRect_(
            AppKit.NSMakeRect(sx - sr, sy - sr, sr * 2, sr * 2)
        )
        AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.32).set()
        sp.fill()

        # Emoji centrado
        attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(22.0),
            AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor(),
        }
        astr = AppKit.NSAttributedString.alloc().initWithString_attributes_(self._icon, attrs)
        sz   = astr.size()
        astr.drawAtPoint_(AppKit.NSMakePoint(cx - sz.width / 2, cy - sz.height / 2))


# ── Panel principal ───────────────────────────────────────────────────────────

class MainPanel:
    """
    Panel flotante con 3 botones de control.
    Thread-safe: llamar toggle_near() desde cualquier thread,
    toggle_near_on_main() solo desde el hilo principal.
    """

    WIDTH  = 260
    HEIGHT = 96

    def __init__(self, bridge, daemon, chat_panel) -> None:
        self._bridge     = bridge
        self._daemon     = daemon
        self._chat_panel = chat_panel
        self._panel: Optional[AppKit.NSPanel] = None
        self._visible    = False

    # ── API pública ───────────────────────────────────────────────────────────

    def toggle_near(self, orb_x: float, orb_y: float, screen_h: float) -> None:
        """Thread-safe: encola el toggle en el hilo principal vía bridge."""
        self._bridge.run_on_main_thread(
            lambda: self._toggle_near(orb_x, orb_y, screen_h)
        )

    def toggle_near_on_main(self, orb_x: float, orb_y: float, screen_h: float) -> None:
        """Llamar únicamente desde el hilo principal."""
        self._toggle_near(orb_x, orb_y, screen_h)

    # ── Hilo principal ────────────────────────────────────────────────────────

    def _toggle_near(self, orb_x: float, orb_y: float, screen_h: float) -> None:
        if self._panel is None:
            self._build()
        if self._visible:
            self._panel.orderOut_(None)
            self._visible = False
        else:
            self._reposition(orb_x, orb_y, screen_h)
            self._panel.orderFront_(None)   # orderFront_ funciona sin activar la app
            self._visible = True

    def _hide(self) -> None:
        if self._panel is not None:
            self._panel.orderOut_(None)
        self._visible = False

    def _reposition(self, orb_x: float, orb_y: float, screen_h: float) -> None:
        sw = AppKit.NSScreen.mainScreen().frame().size.width
        px = max(8.0, min(sw - self.WIDTH - 8.0, orb_x - self.WIDTH / 2))
        above_y = orb_y + 80.0
        below_y = orb_y - self.HEIGHT - 80.0
        py      = above_y if above_y + self.HEIGHT < screen_h - 50 else max(8.0, below_y)
        self._panel.setFrameOrigin_(AppKit.NSMakePoint(px, py))
        print(f"[MainPanel] posición: ({px:.0f}, {py:.0f})")

    def _build(self) -> None:
        print("[MainPanel] construyendo panel...")
        try:
            # ── NSPanel ──────────────────────────────────────────────────────
            self._panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                AppKit.NSMakeRect(0, 0, self.WIDTH, self.HEIGHT),
                AppKit.NSWindowStyleMaskBorderless,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            self._panel.setLevel_(AppKit.NSFloatingWindowLevel + 200)
            self._panel.setOpaque_(False)
            self._panel.setBackgroundColor_(AppKit.NSColor.clearColor())
            self._panel.setHasShadow_(True)
            self._panel.setMovableByWindowBackground_(True)
            self._panel.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | AppKit.NSWindowCollectionBehaviorStationary
                | AppKit.NSWindowCollectionBehaviorIgnoresCycle
            )

            # ── Fondo ─────────────────────────────────────────────────────────
            bg = _PanelBG.alloc().initWithFrame_(
                AppKit.NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
            )
            self._panel.setContentView_(bg)

            # ── 3 botones ─────────────────────────────────────────────────────
            BTN_D = 52
            GAP   = 20
            total = 3 * BTN_D + 2 * GAP
            mx    = (self.WIDTH  - total) / 2
            by    = (self.HEIGHT - BTN_D) / 2

            configs = [
                ("⏻",  (0.92, 0.20, 0.16, 0.80), self._action_quit),
                ("🎤", (0.10, 0.52, 1.00, 0.80), self._action_voice),
                ("💬", (0.00, 0.72, 0.68, 0.80), self._action_chat),
            ]
            for i, (icon, color, action) in enumerate(configs):
                bx  = mx + i * (BTN_D + GAP)
                btn = _IconBtn.alloc().initWithFrame_(AppKit.NSMakeRect(bx, by, BTN_D, BTN_D))
                btn.configure(icon, color, action)
                bg.addSubview_(btn)

            print("[MainPanel] panel construido OK")
        except Exception as e:
            print(f"[MainPanel] ERROR en _build: {e}")
            self._panel = None

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _action_quit(self) -> None:
        AppKit.NSApplication.sharedApplication().terminate_(None)

    def _action_voice(self) -> None:
        self._hide()
        threading.Thread(target=self._daemon.trigger_voice_input, daemon=True).start()

    def _action_chat(self) -> None:
        self._hide()
        self._chat_panel.toggle()
