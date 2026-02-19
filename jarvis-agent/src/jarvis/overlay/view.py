"""
view.py

Plasma Energy Sphere — orb animado de Jarvis.

Esfera oscura rodeada de plasma espeso tipo corona/bola de plasma.
Tendrils gruesos multicapa (glow exterior → núcleo blanco-azul brillante).

Estados:
  idle      → violeta-azul profundo,  8 tendrils, lentos
  listening → verde eléctrico,       12 tendrils, activos
  thinking  → naranja,               10 tendrils, oscilantes
  acting    → azul brillante,        16 tendrils + audio-reactivos
"""

from __future__ import annotations

import math
import objc
import AppKit


# ── Paleta por estado ─────────────────────────────────────────────────────────

_COLORS = {
    "idle":      (0.25, 0.05, 0.92),   # violeta-azul profundo (como la imagen)
    "listening": (0.00, 0.88, 0.42),   # verde eléctrico
    "thinking":  (0.95, 0.48, 0.05),   # naranja cálido
    "acting":    (0.18, 0.42, 1.00),   # azul brillante
}

# Número de tendrils por estado
_N_TENDRILS = {
    "idle":       8,
    "listening": 12,
    "thinking":  10,
    "acting":    16,
}

# Velocidad de fase angular
_ROT_SPEED = {
    "idle":      0.006,
    "listening": 0.018,
    "thinking":  0.020,
    "acting":    0.028,
}

ORB_RADIUS  = 38.0   # radio base de la esfera en px
_HIT_RADIUS = 62.0   # zona interactiva


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
        self._phase: float = 0.0
        self._audio_level: float = 0.0
        self._particles = None

        # Drag
        self._dragging         = False
        self._did_drag         = False
        self._drag_mouse_start = (0.0, 0.0)
        self._drag_orb_start   = (0.0, 0.0)

        self._window = None
        self._orb_click_handler = None

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
        self._did_drag         = False
        self._drag_mouse_start = (loc.x, loc.y)
        self._drag_orb_start   = (self._orb_x, self._orb_y)

    def mouseDragged_(self, event):
        if not self._dragging:
            return
        loc = event.locationInWindow()
        dx  = loc.x - self._drag_mouse_start[0]
        dy  = loc.y - self._drag_mouse_start[1]
        if dx * dx + dy * dy > 25:
            self._did_drag = True
        f = self.frame()
        m = _HIT_RADIUS
        self._orb_x = max(m, min(f.size.width  - m, self._drag_orb_start[0] + dx))
        self._orb_y = max(m, min(f.size.height - m, self._drag_orb_start[1] + dy))

    def mouseUp_(self, event):
        was_click      = self._dragging and not self._did_drag
        self._dragging = False
        self._did_drag = False
        if was_click and self._orb_click_handler is not None:
            self._orb_click_handler(self._orb_x, self._orb_y, self.frame().size.height)

    # ─────────────────────────────────────────────────────── tick / draw ──

    def tick_(self, timer):
        self._phase += _ROT_SPEED.get(self._state, 0.006) * 4.0
        if self._particles is not None:
            self._particles.update(1 / 30.0)
        self.setNeedsDisplay_(True)

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

        # Radio ligeramente expandido al hablar
        orb_r = ORB_RADIUS + (8.0 * al if self._state == "acting" else 0.0)

        # Orden:  glow → tendrils → esfera (tapa raíces) → partículas
        self._draw_glow(ox, oy, r, g, b, orb_r, ph)
        self._draw_tendrils(ox, oy, r, g, b, orb_r, ph, al)
        self._draw_sphere(ox, oy, r, g, b, orb_r, ph)

        if self._particles is not None:
            self._particles.draw()

    # ──────────────────────────────────────── halo atmosférico exterior ──

    def _draw_glow(self, ox, oy, r, g, b, orb_r, ph):
        """
        Halo difuso multicapa, estilo corona de plasma.
        Capas anchas y poco densas + capas internas más intensas.
        """
        pulse = 0.80 + 0.20 * math.sin(ph * 0.55)

        layers = (
            # (distancia desde centro, alpha base)
            (orb_r + 110, 0.005),
            (orb_r +  80, 0.010),
            (orb_r +  58, 0.020),
            (orb_r +  38, 0.038),
            (orb_r +  22, 0.060),
            (orb_r +  10, 0.095),
        )
        for dist, base_a in layers:
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, base_a * pulse).set()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                AppKit.NSMakeRect(ox - dist, oy - dist, dist * 2, dist * 2)
            ).fill()

    # ──────────────────────────────────── tendrils de plasma espeso ──

    def _draw_tendrils(self, ox, oy, r, g, b, orb_r, ph, al):
        """
        Tendrils gruesos estilo bola de plasma / corona solar.
        Cada tendril se dibuja en 5 capas de anchura decreciente:
          1. Glow exterior muy ancho  (difuso, muy transparente)
          2. Glow medio              (semi-difuso)
          3. Cuerpo del tendril      (opaco moderado)
          4. Núcleo brillante        (fino, bien visible)
          5. Núcleo blanco-azulado   (filamento central, máx brillo)
        Además se dibujan blobs en nodos clave para apariencia "blob de plasma".
        """
        n           = _N_TENDRILS.get(self._state, 8)
        n_seg       = 9        # más segmentos → más orgánico
        audio_boost = al * 1.1 if self._state == "acting" else 0.0

        # Color más blanco/brillante para el núcleo
        wr = min(1.0, r * 0.6 + 0.55)
        wg = min(1.0, g * 0.5 + 0.40)
        wb = min(1.0, b * 0.3 + 0.80)

        def _build_path(pts):
            p = AppKit.NSBezierPath.bezierPath()
            p.moveToPoint_(AppKit.NSMakePoint(*pts[0]))
            for px, py in pts[1:]:
                p.lineToPoint_(AppKit.NSMakePoint(px, py))
            p.setLineCapStyle_(AppKit.NSRoundLineCapStyle)
            p.setLineJoinStyle_(AppKit.NSRoundLineJoinStyle)
            return p

        for t in range(n):
            # Ángulo base + rotación lenta
            base_angle = (2 * math.pi * t / n) + ph * 0.10
            t_off = t * 2.39996  # golden ratio

            # Longitud del tendril con ruido multi-frecuencia
            len_noise = (
                0.48 * math.sin(ph * 0.9  + t_off)
                + 0.32 * math.sin(ph * 2.3  + t_off * 1.7)
                + 0.20 * math.sin(ph * 4.1  + t_off * 0.8)
            )
            length = orb_r * (0.85 + 0.75 * len_noise + audio_boost)
            length = max(orb_r * 0.12, length)

            # Construir puntos con desplazamiento perpendicular (apariencia orgánica)
            pts = []
            for s in range(n_seg + 1):
                frac = s / n_seg
                rad  = orb_r + frac * length
                perp = (
                    0.45 * math.sin(ph * 1.7 + frac * math.pi * 2.2 + t_off)
                    + 0.25 * math.sin(ph * 3.5 + frac * math.pi * 4.0 + t_off * 1.3)
                    + 0.12 * math.sin(ph * 6.2 + frac * math.pi * 6.5 + t_off * 0.6)
                )
                angle = base_angle + perp * (1.3 - frac * 0.9)
                pts.append((ox + rad * math.cos(angle), oy + rad * math.sin(angle)))

            bright = 0.45 + 0.55 * abs(len_noise)

            # ── Capa 1: glow exterior muy ancho ──────────────────────────────
            p = _build_path(pts)
            p.setLineWidth_(22.0)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, 0.018 * bright).set()
            p.stroke()

            # ── Capa 2: glow medio ────────────────────────────────────────────
            p = _build_path(pts)
            p.setLineWidth_(11.0)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, 0.055 * bright).set()
            p.stroke()

            # ── Capa 3: cuerpo del tendril ────────────────────────────────────
            p = _build_path(pts)
            p.setLineWidth_(4.5)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, 0.18 * bright).set()
            p.stroke()

            # ── Capa 4: núcleo brillante ─────────────────────────────────────
            p = _build_path(pts)
            p.setLineWidth_(1.8)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, 0.55 * bright).set()
            p.stroke()

            # ── Capa 5: filamento central blanco-azulado ──────────────────────
            p = _build_path(pts)
            p.setLineWidth_(0.7)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(wr, wg, wb, 0.78 * bright).set()
            p.stroke()

            # ── Blobs en nodos: pequeñas manchas de plasma ───────────────────
            for s_idx in range(n_seg // 3, n_seg + 1, n_seg // 3):
                bx, by = pts[s_idx]
                # Radio del blob oscila con el tiempo
                blob_r = 2.5 + 3.5 * abs(math.sin(ph * 1.1 + t_off + s_idx * 0.8))

                # Halo del blob
                AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, 0.06 * bright).set()
                AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                    AppKit.NSMakeRect(bx - blob_r * 2.5, by - blob_r * 2.5,
                                      blob_r * 5.0, blob_r * 5.0)
                ).fill()

                # Núcleo del blob
                AppKit.NSColor.colorWithRed_green_blue_alpha_(wr, wg, wb, 0.28 * bright).set()
                AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                    AppKit.NSMakeRect(bx - blob_r, by - blob_r, blob_r * 2, blob_r * 2)
                ).fill()

    # ────────────────────────────────────────────── cuerpo de la esfera ──

    def _draw_sphere(self, ox, oy, r, g, b, orb_r, ph):
        """
        Esfera muy oscura con borde luminoso (limbo brillante).
        El interior es casi negro con un leve tinte violeta.
        El borde exterior es el color del estado con pulso suave.
        """
        N = 30  # anillos concéntricos para gradiente suave

        for i in range(N - 1, -1, -1):
            frac   = i / (N - 1)    # 0 = centro, 1 = borde
            ring_r = orb_r * frac

            # Curva muy pronunciada: solo el borde exterior brilla
            rim_curve = frac ** 4.5

            cr = r * rim_curve
            cg = g * rim_curve
            cb = b * rim_curve + 0.06 * (1.0 - frac)  # tinte azul-violeta en centro

            # Centro completamente oscuro
            if frac < 0.25:
                cr = 0.01
                cg = 0.01
                cb = 0.04 + 0.04 * frac

            # Pulso en el anillo exterior
            alpha = 1.0
            if frac > 0.88:
                alpha = 0.88 + 0.12 * math.sin(ph * 1.5)

            AppKit.NSColor.colorWithRed_green_blue_alpha_(cr, cg, cb, alpha).set()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                AppKit.NSMakeRect(ox - ring_r, oy - ring_r, ring_r * 2, ring_r * 2)
            ).fill()

        # ── Anillo brillante en el limbo (borde exterior) ─────────────────────
        rim_a = 0.70 + 0.20 * math.sin(ph * 1.4)
        rim_path = AppKit.NSBezierPath.bezierPath()
        rim_path.appendBezierPathWithOvalInRect_(
            AppKit.NSMakeRect(ox - orb_r + 0.5, oy - orb_r + 0.5,
                              (orb_r - 0.5) * 2, (orb_r - 0.5) * 2)
        )
        rim_path.setLineWidth_(2.5)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, rim_a).set()
        rim_path.stroke()

        # Segundo anillo más amplio y suave (halo del limbo)
        rim2_a = 0.30 + 0.10 * math.sin(ph * 1.0)
        rim2_path = AppKit.NSBezierPath.bezierPath()
        rim2_path.appendBezierPathWithOvalInRect_(
            AppKit.NSMakeRect(ox - orb_r - 2, oy - orb_r - 2,
                              (orb_r + 2) * 2, (orb_r + 2) * 2)
        )
        rim2_path.setLineWidth_(5.0)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, rim2_a).set()
        rim2_path.stroke()

        # ── Destello especular tenue (esquina superior-izquierda) ─────────────
        sx = ox - orb_r * 0.28
        sy = oy + orb_r * 0.30
        sr = orb_r * 0.14
        sa = 0.18 + 0.06 * math.sin(ph * 0.9)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.75, 0.65, 1.0, sa).set()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(
            AppKit.NSMakeRect(sx - sr, sy - sr, sr * 2, sr * 2)
        ).fill()

    # ────────────────────────────────────────────────────── API pública ──

    def attach_particles(self, particles) -> None:
        self._particles = particles

    def set_window(self, win) -> None:
        self._window = win

    def set_orb_click_handler(self, fn) -> None:
        """fn(orb_x, orb_y, screen_h) — llamada en el hilo principal al hacer clic en el orb."""
        self._orb_click_handler = fn

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
