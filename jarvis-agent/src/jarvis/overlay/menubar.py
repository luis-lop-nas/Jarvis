"""
menubar.py

Icono de Jarvis en la barra de menú de macOS.
Usa AppKit directamente (no rumps) porque ya gestionamos nuestra propia NSApplication.

Menú:
  ◉ J  ──────────────
  Jarvis Desktop
  ────────────────────
  Silenciar / Activar
  Arrancar al inicio ✓
  ────────────────────
  Salir
"""

from __future__ import annotations

import AppKit
import objc


class _MenuDelegate(AppKit.NSObject):
    """Target de las acciones del menú."""

    def initWithDaemon_(self, daemon) -> "_MenuDelegate":
        self = objc.super(_MenuDelegate, self).init()
        if self is None:
            return None
        self._daemon = daemon
        self._muted  = False
        return self

    def toggleMute_(self, sender) -> None:
        self._muted = not self._muted
        if self._muted:
            self._daemon.stop()
            sender.setTitle_("Activar")
        else:
            self._daemon.start()
            sender.setTitle_("Silenciar")

    def toggleAutostart_(self, sender) -> None:
        try:
            from jarvis.autostart import install, uninstall, is_installed
            if is_installed():
                uninstall()
                sender.setTitle_("Arrancar al inicio")
            else:
                install()
                sender.setTitle_("Arrancar al inicio ✓")
        except Exception as e:
            print(f"⚠️ Autostart error: {e}")

    def quit_(self, sender) -> None:
        AppKit.NSApplication.sharedApplication().terminate_(None)


class MenuBar:
    """
    Añade un ítem a la barra de menú del sistema.
    Instanciar desde el hilo principal DESPUÉS de crear NSApplication.
    """

    TITLE = "◉ J"

    def __init__(self, daemon) -> None:
        self._daemon   = daemon
        self._delegate = _MenuDelegate.alloc().initWithDaemon_(daemon)

        bar        = AppKit.NSStatusBar.systemStatusBar()
        self._item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)

        # Botón visible en la barra
        btn = self._item.button()
        btn.setTitle_(self.TITLE)
        btn.setToolTip_("Jarvis Desktop — Ctrl+Space para hablar")

        # ── Menú desplegable ─────────────────────────────────────────────────
        menu = AppKit.NSMenu.alloc().init()

        # Cabecera informativa
        header = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Jarvis Desktop", "", ""
        )
        header.setEnabled_(False)
        menu.addItem_(header)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Silenciar / Activar
        self._mute_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Silenciar", "toggleMute:", ""
        )
        self._mute_item.setTarget_(self._delegate)
        menu.addItem_(self._mute_item)

        # Arrancar al inicio
        try:
            from jarvis.autostart import is_installed
            autostart_title = "Arrancar al inicio ✓" if is_installed() else "Arrancar al inicio"
        except Exception:
            autostart_title = "Arrancar al inicio"

        self._autostart_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            autostart_title, "toggleAutostart:", ""
        )
        self._autostart_item.setTarget_(self._delegate)
        menu.addItem_(self._autostart_item)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Salir
        quit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Salir", "quit:", "q"
        )
        quit_item.setTarget_(self._delegate)
        menu.addItem_(quit_item)

        self._item.setMenu_(menu)
