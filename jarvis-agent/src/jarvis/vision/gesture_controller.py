"""
gesture_controller.py

Control de JARVIS por gestos de mano usando la cámara del MacBook.

Gestos reconocidos:
  - Puño cerrado      → interrumpir JARVIS (para TTS/grabación en curso)
  - Palma abierta     → pausar / reanudar escucha
  - Pinch             → confirmar acción pendiente
  - V (dos dedos ↑)   → activar modo voz sin wake word
  - Pulgar arriba     → "sí" / confirmar
  - Pulgar abajo      → "no" / cancelar

Requisitos:
    pip install mediapipe opencv-python

Uso típico:
    ctrl = GestureController(
        cfg=GestureConfig(enabled=True, debug=False),
        on_interrupt=daemon.interrupt,
        on_pause=daemon.pause_gesture,
        on_resume=daemon.resume_gesture,
        on_confirm=lambda: daemon.submit_text("sí, confirmo"),
        on_voice=daemon.trigger_voice_input,
        on_yes=lambda: daemon.submit_text("sí"),
        on_no=lambda: daemon.submit_text("no, cancela"),
    )
    ctrl.start()
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Tipos y enumeraciones
# ---------------------------------------------------------------------------

class GestureEvent(str, Enum):
    FIST       = "fist"        # puño cerrado
    OPEN_PALM  = "open_palm"   # palma abierta
    PINCH      = "pinch"       # pinch pulgar+índice
    V_SIGN     = "v_sign"      # dos dedos (V)
    THUMB_UP   = "thumb_up"    # pulgar arriba
    THUMB_DOWN = "thumb_down"  # pulgar abajo


@dataclass
class GestureConfig:
    """Configuración del controlador de gestos."""
    enabled: bool       = False
    cooldown_sec: float = 1.5    # mínimo entre gestos consecutivos
    debug: bool         = False  # mostrar feed de cámara con landmarks
    camera_index: int   = 0      # índice de cámara (0 = FaceTime MacBook)
    stable_frames: int  = 5      # frames consecutivos para confirmar gesto
    # MediaPipe
    min_detection_confidence: float = 0.75
    min_tracking_confidence: float  = 0.55


# ---------------------------------------------------------------------------
# Protocolo de landmark (compatible con mediapipe y con mocks en tests)
# ---------------------------------------------------------------------------

class _LM:
    """Tipo minimal para type hints: landmark con x, y, z normalizados."""
    x: float
    y: float
    z: float


# ---------------------------------------------------------------------------
# Detección de gestos (funciones puras, sin dependencias externas)
# ---------------------------------------------------------------------------

# Índices de landmarks de MediaPipe Hands
_WRIST      = 0
_THUMB_CMC  = 1
_THUMB_MCP  = 2
_THUMB_IP   = 3
_THUMB_TIP  = 4
_INDEX_MCP  = 5
_INDEX_PIP  = 6
_INDEX_TIP  = 8
_MIDDLE_MCP = 9
_MIDDLE_PIP = 10
_MIDDLE_TIP = 12
_RING_MCP   = 13
_RING_PIP   = 14
_RING_TIP   = 16
_PINKY_MCP  = 17
_PINKY_PIP  = 18
_PINKY_TIP  = 20

_TIPS = [_THUMB_TIP, _INDEX_TIP, _MIDDLE_TIP, _RING_TIP, _PINKY_TIP]
_PIPS = [_THUMB_IP,  _INDEX_PIP, _MIDDLE_PIP, _RING_PIP, _PINKY_PIP]
_MCPS = [_THUMB_CMC, _INDEX_MCP, _MIDDLE_MCP, _RING_MCP, _PINKY_MCP]


def fingers_up(landmarks: Sequence[Any], handedness: str = "Right") -> List[bool]:
    """
    Determina qué dedos están extendidos.

    Args:
        landmarks: secuencia de 21 landmarks (objetos con .x, .y, .z).
        handedness: "Right" o "Left" según MediaPipe.

    Returns:
        Lista de 5 bool: [pulgar, índice, medio, anular, meñique].
        True = extendido.
    """
    lm = landmarks
    result: List[bool] = []

    # ── Pulgar ────────────────────────────────────────────────────────────────
    # Compara la posición horizontal del tip vs IP según la mano.
    # En la imagen de cámara (espejo), la mano "Right" de MediaPipe aparece
    # como la mano izquierda del usuario.
    if handedness == "Right":
        # Para mano derecha (en espejo = izquierda del usuario):
        # pulgar extendido → tip.x < ip.x
        result.append(lm[_THUMB_TIP].x < lm[_THUMB_IP].x)
    else:
        # Para mano izquierda (en espejo = derecha del usuario):
        # pulgar extendido → tip.x > ip.x
        result.append(lm[_THUMB_TIP].x > lm[_THUMB_IP].x)

    # ── Cuatro dedos restantes ───────────────────────────────────────────────
    # Extendido si tip.y < pip.y (coordenadas normalizadas: 0=arriba, 1=abajo)
    for tip_i, pip_i in zip(_TIPS[1:], _PIPS[1:]):
        result.append(lm[tip_i].y < lm[pip_i].y)

    return result  # [thumb, index, middle, ring, pinky]


def pinch_distance(landmarks: Sequence[Any]) -> float:
    """Distancia normalizada entre pulgar tip e índice tip (0–√2)."""
    dx = landmarks[_THUMB_TIP].x - landmarks[_INDEX_TIP].x
    dy = landmarks[_THUMB_TIP].y - landmarks[_INDEX_TIP].y
    return math.hypot(dx, dy)


def detect_gesture(
    landmarks: Sequence[Any],
    handedness: str = "Right",
    pinch_threshold: float = 0.06,
) -> Optional[GestureEvent]:
    """
    Clasifica el gesto actual de la mano.

    Args:
        landmarks: 21 landmarks de MediaPipe Hands.
        handedness: "Right" o "Left".
        pinch_threshold: distancia máxima pulgar–índice para considerar pinch.

    Returns:
        GestureEvent o None si no se reconoce ningún gesto con certeza.
    """
    lm = landmarks
    thumb, index, middle, ring, pinky = fingers_up(lm, handedness)

    # ── Pinch (pulgar + índice juntos) — prioridad máxima ───────────────────
    dist = pinch_distance(lm)
    if dist < pinch_threshold:
        return GestureEvent.PINCH

    # ── Pulgar arriba/abajo — antes que FIST para no confundir ───────────────
    # Solo pulgar extendido (lateralmente), 4 dedos doblados
    if not index and not middle and not ring and not pinky:
        # Requiere que el pulgar esté extendido en el eje X (fingers_up lo indica)
        if thumb:
            thumb_tip_y = lm[_THUMB_TIP].y
            thumb_cmc_y = lm[_THUMB_CMC].y
            vertical_span = abs(thumb_tip_y - thumb_cmc_y)

            if vertical_span >= 0.06:
                # Tip significativamente por encima de CMC → pulgar arriba
                if thumb_tip_y < thumb_cmc_y - 0.04:
                    return GestureEvent.THUMB_UP
                # Tip significativamente por debajo de CMC → pulgar abajo
                if thumb_tip_y > thumb_cmc_y + 0.04:
                    return GestureEvent.THUMB_DOWN

        # Pulgar no extendido o dirección ambigua → puño cerrado
        return GestureEvent.FIST

    # ── Palma abierta (los 5 dedos extendidos) ───────────────────────────────
    if thumb and index and middle and ring and pinky:
        return GestureEvent.OPEN_PALM

    # ── V / Dos dedos arriba (índice + medio, resto doblados) ────────────────
    if index and middle and not ring and not pinky:
        return GestureEvent.V_SIGN

    return None


# ---------------------------------------------------------------------------
# Controlador principal
# ---------------------------------------------------------------------------

class GestureController:
    """
    Controlador de gestos de mano. Corre en un thread daemon separado.

    Parámetros de callback:
        on_interrupt  : () → None   — puño cerrado
        on_pause      : () → None   — palma abierta (primer toggle)
        on_resume     : () → None   — palma abierta (segundo toggle)
        on_confirm    : () → None   — pinch
        on_voice      : () → None   — V sign
        on_yes        : () → None   — pulgar arriba
        on_no         : () → None   — pulgar abajo
    """

    def __init__(
        self,
        cfg: GestureConfig,
        on_interrupt: Optional[Callable[[], None]] = None,
        on_pause:     Optional[Callable[[], None]] = None,
        on_resume:    Optional[Callable[[], None]] = None,
        on_confirm:   Optional[Callable[[], None]] = None,
        on_voice:     Optional[Callable[[], None]] = None,
        on_yes:       Optional[Callable[[], None]] = None,
        on_no:        Optional[Callable[[], None]] = None,
    ) -> None:
        self.cfg = cfg

        self._on_interrupt = on_interrupt or (lambda: None)
        self._on_pause     = on_pause     or (lambda: None)
        self._on_resume    = on_resume    or (lambda: None)
        self._on_confirm   = on_confirm   or (lambda: None)
        self._on_voice     = on_voice     or (lambda: None)
        self._on_yes       = on_yes       or (lambda: None)
        self._on_no        = on_no        or (lambda: None)

        self._running           = False
        self._thread: Optional[threading.Thread] = None
        self._paused            = False            # estado pause/resume
        self._last_trigger_time = 0.0              # monotonic, último gesto disparado
        self._stable: dict[str, int] = {}          # gesture_name → frames consecutivos

    # ── API pública ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Arranca el hilo daemon de detección de gestos."""
        if not self.cfg.enabled:
            print("[GestureController] Desactivado en config (use_gestures=False)")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            name="jarvis-gestures",
            daemon=True,
        )
        self._thread.start()
        print(
            f"[GestureController] Activo — cámara {self.cfg.camera_index}, "
            f"cooldown={self.cfg.cooldown_sec}s, debug={self.cfg.debug}"
        )

    def stop(self) -> None:
        """Detiene el hilo de detección."""
        self._running = False

    @property
    def is_paused(self) -> bool:
        """True cuando la escucha está pausada por gesto."""
        return self._paused

    # ── Bucle principal ──────────────────────────────────────────────────────

    def _loop(self) -> None:
        """Bucle de captura + detección. Corre en el thread daemon."""
        # Importaciones tardías: si no están disponibles, el módulo carga igual
        try:
            import cv2
        except ImportError:
            print(
                "[GestureController] OpenCV no encontrado. "
                "Instala con: pip install opencv-python"
            )
            return
        try:
            import mediapipe as mp
        except ImportError:
            print(
                "[GestureController] MediaPipe no encontrado. "
                "Instala con: pip install mediapipe"
            )
            return

        mp_hands = mp.solutions.hands
        mp_draw  = mp.solutions.drawing_utils

        cap = cv2.VideoCapture(self.cfg.camera_index)
        if not cap.isOpened():
            print(
                f"[GestureController] No se pudo abrir la cámara "
                f"(índice {self.cfg.camera_index}). "
                "Comprueba permisos de cámara en Ajustes → Privacidad."
            )
            return

        # Reducir resolución para mejor rendimiento
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        hands = mp_hands.Hands(
            model_complexity=0,  # modelo ligero
            min_detection_confidence=self.cfg.min_detection_confidence,
            min_tracking_confidence=self.cfg.min_tracking_confidence,
            max_num_hands=1,
        )

        frame_skip = 0  # procesar un frame de cada dos
        try:
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                # Procesar uno de cada dos frames (≈15 FPS de análisis)
                frame_skip = (frame_skip + 1) % 2
                if frame_skip:
                    continue

                # BGR → RGB para MediaPipe
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame_rgb.flags.writeable = False
                results = hands.process(frame_rgb)
                frame_rgb.flags.writeable = True

                current_gesture: Optional[GestureEvent] = None

                if results.multi_hand_landmarks and results.multi_handedness:
                    for hand_lm, hand_info in zip(
                        results.multi_hand_landmarks,
                        results.multi_handedness,
                    ):
                        handedness_label = hand_info.classification[0].label
                        current_gesture = detect_gesture(
                            hand_lm.landmark, handedness_label
                        )

                        if self.cfg.debug:
                            mp_draw.draw_landmarks(
                                frame, hand_lm, mp_hands.HAND_CONNECTIONS
                            )

                # ── Estabilidad: exigir N frames consecutivos ────────────────
                self._update_stable(current_gesture)

                # ── Visualización debug ──────────────────────────────────────
                if self.cfg.debug:
                    self._draw_debug(frame, current_gesture)
                    cv2.imshow("JARVIS — Gestures", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

        finally:
            hands.close()
            cap.release()
            if self.cfg.debug:
                try:
                    cv2.destroyAllWindows()
                except Exception:
                    pass

    def _update_stable(self, gesture: Optional[GestureEvent]) -> None:
        """
        Actualiza el contador de estabilidad.
        Dispara el callback solo cuando el mismo gesto se mantiene
        durante cfg.stable_frames frames consecutivos.
        """
        if gesture is None:
            self._stable.clear()
            return

        key = gesture.value

        # Resetear contadores de otros gestos
        for k in list(self._stable):
            if k != key:
                del self._stable[k]

        self._stable[key] = self._stable.get(key, 0) + 1

        if self._stable[key] >= self.cfg.stable_frames:
            # Comprobar cooldown
            now = time.monotonic()
            if now - self._last_trigger_time >= self.cfg.cooldown_sec:
                self._last_trigger_time = now
                self._stable[key] = 0  # resetear para no re-disparar
                self._dispatch(gesture)

    def _dispatch(self, gesture: GestureEvent) -> None:
        """Llama al callback correspondiente. Siempre en el thread gesture."""
        print(f"[GestureController] ✋ Gesto: {gesture.value}")
        try:
            if gesture == GestureEvent.FIST:
                self._on_interrupt()

            elif gesture == GestureEvent.OPEN_PALM:
                if self._paused:
                    self._paused = False
                    self._on_resume()
                    print("[GestureController] ▶  Escucha reanudada")
                else:
                    self._paused = True
                    self._on_pause()
                    print("[GestureController] ⏸  Escucha pausada")

            elif gesture == GestureEvent.PINCH:
                self._on_confirm()

            elif gesture == GestureEvent.V_SIGN:
                self._on_voice()

            elif gesture == GestureEvent.THUMB_UP:
                self._on_yes()

            elif gesture == GestureEvent.THUMB_DOWN:
                self._on_no()

        except Exception as e:
            print(f"[GestureController] Error en callback '{gesture.value}': {e}")

    # ── Debug ────────────────────────────────────────────────────────────────

    def _draw_debug(self, frame: Any, gesture: Optional[GestureEvent]) -> None:
        """Dibuja info de debug sobre el frame (solo si debug=True)."""
        try:
            import cv2
            h, w = frame.shape[:2]

            # Nombre del gesto actual
            if gesture:
                label = gesture.value.replace("_", " ").upper()
                cv2.putText(
                    frame, label,
                    (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                    (0, 255, 80), 2, cv2.LINE_AA,
                )

            # Estado pause
            status = "PAUSED" if self._paused else "ACTIVE"
            color  = (0, 100, 255) if self._paused else (0, 220, 0)
            cv2.putText(
                frame, status,
                (w - 130, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                color, 2, cv2.LINE_AA,
            )

            # Cooldown bar
            elapsed  = time.monotonic() - self._last_trigger_time
            pct      = min(1.0, elapsed / self.cfg.cooldown_sec)
            bar_w    = int(w * pct * 0.4)
            cv2.rectangle(frame, (10, h - 20), (10 + bar_w, h - 8), (0, 200, 255), -1)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Factory helper para integración con JARVIS daemon
# ---------------------------------------------------------------------------

def build_gesture_controller(settings: Any, daemon: Any) -> Optional[GestureController]:
    """
    Crea y devuelve un GestureController conectado al daemon.
    Devuelve None si los gestos están desactivados en settings.

    Callbacks:
        FIST       → daemon.interrupt()
        OPEN_PALM  → daemon.pause_gesture() / daemon.resume_gesture()
        PINCH      → daemon.submit_text("sí, confirmo")
        V_SIGN     → daemon.trigger_voice_input()
        THUMB_UP   → daemon.submit_text("sí")
        THUMB_DOWN → daemon.submit_text("no, cancela")
    """
    cfg = GestureConfig(
        enabled=getattr(settings, "use_gestures", False),
        cooldown_sec=getattr(settings, "gesture_cooldown", 1.5),
        debug=getattr(settings, "gesture_debug", False),
        camera_index=getattr(settings, "gesture_camera_index", 0),
    )
    if not cfg.enabled:
        return None

    enqueue = getattr(daemon, "enqueue_gesture_event", None)
    if callable(enqueue):
        return GestureController(
            cfg=cfg,
            on_interrupt=lambda: enqueue("interrupt"),
            on_pause=lambda: enqueue("pause"),
            on_resume=lambda: enqueue("resume"),
            on_confirm=lambda: enqueue("confirm"),
            on_voice=lambda: enqueue("voice"),
            on_yes=lambda: enqueue("yes"),
            on_no=lambda: enqueue("no"),
        )

    # Fallback retrocompatible si el daemon aún no expone queue de gestos.
    return GestureController(
        cfg=cfg,
        on_interrupt=getattr(daemon, "interrupt", lambda: None),
        on_pause=getattr(daemon, "pause_gesture", lambda: None),
        on_resume=getattr(daemon, "resume_gesture", lambda: None),
        on_confirm=lambda: daemon.submit_text("sí, confirmo"),
        on_voice=getattr(daemon, "trigger_voice_input", lambda: None),
        on_yes=lambda: daemon.submit_text("sí"),
        on_no=lambda: daemon.submit_text("no, cancela"),
    )
