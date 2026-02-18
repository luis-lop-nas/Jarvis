"""
test_overlay_daemon.py

Prueba del overlay CON el daemon completo:
  - Overlay visual (orb + partículas)
  - LLM + STT + TTS
  - Wake word ("hey jarvis") + hotkey (Ctrl+Space)

Ejecutar:
  cd jarvis-agent
  source .venv/bin/activate
  PYTHONPATH=src python tests/test_overlay_daemon.py

Para salir: Ctrl+C o Cmd+Q
"""

from __future__ import annotations

import signal
import sys

import AppKit

sys.path.insert(0, "src")

from jarvis.overlay.window    import JarvisWindow
from jarvis.overlay.view      import JarvisView
from jarvis.overlay.bridge    import OverlayBridge
from jarvis.overlay.particles import ParticleSystem
from jarvis.overlay.daemon    import build_daemon


def main() -> None:
    signal.signal(
        signal.SIGINT,
        lambda *_: AppKit.NSApplication.sharedApplication().terminate_(None),
    )

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    screen = AppKit.NSScreen.mainScreen()
    frame  = screen.frame()
    sw, sh = frame.size.width, frame.size.height

    # ── Overlay ──────────────────────────────────────────────────────────────
    view      = JarvisView.alloc().initWithFrame_(frame)
    _window   = JarvisWindow(view)

    particles = ParticleSystem(view)
    view.attach_particles(particles)

    bridge = OverlayBridge()
    bridge.attach(view, particles)

    # ── Daemon ───────────────────────────────────────────────────────────────
    daemon = build_daemon(bridge, sw, sh)
    daemon.start()

    print("\n🔵 Jarvis Desktop activo.")
    print(f"   Pantalla: {int(sw)}×{int(sh)}")
    print("   Di «Hey Jarvis» o pulsa Ctrl+Space para hablar.\n")

    # AppKit runloop — bloquea aquí
    app.run()

    # Al salir
    daemon.stop()


if __name__ == "__main__":
    main()
