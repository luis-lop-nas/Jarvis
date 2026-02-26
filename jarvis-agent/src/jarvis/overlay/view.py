"""
view.py — Retro ASCII Entity

Entidad abstracta retro formada por caracteres ASCII en movimiento.
Inspiración: primeras interfaces de ordenador (CRT/terminal).
"""

from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

import AppKit
import objc


# ── Paletas de color por estado ───────────────────────────────────────────────
# (r, g, b) normalizados 0-1

_PALETTES: dict[str, dict] = {
    'idle':      {'a': (0.95, 0.95, 0.95), 'b': (0.55, 0.55, 0.55)},
    'listening': {'a': (1.00, 1.00, 1.00), 'b': (0.65, 0.65, 0.65)},
    'thinking':  {'a': (1.00, 1.00, 1.00), 'b': (0.72, 0.72, 0.72)},
    'acting':    {'a': (1.00, 1.00, 1.00), 'b': (0.62, 0.62, 0.62)},
}

_GLYPHS = ['0', '1']

_NUM    = 96      # número de partículas
_BASE_R = 85.0   # radio base de la distribución (compacto)
_HIT_R  = 74.0   # zona interactiva para drag/clic
_PROX_R = 190.0  # zona de proximidad para activar mouse events


# ── Distribución sunflower spiral ─────────────────────────────────────────────

def _cloud_home(i: int, total: int) -> Tuple[float, float]:
    """
    Distribución sunflower spiral deformada orgánicamente.
    Devuelve offset (dx, dy) respecto al centro de la nube.
    """
    golden = math.pi * (3.0 - math.sqrt(5.0))
    r      = math.sqrt(i / total)
    angle  = i * golden
    deform = 0.6 + 0.7 * abs(math.sin(angle * 2.3)) + 0.3 * abs(math.cos(angle * 1.7))
    rx = _BASE_R * r * deform * (1.0 + 0.3 * math.sin(angle * 4.0))
    ry = _BASE_R * r * deform * 0.7 * (1.0 + 0.3 * math.cos(angle * 3.0))
    return math.cos(angle) * rx, math.sin(angle) * ry


# ── Partícula de la nube ──────────────────────────────────────────────────────

class _Particle:
    """
    Partícula individual de la nube JARVIS.

    Estados:
      'cloud'  → spring hacia posición home con ruido orgánico
      'travel' → curva bezier hacia destino (escalonado)
      'wrap'   → orbitar array de puntos (borde ventana / icono Dock)
    """

    __slots__ = (
        'home_dx', 'home_dy',
        'x', 'y', 'vx', 'vy',
        'base_size', 'size',
        'opacity', 'phase', 'noise_t',
        'step', 'acc', 'logic_frame',
        'is_glyph', 'glyph',
        'trail', 'max_trail',
        'color', '_pal_a', '_pal_b',
        'state',
        'wpts', 'wi', 'wsp', 'woff_x', 'woff_y',
        'tfx', 'tfy', 'ttx', 'tty',
        'tt', 'tdelay', 'tdelayed', 'tnext',
    )

    def __init__(self, i: int, total: int, pal: dict) -> None:
        self.home_dx, self.home_dy = _cloud_home(i, total)
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0

        self.base_size = 1.0 + random.random() * 4.5
        self.size      = self.base_size
        self.opacity   = 0.3 + random.random() * 0.7
        self.phase     = random.random() * math.pi * 2.0
        self.noise_t   = random.random() * 100.0

        # on-twos: cada partícula salta 1 o 2 frames lógicos para
        # dar aspecto de animación dibujada a mano (on-twos)
        self.step        = 1 + random.randint(0, 1)
        self.acc         = random.randint(0, self.step)
        self.logic_frame = 0

        self.is_glyph = True
        self.glyph    = random.choice(_GLYPHS)

        self.trail: List[Tuple[float, float]] = []
        self.max_trail = 1 + random.randint(0, 5)

        self._pal_a = pal['a']
        self._pal_b = pal['b']
        self._pick_color()

        # estado
        self.state   = 'cloud'
        self.wpts    = None
        self.wi      = 0.0
        self.wsp     = 0.2 + random.random() * 0.5
        self.woff_x  = (random.random() - 0.5) * 10.0
        self.woff_y  = (random.random() - 0.5) * 10.0

        self.tfx = self.tfy = self.ttx = self.tty = 0.0
        self.tt       = 0.0
        self.tdelay   = 0
        self.tdelayed = 0
        self.tnext    = 'cloud'

    def _pick_color(self) -> None:
        r = random.random()
        if r < 0.60:
            self.color = self._pal_a
        elif r < 0.85:
            self.color = self._pal_b
        else:
            self.color = (1.0, 1.0, 1.0)

    def update_palette(self, pal: dict) -> None:
        self._pal_a = pal['a']
        self._pal_b = pal['b']
        self._pick_color()

    # ── física de nube ────────────────────────────────────────────────────────

    def _cloud_target(self, cx: float, cy: float, audio: float) -> Tuple[float, float]:
        self.noise_t += 0.008
        nx = math.sin(self.noise_t * 1.3 + self.phase) * 14.0
        ny = math.cos(self.noise_t * 1.1 + self.phase) * 10.0
        # audio expande el radio de la nube
        scale = 1.0 + audio * 0.45
        return cx + self.home_dx * scale + nx, cy + self.home_dy * scale + ny

    def _update_cloud(self, cx: float, cy: float, audio: float) -> None:
        tx, ty = self._cloud_target(cx, cy, audio)
        dx, dy  = tx - self.x, ty - self.y
        self.vx += dx * 0.035
        self.vy += dy * 0.035
        self.vx *= 0.78
        self.vy *= 0.78
        self.trail.append((self.x, self.y))
        if len(self.trail) > self.max_trail:
            self.trail.pop(0)
        self.x += self.vx
        self.y += self.vy
        self.size = self.base_size * (0.75 + 0.5 * math.sin(self.logic_frame * 0.05 + self.phase))

    def _update_travel(self) -> None:
        if self.tdelayed < self.tdelay:
            self.tdelayed += 1
            return
        self.tt += 0.04
        t = min(self.tt, 1.0)
        # ease in-out cubic
        e = 4.0 * t * t * t if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0
        mid_x = (self.tfx + self.ttx) * 0.5 + (random.random() - 0.5) * 60.0
        mid_y = min(self.tfy, self.tty) - 0.5 - random.random() * 80.0
        q = 1.0 - e
        self.trail.append((self.x, self.y))
        if len(self.trail) > self.max_trail:
            self.trail.pop(0)
        self.x = q * q * self.tfx + 2.0 * q * e * mid_x + e * e * self.ttx
        self.y = q * q * self.tfy + 2.0 * q * e * mid_y + e * e * self.tty
        self.vx = 0.0
        self.vy = 0.0
        self.size = self.base_size * (1.0 + (1.0 - e) * 2.0)
        if t >= 1.0:
            self.state = self.tnext
            self.tt = 0.0
            if self.wpts:
                self.wi = random.random() * len(self.wpts)

    def _update_wrap(self) -> None:
        if not self.wpts:
            return
        self.wi = (self.wi + self.wsp) % len(self.wpts)
        pt = self.wpts[int(self.wi)]
        self.trail.append((self.x, self.y))
        if len(self.trail) > self.max_trail:
            self.trail.pop(0)
        self.x = pt[0] + self.woff_x + (random.random() - 0.5) * 5.0
        self.y = pt[1] + self.woff_y + (random.random() - 0.5) * 5.0
        self.vx = 0.0
        self.vy = 0.0
        self.size = self.base_size * (0.5 + 0.6 * abs(math.sin(self.logic_frame * 0.09 + self.phase)))

    def update(self, cx: float, cy: float, audio: float) -> None:
        """Update de lógica de la partícula. Se llama cada tick del timer."""
        self.acc += 1
        if self.acc < self.step:
            return
        self.acc = 0
        self.logic_frame += 1
        if self.state == 'cloud':
            self._update_cloud(cx, cy, audio)
        elif self.state == 'travel':
            self._update_travel()
        elif self.state == 'wrap':
            self._update_wrap()

    def send_to_wrap(self, wpts, delay: int = 0) -> None:
        """Enviar la partícula a orbitar un conjunto de puntos."""
        self.wpts  = wpts
        tgt        = wpts[int(random.random() * len(wpts))]
        self.tfx, self.tfy = self.x, self.y
        self.ttx   = tgt[0] + (random.random() - 0.5) * 16.0
        self.tty   = tgt[1] + (random.random() - 0.5) * 16.0
        self.tt    = 0.0
        self.tdelay   = delay
        self.tdelayed = 0
        self.tnext = 'wrap'
        self.state = 'travel'
        self.trail = []
        self._pick_color()

    def return_cloud(self) -> None:
        """Devolver la partícula a la formación de nube."""
        self.state = 'cloud'
        self.wpts  = None
        self.vx    = (random.random() - 0.5) * 4.0
        self.vy    = (random.random() - 0.5) * 4.0
        self.trail = []
        self.tt    = 0.0
        self._pick_color()


# ── Vista principal ────────────────────────────────────────────────────────────

class JarvisView(AppKit.NSView):
    """
    Nube de partículas orgánica JARVIS.
    Cubre la pantalla completa (transparente / click-through en reposo).
    30 fps. Drag de la nube con el ratón.
    """

    def initWithFrame_(self, frame):
        self = objc.super(JarvisView, self).initWithFrame_(frame)
        if self is None:
            return None

        # Margen visual para que no quede pegado a la esquina inferior izquierda.
        self._orb_x = 168.0
        self._orb_y = 92.0
        self._state = 'idle'
        self._audio_level = 0.0
        self._pal   = _PALETTES['idle']

        # inicializar partículas en posición home
        self._particles_cloud: List[_Particle] = [
            _Particle(i, _NUM, self._pal) for i in range(_NUM)
        ]
        for p in self._particles_cloud:
            p.x = self._orb_x + p.home_dx + (random.random() - 0.5) * 20.0
            p.y = self._orb_y + p.home_dy + (random.random() - 0.5) * 20.0

        self._fly_particles = None  # ParticleSystem para fly_to
        self._hud           = None  # JarvisHUD para color dinámico

        # drag
        self._dragging         = False
        self._did_drag         = False
        self._drag_mouse_start = (0.0, 0.0)
        self._drag_orb_start   = (0.0, 0.0)

        self._window            = None
        self._orb_click_handler = None

        # fuente monospace para glyphs retro (evita crear NSFont por frame)
        self._glyph_font = (
            AppKit.NSFont.fontWithName_size_('Monaco', 11.0) or
            AppKit.NSFont.fontWithName_size_('Menlo', 11.0) or
            AppKit.NSFont.monospacedSystemFontOfSize_weight_(11.0, AppKit.NSFontWeightRegular)
        )

        # NSTimer 30 fps
        self._timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / 30.0, self, 'tick:', None, True,
        )
        self._crt_phase = 0.0
        self._grid_phase = random.random() * 10.0
        self._listen_phase = 0.0

        return self

    # ── NSView flags ──────────────────────────────────────────────────────────

    def isOpaque(self):              return False
    def acceptsFirstResponder(self): return True

    # ── hit-test / drag de la nube ────────────────────────────────────────────

    def hitTest_(self, point):
        dx = point.x - self._orb_x
        dy = point.y - self._orb_y
        return self if dx * dx + dy * dy <= _HIT_R ** 2 else None

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
        m = _HIT_R
        self._orb_x = max(m, min(f.size.width  - m, self._drag_orb_start[0] + dx))
        self._orb_y = max(m, min(f.size.height - m, self._drag_orb_start[1] + dy))

    def mouseUp_(self, event):
        was_click      = self._dragging and not self._did_drag
        self._dragging = False
        self._did_drag = False
        if was_click and self._orb_click_handler is not None:
            self._orb_click_handler(self._orb_x, self._orb_y, self.frame().size.height)

    # ── tick ──────────────────────────────────────────────────────────────────

    def tick_(self, timer):
        cx, cy = self._orb_x, self._orb_y
        al     = self._audio_level
        self._crt_phase += 0.035
        self._grid_phase += 0.04
        if self._state == 'listening':
            self._listen_phase += 0.20
        else:
            self._listen_phase += 0.08

        for p in self._particles_cloud:
            p.update(cx, cy, al)

        if self._fly_particles is not None:
            self._fly_particles.update(1.0 / 30.0)

        self.setNeedsDisplay_(True)

        # proximidad: activar/desactivar mouse events según distancia del cursor
        if self._window is not None:
            loc  = AppKit.NSEvent.mouseLocation()
            dx   = loc.x - cx
            dy   = loc.y - cy
            near = dx * dx + dy * dy <= _PROX_R ** 2
            self._window.setIgnoresMouseEvents_(not near)

    # ── draw ──────────────────────────────────────────────────────────────────

    def drawRect_(self, dirty_rect):
        cx, cy  = self._orb_x, self._orb_y
        ar, ag, ab = self._pal['a']   # color acento A (principal)

        # ── Bloque visual principal ────────────────────────────────────────
        block_w = 206.0
        block_h = 128.0

        # Animación diferenciada en estado listening: oscilación + respiración.
        if self._state == 'listening':
            bob_x = math.sin(self._listen_phase * 0.8) * 5.0
            bob_y = abs(math.sin(self._listen_phase)) * 4.0
            scale = 1.0 + 0.05 * abs(math.sin(self._listen_phase * 1.5))
        else:
            bob_x = math.sin(self._listen_phase * 0.35) * 1.2
            bob_y = 0.0
            scale = 1.0

        block_w *= scale
        block_h *= scale
        x0 = cx - block_w / 2.0 + bob_x
        y0 = cy - block_h / 2.0 + bob_y

        bg_rect = AppKit.NSMakeRect(x0, y0, block_w, block_h)
        bg_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bg_rect, 20.0, 20.0)
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.98).set()
        bg_path.fill()

        # Borde sutil blanco
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.92, 0.92, 0.92, 0.20).set()
        bg_path.setLineWidth_(1.0)
        bg_path.stroke()

        # ── Rejilla binaria animada tipo referencia ────────────────────────
        rows = 12
        cols = 26
        mx = 14.0
        my = 12.0
        cell_w = (block_w - mx * 2.0) / cols
        cell_h = (block_h - my * 2.0) / rows

        font = (
            AppKit.NSFont.fontWithName_size_('Monaco', 11.0) or
            AppKit.NSFont.fontWithName_size_('Menlo', 11.0) or
            AppKit.NSFont.monospacedSystemFontOfSize_weight_(11.0, AppKit.NSFontWeightRegular)
        )

        for r in range(rows):
            for c in range(cols):
                px = x0 + mx + c * cell_w
                py = y0 + my + (rows - r - 1) * cell_h

                # Máscara orgánica horizontal similar a la captura (bandas + recortes)
                wave = math.sin(c * 0.17 + r * 0.41 + self._grid_phase * 1.2)
                ridge = math.sin(r * 0.95 - self._grid_phase * 0.55)
                band_cut = abs(math.sin(r * 0.68 + self._grid_phase * 0.35)) > 0.96
                if band_cut:
                    continue

                density = 0.42 + 0.34 * wave + 0.22 * ridge
                if self._state == 'listening':
                    density += 0.18 * math.sin((c * 0.6) - self._listen_phase * 2.2)
                if density < 0.18:
                    continue

                bit = '0' if math.sin(c * 0.71 + r * 0.33 + self._grid_phase * 2.2) > 0.35 else '1'
                alpha = min(0.98, 0.44 + 0.42 * max(0.0, density))
                color = AppKit.NSColor.colorWithRed_green_blue_alpha_(ar, ag, ab, alpha)
                s = AppKit.NSAttributedString.alloc().initWithString_attributes_(
                    bit,
                    {
                        AppKit.NSFontAttributeName: font,
                        AppKit.NSForegroundColorAttributeName: color,
                    },
                )
                s.drawAtPoint_(AppKit.NSMakePoint(px, py))

        # Barra de barrido en modo escucha para feedback inmediato.
        if self._state == 'listening':
            sweep = (math.sin(self._listen_phase * 0.9) * 0.5 + 0.5) * (block_h - 14.0)
            sy = y0 + 7.0 + sweep
            AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.12).set()
            AppKit.NSRectFill(AppKit.NSMakeRect(x0 + 8.0, sy, block_w - 16.0, 1.4))

        # ── Partículas fly_to (encima de la nube) ────────────────────────────
        if self._fly_particles is not None:
            self._fly_particles.draw()

        # ── Scanlines CRT sutiles ────────────────────────────────────────────
        h = block_h
        w = block_w
        step = 3.0
        y = 0.0
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.85, 0.85, 0.85, 0.05).set()
        while y < h:
            AppKit.NSRectFill(AppKit.NSMakeRect(x0, y0 + y, w, 1.0))
            y += step

    # ── API pública ───────────────────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        self._state = state
        pal = _PALETTES.get(state, _PALETTES['idle'])
        self._pal = pal
        for p in self._particles_cloud:
            p.update_palette(pal)
        # sincronizar color del HUD si está conectado
        if self._hud is not None:
            self._hud.set_accent_color(*pal['a'])

    def set_position(self, x: float, y: float) -> None:
        self._orb_x = x
        self._orb_y = y

    def set_audio_level(self, level: float) -> None:
        self._audio_level = max(0.0, min(1.0, level))

    def attach_particles(self, particles) -> None:
        """Conectar el sistema de partículas fly_to."""
        self._fly_particles = particles

    def set_window(self, win) -> None:
        """Pasar referencia NSWindow para toggle de mouse events por proximidad."""
        self._window = win

    def set_orb_click_handler(self, fn) -> None:
        """fn(orb_x, orb_y, screen_h) — callback al hacer clic en la nube."""
        self._orb_click_handler = fn

    def set_hud(self, hud) -> None:
        """Conectar JarvisHUD para actualizar su color de borde al cambiar estado."""
        self._hud = hud

    @property
    def orb_position(self) -> Tuple[float, float]:
        return self._orb_x, self._orb_y
