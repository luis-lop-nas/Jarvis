"""
main_panel.py

Panel de control liquid glass — esquina inferior derecha.
Se desliza desde fuera de pantalla (derecha) con ease-out + fade.
Thread-safe: toggle() desde cualquier hilo.
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

# Posición en la esquina inferior derecha
_MARGIN_X = 20   # px desde el borde derecho de la pantalla
_MARGIN_Y = 40   # px desde el borde inferior (deja espacio al Dock)

# Duración de las animaciones (segundos)
_DUR_SHOW = 0.34
_DUR_HIDE = 0.22


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


# ── Animador timer-based ──────────────────────────────────────────────────────

class _PanelAnimator(AppKit.NSObject):
    """
    Anima la posición X y alpha de un NSPanel a 60 fps.
    Curva ease-out quint (f(t) = 1 - (1-t)^5) para un deslizamiento
    rápido al inicio que frena suavemente al llegar al destino.
    """

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
        """Inicia una animación. Siempre llamar desde el hilo principal."""
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
            1.0 / 60.0, self, "animTick:", None, True
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
        self._progress = min(1.0, self._progress + self._step)

        # Ease-out quint: frena con elegancia al llegar al destino
        inv = 1.0 - self._progress
        t   = 1.0 - inv * inv * inv * inv * inv   # 1 - (1-p)^5

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


# ── Panel principal ───────────────────────────────────────────────────────────

class MainPanel:
    """
    Panel de control liquid glass — esquina inferior derecha.
    Entra deslizándose desde la derecha (ease-out quint + fade).
    Sale deslizándose hacia la derecha (ease-out quint + fade).
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

    # ── Posiciones ───────────────────────────────────────────────────────────

    @objc.python_method
    def _positions(self):
        """Devuelve (final_x, final_y, offscreen_x) según la pantalla principal."""
        sf          = AppKit.NSScreen.mainScreen().frame()
        final_x     = sf.size.width - self.WIDTH - _MARGIN_X
        final_y     = _MARGIN_Y
        offscreen_x = sf.size.width + 40   # justo fuera del borde derecho
        return final_x, final_y, offscreen_x

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

        # Debounce: ignorar clicks mientras ya se está animando
        if self._animating:
            return

        final_x, final_y, offscreen_x = self._positions()

        if self._visible:
            # ── Ocultar: deslizar hacia la derecha ───────────────────────────
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
            # ── Mostrar: aparecer desde la derecha ───────────────────────────
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
        """Ocultar inmediato (botones del panel). No animar para no robar el foco."""
        if self._animator:
            self._animator.cancel()
        if self._panel:
            self._panel.orderOut_(None)
        self._visible   = False
        self._animating = False

    def _build(self) -> None:
        # ── Animador (siempre en hilo principal) ─────────────────────────────
        self._animator = _PanelAnimator.alloc().init()

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
        self._panel.setHidesOnDeactivate_(False)
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
        """Graba voz. trigger_voice_input es non-blocking → no hace falta thread."""
        self._hide()
        self._daemon.trigger_voice_input()

    def _action_text(self) -> None:
        """
        Muestra el popup de texto DIRECTAMENTE en el hilo principal.

        Llamar _show() desde el handler del click (gesto de usuario) garantiza
        que macOS 14+ permita asignar el foco al campo de texto.
        Después, notificamos al daemon para que espere el resultado.
        """
        popup = self._daemon._text_popup
        # Señal para que show_and_wait() omita la llamada al bridge
        popup._already_shown = True
        self._hide()
        popup._show()                        # foco garantizado: contexto de gesto
        self._daemon.trigger_text_input()    # daemon espera el resultado (non-blocking)
