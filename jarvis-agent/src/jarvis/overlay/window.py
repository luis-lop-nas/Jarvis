"""
window.py

NSWindow transparente, click-through, siempre encima de todo.
Cubre la pantalla completa pero es invisible al usuario y a los clicks.
"""

from __future__ import annotations

import AppKit


class JarvisWindow:
    """Ventana transparente que flota sobre toda la interfaz."""

    def __init__(self, view: AppKit.NSView) -> None:
        screen = AppKit.NSScreen.mainScreen()
        frame  = screen.frame()

        self.win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless,   # sin bordes, sin barra de título
            AppKit.NSBackingStoreBuffered,
            False,
        )

        # Nivel 1000 → encima de apps normales, notificaciones, Spotlight
        self.win.setLevel_(1000)

        # Completamente transparente
        self.win.setOpaque_(False)
        self.win.setBackgroundColor_(AppKit.NSColor.clearColor())

        # Click-through total por defecto; view.py lo desactiva cerca del orb
        self.win.setIgnoresMouseEvents_(True)
        self.win.setAcceptsMouseMovedEvents_(True)

        # Visible en todos los Spaces sin animación al cambiar
        self.win.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
            AppKit.NSWindowCollectionBehaviorStationary       |
            AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )

        # No aparece en la lista de ventanas de Mission Control
        self.win.setSharingType_(AppKit.NSWindowSharingNone)

        self.win.setContentView_(view)
        self.win.makeKeyAndOrderFront_(None)

        # Pasar referencia de NSWindow a la view para el toggle de proximidad
        view.set_window(self.win)

    @property
    def screen_frame(self) -> AppKit.NSRect:
        return AppKit.NSScreen.mainScreen().frame()
