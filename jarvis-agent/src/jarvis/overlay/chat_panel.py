"""
chat_panel.py

Panel de chat flotante persistente para Jarvis.
Muestra el historial de conversación y permite enviar mensajes de texto.

Características:
  - Fondo oscuro semitransparente con borde azul eléctrico (misma estética que HUD)
  - Historial scrollable de mensajes (usuario y Jarvis)
  - Campo de texto en la parte inferior — Enter para enviar
  - Toggle mostrar/ocultar desde el menú ◉ J
  - Thread-safe — las APIs públicas se pueden llamar desde cualquier thread
  - Draggable desde cualquier zona libre
"""

from __future__ import annotations

import threading
from typing import Optional

import AppKit
import objc


# ── Fondo con esquinas redondeadas ────────────────────────────────────────────

class _ChatBG(AppKit.NSView):
    def drawRect_(self, rect: AppKit.NSRect) -> None:
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), 14.0, 14.0
        )
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.04, 0.04, 0.09, 0.95).set()
        path.fill()
        path.setLineWidth_(1.5)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 0.71, 1.0, 0.55).set()
        path.stroke()

    def isOpaque(self) -> bool:
        return False


# ── Separador delgado ─────────────────────────────────────────────────────────

class _SepView(AppKit.NSView):
    def drawRect_(self, rect: AppKit.NSRect) -> None:
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 0.71, 1.0, 0.20).set()
        AppKit.NSRectFill(self.bounds())

    def isOpaque(self) -> bool:
        return False


# ── Controller (target de botones + delegate de NSTextField) ──────────────────

class _ChatCtrl(AppKit.NSObject):

    def initWithPanel_(self, panel: "ChatPanel") -> "_ChatCtrl":
        self = objc.super(_ChatCtrl, self).init()
        if self is None:
            return None
        self._cp = panel
        return self

    # Botón ✕ cerrar
    def close_(self, sender) -> None:
        self._cp._close()

    # NSTextField delegate — captura Return
    def control_textView_doCommandBySelector_(
        self,
        control: AppKit.NSControl,
        textView: AppKit.NSTextView,
        selector: str,
    ) -> bool:
        if selector == "insertNewline:":
            text = (control.stringValue() or "").strip()
            if text:
                control.setStringValue_("")
                self._cp._submit_text(text)
            return True
        return False


# ── Panel principal ───────────────────────────────────────────────────────────

class ChatPanel:
    """
    Panel de chat flotante con historial persistente.

    Uso (thread-safe):
        panel = ChatPanel(bridge, daemon)
        panel.toggle()                   # mostrar / ocultar
        panel.add_user_message("...")    # añadir mensaje usuario
        panel.add_jarvis_message("...")  # añadir respuesta Jarvis
    """

    WIDTH    = 480
    HEIGHT   = 560
    Y_POS    = 100.0   # px desde la base de la pantalla

    def __init__(self, bridge, daemon) -> None:
        self._bridge  = bridge
        self._daemon  = daemon
        self._panel:  Optional[AppKit.NSPanel]     = None
        self._tv:     Optional[AppKit.NSTextView]  = None
        self._input:  Optional[AppKit.NSTextField] = None
        self._ctrl:   Optional[_ChatCtrl]          = None
        self._visible = False

    # ── API pública (thread-safe) ─────────────────────────────────────────────

    def toggle(self) -> None:
        """Muestra u oculta el panel. Thread-safe."""
        self._bridge.run_on_main_thread(self._toggle)

    def add_user_message(self, text: str) -> None:
        """Añade mensaje del usuario al historial. Thread-safe."""
        self._bridge.run_on_main_thread(lambda: self._append("user", text))

    def add_jarvis_message(self, text: str) -> None:
        """Añade respuesta de Jarvis al historial. Thread-safe."""
        self._bridge.run_on_main_thread(lambda: self._append("jarvis", text))

    # ── Hilo principal ────────────────────────────────────────────────────────

    def _toggle(self) -> None:
        if self._panel is None:
            self._build()
        if self._visible:
            self._panel.orderOut_(None)
            self._visible = False
        else:
            self._panel.makeKeyAndOrderFront_(None)
            AppKit.NSApp.activateIgnoringOtherApps_(True)
            self._panel.makeFirstResponder_(self._input)
            self._visible = True

    def _close(self) -> None:
        if self._panel is not None:
            self._panel.orderOut_(None)
        self._visible = False

    def _build(self) -> None:
        """Construye el NSPanel la primera vez. Solo hilo principal."""
        screen = AppKit.NSScreen.mainScreen()
        sf     = screen.frame()
        sw     = sf.size.width
        x      = (sw - self.WIDTH) / 2

        self._panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(x, self.Y_POS, self.WIDTH, self.HEIGHT),
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

        bg = _ChatBG.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        )
        self._panel.setContentView_(bg)

        self._ctrl = _ChatCtrl.alloc().initWithPanel_(self)

        HEADER_H = 46
        INPUT_H  = 50

        # ── Título ───────────────────────────────────────────────────────────
        lbl = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(16, self.HEIGHT - HEADER_H + 10, self.WIDTH - 56, 26)
        )
        lbl.setStringValue_("◉  Jarvis Chat")
        lbl.setBezeled_(False)
        lbl.setDrawsBackground_(False)
        lbl.setEditable_(False)
        lbl.setSelectable_(False)
        lbl.setFont_(AppKit.NSFont.systemFontOfSize_weight_(14, AppKit.NSFontWeightSemibold))
        lbl.setTextColor_(AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 0.71, 1.0, 0.9))
        bg.addSubview_(lbl)

        # ── Botón cerrar ─────────────────────────────────────────────────────
        btn_close = AppKit.NSButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(self.WIDTH - 38, self.HEIGHT - HEADER_H + 10, 24, 24)
        )
        btn_close.setTitle_("✕")
        btn_close.setBordered_(False)
        btn_close.setFont_(AppKit.NSFont.systemFontOfSize_(14))
        btn_close.setTarget_(self._ctrl)
        btn_close.setAction_("close:")
        bg.addSubview_(btn_close)

        # ── Separador header ─────────────────────────────────────────────────
        sep1 = _SepView.alloc().initWithFrame_(
            AppKit.NSMakeRect(12, self.HEIGHT - HEADER_H, self.WIDTH - 24, 1)
        )
        bg.addSubview_(sep1)

        # ── Separador sobre input ─────────────────────────────────────────────
        sep2 = _SepView.alloc().initWithFrame_(
            AppKit.NSMakeRect(12, INPUT_H, self.WIDTH - 24, 1)
        )
        bg.addSubview_(sep2)

        # ── Icono ◉ en input ─────────────────────────────────────────────────
        ico = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(14, 10, 26, 30)
        )
        ico.setStringValue_("◉")
        ico.setBezeled_(False)
        ico.setDrawsBackground_(False)
        ico.setEditable_(False)
        ico.setSelectable_(False)
        ico.setFont_(AppKit.NSFont.systemFontOfSize_(19))
        ico.setTextColor_(AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 0.71, 1.0, 0.8))
        bg.addSubview_(ico)

        # ── Campo de texto ───────────────────────────────────────────────────
        self._input = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(44, 10, self.WIDTH - 60, 30)
        )
        self._input.setPlaceholderString_("Escríbele a Jarvis… (Enter para enviar)")
        self._input.setBezeled_(False)
        self._input.setDrawsBackground_(False)
        self._input.setFont_(AppKit.NSFont.systemFontOfSize_weight_(15, AppKit.NSFontWeightLight))
        self._input.setTextColor_(AppKit.NSColor.whiteColor())
        self._input.setFocusRingType_(AppKit.NSFocusRingTypeNone)
        self._input.setDelegate_(self._ctrl)
        bg.addSubview_(self._input)

        # ── NSScrollView + NSTextView para historial ─────────────────────────
        scroll_y = INPUT_H + 8
        scroll_h = self.HEIGHT - HEADER_H - INPUT_H - 16

        scroll = AppKit.NSScrollView.alloc().initWithFrame_(
            AppKit.NSMakeRect(8, scroll_y, self.WIDTH - 16, scroll_h)
        )
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setBorderType_(AppKit.NSNoBorder)
        scroll.setDrawsBackground_(False)
        scroll.setAutohidesScrollers_(True)
        bg.addSubview_(scroll)

        tv_w = self.WIDTH - 16 - 4
        self._tv = AppKit.NSTextView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, tv_w, scroll_h)
        )
        self._tv.setEditable_(False)
        self._tv.setSelectable_(True)
        self._tv.setDrawsBackground_(False)
        self._tv.setVerticallyResizable_(True)
        self._tv.setHorizontallyResizable_(False)
        self._tv.setAutoresizingMask_(AppKit.NSViewWidthSizable)

        tc = self._tv.textContainer()
        tc.setWidthTracksTextView_(True)
        tc.setContainerSize_(AppKit.NSMakeSize(tv_w, 1e7))

        scroll.setDocumentView_(self._tv)

        # Mensaje de bienvenida
        self._append("jarvis", "Hola. ¿En qué te puedo ayudar?")

    # ── Lógica de envío ───────────────────────────────────────────────────────

    def _submit_text(self, text: str) -> None:
        """Hilo principal. Añade mensaje usuario y delega al daemon en background."""
        self._append("user", text)
        threading.Thread(
            target=self._daemon.submit_text,
            args=(text,),
            daemon=True,
        ).start()

    # ── Renderizado de mensajes ───────────────────────────────────────────────

    def _append(self, role: str, text: str) -> None:
        """Añade un mensaje al historial. Solo hilo principal."""
        if self._tv is None:
            return

        storage = self._tv.textStorage()
        storage.beginEditing()

        # Espaciado entre mensajes
        if storage.length() > 0:
            nl = AppKit.NSAttributedString.alloc().initWithString_attributes_(
                "\n\n",
                {AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(5)},
            )
            storage.appendAttributedString_(nl)

        if role == "user":
            lbl_color  = AppKit.NSColor.colorWithRed_green_blue_alpha_(0.55, 0.85, 1.0, 0.65)
            text_color = AppKit.NSColor.colorWithRed_green_blue_alpha_(0.85, 0.95, 1.0, 0.95)
            lbl_str    = "Tú"
            font_w     = AppKit.NSFontWeightRegular
        else:
            lbl_color  = AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 0.71, 1.0, 0.75)
            text_color = AppKit.NSColor.colorWithRed_green_blue_alpha_(0.88, 0.94, 1.0, 0.92)
            lbl_str    = "◈ Jarvis"
            font_w     = AppKit.NSFontWeightLight

        # Etiqueta de nombre
        lbl_astr = AppKit.NSAttributedString.alloc().initWithString_attributes_(
            lbl_str + "\n",
            {
                AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_weight_(
                    10, AppKit.NSFontWeightSemibold
                ),
                AppKit.NSForegroundColorAttributeName: lbl_color,
            },
        )
        storage.appendAttributedString_(lbl_astr)

        # Texto del mensaje
        msg_astr = AppKit.NSAttributedString.alloc().initWithString_attributes_(
            text,
            {
                AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_weight_(14, font_w),
                AppKit.NSForegroundColorAttributeName: text_color,
            },
        )
        storage.appendAttributedString_(msg_astr)

        storage.endEditing()

        # Auto-scroll al final
        self._tv.scrollRangeToVisible_(AppKit.NSMakeRange(storage.length(), 0))
