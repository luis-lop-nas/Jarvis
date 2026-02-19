"""
view.py

NSView personalizado que dibuja el orb de Jarvis y sus animaciones.

Coordenadas macOS: (0,0) = esquina inferior-izquierda de la pantalla.
El orb vive en la esquina inferior-izquierda por defecto.

Estados del orb:
  idle      → azul, pulso suave
  listening → verde, pulso rápido
  thinking  → naranja, oscilación
  acting    → azul eléctrico, intenso
"""

from __future__ import annotations

import math
import objc
import AppKit


# Paleta
_COLORS = {
    "idle":      (0.00, 0.71, 1.00),   # azul eléctrico
    "listening": (0.00, 0.95, 0.50),   # verde
    "thinking":  (1.00, 0.60, 0.00),   # naranja
    "acting":    (0.00, 0.85, 1.00),   # azul brillante
}


class JarvisView(AppKit.NSView):
    """Vista transparente que renderiza el orb a ~30 fps."""

    # ------------------------------------------------------------------ init

    def initWithFrame_(self, frame: AppKit.NSRect) -> "JarvisView":
        self = objc.super(JarvisView, self).initWithFrame_(frame)
        if self is None:
            return None

        # Posición del orb en coordenadas de pantalla
        self._orb_x: float = 68.0
        self._orb_y: float = 68.0   # 68 px desde abajo-izquierda

        self._state: str  = "idle"
        self._pulse: float = 0.0    # fase del seno para la animación
        self._particles = None      # ParticleSystem opcional

        # Estado de drag
        self._dragging:          bool  = False
        self._drag_mouse_start:  tuple = (0.0, 0.0)
        self._drag_orb_start:    tuple = (0.0, 0.0)

        # Ángulo de rotación de los anillos orbitales (thinking/acting)
        self._orbit_angle: float = 0.0

        # Nivel de audio para VU meter (0.0 = silencio, 1.0 = máximo)
        self._audio_level: float = 0.0

        # Referencia a NSWindow para toggle de click-through
        self._window = None

        # Timer a 30 fps — llama a tick_ en cada frame
        self._timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1 / 30.0, self, "tick:", None, True
        )

        return self

    # ----------------------------------------------------------------- flags

    def isOpaque(self) -> bool:
        return False   # imprescindible para transparencia

    def acceptsFirstResponder(self) -> bool:
        return True    # necesario para recibir eventos de ratón

    # ────────────────────────────────────────────── hit-test y drag del orb ──

    _HIT_RADIUS = 45.0   # px — zona interactiva alrededor del orb (cubre el halo exterior)

    def hitTest_(self, point: AppKit.NSPoint):
        """Solo captura el evento si el punto está dentro del radio del orb."""
        dx = point.x - self._orb_x
        dy = point.y - self._orb_y
        if dx * dx + dy * dy <= self._HIT_RADIUS ** 2:
            return self
        return None   # click-through al resto de apps

    def mouseDown_(self, event: AppKit.NSEvent) -> None:
        loc = event.locationInWindow()
        self._dragging = True
        self._drag_mouse_start = (loc.x, loc.y)
        self._drag_orb_start   = (self._orb_x, self._orb_y)

    def mouseDragged_(self, event: AppKit.NSEvent) -> None:
        if not self._dragging:
            return
        loc = event.locationInWindow()
        dx  = loc.x - self._drag_mouse_start[0]
        dy  = loc.y - self._drag_mouse_start[1]

        frame  = self.frame()
        margin = self._HIT_RADIUS
        new_x  = max(margin, min(frame.size.width  - margin, self._drag_orb_start[0] + dx))
        new_y  = max(margin, min(frame.size.height - margin, self._drag_orb_start[1] + dy))

        self._orb_x = new_x
        self._orb_y = new_y

    def mouseUp_(self, event: AppKit.NSEvent) -> None:
        self._dragging = False

    # --------------------------------------------------------------- tick/draw

    def tick_(self, timer: AppKit.NSTimer) -> None:
        """Avanza la fase de animación y pide redibujo."""
        speed = 0.08 if self._state == "listening" else 0.04
        self._pulse += speed
        if self._state in ("thinking", "acting"):
            self._orbit_angle += 0.06   # ~1.8 rad/s → vuelta completa en ~3.5s
        if self._particles is not None:
            self._particles.update(1 / 30.0)
        self.setNeedsDisplay_(True)

        # Toggle click-through: ignorar eventos excepto cuando el cursor está cerca del orb
        if self._window is not None:
            loc = AppKit.NSEvent.mouseLocation()
            dx = loc.x - self._orb_x
            dy = loc.y - self._orb_y
            near = (dx * dx + dy * dy) <= (self._HIT_RADIUS + 8.0) ** 2
            self._window.setIgnoresMouseEvents_(not near)

    def drawRect_(self, dirty_rect: AppKit.NSRect) -> None:
        """Dibuja el orb con sus halos de glow. Llamado en cada frame."""
        pulse = math.sin(self._pulse)          # -1 → 1
        norm  = pulse * 0.3 + 0.7             #  0.4 → 1.0  (siempre positivo)

        r, g, b = _COLORS.get(self._state, _COLORS["idle"])
        ox, oy  = self._orb_x, self._orb_y

        # ── Halos concéntricos (glow exterior) ──────────────────────────────
        for i, (radius, base_alpha) in enumerate([(55, 0.04), (42, 0.07), (30, 0.11)]):
            alpha = base_alpha * norm
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, alpha).set()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                AppKit.NSMakeRect(ox - radius, oy - radius, radius * 2, radius * 2)
            ).fill()

        # ── Orb principal ────────────────────────────────────────────────────
        orb_r = 15.0
        # VU meter: expande el orb hasta +9px según el nivel de audio (mic/TTS)
        if self._state in ("listening", "acting"):
            orb_r += 9.0 * self._audio_level
        alpha = 0.50 + 0.40 * norm
        AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, alpha).set()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(
            AppKit.NSMakeRect(ox - orb_r, oy - orb_r, orb_r * 2, orb_r * 2)
        ).fill()

        # ── Núcleo blanco ────────────────────────────────────────────────────
        core_r = 5.0
        AppKit.NSColor.colorWithRed_green_blue_alpha_(1, 1, 1, 0.55 * norm).set()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(
            AppKit.NSMakeRect(ox - core_r, oy - core_r, core_r * 2, core_r * 2)
        ).fill()

        # ── Anillo exterior (solo en listening/thinking) ─────────────────────
        if self._state in ("listening", "thinking"):
            ring_r = 22.0 + abs(pulse) * 4
            path = AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                AppKit.NSMakeRect(ox - ring_r, oy - ring_r, ring_r * 2, ring_r * 2)
            )
            path.setLineWidth_(1.2)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, 0.35 * norm).set()
            path.stroke()

        # ── Anillos orbitales (thinking / acting) ────────────────────────────
        if self._state in ("thinking", "acting"):
            self._draw_orbit(ox, oy, r, g, b, norm)

        # ── Partículas fly_to (siempre encima) ───────────────────────────────
        if self._particles is not None:
            self._particles.draw()

    # --------------------------------------------------------- orbit animation

    def _draw_orbit(self, ox: float, oy: float, r: float, g: float, b: float, norm: float) -> None:
        """
        Dos anillos de puntos que orbitan el orb en sentidos contrarios.
        Ring 1 — 6 puntos, r=30px, sentido horario, tamaño 3px.
        Ring 2 — 8 puntos, r=44px, anti-horario (×0.65), tamaño 2px.
        El alpha de cada punto varía con la profundidad (efecto 3D).
        """
        angle = self._orbit_angle

        # Anillo interior
        for i in range(6):
            a   = angle + (2 * math.pi * i / 6)
            px  = ox + 30.0 * math.cos(a)
            py  = oy + 30.0 * math.sin(a)
            # Profundidad: puntos "delante" (sin > 0) más brillantes
            depth = 0.45 + 0.55 * math.sin(a)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, norm * 0.85 * depth).set()
            s = 3.0
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                AppKit.NSMakeRect(px - s, py - s, s * 2, s * 2)
            ).fill()

        # Anillo exterior (contra-rotante, más lento)
        for i in range(8):
            a   = -angle * 0.65 + (2 * math.pi * i / 8)
            px  = ox + 44.0 * math.cos(a)
            py  = oy + 44.0 * math.sin(a)
            depth = 0.35 + 0.65 * math.sin(a)
            AppKit.NSColor.colorWithRed_green_blue_alpha_(r, g, b, norm * 0.55 * depth).set()
            s = 2.0
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                AppKit.NSMakeRect(px - s, py - s, s * 2, s * 2)
            ).fill()

    # ------------------------------------------------------- particle system

    def attach_particles(self, particles) -> None:
        """Conectar el sistema de partículas. Llamar desde el hilo principal."""
        self._particles = particles

    # ----------------------------------------------------------- state control

    def set_window(self, win) -> None:
        """Referencia al NSWindow para toggle de click-through por proximidad."""
        self._window = win

    def set_state(self, state: str) -> None:
        """Cambiar estado del orb. Llamar SIEMPRE desde el hilo principal."""
        self._state = state

    def set_position(self, x: float, y: float) -> None:
        """Mover el orb a nuevas coordenadas de pantalla."""
        self._orb_x = x
        self._orb_y = y

    def set_audio_level(self, level: float) -> None:
        """Actualizar nivel de audio para el VU meter. Llamar desde hilo principal."""
        self._audio_level = max(0.0, min(1.0, level))

    @property
    def orb_position(self) -> tuple[float, float]:
        return self._orb_x, self._orb_y
