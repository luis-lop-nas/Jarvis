"""
swift_bridge.py
──────────────
Reemplaza el OverlayBridge de PyObjC para comunicarse con el overlay Swift.
Misma interfaz que bridge.py — el daemon.py no necesita cambios.

Uso en daemon.py:
    from jarvis.overlay.swift_bridge import SwiftOverlayBridge as OverlayBridge

Seguridad:
- Autenticación por token: cada mensaje incluye un `token` generado al inicio
  del proceso daemon. El token se escribe en ~/.jarvis/ipc.token (chmod 600)
  para que el overlay Swift pueda leerlo y validarlo.
- Límite de tamaño de mensaje: MAX_MESSAGE_BYTES = 65536 (64 KB). Mensajes
  más grandes son descartados para prevenir DoS.
- Validación de campos: todos los valores se validan antes de serializar.
"""

import json
import os
import secrets
import socket
import subprocess
import threading
import time
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SOCKET_PATH = "/tmp/jarvis_overlay.sock"
OVERLAY_APP = (
    Path(__file__).parent.parent.parent.parent
    / "JarvisOverlay"
    / "build"
    / "JarvisOverlay.app"
)

# Límite de tamaño de mensaje (64 KB). Mensajes más grandes indican un bug
# o un intento de explotar el canal IPC.
MAX_MESSAGE_BYTES = 65_536

# Directorio y fichero del token IPC (solo lectura por el propietario del proceso)
_TOKEN_DIR = Path.home() / ".jarvis"
_TOKEN_FILE = _TOKEN_DIR / "ipc.token"

# Estados válidos del overlay
_VALID_STATES = {"idle", "listening", "thinking", "acting", "error"}


def _generate_and_save_token() -> str:
    """
    Genera un token criptográficamente seguro y lo persiste en ~/.jarvis/ipc.token
    con permisos 0600 (solo el propietario puede leerlo).
    """
    token = secrets.token_hex(32)
    _TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    # Escribir con permisos restrictivos: solo el dueño puede leer/escribir
    _TOKEN_FILE.write_text(token)
    _TOKEN_FILE.chmod(0o600)
    return token


class SwiftOverlayBridge:
    """
    Puente IPC entre Python daemon y el overlay Swift/Metal.
    Manda comandos JSON autenticados por Unix Domain Socket.

    Seguridad:
    - Token aleatorio incluido en cada mensaje (generado al instanciar).
    - Validación de tipos y valores de todos los campos antes de enviar.
    - Límite de 64 KB por mensaje para prevenir DoS.
    - Socket descriptor heredado protegido por permisos del proceso.
    """

    def __init__(self) -> None:
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._connected = False
        self._overlay_process: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        # Token de autenticación: generado una vez por proceso
        self._token: str = _generate_and_save_token()
        logger.debug("IPC token generado y guardado en %s", _TOKEN_FILE)

    # ─────────────────────────────────────────────
    # Arrancar el overlay Swift
    # ─────────────────────────────────────────────
    def launch_overlay(self) -> None:
        """Lanza JarvisOverlay.app si no está corriendo."""
        app_path = str(OVERLAY_APP)
        if not Path(app_path).exists():
            logger.warning("Overlay app no encontrada en %s", app_path)
            return

        self._overlay_process = subprocess.Popen(
            ["open", "-a", app_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Esperar a que el socket esté disponible (máximo 3 s)
        for _ in range(30):
            if Path(SOCKET_PATH).exists():
                break
            time.sleep(0.1)

        self._connect()

    # ─────────────────────────────────────────────
    # Conectar al socket
    # ─────────────────────────────────────────────
    def _connect(self) -> None:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(5.0)
            s.connect(SOCKET_PATH)
            self._sock = s
            self._connected = True
            logger.info("Conectado al overlay Swift")
        except Exception as e:
            logger.warning("No se pudo conectar al overlay Swift: %s", e)
            self._connected = False

    def _send(self, cmd: Dict[str, Any]) -> None:
        """
        Envía un comando JSON autenticado al overlay. Thread-safe.

        Siempre incluye el token de autenticación. Descarta mensajes que
        superan MAX_MESSAGE_BYTES para prevenir DoS.
        """
        if not self._connected:
            self._connect()
        if not self._connected:
            return

        # Inyectar token en cada mensaje
        cmd_with_token = {"token": self._token, **cmd}

        try:
            line = json.dumps(cmd_with_token, ensure_ascii=False) + "\n"
        except (TypeError, ValueError) as e:
            logger.error("No se pudo serializar el comando IPC: %s | cmd=%s", e, cmd)
            return

        encoded = line.encode("utf-8")
        if len(encoded) > MAX_MESSAGE_BYTES:
            logger.error(
                "Mensaje IPC descartado: tamaño %d > límite %d bytes. action=%s",
                len(encoded),
                MAX_MESSAGE_BYTES,
                cmd.get("action", "?"),
            )
            return

        try:
            with self._lock:
                self._sock.sendall(encoded)  # type: ignore[union-attr]
        except Exception as e:
            logger.warning("Error enviando al overlay: %s", e)
            self._connected = False

    # ─────────────────────────────────────────────
    # API pública — validada antes de enviar
    # ─────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        """state: 'idle' | 'listening' | 'thinking' | 'acting' | 'error'"""
        state = str(state).strip().lower()
        if state not in _VALID_STATES:
            logger.warning("set_state: estado no válido '%s' — ignorado", state)
            return
        self._send({"action": "set_state", "state": state})

    def say(self, text: str, duration: float = 4.0) -> None:
        """Mostrar texto en el HUD. text se trunca a 2000 chars."""
        text = str(text)[:2000]
        duration = float(max(0.1, min(duration, 60.0)))
        self._send({"action": "say", "text": text, "duration": duration})

    def hide_hud(self) -> None:
        self._send({"action": "hide_hud"})

    def fly_to(self, x: float, y: float) -> None:
        """Volar la entidad a una posición (ej: icono del Dock)."""
        x = float(x)
        y = float(y)
        self._send({"action": "fly_to", "x": x, "y": y})

    def wrap_window(self, x: float, y: float, width: float, height: float) -> None:
        """Rodear el borde de una ventana."""
        x, y, width, height = float(x), float(y), float(width), float(height)
        if width <= 0 or height <= 0:
            logger.warning("wrap_window: dimensiones no válidas (%s, %s)", width, height)
            return
        self._send({
            "action": "wrap_window",
            "rect": {"x": x, "y": y, "width": width, "height": height},
        })

    def return_home(self) -> None:
        """Volver la entidad a la posición de reposo."""
        self._send({"action": "return_home"})

    def run_on_main_thread(self, fn: Any) -> None:
        """Compatibilidad con OverlayBridge — simplemente ejecuta fn."""
        fn()

    def stop(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        if self._overlay_process:
            self._overlay_process.terminate()
        # Eliminar token al apagar
        try:
            _TOKEN_FILE.unlink(missing_ok=True)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────
# Singleton — igual que en bridge.py
# ─────────────────────────────────────────────────────────
_bridge: Optional[SwiftOverlayBridge] = None


def get_bridge() -> SwiftOverlayBridge:
    global _bridge
    if _bridge is None:
        _bridge = SwiftOverlayBridge()
    return _bridge
