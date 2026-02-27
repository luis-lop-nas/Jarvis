"""
camera_context.py

Hilo daemon que:
1. Captura frames de la cámara periódicamente
2. Detecta si el usuario está mirando la cámara (MediaPipe Face Detection)
3. Si hay cara: analiza objetos con Groq Vision (llama-3.2-11b-vision-preview)
4. Expone estado thread-safe para que daemon.py lo inyecte en el contexto LLM

Activar con CAMERA_CONTEXT=true en .env (desactivado por defecto).
"""
from __future__ import annotations

import base64
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class CameraContextConfig:
    enabled: bool = False
    camera_index: int = 0
    interval_s: float = 5.0    # segundos entre análisis completos
    face_only: bool = False    # solo detección de cara, sin gastar cuota Groq Vision
    groq_api_key: str = ""


class CameraContextAnalyzer:
    """
    Analiza periódicamente la cámara para detectar presencia del usuario y objetos.

    Expone estado thread-safe:
      - user_present (bool): hay cara visible
      - looking_at_camera (bool): cara frontal y centrada
      - object_context (str): descripción breve de objetos (Groq Vision)

    Uso:
        cfg = CameraContextConfig(enabled=True, groq_api_key="gsk_...")
        analyzer = CameraContextAnalyzer(cfg)
        analyzer.start()
        # ... en _get_context() del daemon:
        snippet = analyzer.get_context_snippet()  # "usuario mirando | objetos: taza"
        analyzer.stop()
    """

    def __init__(self, cfg: CameraContextConfig) -> None:
        self.cfg = cfg
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Estado compartido (actualizado por el hilo, leído por el daemon)
        self._user_present: bool = False
        self._looking_at_camera: bool = False
        self._object_context: str = ""
        self._last_analysis: float = 0.0

        # MediaPipe (inicializado lazy en el hilo)
        self._mp_face = None

    # ── API pública ──────────────────────────────────────────────────────────

    @property
    def user_present(self) -> bool:
        with self._lock:
            return self._user_present

    @property
    def looking_at_camera(self) -> bool:
        with self._lock:
            return self._looking_at_camera

    @property
    def object_context(self) -> str:
        with self._lock:
            return self._object_context

    def get_context_snippet(self) -> str:
        """
        Retorna string listo para inyectar en el contexto LLM.
        Ejemplo: "usuario mirando | objetos: portátil, taza de café"
        Retorna "" si no hay información relevante.
        """
        with self._lock:
            parts: list[str] = []
            if self._user_present:
                gaze = "mirando" if self._looking_at_camera else "presente"
                parts.append(f"usuario {gaze}")
            if self._object_context:
                parts.append(f"objetos: {self._object_context}")
        return " | ".join(parts)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="camera-context",
            daemon=True,
        )
        self._thread.start()
        log.info("CameraContextAnalyzer iniciado (cámara %d, intervalo %.1fs)",
                 self.cfg.camera_index, self.cfg.interval_s)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._thread = None

    # ── Hilo interno ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        import cv2  # dependencia opcional: pip install -e ".[gestures]"
        import numpy as np  # noqa: F401 — usado en _detect_face / _analyze_objects_groq
        cap = cv2.VideoCapture(self.cfg.camera_index)
        if not cap.isOpened():
            log.warning("CameraContextAnalyzer: no se pudo abrir cámara %d",
                        self.cfg.camera_index)
            return

        self._init_face_detector()

        try:
            while not self._stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.1)
                    continue

                now = time.monotonic()
                if (now - self._last_analysis) < self.cfg.interval_s:
                    time.sleep(0.05)
                    continue

                self._last_analysis = now
                self._analyze_frame(frame)

        finally:
            cap.release()

    def _init_face_detector(self) -> None:
        try:
            import mediapipe as mp
            self._mp_face = mp.solutions.face_detection.FaceDetection(
                model_selection=0,            # modelo corta distancia (≤2m, más rápido)
                min_detection_confidence=0.6,
            )
            log.info("MediaPipe Face Detection cargado")
        except Exception as e:
            log.warning("MediaPipe Face Detection no disponible: %s", e)

    def _analyze_frame(self, frame: np.ndarray) -> None:
        present, looking = self._detect_face(frame)

        obj_ctx = ""
        if present and not self.cfg.face_only and self.cfg.groq_api_key:
            obj_ctx = self._analyze_objects_groq(frame)

        with self._lock:
            self._user_present = present
            self._looking_at_camera = looking
            if obj_ctx:
                self._object_context = obj_ctx
            elif not present:
                # Limpiar contexto si no hay nadie
                self._object_context = ""

    def _detect_face(self, frame: np.ndarray) -> tuple[bool, bool]:
        """
        Retorna (user_present, looking_at_camera).

        'looking_at_camera': cara frontal, centrada y suficientemente grande.
        Heurística: face_width > 12% del frame, cx en [30%, 70%], cy < 65%.
        """
        if self._mp_face is None:
            return False, False

        try:
            import cv2
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._mp_face.process(rgb)
        except Exception as e:
            log.debug("Face detection error: %s", e)
            return False, False

        if not results.detections:
            return False, False

        # Tomar la cara más grande (la más próxima a la cámara)
        best = max(
            results.detections,
            key=lambda d: (
                d.location_data.relative_bounding_box.width
                * d.location_data.relative_bounding_box.height
            ),
        )
        bbox = best.location_data.relative_bounding_box
        face_w = bbox.width
        cx = bbox.xmin + face_w / 2          # centro horizontal [0, 1]
        cy = bbox.ymin + bbox.height / 2     # centro vertical [0, 1]

        looking = face_w > 0.12 and 0.3 < cx < 0.7 and cy < 0.65

        return True, looking

    def _analyze_objects_groq(self, frame: np.ndarray) -> str:
        """
        Envía frame a Groq Vision y retorna descripción de objetos en una frase.
        Modelo: llama-3.2-11b-vision-preview (rápido, suficiente para contexto).
        Retorna "" si no hay objetos notables o si falla la API.
        """
        try:
            from groq import Groq

            # Reducir resolución para minimizar tokens y latencia
            import cv2
            small = cv2.resize(frame, (640, 480))
            _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
            b64 = base64.b64encode(buf.tobytes()).decode()

            client = Groq(api_key=self.cfg.groq_api_key)
            resp = client.chat.completions.create(
                model="llama-3.2-11b-vision-preview",
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                "Describe briefly the objects visible near the person "
                                "or being held by them. Focus on specific, notable objects. "
                                "If there are no notable objects, reply with an empty string. "
                                "One short sentence max. Reply only with the description, no preamble."
                            ),
                        },
                    ],
                }],
                max_tokens=60,
                temperature=0.1,
            )

            if not resp.choices or not resp.choices[0].message.content:
                return ""

            result = resp.choices[0].message.content.strip()
            # Descartar respuestas vacías o genéricas
            if len(result) < 4 or result.lower() in {"", "none", "nothing", "no objects",
                                                       "no notable objects"}:
                return ""
            return result

        except Exception as e:
            log.debug("Groq Vision error en object analysis: %s", e)
            return ""
