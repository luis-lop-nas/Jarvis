"""
annotation.py

Overlay de anotaciones visuales: dibuja flechas, círculos, rectángulos y texto
sobre la pantalla en una ventana NSWindow transparente fullscreen (nivel 1001,
sobre el overlay de Jarvis).

Click-through total (ignoresMouseEvents=True). Las anotaciones expiran
automáticamente tras duration_s segundos.

Solo disponible en modo desktop (PyObjC).

Uso:
    overlay = AnnotationOverlay()
    set_instance(overlay)
    overlay.add_annotation(type="circle", x=0.5, y=0.5, color="red", duration_s=10)
    overlay.add_annotation(type="arrow", x=0.2, y=0.3, x2=0.5, y2=0.5, color="yellow")
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

# Singleton module-level
_instance: Optional["AnnotationOverlay"] = None


def set_instance(overlay: "AnnotationOverlay") -> None:
    """Registra la instancia global del overlay de anotaciones."""
    global _instance
    _instance = overlay


def get_instance() -> Optional["AnnotationOverlay"]:
    """Retorna la instancia global, o None si no está disponible."""
    return _instance


# ── Paleta de colores RGBA (0-1) ──────────────────────────────────────────────

_COLORS: dict[str, tuple[float, float, float, float]] = {
    "red":    (1.0, 0.15, 0.15, 0.95),
    "yellow": (1.0, 0.90, 0.00, 0.95),
    "green":  (0.0, 1.00, 0.40, 0.95),
    "blue":   (0.2, 0.50, 1.00, 0.95),
    "white":  (1.0, 1.00, 1.00, 0.95),
    "orange": (1.0, 0.55, 0.00, 0.95),
    "purple": (0.7, 0.20, 1.00, 0.95),
}


@dataclass
class Annotation:
    type: str                    # "arrow" | "circle" | "rect" | "text"
    x: float                     # normalizado [0,1] desde top-left
    y: float                     # normalizado [0,1] desde top-left
    x2: float = 0.0              # para arrow/rect (extremo)
    y2: float = 0.0
    radius: float = 40.0         # para circle (píxeles lógicos)
    text: str = ""               # etiqueta o contenido de texto
    color: str = "red"
    thickness: float = 3.0
    expires_at: float = field(default_factory=lambda: time.monotonic() + 10.0)


# ── NSView con dibujo ─────────────────────────────────────────────────────────

try:
    import AppKit
    import objc

    class _AnnotationView(AppKit.NSView):
        """Vista transparente que dibuja las anotaciones activas."""

        def initWithFrame_(self, frame):
            self = objc.super(_AnnotationView, self).initWithFrame_(frame)
            if self is None:
                return None
            self._annotations: list[Annotation] = []
            self._lock = threading.Lock()
            # NSTimer 10 fps (anotaciones estáticas, no necesitan 30 fps)
            self._timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.1, self, "tick:", None, True,
            )
            return self

        def isOpaque(self):
            return False

        def tick_(self, _timer):
            now = time.monotonic()
            with self._lock:
                self._annotations = [a for a in self._annotations if a.expires_at > now]
            self.setNeedsDisplay_(True)

        def drawRect_(self, rect):
            try:
                self.__draw(rect)
            except Exception:
                pass

        def __draw(self, rect):
            # Fondo completamente transparente
            AppKit.NSColor.clearColor().set()
            AppKit.NSRectFill(self.bounds())

            with self._lock:
                anns = list(self._annotations)

            if not anns:
                return

            w = self.bounds().size.width
            h = self.bounds().size.height

            for ann in anns:
                rgba = _COLORS.get(ann.color, _COLORS["red"])
                r, g, b, a = rgba
                color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)
                color.set()

                # Coordenadas normalizadas → píxeles (macOS: y=0 abajo)
                px  = ann.x  * w
                py  = (1.0 - ann.y) * h   # flip Y: top-left → bottom-left origin
                px2 = ann.x2 * w
                py2 = (1.0 - ann.y2) * h

                if ann.type == "circle":
                    path = AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                        AppKit.NSMakeRect(
                            px - ann.radius, py - ann.radius,
                            ann.radius * 2.0, ann.radius * 2.0,
                        )
                    )
                    path.setLineWidth_(ann.thickness)
                    path.stroke()

                elif ann.type == "rect":
                    rw = (ann.x2 - ann.x) * w
                    rh = (ann.y2 - ann.y) * h
                    path = AppKit.NSBezierPath.bezierPathWithRect_(
                        AppKit.NSMakeRect(px, py - rh, rw, rh)
                    )
                    path.setLineWidth_(ann.thickness)
                    path.stroke()

                elif ann.type == "arrow":
                    self.__draw_arrow(px, py, px2, py2, ann.thickness, color)

                elif ann.type == "text":
                    attrs = {
                        AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(20),
                        AppKit.NSForegroundColorAttributeName: color,
                    }
                    AppKit.NSString.stringWithString_(ann.text).drawAtPoint_withAttributes_(
                        AppKit.NSMakePoint(px, py), attrs
                    )

                # Etiqueta pequeña bajo el símbolo (para tipos no-texto)
                if ann.text and ann.type != "text":
                    label_attrs = {
                        AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(14),
                        AppKit.NSForegroundColorAttributeName: color,
                    }
                    label_y = py - ann.radius - 20.0 if ann.type == "circle" else py - 20.0
                    AppKit.NSString.stringWithString_(ann.text).drawAtPoint_withAttributes_(
                        AppKit.NSMakePoint(px - len(ann.text) * 4, label_y), label_attrs
                    )

        def __draw_arrow(self, x1, y1, x2, y2, thickness, color):
            """Dibuja una flecha de (x1,y1) a (x2,y2) con punta de flecha."""
            path = AppKit.NSBezierPath.bezierPath()
            path.setLineWidth_(thickness)
            path.moveToPoint_(AppKit.NSMakePoint(x1, y1))
            path.lineToPoint_(AppKit.NSMakePoint(x2, y2))
            path.stroke()

            # Punta de flecha: dos segmentos a ±25° del extremo
            angle = math.atan2(y2 - y1, x2 - x1)
            head_len = 18.0
            for da in (+0.45, -0.45):
                hx = x2 - head_len * math.cos(angle + da)
                hy = y2 - head_len * math.sin(angle + da)
                tip = AppKit.NSBezierPath.bezierPath()
                tip.setLineWidth_(thickness)
                tip.moveToPoint_(AppKit.NSMakePoint(x2, y2))
                tip.lineToPoint_(AppKit.NSMakePoint(hx, hy))
                tip.stroke()

    # ── Overlay de anotaciones ────────────────────────────────────────────────

    class AnnotationOverlay:
        """
        Ventana NSWindow fullscreen transparente (nivel 1001) que muestra
        anotaciones visuales. Click-through total.

        Thread-safe: add_annotation() y clear() pueden llamarse desde cualquier thread.
        """

        def __init__(self) -> None:
            screen = AppKit.NSScreen.mainScreen().frame()
            win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                screen,
                AppKit.NSWindowStyleMaskBorderless,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            win.setLevel_(1001)                    # sobre Jarvis overlay (nivel 1000)
            win.setOpaque_(False)
            win.setBackgroundColor_(AppKit.NSColor.clearColor())
            win.setIgnoresMouseEvents_(True)        # click-through total
            win.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | AppKit.NSWindowCollectionBehaviorStationary
            )

            self._view = _AnnotationView.alloc().initWithFrame_(screen)
            win.setContentView_(self._view)
            win.orderFrontRegardless()
            self._window = win

        def add_annotation(self, **kwargs) -> None:
            """
            Thread-safe. Añade una anotación al overlay.

            Parámetros:
                type (str): "circle" | "arrow" | "rect" | "text"
                x, y (float): posición normalizada [0,1] desde top-left
                x2, y2 (float): extremo para arrow/rect
                radius (float): radio en px para circle (default 40)
                text (str): etiqueta o contenido de texto
                color (str): "red"|"yellow"|"green"|"blue"|"white"|"orange"|"purple"
                thickness (float): grosor de línea (default 3.0)
                duration_s (float): segundos de visibilidad (default 10)
            """
            duration_s = float(kwargs.pop("duration_s", 10.0))
            ann = Annotation(
                expires_at=time.monotonic() + duration_s,
                **kwargs,
            )
            with self._view._lock:
                self._view._annotations.append(ann)

        def clear(self) -> None:
            """Elimina todas las anotaciones activas."""
            with self._view._lock:
                self._view._annotations.clear()

        def hide(self) -> None:
            """Oculta el overlay."""
            self._window.orderOut_(None)

        def show(self) -> None:
            """Muestra el overlay."""
            self._window.orderFrontRegardless()

except ImportError:
    # Entorno sin AppKit (tests, servidor web, CLI)

    class AnnotationOverlay:  # type: ignore[no-redef]
        """Stub para entornos sin PyObjC."""

        def add_annotation(self, **kwargs) -> None:
            pass

        def clear(self) -> None:
            pass

        def hide(self) -> None:
            pass

        def show(self) -> None:
            pass
