"""
gaze_trigger.py
───────────────
Monitor que activa Jarvis cuando el usuario mira a la cámara y habla,
sin necesidad de wake word ni hotkey.

Condiciones para activar:
  1. Cara centrada en cámara   (CameraContextAnalyzer.looking_at_camera)
  2. RMS del micrófono ≥ umbral (WakeWordListener.latest_rms)
  3. Ambas condiciones durante N chunks consecutivos (~0.3 s)

Usa el stream de audio del WakeWordListener (ya abierto) — no abre
un segundo stream de audio.

Requiere: pip install -e "[gestures]"  (MediaPipe + OpenCV)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)


# ── Config ───────────────────────────────────────────────────────────────────

@dataclass
class GazeTriggerConfig:
    enabled:            bool  = False
    rms_threshold:      float = 400.0   # int16 RMS mínimo para considerar "habla"
    cooldown:           float = 3.0     # segundos mínimos entre activaciones
    camera_index:       int   = 0       # índice de cámara (0 = frontal por defecto)
    consecutive_chunks: int   = 2       # chunks consecutivos requeridos (~0.3 s a 0.15 s/poll)
    debug:              bool  = False   # GAZE_DEBUG=true → ventana OpenCV con overlay


# ── Monitor ──────────────────────────────────────────────────────────────────

class GazeTriggerMonitor:
    """
    Hilo daemon que monitoriza cámara + micrófono.
    Cuando detecta cara + voz durante `consecutive_chunks` polls, llama `on_trigger`.

    Si MediaPipe/OpenCV no está instalado, desactiva la condición de cámara y
    activa solo por RMS de micrófono (menos preciso, pero funcional para pruebas).
    """

    def __init__(
        self,
        config: GazeTriggerConfig,
        wake_listener,              # WakeWordListener — fuente de latest_rms
        on_trigger: Callable[[], None],
    ) -> None:
        self._cfg          = config
        self._wake         = wake_listener
        self._on_trigger   = on_trigger
        self._running      = False
        self._thread: Optional[threading.Thread] = None
        self._camera_ctx   = None
        self._has_camera   = False

    # MARK: - Lifecycle

    def start(self) -> None:
        self._running  = True
        self._has_camera = self._init_camera()
        self._thread   = threading.Thread(
            target=self._loop, name="gaze-trigger", daemon=True
        )
        self._thread.start()

        camara = f"cámara {self._cfg.camera_index}" if self._has_camera else "sin cámara"
        log.info("GazeTriggerMonitor iniciado (RMS≥%.0f, cooldown=%.1fs, %s)",
                 self._cfg.rms_threshold, self._cfg.cooldown, camara)
        print(f"👁  Gaze trigger activo — RMS≥{self._cfg.rms_threshold:.0f}, {camara}")
        if not self._has_camera:
            print("   ⚠  Sin detección de cara: se activará solo por voz.")
            print("   Instala MediaPipe con: pip install -e '[gestures]'")

    def stop(self) -> None:
        self._running = False
        if self._camera_ctx is not None:
            try:
                self._camera_ctx.stop()
            except Exception:
                pass

    def get_debug_frame(self):
        """Devuelve el frame anotado para mostrar en el hilo principal. None si no hay."""
        if self._camera_ctx is None:
            return None
        return getattr(self._camera_ctx, "debug_frame", None)

    # MARK: - Camera setup

    def _init_camera(self) -> bool:
        """Intenta arrancar CameraContextAnalyzer. Devuelve True si OK."""
        try:
            from jarvis.vision.camera_context import (
                CameraContextAnalyzer,
                CameraContextConfig,
            )
            cfg = CameraContextConfig(
                enabled=True,
                camera_index=self._cfg.camera_index,
                interval_s=5.0,       # intervalo de análisis Groq (no se usa — face_only)
                face_only=True,       # solo detección de cara; sin gastar cuota de API
                groq_api_key="",
                debug=self._cfg.debug,
            )
            self._camera_ctx = CameraContextAnalyzer(cfg)
            self._camera_ctx.start()
            log.info("Cámara iniciada para gaze trigger (índice=%d)", self._cfg.camera_index)
            return True
        except ImportError:
            log.warning("MediaPipe no instalado — gaze trigger sin detección de cara")
            return False
        except Exception as exc:
            log.warning("No se pudo iniciar cámara para gaze trigger: %s", exc)
            return False

    # MARK: - Main loop

    def _loop(self) -> None:
        consecutive  = 0
        last_trigger = 0.0

        while self._running:
            time.sleep(0.15)

            # ── Cooldown entre activaciones ──────────────────────────────────
            if time.monotonic() - last_trigger < self._cfg.cooldown:
                consecutive = 0
                continue

            # ── Condición 1: cara mirando a la cámara ───────────────────────
            if self._has_camera and self._camera_ctx is not None:
                if not self._camera_ctx.looking_at_camera:
                    consecutive = 0
                    continue

            # ── Condición 2: voz en el micrófono (RMS del wake listener) ────
            rms = getattr(self._wake, "latest_rms", 0.0)
            if rms >= self._cfg.rms_threshold:
                consecutive += 1
                if consecutive >= self._cfg.consecutive_chunks:
                    consecutive  = 0
                    last_trigger = time.monotonic()
                    face_str     = "cara + " if self._has_camera else ""
                    log.info("👁 Gaze trigger: %svoz (RMS=%.0f)", face_str, rms)
                    print(f"\n👁  Gaze trigger — {face_str}voz detectada (RMS={rms:.0f})")
                    try:
                        self._on_trigger()
                    except Exception as exc:
                        log.error("on_trigger error: %s", exc)
            else:
                consecutive = 0
