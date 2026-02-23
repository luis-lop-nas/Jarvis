"""
view.py — Cloud Entity

Nube orgánica de 80 partículas estilo "cloud entity / glitch art".
Reemplaza la esfera 3D con corona solar.

Paletas por estado:
  idle      → cyan  #00ffe0 + purple #7b2fff
  listening → green #00ff88 + cyan   #00ffe0
  thinking  → yellow #ffe100 + orange #ff8c00
  acting    → pink  #ff2060 + purple #8b00ff

Cada partícula tiene:
  - Posición home en distribución sunflower spiral deformada
  - Spring physics + ruido Perlin para movimiento orgánico
  - Trail (rastro de posiciones anteriores)
  - 7% de probabilidad de ser un glyph con aberración cromática

Ciclo de render: NSTimer 30 fps → tick_ → update partículas → setNeedsDisplay_
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
    'idle':      {'a': (0.000, 1.000, 0.878), 'b': (0.482, 0.188, 1.000)},
    'listening': {'a': (0.000, 1.000, 0.533), 'b': (0.000, 1.000, 0.878)},
    'thinking':  {'a': (1.000, 0.882, 0.000), 'b': (1.000, 0.549, 0.000)},
    'acting':    {'a': (1.000, 0.125, 0.376), 'b': (0.545, 0.000, 1.000)},
}

_GLYPHS = ['◆', '◇', '✦', '◉', '▸', '◌', '✕', '○', '◈', '▲', '▶', '▼', '⬡', '◐']

_NUM    = 80      # número de partículas
_BASE_R = 85.0   # radio base de la distribución (compacto)
_HIT_R  = 44.0   # zona interactiva para drag/clic
_PROX_R = 115.0  # zona de proximidad para activar mouse events


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

        self.is_glyph = random.random() < 0.07
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

        self._orb_x = 80.0
        self._orb_y = 80.0
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

        # fuente monospace para glyphs — tamaño fijo (evita crear NSFont por frame)
        self._glyph_font = (
            AppKit.NSFont.fontWithName_size_('SF Mono', 14.0) or
            AppKit.NSFont.fontWithName_size_('Menlo', 14.0) or
            AppKit.NSFont.monospacedSystemFontOfSize_weight_(14.0, AppKit.NSFontWeightRegular)
        )

        # NSTimer 30 fps
        self._timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / 30.0, self, 'tick:', None, True,
        )

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

        # ── Partículas de la nube ─────────────────────────────────────────────
        for p in self._particles_cloud:
            cr, cg, cb = p.color
            a  = p.opacity
            px, py, sz = p.x, p.y, p.size

            # trail: líneas progresivamente más transparentes y delgadas
            trail = p.trail
            n_tr  = len(trail)
            if n_tr >= 2:
                for i in range(n_tr - 1):
                    x0, y0 = trail[i]
                    x1, y1 = trail[i + 1]
                    seg_alpha = a * (i / n_tr) * 0.45
                    if seg_alpha < 0.008:
                        continue
                    seg = AppKit.NSBezierPath.bezierPath()
                    seg.setLineWidth_(sz * 0.28 * ((i + 1) / n_tr))
                    seg.setLineCapStyle_(AppKit.NSLineCapStyleRound)
                    seg.moveToPoint_(AppKit.NSMakePoint(x0, y0))
                    seg.lineToPoint_(AppKit.NSMakePoint(x1, y1))
                    AppKit.NSColor.colorWithRed_green_blue_alpha_(cr, cg, cb, seg_alpha).set()
                    seg.stroke()

            # dibujar partícula
            if p.is_glyph and sz > 2.5:
                # aberración cromática: rojo (izq) + cyan (der) + color propio (centro)
                font = self._glyph_font

                s_red = AppKit.NSAttributedString.alloc().initWithString_attributes_(
                    p.glyph,
                    {AppKit.NSFontAttributeName: font,
                     AppKit.NSForegroundColorAttributeName:
                         AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 0.125, 0.376, a * 0.30)},
                )
                s_red.drawAtPoint_(AppKit.NSMakePoint(px - 1.5, py))

                s_cyan = AppKit.NSAttributedString.alloc().initWithString_attributes_(
                    p.glyph,
                    {AppKit.NSFontAttributeName: font,
                     AppKit.NSForegroundColorAttributeName:
                         AppKit.NSColor.colorWithRed_green_blue_alpha_(0.0, 1.0, 0.878, a * 0.30)},
                )
                s_cyan.drawAtPoint_(AppKit.NSMakePoint(px + 1.5, py))

                s_main = AppKit.NSAttributedString.alloc().initWithString_attributes_(
                    p.glyph,
                    {AppKit.NSFontAttributeName: font,
                     AppKit.NSForegroundColorAttributeName:
                         AppKit.NSColor.colorWithRed_green_blue_alpha_(cr, cg, cb, a)},
                )
                s_main.drawAtPoint_(AppKit.NSMakePoint(px, py))

            else:
                # glow dot: halo exterior + core + núcleo oscuro
                for glow_r, ga in ((sz * 4.0, 0.040), (sz * 2.2, 0.090)):
                    AppKit.NSColor.colorWithRed_green_blue_alpha_(cr, cg, cb, a * ga).set()
                    AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                        AppKit.NSMakeRect(px - glow_r, py - glow_r, glow_r * 2.0, glow_r * 2.0)
                    ).fill()

                AppKit.NSColor.colorWithRed_green_blue_alpha_(cr, cg, cb, a * 0.85).set()
                AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                    AppKit.NSMakeRect(px - sz, py - sz, sz * 2.0, sz * 2.0)
                ).fill()

                # núcleo oscuro (efecto ink / glass)
                cr_k = sz * 0.30
                AppKit.NSColor.colorWithRed_green_blue_alpha_(0.03, 0.03, 0.07, 0.70).set()
                AppKit.NSBezierPath.bezierPathWithOvalInRect_(
                    AppKit.NSMakeRect(px - cr_k, py - cr_k, cr_k * 2.0, cr_k * 2.0)
                ).fill()

        # ── Partículas fly_to (encima de la nube) ────────────────────────────
        if self._fly_particles is not None:
            self._fly_particles.draw()

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
