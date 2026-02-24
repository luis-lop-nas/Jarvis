"""
jarvis_swift_bridge.py
──────────────────────
Reemplaza el OverlayBridge de PyObjC para comunicarse con el overlay Swift.
Misma interfaz que bridge.py — el daemon.py no necesita cambios.

Uso en daemon.py:
    from jarvis.overlay.swift_bridge import SwiftOverlayBridge as OverlayBridge
"""

import json
import socket
import subprocess
import time
import threading
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SOCKET_PATH = "/tmp/jarvis_overlay.sock"
OVERLAY_APP  = Path(__file__).parent.parent.parent.parent / "JarvisOverlay" / "build" / "JarvisOverlay.app"


class SwiftOverlayBridge:
    """
    Puente IPC entre Python daemon y el overlay Swift/Metal.
    Manda comandos JSON por Unix Domain Socket.
    """

    def __init__(self):
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._connected = False
        self._overlay_process: subprocess.Popen | None = None

    # ─────────────────────────────────────────────
    # Arrancar el overlay Swift
    # ─────────────────────────────────────────────
    def launch_overlay(self):
        """Lanza JarvisOverlay.app si no está corriendo."""
        app_path = str(OVERLAY_APP)
        if not Path(app_path).exists():
            logger.warning(f"Overlay app no encontrada en {app_path}")
            return

        self._overlay_process = subprocess.Popen(
            ["open", "-a", app_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        # Esperar a que el socket esté disponible
        for _ in range(30):  # hasta 3 segundos
            if Path(SOCKET_PATH).exists():
                break
            time.sleep(0.1)

        self._connect()

    # ─────────────────────────────────────────────
    # Conectar al socket
    # ─────────────────────────────────────────────
    def _connect(self):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(SOCKET_PATH)
            self._sock = s
            self._connected = True
            logger.info("✅ Conectado al overlay Swift")
        except Exception as e:
            logger.warning(f"No se pudo conectar al overlay Swift: {e}")
            self._connected = False

    def _send(self, cmd: dict):
        """Envía un comando JSON al overlay. Thread-safe."""
        if not self._connected:
            self._connect()
        if not self._connected:
            return
        try:
            with self._lock:
                line = json.dumps(cmd) + "\n"
                self._sock.sendall(line.encode())
        except Exception as e:
            logger.warning(f"Error enviando al overlay: {e}")
            self._connected = False

    # ─────────────────────────────────────────────
    # API pública — misma interfaz que OverlayBridge
    # ─────────────────────────────────────────────
    def set_state(self, state: str):
        """state: 'idle' | 'listening' | 'thinking' | 'acting'"""
        self._send({"action": "set_state", "state": state})

    def say(self, text: str, duration: float = 4.0):
        """Mostrar texto en el HUD."""
        self._send({"action": "say", "text": text, "duration": duration})

    def hide_hud(self):
        self._send({"action": "hide_hud"})

    def fly_to(self, x: float, y: float):
        """Volar la entidad a una posición (ej: icono del Dock)."""
        self._send({"action": "fly_to", "x": x, "y": y})

    def wrap_window(self, x: float, y: float, width: float, height: float):
        """Rodear el borde de una ventana."""
        self._send({
            "action": "wrap_window",
            "rect": {"x": x, "y": y, "width": width, "height": height}
        })

    def return_home(self):
        """Volver la entidad a la posición de reposo."""
        self._send({"action": "return_home"})

    def run_on_main_thread(self, fn):
        """Compatibilidad con OverlayBridge — simplemente ejecuta fn."""
        fn()

    def stop(self):
        if self._sock:
            self._sock.close()
        if self._overlay_process:
            self._overlay_process.terminate()


# ─────────────────────────────────────────────────────────
# Singleton — igual que en bridge.py
# ─────────────────────────────────────────────────────────
_bridge: SwiftOverlayBridge | None = None

def get_bridge() -> SwiftOverlayBridge:
    global _bridge
    if _bridge is None:
        _bridge = SwiftOverlayBridge()
    return _bridge
