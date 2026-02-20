"""
text_input.py

Popup de entrada de texto para Jarvis.
Diseño: barra oscura con borde azul eléctrico, ◉ a la izquierda, × arriba-derecha.

Comportamiento:
  - Enter    → envía el texto
  - Escape   → cancela sin enviar
  - × button → cancela sin enviar
  - Clic fuera → NO cierra (hidesOnDeactivate = False)
"""

from __future__ import annotations

import threading
from typing import Optional

import AppKit
import objc


# ── Constantes de diseño ──────────────────────────────────────────────────────

_CORNER   = 14.0   # radio de esquinas
_TRACK    = 0x01 | 0x80   # NSTrackingArea: MouseEnteredAndExited | ActiveAlways


# ── Fondo redondeado ──────────────────────────────────────────────────────────

class _RoundedView(AppKit.NSView):
    def drawRect_(self, rect: AppKit.NSRect) -> None:
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), _CORNER, _CORNER
        )
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.04, 0.04, 0.09, 0.93).set()
        path.fill()
        path.setLineWidth_(1.5)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 0.71, 1.0, 0.7).set()
        path.stroke()

    def isOpaque(self) -> bool:
        return False


# ── Botón × ───────────────────────────────────────────────────────────────────

class _CloseBtn(AppKit.NSView):
    """Pequeño botón × en la esquina superior derecha del popup."""

    def initWithFrame_(self, frame):
        self = objc.super(_CloseBtn, self).initWithFrame_(frame)
        if self is None:
            return None
        self._action = None
        self._hover  = False
        return self

    @objc.python_method
    def set_action(self, fn) -> None:
        self._action = fn

    # ── Hover ────────────────────────────────────────────────────────────────

    def updateTrackingAreas(self) -> None:
        objc.super(_CloseBtn, self).updateTrackingAreas()
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
        cx = b.size.width  / 2
        cy = b.size.height / 2
        r  = b.size.width  / 2

        # Círculo de fondo
        circle = AppKit.NSBezierPath.bezierPathWithOvalInRect_(b)
        if self._hover:
            AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.18).set()
        else:
            AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.08).set()
        circle.fill()

        # × centrada
        cross = AppKit.NSBezierPath.bezierPath()
        cross.setLineWidth_(1.4)
        cross.setLineCapStyle_(AppKit.NSLineCapStyleRound)
        s = r * 0.38
        if self._hover:
            AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.90).set()
        else:
            AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.50).set()
        cross.moveToPoint_(AppKit.NSMakePoint(cx - s, cy - s))
        cross.lineToPoint_(AppKit.NSMakePoint(cx + s, cy + s))
        cross.moveToPoint_(AppKit.NSMakePoint(cx + s, cy - s))
        cross.lineToPoint_(AppKit.NSMakePoint(cx - s, cy + s))
        cross.stroke()


# ── Delegate del NSTextField ──────────────────────────────────────────────────

class _FieldDelegate(AppKit.NSObject):

    def initWithSubmit_cancel_(self, submit_fn, cancel_fn) -> "_FieldDelegate":
        self = objc.super(_FieldDelegate, self).init()
        if self is None:
            return None
        self._submit = submit_fn
        self._cancel = cancel_fn
        return self

    def control_textView_doCommandBySelector_(
        self,
        control: AppKit.NSControl,
        textView: AppKit.NSTextView,
        selector: str,
    ) -> bool:
        if selector == "insertNewline:":
            text = control.stringValue().strip()
            if text:
                self._submit(text)
            else:
                self._cancel()
            return True
        if selector == "cancelOperation:":
            self._cancel()
            return True
        return False


# ── Popup principal ───────────────────────────────────────────────────────────

class TextInputPopup:
    """
    Popup de entrada de texto thread-safe.

    Llamar desde un thread secundario:
        text = popup.show_and_wait()
    Bloquea hasta Enter / × / Escape / timeout (30 s).
    Clicar fuera NO lo cierra (hidesOnDeactivate = False).
    """

    WIDTH   = 520
    HEIGHT  = 62
    TIMEOUT = 30.0

    # Tamaño y posición del botón ×
    _CLOSE_SIZE = 20
    _CLOSE_PAD  = 10   # margen desde el borde derecho/superior

    def __init__(self, bridge) -> None:
        self._bridge        = bridge
        self._event         = threading.Event()
        self._text: Optional[str] = None
        self._window        = None
        self._delegate      = None
        self._already_shown = False   # True si mostrado desde hilo principal con gesto

    # ── API pública ───────────────────────────────────────────────────────────

    def show_and_wait(self) -> Optional[str]:
        """Muestra el popup y espera. Thread-safe (llamar desde thread secundario).

        Si _already_shown=True (popup ya mostrado directamente desde el hilo
        principal con contexto de gesto), omite la llamada al bridge.
        """
        self._event.clear()
        self._text = None
        if not self._already_shown:
            self._bridge.run_on_main_thread(self._show)
        self._already_shown = False
        self._event.wait(timeout=self.TIMEOUT)
        if self._window is not None:
            self._bridge.run_on_main_thread(self._close)
        return self._text

    # ── Hilo principal ────────────────────────────────────────────────────────

    def _show(self) -> None:
        """Crea y muestra el popup. Debe llamarse desde el hilo principal."""
        self._prev_app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()

        screen = AppKit.NSScreen.mainScreen()
        sf     = screen.frame()
        sw, sh = sf.size.width, sf.size.height

        x = (sw - self.WIDTH) / 2
        y = sh * 0.63
        frame = AppKit.NSMakeRect(x, y, self.WIDTH, self.HEIGHT)

        # ── NSPanel ───────────────────────────────────────────────────────────
        self._window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self._window.setLevel_(1002)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._window.setHasShadow_(True)
        # ── CLAVE: no ocultar al perder foco de la app ────────────────────────
        self._window.setHidesOnDeactivate_(False)

        # ── Fondo ─────────────────────────────────────────────────────────────
        bg = _RoundedView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        )
        self._window.setContentView_(bg)

        # ── Icono ◉ ───────────────────────────────────────────────────────────
        icon = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(14, 14, 28, 34)
        )
        icon.setStringValue_("◉")
        icon.setBezeled_(False)
        icon.setDrawsBackground_(False)
        icon.setEditable_(False)
        icon.setSelectable_(False)
        icon.setFont_(AppKit.NSFont.systemFontOfSize_(22))
        icon.setTextColor_(
            AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 0.71, 1.0, 0.9)
        )
        bg.addSubview_(icon)

        # ── Botón × (esquina superior derecha) ────────────────────────────────
        cs  = self._CLOSE_SIZE
        pad = self._CLOSE_PAD
        # macOS coords: y=0 es la parte inferior de la vista
        close_x = self.WIDTH  - cs - pad
        close_y = self.HEIGHT - cs - pad
        close_btn = _CloseBtn.alloc().initWithFrame_(
            AppKit.NSMakeRect(close_x, close_y, cs, cs)
        )
        close_btn.set_action(self._cancel)
        bg.addSubview_(close_btn)

        # ── Campo de texto (deja espacio para el ×) ───────────────────────────
        field_x = 50
        field_w = self.WIDTH - field_x - cs - pad * 2 - 6   # margen al botón
        field = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(field_x, 11, field_w, 40)
        )
        field.setPlaceholderString_("Escríbele a Jarvis…")
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setFont_(
            AppKit.NSFont.systemFontOfSize_weight_(19, AppKit.NSFontWeightLight)
        )
        field.setTextColor_(AppKit.NSColor.whiteColor())
        field.setFocusRingType_(AppKit.NSFocusRingTypeNone)

        self._delegate = _FieldDelegate.alloc().initWithSubmit_cancel_(
            self._submit, self._cancel
        )
        field.setDelegate_(self._delegate)
        bg.addSubview_(field)

        # ── Foco ──────────────────────────────────────────────────────────────
        self._window.makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        self._window.makeFirstResponder_(field)

    def _submit(self, text: str) -> None:
        self._text = text
        self._close()
        self._event.set()

    def _cancel(self) -> None:
        self._close()
        self._event.set()

    def _close(self) -> None:
        if self._window is not None:
            self._window.orderOut_(None)
            self._window = None
        prev = getattr(self, "_prev_app", None)
        if prev is not None:
            prev.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
            self._prev_app = None
