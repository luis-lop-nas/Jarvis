"""
bridge.py

Cola de eventos thread-safe entre el daemon (LLM, voz, tools)
y el overlay visual (NSWindow, NSView).

El daemon pone eventos en la cola desde cualquier thread.
Un NSTimer en el hilo principal consume la cola y actualiza la UI.

Eventos soportados:
  {"type": "state",  "value": "idle|listening|thinking|acting"}
  {"type": "fly_to", "x": float, "y": float, "callback": fn|None}
  {"type": "move",   "x": float, "y": float}
  {"type": "_fn",    "fn": callable}   # función arbitraria en hilo principal
"""

from __future__ import annotations

import queue
import threading
from typing import Callable, Optional

import AppKit


class OverlayBridge:
    """IPC thread-safe entre daemon y overlay."""

    def __init__(self) -> None:
        self._q: queue.Queue[dict] = queue.Queue()
        self._view = None
        self._particles = None
        self._notch = None
        self._pump_timer: Optional[AppKit.NSTimer] = None
        self._state_name: str = "idle"

    # ------------------------------------------------------------------
    # Inicialización (hilo principal)
    # ------------------------------------------------------------------

    def attach(self, view, particles=None) -> None:
        """
        Conectar bridge con la view y el sistema de partículas.
        Llamar desde el hilo principal DESPUÉS de crear el overlay.
        """
        self._view = view
        self._particles = particles

    def attach_notch(self, notch) -> None:
        """Conectar el NotchPanel para recibir state y audio_level."""
        self._notch = notch

        # Timer que vacía la cola cada 50ms en el hilo principal
        self._pump_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.05, self._PumpTarget.new(), "pump:", self, True
        )

    # ------------------------------------------------------------------
    # API para el daemon (thread-safe — puede llamarse desde cualquier thread)
    # ------------------------------------------------------------------

    def set_state(self, state: str) -> None:
        """Cambiar el estado visual del orb: idle | listening | thinking | acting."""
        self._state_name = state
        self._q.put({"type": "state", "value": state})

    @property
    def state_name(self) -> str:
        """Último estado solicitado del orb."""
        return self._state_name

    def fly_to(self, x: float, y: float, callback: Optional[Callable] = None) -> None:
        """Animar partículas desde el orb hasta (x, y). Llama callback al terminar."""
        self._q.put({"type": "fly_to", "x": x, "y": y, "callback": callback})

    def move_orb(self, x: float, y: float) -> None:
        """Mover el orb a nueva posición en pantalla."""
        self._q.put({"type": "move", "x": x, "y": y})

    def run_on_main_thread(self, fn: Callable) -> None:
        """Ejecutar fn() en el hilo principal (en el próximo ciclo del timer, ≤50ms)."""
        self._q.put({"type": "_fn", "fn": fn})

    def set_audio_level(self, level: float) -> None:
        """Enviar nivel de audio (0.0–1.0) al orb para el VU meter."""
        self._q.put({"type": "audio_level", "value": max(0.0, min(1.0, level))})

    # ------------------------------------------------------------------
    # Procesado en hilo principal (llamado por el timer)
    # ------------------------------------------------------------------

    def _process_queue(self) -> None:
        try:
            while True:
                event = self._q.get_nowait()
                self._dispatch(event)
        except queue.Empty:
            pass

    def _dispatch(self, event: dict) -> None:
        t = event["type"]

        if t == "state":
            if self._view is not None:
                self._view.set_state(event["value"])
            if self._notch is not None:
                self._notch.set_state(event["value"])

        elif t == "move" and self._view is not None:
            self._view.set_position(event["x"], event["y"])

        elif t == "fly_to":
            if self._particles is not None:
                self._particles.fly_to(event["x"], event["y"], event.get("callback"))
            elif event.get("callback"):
                threading.Thread(target=event["callback"], daemon=True).start()

        elif t == "audio_level":
            if self._view is not None:
                self._view.set_audio_level(event["value"])
            if self._notch is not None:
                self._notch.set_audio_level(event["value"])

        elif t == "_fn":
            try:
                event["fn"]()
            except Exception as e:
                print(f"⚠️ run_on_main_thread error: {e}")

    # ------------------------------------------------------------------
    # Clase auxiliar como target del NSTimer (necesita ser un NSObject)
    # ------------------------------------------------------------------

    class _PumpTarget(AppKit.NSObject):
        def pump_(self, timer: AppKit.NSTimer) -> None:
            bridge: OverlayBridge = timer.userInfo()
            if bridge is not None:
                bridge._process_queue()
