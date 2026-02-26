"""
tests/test_ipc_bridge.py

Tests unitarios para SwiftOverlayBridge:
- Conexión cuando el overlay no está activo
- Mensajes malformados / campos inválidos
- Límite de tamaño de mensaje
- Autenticación: token incluido en mensajes
- Reconexión automática
"""
from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from jarvis.overlay.swift_bridge import (
    MAX_MESSAGE_BYTES,
    SwiftOverlayBridge,
    _TOKEN_FILE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_bridge() -> SwiftOverlayBridge:
    """Crea un bridge sin conectar al socket real."""
    with patch("jarvis.overlay.swift_bridge._generate_and_save_token", return_value="test-token-abc"):
        bridge = SwiftOverlayBridge()
    bridge._connected = False
    return bridge


def _connected_bridge() -> tuple[SwiftOverlayBridge, MagicMock]:
    """Crea un bridge con socket mock conectado."""
    bridge = _make_bridge()
    mock_sock = MagicMock()
    bridge._sock = mock_sock
    bridge._connected = True
    return bridge, mock_sock


# ─────────────────────────────────────────────────────────────────────────────
# Inicialización
# ─────────────────────────────────────────────────────────────────────────────

class TestBridgeInit:
    def test_token_generated_on_init(self):
        with patch("jarvis.overlay.swift_bridge._generate_and_save_token",
                   return_value="mytoken") as mock_gen:
            bridge = SwiftOverlayBridge()
            mock_gen.assert_called_once()
            assert bridge._token == "mytoken"

    def test_starts_disconnected(self):
        bridge = _make_bridge()
        assert bridge._connected is False

    def test_token_file_permissions(self, tmp_path):
        """El token debe escribirse con permisos 0600."""
        token_path = tmp_path / "ipc.token"
        with patch("jarvis.overlay.swift_bridge._TOKEN_FILE", token_path):
            with patch("jarvis.overlay.swift_bridge._TOKEN_DIR", tmp_path):
                bridge = SwiftOverlayBridge()
        if token_path.exists():
            mode = oct(token_path.stat().st_mode)[-3:]
            assert mode == "600", f"Permisos incorrectos: {mode}"


# ─────────────────────────────────────────────────────────────────────────────
# Conexión
# ─────────────────────────────────────────────────────────────────────────────

class TestConnection:
    def test_connect_fails_gracefully_when_no_socket(self):
        """Si no hay socket en /tmp, debe fallar sin excepción no controlada."""
        bridge = _make_bridge()
        # Forzar que el socket no exista
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_sock.connect.side_effect = FileNotFoundError("No such file")
            mock_socket_cls.return_value = mock_sock
            bridge._connect()
        assert bridge._connected is False

    def test_connect_fails_gracefully_on_refused(self):
        bridge = _make_bridge()
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_sock.connect.side_effect = ConnectionRefusedError("refused")
            mock_socket_cls.return_value = mock_sock
            bridge._connect()
        assert bridge._connected is False

    def test_reconnects_when_send_fails(self):
        """Si sendall falla, _connected se pone a False para forzar reconexión."""
        bridge, mock_sock = _connected_bridge()
        mock_sock.sendall.side_effect = BrokenPipeError("pipe broken")
        bridge._send({"action": "hide_hud"})
        assert bridge._connected is False

    def test_send_skipped_when_not_connected_and_reconnect_fails(self):
        """Si no hay conexión y la reconexión falla, _send no levanta excepción."""
        bridge = _make_bridge()
        with patch.object(bridge, "_connect"):  # connect no hace nada
            bridge._send({"action": "hide_hud"})  # no debe lanzar


# ─────────────────────────────────────────────────────────────────────────────
# Autenticación por token
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenAuth:
    def test_token_included_in_every_message(self):
        bridge, mock_sock = _connected_bridge()
        bridge._token = "super-secret-token"

        bridge.set_state("idle")

        call_args = mock_sock.sendall.call_args[0][0]
        msg = json.loads(call_args.decode().strip())
        assert msg.get("token") == "super-secret-token"

    def test_token_in_say_message(self):
        bridge, mock_sock = _connected_bridge()
        bridge._token = "abc123"

        bridge.say("hola", duration=3.0)

        data = mock_sock.sendall.call_args[0][0]
        msg = json.loads(data.decode().strip())
        assert msg["token"] == "abc123"
        assert msg["action"] == "say"

    def test_token_in_fly_to_message(self):
        bridge, mock_sock = _connected_bridge()
        bridge._token = "tok"

        bridge.fly_to(100.0, 200.0)

        data = mock_sock.sendall.call_args[0][0]
        msg = json.loads(data.decode().strip())
        assert msg["token"] == "tok"
        assert msg["action"] == "fly_to"


# ─────────────────────────────────────────────────────────────────────────────
# Validación de campos
# ─────────────────────────────────────────────────────────────────────────────

class TestFieldValidation:
    def test_invalid_state_ignored(self):
        bridge, mock_sock = _connected_bridge()
        bridge.set_state("invalid_state_xyz")
        mock_sock.sendall.assert_not_called()

    def test_valid_states_accepted(self):
        bridge, mock_sock = _connected_bridge()
        for state in ("idle", "listening", "thinking", "acting", "error"):
            mock_sock.reset_mock()
            bridge.set_state(state)
            mock_sock.sendall.assert_called_once()

    def test_say_truncates_long_text(self):
        bridge, mock_sock = _connected_bridge()
        long_text = "x" * 5000
        bridge.say(long_text)
        data = mock_sock.sendall.call_args[0][0]
        msg = json.loads(data.decode().strip())
        assert len(msg["text"]) == 2000

    def test_say_clamps_duration(self):
        bridge, mock_sock = _connected_bridge()
        bridge.say("hola", duration=9999.0)
        data = mock_sock.sendall.call_args[0][0]
        msg = json.loads(data.decode().strip())
        assert msg["duration"] <= 60.0

    def test_wrap_window_blocks_invalid_dimensions(self):
        bridge, mock_sock = _connected_bridge()
        bridge.wrap_window(0.0, 0.0, -10.0, 0.0)  # width negativo
        mock_sock.sendall.assert_not_called()

    def test_wrap_window_valid(self):
        bridge, mock_sock = _connected_bridge()
        bridge.wrap_window(10.0, 20.0, 100.0, 200.0)
        mock_sock.sendall.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Límite de tamaño de mensaje
# ─────────────────────────────────────────────────────────────────────────────

class TestMessageSizeLimit:
    def test_oversized_message_not_sent(self):
        bridge, mock_sock = _connected_bridge()

        # Construir un mensaje que supere MAX_MESSAGE_BYTES
        huge_text = "A" * (MAX_MESSAGE_BYTES + 100)
        # Inyectamos directamente en _send para evitar el truncado de say()
        bridge._send({"action": "say", "text": huge_text, "duration": 1.0})

        mock_sock.sendall.assert_not_called()

    def test_normal_message_sent(self):
        bridge, mock_sock = _connected_bridge()
        bridge._send({"action": "hide_hud"})
        mock_sock.sendall.assert_called_once()

    def test_max_bytes_constant_is_reasonable(self):
        assert 1024 <= MAX_MESSAGE_BYTES <= 1024 * 1024  # entre 1KB y 1MB


# ─────────────────────────────────────────────────────────────────────────────
# stop() limpia el token
# ─────────────────────────────────────────────────────────────────────────────

class TestStop:
    def test_stop_closes_socket(self):
        bridge, mock_sock = _connected_bridge()
        bridge.stop()
        mock_sock.close.assert_called_once()

    def test_stop_removes_token_file(self, tmp_path):
        token_path = tmp_path / "ipc.token"
        token_path.write_text("token123")
        bridge = _make_bridge()
        with patch("jarvis.overlay.swift_bridge._TOKEN_FILE", token_path):
            bridge.stop()
        assert not token_path.exists()

    def test_stop_handles_missing_token_gracefully(self):
        bridge = _make_bridge()
        # No debe lanzar aunque el fichero no exista
        with patch("jarvis.overlay.swift_bridge._TOKEN_FILE", Path("/nonexistent/path/token")):
            bridge.stop()  # no lanza
