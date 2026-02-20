"""
view.py

Dot Sphere — esfera 3D de puntos animada.

Cuadrícula lat/lon proyectada en 3D con deformación de ondas sinusoidales.
La esfera rota continuamente y se deforma según el estado de Jarvis:

  idle      → azul, rotación lenta, deformación mínima (respiración)
  listening → cyan-verde, deformación reactiva al audio
  thinking  → violeta, ondas de "actividad cerebral"
  acting    → cyan brillante, deformación máxima (habla)
"""

from __future__ import annotations

import math
import objc
import AppKit


# ── Paleta por estado ─────────────────────────────────────────────────────────

_COLORS = {
    "idle":      (0.00, 0.78, 1.00),   # azul eléctrico máximo
    "listening": (0.00, 0.92, 0.65),   # verde-cyan eléctrico
    "thinking":  (0.14, 0.04, 1.00),   # violeta eléctrico
    "acting":    (0.12, 0.94, 1.00),   # cyan eléctrico brillante
}

# Velocidad de rotación Y por estado
_ROT_SPEED = {
    "idle":      0.006,
    "listening": 0.013,
    "thinking":  0.018,
    "acting":    0.025,
}

# Amplitud base de deformación radial (fracción de ORB_RADIUS)
_DEFORM_AMP = {
    "idle":      0.032,
    "listening": 0.090,
    "thinking":  0.140,
    "acting":    0.280,
}

ORB_RADIUS  = 36.0   # radio de la esfera en puntos macOS
_HIT_RADIUS = 48.0   # zona interactiva (clic / drag)

# Valores objetivo de corona por estado (para lerp suave)
_DRIFT_SPD_T = {"idle": 0.30, "listening": 0.42, "thinking": 0.36, "acting": 0.55}
_DRIFT_AMP_T = {"idle": 0.10, "listening": 0.16, "thinking": 0.13, "acting": 0.20}
_CRV_SCALE_T = {"idle": 1.00, "listening": 1.30, "thinking": 1.15, "acting": 1.60}

_LERP = 0.06   # factor de suavizado por frame (~1.2 s para llegar al 95 %)

# ── Cuadrícula lat/lon ────────────────────────────────────────────────────────

_N_LAT = 30   # bandas de latitud
_N_LON = 38   # puntos por banda → total ~1140 puntos


def _sphere_grid(n_lat: int, n_lon: int) -> list[tuple]:
    """
    Genera puntos en cuadrícula lat/lon sobre la esfera unidad.
    Devuelve lista de (x, y, z, theta, phi).
    """
    pts = []
    for i in range(n_lat):
        theta = math.pi * (i + 0.5) / n_lat   # 0 (polo N) → π (polo S)
        st = math.sin(theta)
        ct = math.cos(theta)
        for j in range(n_lon):
            phi = 2.0 * math.pi * j / n_lon
            pts.append((st * math.cos(phi), st * math.sin(phi), ct, theta, phi))
    return pts


# Pre-computar una sola vez
_BASE_POINTS: list[tuple] = _sphere_grid(_N_LAT, _N_LON)


# ── Vista principal ───────────────────────────────────────────────────────────

class JarvisView(AppKit.NSView):
    """Orb de puntos 3D a 30 fps."""

    # ── init ──────────────────────────────────────────────────────────────────

    def initWithFrame_(self, frame):
        self = objc.super(JarvisView, self).initWithFrame_(frame)
        if self is None:
            return None

        self._orb_x       = 80.0
        self._orb_y       = 80.0
        self._state       = "idle"

        # Fases de animación
        self._phase   = 0.0    # fase de deformación
        self._rot_y   = 0.0    # rotación Y (horizontal, continua)
        self._tilt_ph = 0.0    # tilt X (inclinación orgánica lenta)

        self._audio_level = 0.0
        self._particles   = None

        # ── Variables suavizadas (lerp hacia el estado objetivo) ──────────────
        r0, g0, b0 = _COLORS["idle"]
        self._s_r          = r0
        self._s_g          = g0
        self._s_b          = b0
        self._s_amp        = _DEFORM_AMP["idle"]
        self._s_rot_spd    = _ROT_SPEED["idle"]
        self._s_drift_spd  = _DRIFT_SPD_T["idle"]
        self._s_drift_amp  = _DRIFT_AMP_T["idle"]
        self._s_crv_scale  = _CRV_SCALE_T["idle"]
        self._s_audio_bst  = 0.0   # audio boost suavizado

        # Drag
        self._dragging         = False
        self._did_drag         = False
        self._drag_mouse_start = (0.0, 0.0)
        self._drag_orb_start   = (0.0, 0.0)

        self._window            = None
        self._orb_click_handler = None

        # Timer 30 fps
        self._timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / 30.0, self, "tick:", None, True
        )
        return self

    # ── flags NSView ─────────────────────────────────────────────────────────

    def isOpaque(self):            return False
    def acceptsFirstResponder(self): return True

    # ── hit-test y drag del orb ──────────────────────────────────────────────

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

    # ── tick ─────────────────────────────────────────────────────────────────

    def tick_(self, timer):
        st = self._state
        al = self._audio_level

        # ── Lerp de todos los parámetros hacia el objetivo del estado ─────────
        tr, tg, tb = _COLORS.get(st, _COLORS["idle"])
        self._s_r         += (tr                              - self._s_r)        * _LERP
        self._s_g         += (tg                              - self._s_g)        * _LERP
        self._s_b         += (tb                              - self._s_b)        * _LERP
        self._s_amp       += (_DEFORM_AMP.get(st, 0.032)      - self._s_amp)      * _LERP
        self._s_rot_spd   += (_ROT_SPEED.get(st, 0.006)       - self._s_rot_spd)  * _LERP
        self._s_drift_spd += (_DRIFT_SPD_T.get(st, 0.30)      - self._s_drift_spd)* _LERP
        self._s_drift_amp += (_DRIFT_AMP_T.get(st, 0.10)      - self._s_drift_amp)* _LERP
        self._s_crv_scale += (_CRV_SCALE_T.get(st, 1.00)      - self._s_crv_scale)* _LERP

        # Audio boost: respuesta más rápida (0.18) para no sentir latencia
        t_bst = al * (0.50 if st in ("acting", "listening") else 0.0)
        self._s_audio_bst += (t_bst - self._s_audio_bst) * 0.18

        spd = self._s_rot_spd
        self._rot_y   += spd
        self._phase   += spd * 3.6
        self._tilt_ph += 0.0065

        if self._particles is not None:
            self._particles.update(1.0 / 30.0)

        self.setNeedsDisplay_(True)

        if self._window is not None:
            loc  = AppKit.NSEvent.mouseLocation()
            dx   = loc.x - self._orb_x
            dy   = loc.y - self._orb_y
            near = dx * dx + dy * dy <= (_HIT_RADIUS + 8.0) ** 2
            self._window.setIgnoresMouseEvents_(not near)

    # ── draw ─────────────────────────────────────────────────────────────────

    def drawRect_(self, dirty_rect):
        # Usar valores suavizados en lugar de los del estado directo
        r, g, b = self._s_r, self._s_g, self._s_b
        ox, oy  = self._orb_x, self._orb_y
        ph      = self._phase
        al      = self._audio_level

        # Amplitud: suavizada + audio boost suavizado
        amp = self._s_amp + self._s_audio_bst

        # ── Matrices de rotación (pre-calcular) ───────────────────────────────
        cry = math.cos(self._rot_y)
        sry = math.sin(self._rot_y)

        # Tilt X: doble frecuencia para movimiento más orgánico
        tilt = (0.24 * math.sin(self._tilt_ph)
                + 0.08 * math.sin(self._tilt_ph * 2.47))
        ctx  = math.cos(tilt)
        stx  = math.sin(tilt)

        # Onda de habla: se activa cuando Jarvis habla (acting + audio)
        speech_amp = al * 0.22 if self._state == "acting" else 0.0

        # ── Proyectar todos los puntos ─────────────────────────────────────────
        projected: list = []

        for bx, by, bz, theta, phi in _BASE_POINTS:

            # Offset por punto (golden ratio) → cada punto se mueve independiente
            t_off = theta * 1.6180 + phi * 0.6180

            # Deformación radial: 5 armónicos con offsets únicos por punto
            d = (
                0.36 * math.sin(2.0 * theta + ph * 0.78 + t_off * 0.30) * math.cos(2.0 * phi + ph * 0.55)
                + 0.24 * math.sin(3.5 * theta - ph * 1.12 + t_off * 0.52)
                + 0.16 * math.cos(theta  + 3.0 * phi - ph * 0.42 + t_off * 0.18)
                + 0.14 * math.sin(5.0 * theta + 2.5 * phi + ph * 1.60 + t_off * 0.40)
                + 0.10 * math.cos(4.0 * theta - 1.5 * phi + ph * 0.95 + t_off * 0.65)
            )

            # Onda de habla: burbujeo reactivo al nivel de audio
            if speech_amp > 0.0:
                d += speech_amp * math.sin(theta * 3.0 + ph * 2.80 + t_off) \
                               * math.cos(phi   * 2.0 + ph * 1.90)

            radius = ORB_RADIUS * (1.0 + amp * d)

            # Rotación alrededor del eje Y
            rx =  bx * cry + bz * sry
            rz = -bx * sry + bz * cry
            ry =  by

            # Tilt alrededor del eje X
            fx =  rx
            fy =  ry * ctx - rz * stx
            fz =  ry * stx + rz * ctx

            # Perspectiva leve (los puntos cercanos parecen ligeramente más grandes)
            persp = 0.82 + 0.18 * fz

            sx = ox + fx * radius * persp
            sy = oy + fy * radius * persp

            # Brillo: frente moderado + limbo (borde) muy brillante → efecto 3D
            front = (fz + 1.0) * 0.5                       # 0 = atrás, 1 = delante
            limbo = math.sqrt(max(0.0, 1.0 - fz * fz))    # máx en ecuador (borde visual)
            bright = 0.18 * front + 0.82 * limbo

            projected.append((fz, sx, sy, bright))

        # Ordenar de atrás a adelante (painter's algorithm)
        projected.sort(key=lambda p: p[0])

        # ── Corona solar ─────────────────────────────────────────────────────
        self._draw_corona(ox, oy, r, g, b, amp)

        # ── Puntos en dos pasadas: glow (grande, transparente) + core (pequeño, opaco) ──
        N_BK = 8
        buckets: list[list] = [[] for _ in range(N_BK)]

        for fz, sx, sy, bright in projected:
            bk = min(N_BK - 1, int(bright * N_BK))
            buckets[bk].append((sx, sy, bright))

        for bk, dots in enumerate(buckets):
            if not dots:
                continue
            bri = (bk + 0.5) / N_BK  # 0.06 a 0.94

            # Color del bucket: de azul oscuro (atrás) a cyan brillante (delante/borde)
            dr = min(1.0, r * (0.15 + 0.85 * bri) + 0.04)
            dg = min(1.0, g * (0.15 + 0.85 * bri) + 0.04)
            db = min(1.0, b * (0.30 + 0.70 * bri) + 0.18 * (1.0 - bri))

            # ── Pasada glow: halo suave alrededor de cada punto ───────────────
            glow_r = 1.6 + 1.8 * bri
            path_g = AppKit.NSBezierPath.bezierPath()
            for sx, sy, _ in dots:
                path_g.appendBezierPathWithOvalInRect_(
                    AppKit.NSMakeRect(sx - glow_r, sy - glow_r, glow_r * 2.0, glow_r * 2.0)
                )
            AppKit.NSColor.colorWithRed_green_blue_alpha_(
                dr, dg, db, max(0.01, 0.06 * bri)
            ).set()
            path_g.fill()

            # ── Pasada core: punto sólido ─────────────────────────────────────
            core_r = 0.55 + 0.70 * bri
            path_c = AppKit.NSBezierPath.bezierPath()
            for sx, sy, _ in dots:
                path_c.appendBezierPathWithOvalInRect_(
                    AppKit.NSMakeRect(sx - core_r, sy - core_r, core_r * 2.0, core_r * 2.0)
                )
            AppKit.NSColor.colorWithRed_green_blue_alpha_(
                dr, dg, db, 0.10 + 0.82 * bri
            ).set()
            path_c.fill()

        # ── Partículas fly_to ─────────────────────────────────────────────────
        if self._particles is not None:
            self._particles.draw()

    # ── Corona solar ─────────────────────────────────────────────────────────

    # Parámetros por filamento: (ángulo_base, len_factor, curve_factor, bright, phase_off)
    #   len_factor  : 0–1 → longitud relativa al radio
    #   curve_factor: curvatura perpendicular (+ derecha, - izquierda)
    #   bright      : 0–1 → brillo base
    _CORONA = tuple(
        (
            (i * 2.39996) % (2 * math.pi),                    # ángulo (golden ratio)
            0.10 + 0.90 * abs(math.sin(i * 0.6931 + 0.50)),   # longitud
            0.32 * math.sin(i * 1.3100 + 0.28),               # curvatura
            0.18 + 0.82 * abs(math.sin(i * 2.39996)),         # brillo
            i * 2.39996 * 0.51,                               # desfase de fase
        )
        for i in range(115)
    )

    def _draw_corona(self, ox: float, oy: float, r: float, g: float, b: float,
                     amp: float) -> None:
        """
        Corona solar: filamentos finos que emergen de la superficie del orb.
        Igual que prominencias solares o conexiones neuronales.
        3 pasadas: glow exterior → cuerpo → núcleo blanco-azul.
        """
        ph = self._phase

        # ── Halo ambiental (nube difusa detrás) ───────────────────────────────
        pulse_h = 0.80 + 0.20 * math.sin(ph * 0.28)
        for df, ba in ((1.38, 0.012), (1.18, 0.022), (1.07, 0.038)):
            d = ORB_RADIUS * df
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, ba * pulse_h).set()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                AppKit.NSMakeRect(ox - d, oy - d, d * 2.0, d * 2.0)
            ).fill()

        # ── Parámetros suavizados (sin saltos de estado) ──────────────────────
        drift_spd   = self._s_drift_spd
        drift_amp   = self._s_drift_amp
        crv_scale   = self._s_crv_scale
        audio_boost = self._s_audio_bst

        # ── Geometría de filamentos ────────────────────────────────────────────
        geom: list = []
        for ang0, len_f, crv, bright, ph_off in self._CORONA:

            # Ángulo: deriva principal + flutter secundario siempre presente
            angle = (ang0
                     + drift_amp * math.sin(ph * drift_spd + ph_off)
                     + 0.045    * math.sin(ph * 0.78       + ph_off * 1.618))

            # Origen: justo en la superficie
            base_r = ORB_RADIUS * (1.01 + amp * 0.06 * abs(math.sin(ph * 0.38 + ph_off)))
            bx = ox + base_r * math.cos(angle)
            by = oy + base_r * math.sin(angle)

            # Longitud: un poco más corta + reacción al audio y estado
            length = ORB_RADIUS * (0.03 + 0.26 * len_f) \
                     * (0.55 + 0.45 * abs(math.sin(ph * 0.20 + ph_off))) \
                     * (1.0 + amp * 0.55 + audio_boost)

            # Punto final
            ex = ox + (base_r + length) * math.cos(angle)
            ey = oy + (base_r + length) * math.sin(angle)

            # Control point: curvatura más viva según estado
            perp = angle + math.pi * 0.5
            cp_d = length * crv * crv_scale * (0.75 + 0.25 * math.sin(ph * 0.32 + ph_off))
            mx   = (bx + ex) * 0.5 + cp_d * math.cos(perp)
            my   = (by + ey) * 0.5 + cp_d * math.sin(perp)

            geom.append((bx, by, mx, my, ex, ey, bright))

        # ── 4 pasadas: muy difuso → difuso → suave → tenue hilo ──────────────
        # Sin núcleo duro — solo capas de glow superpuestas
        N_BK = 6
        for line_w, alpha_f in ((20.0, 0.010), (10.0, 0.022), (4.5, 0.055), (1.4, 0.10)):
            bk_paths = [AppKit.NSBezierPath.bezierPath() for _ in range(N_BK)]

            for bx, by, mx, my, ex, ey, bright in geom:
                bk = min(N_BK - 1, int(bright * N_BK))
                p  = bk_paths[bk]
                p.moveToPoint_(AppKit.NSMakePoint(bx, by))
                p.curveToPoint_controlPoint1_controlPoint2_(
                    AppKit.NSMakePoint(ex, ey),
                    AppKit.NSMakePoint(mx, my),
                    AppKit.NSMakePoint(mx, my),
                )

            for bk, path in enumerate(bk_paths):
                if path.elementCount() == 0:
                    continue
                bri = (bk + 0.5) / N_BK
                path.setLineWidth_(line_w)
                path.setLineCapStyle_(AppKit.NSRoundLineCapStyle)
                AppKit.NSColor.colorWithRed_green_blue_alpha_(
                    r, g, b, alpha_f * bri
                ).set()
                path.stroke()

    # ── API pública ───────────────────────────────────────────────────────────

    def attach_particles(self, particles) -> None:
        self._particles = particles

    def set_window(self, win) -> None:
        self._window = win

    def set_orb_click_handler(self, fn) -> None:
        """fn(orb_x, orb_y, screen_h) llamada desde el hilo principal al hacer clic."""
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
