"""
view.py

Plasma Energy Sphere — orb animado de Jarvis.

La esfera simula un cuerpo oscuro con borde luminoso y tendrils de plasma
(arcos eléctricos) que emergen de la superficie y pulsan según el estado.

Estados:
  idle      → azul profundo,    10 tendrils, lentos
  listening → verde eléctrico,  14 tendrils, activos
  thinking  → naranja,          12 tendrils, oscilantes
  acting    → azul brillante,   20 tendrils + audio-reactivos
"""

from __future__ import annotations

import math
import objc
import AppKit


# ── Paleta por estado ─────────────────────────────────────────────────────────

_COLORS = {
    "idle":      (0.15, 0.45, 1.00),
    "listening": (0.00, 0.92, 0.45),
    "thinking":  (1.00, 0.55, 0.05),
    "acting":    (0.25, 0.65, 1.00),
}

# Número de tendrils (arcos eléctricos) por estado
_N_TENDRILS = {
    "idle":      10,
    "listening": 14,
    "thinking":  12,
    "acting":    20,
}

# Velocidad de fase angular (rad/frame a 30fps × 4 → rad unitario)
_ROT_SPEED = {
    "idle":      0.007,
    "listening": 0.018,
    "thinking":  0.022,
    "acting":    0.030,
}

ORB_RADIUS  = 38.0   # radio base de la esfera en px
_HIT_RADIUS = 62.0   # zona interactiva (drag + click-through toggle)


# ── Vista principal ───────────────────────────────────────────────────────────

class JarvisView(AppKit.NSView):
    """Renderiza el plasma orb a 30 fps."""

    # ------------------------------------------------------------------ init

    def initWithFrame_(self, frame):
        self = objc.super(JarvisView, self).initWithFrame_(frame)
        if self is None:
            return None

        self._orb_x: float = 80.0
        self._orb_y: float = 80.0
        self._state: str   = "idle"
        self._phase: float = 0.0          # fase global de animación
        self._audio_level: float = 0.0    # 0-1, nivel de audio (VU meter)
        self._particles = None

        # Drag
        self._dragging         = False
        self._drag_mouse_start = (0.0, 0.0)
        self._drag_orb_start   = (0.0, 0.0)

        self._window = None   # referencia al NSWindow para click-through

        # Timer 30 fps
        self._timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1 / 30.0, self, "tick:", None, True
        )
        return self

    # ----------------------------------------------------------------- flags

    def isOpaque(self):          return False
    def acceptsFirstResponder(self): return True

    # ──────────────────────────────────────────── hit-test y drag del orb ──

    def hitTest_(self, point):
        dx = point.x - self._orb_x
        dy = point.y - self._orb_y
        return self if dx * dx + dy * dy <= _HIT_RADIUS ** 2 else None

    def mouseDown_(self, event):
        loc = event.locationInWindow()
        self._dragging         = True
        self._drag_mouse_start = (loc.x, loc.y)
        self._drag_orb_start   = (self._orb_x, self._orb_y)

    def mouseDragged_(self, event):
        if not self._dragging:
            return
        loc = event.locationInWindow()
        dx  = loc.x - self._drag_mouse_start[0]
        dy  = loc.y - self._drag_mouse_start[1]
        f   = self.frame()
        m   = _HIT_RADIUS
        self._orb_x = max(m, min(f.size.width  - m, self._drag_orb_start[0] + dx))
        self._orb_y = max(m, min(f.size.height - m, self._drag_orb_start[1] + dy))

    def mouseUp_(self, event):
        self._dragging = False

    # ─────────────────────────────────────────────────────── tick / draw ──

    def tick_(self, timer):
        self._phase += _ROT_SPEED.get(self._state, 0.007) * 4.0
        if self._particles is not None:
            self._particles.update(1 / 30.0)
        self.setNeedsDisplay_(True)

        # Toggle click-through según proximidad del cursor
        if self._window is not None:
            loc  = AppKit.NSEvent.mouseLocation()
            dx   = loc.x - self._orb_x
            dy   = loc.y - self._orb_y
            near = dx * dx + dy * dy <= (_HIT_RADIUS + 8.0) ** 2
            self._window.setIgnoresMouseEvents_(not near)

    def drawRect_(self, dirty_rect):
        r, g, b = _COLORS.get(self._state, _COLORS["idle"])
        ox, oy  = self._orb_x, self._orb_y
        ph      = self._phase
        al      = self._audio_level

        # Radio animado (audio-reactivo al hablar)
        orb_r = ORB_RADIUS + (10.0 * al if self._state == "acting" else 0.0)

        # Orden de dibujo:
        # 1. Halo exterior difuso
        # 2. Tendrils (debajo del cuerpo → la esfera tapa los segmentos interiores)
        # 3. Cuerpo de la esfera
        # 4. Partículas fly_to

        self._draw_glow(ox, oy, r, g, b, orb_r, ph)
        self._draw_tendrils(ox, oy, r, g, b, orb_r, ph, al)
        self._draw_sphere(ox, oy, r, g, b, orb_r, ph)

        if self._particles is not None:
            self._particles.draw()

    # ──────────────────────────────────────────── halo exterior difuso ──

    def _draw_glow(self, ox, oy, r, g, b, orb_r, ph):
        """Tres anillos concéntricos de glow exterior."""
        pulse = 0.75 + 0.25 * math.sin(ph * 0.7)
        for dist, base_a in (
            (orb_r + 52, 0.022),
            (orb_r + 30, 0.052),
            (orb_r + 13, 0.088),
        ):
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, base_a * pulse).set()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                AppKit.NSMakeRect(ox - dist, oy - dist, dist * 2, dist * 2)
            ).fill()

    # ────────────────────────────────────── tendrils (arcos eléctricos) ──

    def _draw_tendrils(self, ox, oy, r, g, b, orb_r, ph, al):
        """
        Dibuja n tendrils que emergen de la superficie de la esfera.
        Cada tendril tiene 6 segmentos con desplazamiento sinusoidal multi-frecuencia.
        Se dibujan ANTES de la esfera para que esta tape los segmentos internos.
        """
        n        = _N_TENDRILS.get(self._state, 10)
        n_seg    = 6
        # Boost de longitud cuando Jarvis habla
        audio_boost = al * 0.9 if self._state == "acting" else 0.0

        for t in range(n):
            # Ángulo base del tendril (distribución uniforme + lenta rotación)
            base_angle = (2 * math.pi * t / n) + ph * 0.15
            t_off = t * 2.39996   # golden ratio para separar fases entre tendrils

            # Longitud del tendril (ruido multi-frecuencia)
            len_noise = (
                0.50 * math.sin(ph * 1.1 + t_off)
                + 0.30 * math.sin(ph * 2.3 + t_off * 1.7)
                + 0.20 * math.sin(ph * 3.7 + t_off * 0.9)
            )
            length = orb_r * (0.55 + 0.35 * len_noise + audio_boost)
            length = max(orb_r * 0.08, length)

            # Construir los puntos del tendril
            pts = []
            for s in range(n_seg + 1):
                frac = s / n_seg
                rad  = orb_r + frac * length
                # Desplazamiento perpendicular sinusoidal (da apariencia jagged / orgánica)
                perp = (
                    0.30 * math.sin(ph * 2.1 + frac * math.pi * 3 + t_off)
                    + 0.15 * math.sin(ph * 4.3 + frac * math.pi * 5 + t_off * 1.3)
                    + 0.08 * math.sin(ph * 7.1 + frac * math.pi * 7 + t_off * 0.7)
                )
                angle = base_angle + perp * (1.0 - frac * 0.5)
                pts.append((ox + rad * math.cos(angle), oy + rad * math.sin(angle)))

            base_a = 0.45 + 0.30 * abs(len_noise)

            # Halo exterior difuso
            p_halo = AppKit.NSBezierPath.bezierPath()
            p_halo.moveToPoint_(AppKit.NSMakePoint(*pts[0]))
            for px, py in pts[1:]:
                p_halo.lineToPoint_(AppKit.NSMakePoint(px, py))
            p_halo.setLineWidth_(3.2)
            p_halo.setLineCapStyle_(AppKit.NSRoundLineCapStyle)
            p_halo.setLineJoinStyle_(AppKit.NSRoundLineJoinStyle)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, base_a * 0.28).set()
            p_halo.stroke()

            # Núcleo brillante
            p_core = AppKit.NSBezierPath.bezierPath()
            p_core.moveToPoint_(AppKit.NSMakePoint(*pts[0]))
            for px, py in pts[1:]:
                p_core.lineToPoint_(AppKit.NSMakePoint(px, py))
            p_core.setLineWidth_(0.9)
            p_core.setLineCapStyle_(AppKit.NSRoundLineCapStyle)
            p_core.setLineJoinStyle_(AppKit.NSRoundLineJoinStyle)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, base_a * 0.88).set()
            p_core.stroke()

            # Brillo en la punta
            tip_x, tip_y = pts[-1]
            tip_r = 2.0 + 1.5 * abs(len_noise)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, base_a * 0.60).set()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                AppKit.NSMakeRect(tip_x - tip_r, tip_y - tip_r, tip_r * 2, tip_r * 2)
            ).fill()

    # ──────────────────────────────────────── cuerpo de la esfera ──

    def _draw_sphere(self, ox, oy, r, g, b, orb_r, ph):
        """
        Simula una esfera oscura con borde luminoso usando 22 círculos concéntricos.
        Se dibuja de fuera a dentro: el mayor es brillante (borde), el menor es negro (centro).
        Cada círculo más pequeño tapa el centro del anterior → gradiente radial.
        """
        N = 22
        for i in range(N - 1, -1, -1):
            frac   = i / (N - 1)          # 0 = centro, 1 = borde
            ring_r = orb_r * frac
            bright = frac ** 0.6          # borde brillante, centro oscuro

            cr = r * bright + 0.02 * (1.0 - frac)
            cg = g * bright + 0.02 * (1.0 - frac)
            cb = b * bright + 0.08 * (1.0 - frac)  # tinte azul oscuro en el centro

            # Pulso sutil solo en el anillo exterior (frac > 0.88)
            alpha = 1.0
            if frac > 0.88:
                alpha = 0.85 + 0.15 * math.sin(ph * 1.3)

            AppKit.NSColor.colorWithRed_green_blue_alpha_(cr, cg, cb, alpha).set()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                AppKit.NSMakeRect(ox - ring_r, oy - ring_r, ring_r * 2, ring_r * 2)
            ).fill()

        # Destello especular (esquina superior-izquierda)
        sx = ox - orb_r * 0.30
        sy = oy + orb_r * 0.32
        sr = orb_r * 0.20
        sa = 0.28 + 0.08 * math.sin(ph * 0.9)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, sa).set()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(
            AppKit.NSMakeRect(sx - sr, sy - sr, sr * 2, sr * 2)
        ).fill()

    # ────────────────────────────────────────────────────── API pública ──

    def attach_particles(self, particles) -> None:
        self._particles = particles

    def set_window(self, win) -> None:
        self._window = win

    def set_state(self, state: str) -> None:
        self._state = state

    def set_position(self, x: float, y: float) -> None:
        self._orb_x = x
        self._orb_y = y

    def set_audio_level(self, level: float) -> None:
        self._audio_level = max(0.0, min(1.0, level))

    @property
    def orb_position(self) -> tuple[float, float]:
        return self._orb_x, self._orb_y
