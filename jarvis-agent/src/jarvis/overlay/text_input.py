"""
text_input.py

Popup minimalista de entrada de texto para Jarvis.
Aparece centrado en pantalla cuando el usuario usa el hotkey (Ctrl+Space)
en lugar de hablar por voz.

Diseño: ventana flotante oscura con borde azul eléctrico, campo de texto blanco.

Uso (desde un thread secundario):
    popup = TextInputPopup(bridge)
    text  = popup.show_and_wait()   # bloquea hasta Enter/Escape/timeout
    if text:
        agent.run(text)
"""

from __future__ import annotations

import threading
from typing import Optional

import AppKit
import objc


# ── Vista con fondo oscuro y esquinas redondeadas ─────────────────────────────

class _RoundedView(AppKit.NSView):
    def drawRect_(self, rect: AppKit.NSRect) -> None:
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), 14.0, 14.0
        )
        # Fondo oscuro semitransparente
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.04, 0.04, 0.09, 0.93).set()
        path.fill()
        # Borde azul eléctrico
        path.setLineWidth_(1.5)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 0.71, 1.0, 0.7).set()
        path.stroke()

    def isOpaque(self) -> bool:
        return False


# ── Delegate del NSTextField (captura Return y Escape) ────────────────────────

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
    La función bloquea hasta que el usuario confirma (Enter), cancela (Escape)
    o expira el timeout (30s). Devuelve el texto o None si cancelado/timeout.
    """

    WIDTH   = 520
    HEIGHT  = 62
    TIMEOUT = 30.0

    def __init__(self, bridge) -> None:
        self._bridge   = bridge
        self._event    = threading.Event()
        self._text: Optional[str] = None
        self._window   = None
        self._delegate = None

    # ── API pública ───────────────────────────────────────────────────────────

    def show_and_wait(self) -> Optional[str]:
        """Muestra el popup y espera. Thread-safe (llamar desde thread secundario)."""
        self._event.clear()
        self._text = None
        self._bridge.run_on_main_thread(self._show)
        self._event.wait(timeout=self.TIMEOUT)
        # Si expiró el timeout, cerrar el popup si sigue abierto
        if self._window is not None:
            self._bridge.run_on_main_thread(self._close)
        return self._text

    # ── Hilo principal ────────────────────────────────────────────────────────

    def _show(self) -> None:
        """Crea y muestra el popup. Llamado en el hilo principal."""
        # Guardar app activa para restaurar el foco al cerrar
        import AppKit as _AppKit
        self._prev_app = _AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()

        screen = AppKit.NSScreen.mainScreen()
        sf     = screen.frame()
        sw, sh = sf.size.width, sf.size.height

        # Centrado horizontalmente, 65% desde abajo (ligeramente arriba del centro)
        x = (sw - self.WIDTH) / 2
        y = sh * 0.63
        frame = AppKit.NSMakeRect(x, y, self.WIDTH, self.HEIGHT)

        # Ventana borderless flotante
        self._window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self._window.setLevel_(1002)   # encima del overlay y la barra de menú
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._window.setHasShadow_(True)

        # Vista de fondo redondeada
        bg = _RoundedView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        )
        self._window.setContentView_(bg)

        # Icono ◉ a la izquierda
        icon_frame = AppKit.NSMakeRect(14, 14, 28, 34)
        icon = AppKit.NSTextField.alloc().initWithFrame_(icon_frame)
        icon.setStringValue_("◉")
        icon.setBezeled_(False)
        icon.setDrawsBackground_(False)
        icon.setEditable_(False)
        icon.setSelectable_(False)
        icon.setFont_(AppKit.NSFont.systemFontOfSize_(22))
        icon.setTextColor_(AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 0.71, 1.0, 0.9))
        bg.addSubview_(icon)

        # Campo de texto
        field_frame = AppKit.NSMakeRect(50, 11, self.WIDTH - 66, 40)
        field = AppKit.NSTextField.alloc().initWithFrame_(field_frame)
        field.setPlaceholderString_("Escríbele a Jarvis…")
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setFont_(AppKit.NSFont.systemFontOfSize_weight_(19, AppKit.NSFontWeightLight))
        field.setTextColor_(AppKit.NSColor.whiteColor())
        field.setFocusRingType_(AppKit.NSFocusRingTypeNone)

        self._delegate = _FieldDelegate.alloc().initWithSubmit_cancel_(
            self._submit, self._cancel
        )
        field.setDelegate_(self._delegate)
        bg.addSubview_(field)

        # Mostrar y capturar foco
        self._window.makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        self._window.makeFirstResponder_(field)

    def _submit(self, text: str) -> None:
        """Llamado desde el hilo principal cuando el usuario pulsa Enter."""
        self._text = text
        self._close()
        self._event.set()

    def _cancel(self) -> None:
        """Llamado desde el hilo principal cuando el usuario pulsa Escape."""
        self._close()
        self._event.set()

    def _close(self) -> None:
        if self._window is not None:
            self._window.orderOut_(None)
            self._window = None
        # Devolver el foco a la app que estaba activa antes del popup
        prev = getattr(self, "_prev_app", None)
        if prev is not None:
            prev.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
            self._prev_app = None
