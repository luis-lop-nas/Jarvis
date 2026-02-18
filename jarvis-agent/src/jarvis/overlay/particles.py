"""
particles.py

Sistema de partículas para la animación fly_to.
Las partículas nacen en el orb y vuelan en arco bezier hasta el destino.

Integración con JarvisView:
  view.attach_particles(ParticleSystem(view))

Entonces:
  - view.tick_()      llama a particles.update(dt)
  - view.drawRect_()  llama a particles.draw()
"""

from __future__ import annotations

import math
import random
import threading
from typing import Callable, List, Optional

import AppKit


# ── Partícula individual ────────────────────────────────────────────────────────

class _Particle:
    """Una partícula que sigue una curva bezier cuadrática de A → B."""

    __slots__ = (
        "x0", "y0", "x1", "y1",
        "cx", "cy",          # control point de la curva
        "x", "y",            # posición actual
        "t",                 # progreso 0→1
        "delay",             # tiempo antes de arrancar
        "speed",             # unidades de t por segundo
        "size",
        "alpha",
        "alive",
    )

    def __init__(
        self,
        x0: float, y0: float,
        x1: float, y1: float,
        wobble: float,   # desviación perpendicular al eje de vuelo
        delay: float,
        speed: float,
    ) -> None:
        self.x0, self.y0 = x0, y0
        self.x1, self.y1 = x1, y1
        self.x,  self.y  = x0, y0

        # Vector perpendicular al eje de vuelo → punto de control
        dx, dy = x1 - x0, y1 - y0
        dist   = math.sqrt(dx * dx + dy * dy) or 1.0
        px, py = -dy / dist, dx / dist           # perpendicular unitario
        self.cx = (x0 + x1) / 2 + px * wobble
        self.cy = (y0 + y1) / 2 + py * wobble

        self.delay = delay
        self.speed = speed
        self.t     = 0.0
        self.size  = random.uniform(2.0, 4.5)
        self.alpha = 0.0
        self.alive = True

    def update(self, dt: float) -> None:
        if self.delay > 0:
            self.delay -= dt
            return

        self.t += self.speed * dt
        if self.t >= 1.0:
            self.t     = 1.0
            self.alive = False

        t, u = self.t, 1.0 - self.t

        # Bezier cuadrática: B(t) = u²·P0 + 2·u·t·C + t²·P1
        self.x = u*u*self.x0 + 2*u*t*self.cx + t*t*self.x1
        self.y = u*u*self.y0 + 2*u*t*self.cy + t*t*self.y1

        # Fade in/out suave
        if t < 0.15:
            self.alpha = t / 0.15
        elif t > 0.72:
            self.alpha = (1.0 - t) / 0.28
        else:
            self.alpha = 1.0

    def draw(self) -> None:
        if not self.alive or self.alpha <= 0:
            return

        # Halo
        AppKit.NSColor.colorWithRed_green_blue_alpha_(
            0.0, 0.71, 1.0, self.alpha * 0.35
        ).set()
        r = self.size * 1.6
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(
            AppKit.NSMakeRect(self.x - r, self.y - r, r * 2, r * 2)
        ).fill()

        # Cuerpo
        AppKit.NSColor.colorWithRed_green_blue_alpha_(
            0.0, 0.71, 1.0, self.alpha * 0.85
        ).set()
        s = self.size
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(
            AppKit.NSMakeRect(self.x - s, self.y - s, s * 2, s * 2)
        ).fill()

        # Núcleo blanco
        AppKit.NSColor.colorWithRed_green_blue_alpha_(
            1.0, 1.0, 1.0, self.alpha * 0.7
        ).set()
        c = s * 0.45
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(
            AppKit.NSMakeRect(self.x - c, self.y - c, c * 2, c * 2)
        ).fill()


# ── Oleada de partículas (un fly_to = un _Flight) ──────────────────────────────

class _Flight:
    """30 partículas escalonadas desde el orb hasta el destino."""

    COUNT = 30    # partículas totales
    EMIT_SPAN = 0.35  # segundos en los que se emiten todas las partículas

    def __init__(
        self,
        x0: float, y0: float,
        x1: float, y1: float,
        callback: Optional[Callable],
    ) -> None:
        self.x1, self.y1   = x1, y1
        self.callback      = callback
        self.elapsed       = 0.0
        self.done          = False
        self._cb_fired     = False

        # Duración total del vuelo (s)
        dx, dy  = x1 - x0, y1 - y0
        dist    = math.sqrt(dx * dx + dy * dy)
        # ~0.6s para 400 px, escala con distancia pero acotado
        self._duration = max(0.5, min(1.2, dist / 650))

        speed_base = 1.0 / self._duration

        self.particles: List[_Particle] = []
        for i in range(self.COUNT):
            delay  = (i / self.COUNT) * self.EMIT_SPAN
            wobble = random.uniform(-50, 50)
            speed  = speed_base * random.uniform(0.85, 1.15)
            self.particles.append(_Particle(x0, y0, x1, y1, wobble, delay, speed))

    def update(self, dt: float) -> None:
        self.elapsed += dt

        # Callback cuando las primeras partículas llegan (~65%)
        if not self._cb_fired and self.elapsed >= self._duration * 0.65:
            self._cb_fired = True
            if self.callback:
                threading.Thread(target=self.callback, daemon=True).start()

        for p in self.particles:
            p.update(dt)

        # Flight terminado cuando todas las partículas murieron
        if all(not p.alive for p in self.particles):
            self.done = True

    def draw(self) -> None:
        for p in self.particles:
            p.draw()


# ── Sistema de partículas ──────────────────────────────────────────────────────

class ParticleSystem:
    """
    Gestiona múltiples vuelos simultáneos.
    Se integra en el ciclo de render de JarvisView.
    """

    def __init__(self, view) -> None:
        self._view    = view
        self._flights: List[_Flight] = []

    # ── API pública (thread-safe vía bridge — siempre hilo principal) ─────────

    def fly_to(
        self,
        tx: float,
        ty: float,
        callback: Optional[Callable] = None,
    ) -> None:
        """Lanzar partículas desde el orb hasta (tx, ty)."""
        ox, oy = self._view.orb_position
        self._flights.append(_Flight(ox, oy, tx, ty, callback))

    # ── Ciclo de render (llamar desde el hilo principal) ─────────────────────

    def update(self, dt: float) -> None:
        """Avanzar física de partículas. Llamar desde view.tick_()."""
        for f in self._flights[:]:
            f.update(dt)
            if f.done:
                self._flights.remove(f)

    def draw(self) -> None:
        """Dibujar partículas. Llamar desde view.drawRect_() DESPUÉS del orb."""
        for f in self._flights:
            f.draw()

    @property
    def active(self) -> bool:
        return bool(self._flights)
