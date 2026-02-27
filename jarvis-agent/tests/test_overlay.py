"""
test_overlay.py

Prueba standalone del overlay — sin voz, sin LLM, sin nada.
Muestra el orb en pantalla, cicla por todos los estados cada 2s
y lanza partículas hacia varias esquinas de la pantalla.

Ejecutar:
  cd jarvis-agent
  source .venv/bin/activate
  PYTHONPATH=src python tests/test_overlay.py

Para salir: Ctrl+C o Cmd+Q
"""

from __future__ import annotations

import signal
import sys
import threading
import time

import AppKit

sys.path.insert(0, "src")

from jarvis.overlay.window    import JarvisWindow
from jarvis.overlay.view      import JarvisView
from jarvis.overlay.bridge    import OverlayBridge
from jarvis.overlay.particles import ParticleSystem


# ── Secuencia de demo ─────────────────────────────────────────────────────────

def demo(bridge: OverlayBridge, screen_w: float, screen_h: float) -> None:
    """Cicla estados y lanza partículas a las esquinas."""

    time.sleep(0.5)  # dar tiempo al runloop

    steps = [
        # (estado, mensaje, fly_to destino o None)
        ("idle",      "idle",      None),
        ("listening", "listening", None),
        ("thinking",  "thinking",  None),
        ("acting",    "acting",    (screen_w * 0.85, screen_h * 0.85)),  # arriba-derecha
        ("idle",      "fly centro",(screen_w * 0.50, screen_h * 0.50)),  # centro
        ("acting",    "fly dock",  (screen_w * 0.50, 40.0)),             # dock (abajo-centro)
        ("idle",      "idle final",None),
    ]

    for state, label, target in steps:
        print(f"  → {label}")
        bridge.set_state(state)
        if target:
            tx, ty = target
            bridge.fly_to(tx, ty, callback=lambda lbl=label: print(f"    ✓ callback: {lbl}"))
        time.sleep(2.5)

    bridge.set_state("idle")
    print("\n✅ Demo completada. Orb en idle. Cierra con Cmd+Q o Ctrl+C.\n")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    signal.signal(signal.SIGINT, lambda *_: AppKit.NSApplication.sharedApplication().terminate_(None))

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    screen = AppKit.NSScreen.mainScreen()
    frame  = screen.frame()
    sw, sh = frame.size.width, frame.size.height

    # Overlay
    view      = JarvisView.alloc().initWithFrame_(frame)
    _window   = JarvisWindow(view)

    # Partículas
    particles = ParticleSystem(view)
    view.attach_particles(particles)

    # Bridge (con partículas)
    bridge = OverlayBridge()
    bridge.attach(view, particles)

    print("\n🔵 Overlay activo.")
    print(f"   Pantalla: {int(sw)}×{int(sh)}")
    print("   Orb en esquina inferior-izquierda.\n")

    t = threading.Thread(target=demo, args=(bridge, sw, sh), daemon=True)
    t.start()

    app.run()


if __name__ == "__main__":
    main()
