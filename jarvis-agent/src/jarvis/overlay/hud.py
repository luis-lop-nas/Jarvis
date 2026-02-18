"""
hud.py

Panel HUD flotante estilo Iron Man que muestra el texto de respuesta de Jarvis.

Aparece centrado en la parte inferior de la pantalla cuando Jarvis responde
y desaparece automáticamente tras FADE_DELAY segundos de silencio.

Características:
  - Fondo oscuro semitransparente con borde azul eléctrico
  - Texto blanco con fuente ligera, hasta 6 líneas con wrapping
  - Click-through (no captura eventos de ratón)
  - Visible en todos los Spaces (no desaparece al cambiar espacio)
  - Fade out automático 3.5s después de terminar el TTS
  - Thread-safe — todas las APIs públicas se pueden llamar desde cualquier thread
"""

from __future__ import annotations

from typing import Optional

import AppKit
import objc


# ── Vista con fondo oscuro y esquinas redondeadas ─────────────────────────────

class _HUDBackground(AppKit.NSView):
    def drawRect_(self, rect: AppKit.NSRect) -> None:
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), 12.0, 12.0
        )
        # Fondo oscuro casi opaco
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.03, 0.03, 0.09, 0.91).set()
        path.fill()
        # Borde azul eléctrico tenue
        path.setLineWidth_(1.5)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 0.71, 1.0, 0.50).set()
        path.stroke()

    def isOpaque(self) -> bool:
        return False


# ── Target de NSTimer ─────────────────────────────────────────────────────────

class _HUDTimerTarget(AppKit.NSObject):
    """Target del timer de fade-out. Recibe el HUD como userInfo."""
    def fire_(self, timer: AppKit.NSTimer) -> None:
        hud = timer.userInfo()
        if hud is not None:
            hud._close()


# ── HUD principal ─────────────────────────────────────────────────────────────

class JarvisHUD:
    """
    Panel flotante que muestra el texto de respuesta de Jarvis.

    Uso (desde cualquier thread):
        hud.show_text("Entendido, abro Safari ahora mismo.")
        # ... cuando TTS termina ...
        hud.schedule_hide()   # desaparece tras FADE_DELAY segundos
        # o inmediatamente:
        hud.hide()
    """

    WIDTH      = 600       # px — ancho fijo del panel
    PADDING_X  = 20        # px — margen horizontal interior
    PADDING_Y  = 14        # px — margen vertical interior
    Y_OFFSET   = 120.0     # px — altura desde la base de la pantalla (encima del Dock)
    FADE_DELAY = 3.5       # segundos hasta desaparecer tras el TTS

    def __init__(self, bridge) -> None:
        self._bridge = bridge
        self._window: Optional[AppKit.NSPanel]    = None
        self._bg:     Optional[_HUDBackground]    = None
        self._icon:   Optional[AppKit.NSTextField] = None
        self._label:  Optional[AppKit.NSTextField] = None
        self._timer:  Optional[AppKit.NSTimer]     = None

    # ── API pública (thread-safe) ─────────────────────────────────────────────

    def show_text(self, text: str) -> None:
        """Muestra texto en el HUD. Thread-safe."""
        self._bridge.run_on_main_thread(lambda: self._show(text))

    def schedule_hide(self) -> None:
        """Oculta el HUD tras FADE_DELAY segundos. Thread-safe."""
        self._bridge.run_on_main_thread(self._start_timer)

    def hide(self) -> None:
        """Oculta el HUD inmediatamente. Thread-safe."""
        self._bridge.run_on_main_thread(self._close)

    # ── Hilo principal ────────────────────────────────────────────────────────

    def _show(self, text: str) -> None:
        """Crea o actualiza el panel. Hilo principal."""
        self._cancel_timer()
        if self._window is None:
            self._build_window()
        self._set_text(text)
        self._window.orderFront_(None)

    def _build_window(self) -> None:
        """Crea el NSPanel la primera vez. Hilo principal."""
        screen = AppKit.NSScreen.mainScreen()
        sf = screen.frame()
        sw = sf.size.width
        h = self._calc_height("A")   # altura inicial mínima

        x = (sw - self.WIDTH) / 2
        frame = AppKit.NSMakeRect(x, self.Y_OFFSET, self.WIDTH, h)

        self._window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        # Nivel muy alto — encima del overlay y de la barra de menú
        self._window.setLevel_(AppKit.NSFloatingWindowLevel + 5)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._window.setHasShadow_(True)
        # Click-through: el HUD es solo visual
        self._window.setIgnoresMouseEvents_(True)
        # Visible en todos los Spaces y estático (no se mueve al cambiar Space)
        self._window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )

        # Fondo con esquinas redondeadas
        self._bg = _HUDBackground.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, self.WIDTH, h)
        )
        self._window.setContentView_(self._bg)

        # Icono ◈ identificador de Jarvis
        self._icon = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(self.PADDING_X, h - 26, 16, 18)
        )
        self._icon.setStringValue_("◈")
        self._icon.setBezeled_(False)
        self._icon.setDrawsBackground_(False)
        self._icon.setEditable_(False)
        self._icon.setSelectable_(False)
        self._icon.setFont_(AppKit.NSFont.systemFontOfSize_(10))
        self._icon.setTextColor_(
            AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 0.71, 1.0, 0.65)
        )
        self._bg.addSubview_(self._icon)

        # Label de texto principal
        lx = self.PADDING_X + 22
        lw = self.WIDTH - lx - self.PADDING_X
        lh = max(22, h - self.PADDING_Y * 2)
        self._label = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(lx, self.PADDING_Y, lw, lh)
        )
        self._label.setStringValue_("")
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setFont_(
            AppKit.NSFont.systemFontOfSize_weight_(15, AppKit.NSFontWeightLight)
        )
        self._label.setTextColor_(
            AppKit.NSColor.colorWithRed_green_blue_alpha_(0.88, 0.94, 1.0, 0.95)
        )
        self._label.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        self._label.setMaximumNumberOfLines_(6)
        self._bg.addSubview_(self._label)

    def _set_text(self, text: str) -> None:
        """Actualiza el texto y redimensiona el panel. Hilo principal."""
        if self._label is None:
            return
        self._label.setStringValue_(text)

        h = self._calc_height(text)
        screen = AppKit.NSScreen.mainScreen()
        sf = screen.frame()
        sw = sf.size.width
        x = (sw - self.WIDTH) / 2

        # Redimensionar ventana y subviews
        self._window.setFrame_display_(
            AppKit.NSMakeRect(x, self.Y_OFFSET, self.WIDTH, h), False
        )
        self._bg.setFrame_(AppKit.NSMakeRect(0, 0, self.WIDTH, h))
        self._bg.setNeedsDisplay_(True)
        self._icon.setFrame_(AppKit.NSMakeRect(self.PADDING_X, h - 26, 16, 18))
        lx = self.PADDING_X + 22
        lw = self.WIDTH - lx - self.PADDING_X
        self._label.setFrame_(
            AppKit.NSMakeRect(lx, self.PADDING_Y, lw, max(22, h - self.PADDING_Y * 2))
        )

    def _calc_height(self, text: str) -> float:
        """Altura aproximada del panel para el texto dado."""
        label_width = self.WIDTH - self.PADDING_X * 2 - 24
        chars_per_line = label_width / 9.2          # ~9.2px por carácter a 15pt Light
        lines = max(1.0, len(text) / max(1.0, chars_per_line))
        return max(52.0, round(lines + 0.8) * 22 + self.PADDING_Y * 2)

    def _start_timer(self) -> None:
        """Arranca timer de fade-out. Hilo principal."""
        self._cancel_timer()
        self._timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            self.FADE_DELAY,
            _HUDTimerTarget.new(),
            "fire:",
            self,    # userInfo → recuperado en fire_
            False,
        )

    def _cancel_timer(self) -> None:
        """Cancela el timer pendiente. Hilo principal."""
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def _close(self) -> None:
        """Oculta el panel. Hilo principal."""
        self._cancel_timer()
        if self._window is not None:
            self._window.orderOut_(None)
