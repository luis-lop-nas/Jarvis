"""
vision_monitor.py

Ventana de debug flotante para Jarvis Desktop.

Muestra en tiempo real:
  - Feed de cámara mirroreado con landmarks de mano (MediaPipe Hands)
  - Bounding box de cara con esquinas decorativas (MediaPipe Face Detection)
  - Nombre del gesto detectado (top-left del frame)
  - Barra de estabilidad de gesto (bottom del frame)
  - Panel de estado: cara / gesto / pausa / objetos detectados

Solo disponible en modo desktop (PyObjC + OpenCV + MediaPipe).
Fallo graceful si alguna dependencia no está instalada.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Optional

try:
    import AppKit

    # ── Timer target (NSObject necesario para NSTimer) ────────────────────────

    class _PumpTarget(AppKit.NSObject):
        """Target del NSTimer de actualización de UI (20 fps)."""

        def pump_(self, timer: AppKit.NSTimer) -> None:  # noqa: N802
            monitor: VisionMonitor = timer.userInfo()
            if monitor is not None:
                monitor._pump()

    # ── Ventana de monitor ────────────────────────────────────────────────────

    class VisionMonitor:
        """
        Ventana NSWindow flotante (NSFloatingWindowLevel) que muestra
        el feed de cámara anotado con mano, cara y estado del sistema.

        Uso:
            monitor = VisionMonitor(camera_index=0)
            # ... dentro de applicationDidFinishLaunching_:
            monitor.start(gesture_ctrl=ctrl, camera_ctx=ctx)
            # ... al cerrar:
            monitor.stop()
        """

        _WIN_W = 640
        _IMG_H = 360
        _STATUS_H = 60
        _WIN_H = _IMG_H + _STATUS_H  # 420

        def __init__(self, camera_index: int = 0) -> None:
            self._camera_index = camera_index
            self._gesture_ctrl: Any = None
            self._camera_ctx: Any = None

            self._running = False
            self._thread: Optional[threading.Thread] = None
            self._timer: Optional[Any] = None

            # Estado compartido capture_loop ↔ _pump (protegido por lock)
            self._lock = threading.Lock()
            self._pending_frame: Optional[Any] = None  # numpy BGR array
            self._last_gesture_name: str = ""
            self._face_present: bool = False
            self._face_looking: bool = False

            # ── Crear ventana NSWindow ─────────────────────────────────────
            screen_frame = AppKit.NSScreen.mainScreen().frame()
            sw = screen_frame.size.width
            sh = screen_frame.size.height

            # Esquina superior derecha con márgenes
            wx = sw - self._WIN_W - 20
            wy = sh - self._WIN_H - 40  # espacio para title bar + menu bar

            style = (
                AppKit.NSWindowStyleMaskTitled
                | AppKit.NSWindowStyleMaskClosable
                | AppKit.NSWindowStyleMaskResizable
                | AppKit.NSWindowStyleMaskMiniaturizable
            )

            win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                AppKit.NSMakeRect(wx, wy, self._WIN_W, self._WIN_H),
                style,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            win.setTitle_("Jarvis — Vision Monitor")
            win.setLevel_(AppKit.NSFloatingWindowLevel)
            win.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            )

            content = win.contentView()

            # NSImageView — feed de cámara (360px superiores del content view)
            self._image_view = AppKit.NSImageView.alloc().initWithFrame_(
                AppKit.NSMakeRect(0, self._STATUS_H, self._WIN_W, self._IMG_H)
            )
            # NSImageScaleAxesIndependently = 1 (rellena todo el rect)
            self._image_view.setImageScaling_(1)
            content.addSubview_(self._image_view)

            # NSTextField — panel de estado (60px inferiores)
            self._status_label = AppKit.NSTextField.alloc().initWithFrame_(
                AppKit.NSMakeRect(0, 0, self._WIN_W, self._STATUS_H)
            )
            self._status_label.setEditable_(False)
            self._status_label.setSelectable_(False)
            self._status_label.setBezeled_(False)
            self._status_label.setDrawsBackground_(True)
            self._status_label.setBackgroundColor_(
                AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.04, 0.04, 0.06, 1.0
                )
            )
            self._status_label.setTextColor_(AppKit.NSColor.whiteColor())
            try:
                font = AppKit.NSFont.monospacedSystemFontOfSize_weight_(
                    13.0, AppKit.NSFontWeightRegular
                )
            except Exception:
                font = AppKit.NSFont.systemFontOfSize_(13.0)
            self._status_label.setFont_(font)
            self._status_label.setStringValue_("Iniciando Vision Monitor…")
            try:
                self._status_label.setAlignment_(AppKit.NSCenterTextAlignment)
            except Exception:
                try:
                    self._status_label.setAlignment_(AppKit.NSTextAlignmentCenter)
                except Exception:
                    pass
            content.addSubview_(self._status_label)

            win.orderFrontRegardless()
            self._window = win

        # ── API pública ───────────────────────────────────────────────────────

        def start(self, gesture_ctrl: Any = None, camera_ctx: Any = None) -> None:
            """
            Inicia el hilo de captura y el NSTimer de actualización de UI.
            Llamar desde applicationDidFinishLaunching_ (hilo principal).
            """
            self._gesture_ctrl = gesture_ctrl
            self._camera_ctx = camera_ctx

            self._running = True
            self._thread = threading.Thread(
                target=self._capture_loop,
                name="jarvis-vision-monitor",
                daemon=True,
            )
            self._thread.start()

            # NSTimer a 20 fps en el hilo principal
            self._timer = (
                AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    1.0 / 20.0,
                    _PumpTarget.new(),
                    "pump:",
                    self,
                    True,
                )
            )

        def stop(self) -> None:
            """Detiene la captura y el timer."""
            self._running = False
            if self._timer is not None:
                self._timer.invalidate()
                self._timer = None

        # ── Hilo de captura ───────────────────────────────────────────────────

        def _capture_loop(self) -> None:
            """
            Hilo daemon: abre la cámara, detecta manos y cara con MediaPipe,
            dibuja anotaciones sobre el frame y lo almacena en _pending_frame.
            """
            os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")

            try:
                import cv2
            except ImportError:
                print(
                    "[VisionMonitor] ⚠️ OpenCV no disponible. "
                    "Instala con: pip install opencv-python"
                )
                return

            try:
                import mediapipe as mp
            except ImportError:
                print(
                    "[VisionMonitor] ⚠️ MediaPipe no disponible. "
                    "Instala con: pip install mediapipe"
                )
                mp = None

            try:
                from jarvis.vision.gesture_controller import (
                    detect_gesture as _detect_gesture,
                )
            except ImportError:
                _detect_gesture = None

            # ── Inicializar detectores ─────────────────────────────────────
            hands = None
            mp_draw = None
            mp_hands_mod = None
            face_det = None

            if mp is not None:
                mp_sol = getattr(mp, "solutions", None)
                if mp_sol is not None:
                    try:
                        mp_hands_mod = mp_sol.hands
                        mp_draw = mp_sol.drawing_utils
                        hands = mp_hands_mod.Hands(
                            model_complexity=0,
                            min_detection_confidence=0.7,
                            min_tracking_confidence=0.5,
                            max_num_hands=1,
                        )
                    except Exception as e:
                        print(f"[VisionMonitor] Hands init error: {e}")

                    try:
                        face_det = mp_sol.face_detection.FaceDetection(
                            model_selection=0,
                            min_detection_confidence=0.6,
                        )
                    except Exception as e:
                        print(f"[VisionMonitor] FaceDetection init error: {e}")

            # ── Abrir cámara ───────────────────────────────────────────────
            cap = cv2.VideoCapture(self._camera_index)
            if not cap.isOpened():
                print(
                    f"[VisionMonitor] ⚠️ No se pudo abrir cámara {self._camera_index}. "
                    "Comprueba permisos de cámara en Ajustes → Privacidad."
                )
                return

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            # Contadores de estabilidad de gesto (solo para visualización)
            _stable: dict[str, int] = {}
            STABLE_FRAMES = 5

            try:
                while self._running:
                    ret, frame = cap.read()
                    if not ret:
                        time.sleep(0.05)
                        continue

                    # Mirror horizontal (efecto selfie)
                    frame = cv2.flip(frame, 1)
                    h, w = frame.shape[:2]

                    # Convertir a RGB una sola vez para MediaPipe
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                    current_gesture = None

                    # ── Manos: landmarks + gesto ───────────────────────────
                    if hands is not None and mp_draw is not None and mp_hands_mod is not None:
                        frame_rgb.flags.writeable = False
                        hand_res = hands.process(frame_rgb)
                        frame_rgb.flags.writeable = True

                        if (
                            hand_res.multi_hand_landmarks
                            and hand_res.multi_handedness
                        ):
                            for hand_lm, hand_info in zip(
                                hand_res.multi_hand_landmarks,
                                hand_res.multi_handedness,
                            ):
                                mp_draw.draw_landmarks(
                                    frame,
                                    hand_lm,
                                    mp_hands_mod.HAND_CONNECTIONS,
                                    mp_draw.DrawingSpec(
                                        color=(0, 255, 128),
                                        thickness=2,
                                        circle_radius=3,
                                    ),
                                    mp_draw.DrawingSpec(
                                        color=(255, 100, 0), thickness=2
                                    ),
                                )
                                if _detect_gesture is not None:
                                    label = hand_info.classification[0].label
                                    current_gesture = _detect_gesture(
                                        hand_lm.landmark, label
                                    )

                    # ── Cara: bbox con esquinas decorativas ────────────────
                    face_present = False
                    face_looking = False
                    if face_det is not None:
                        face_res = face_det.process(frame_rgb)
                        if face_res.detections:
                            best = max(
                                face_res.detections,
                                key=lambda d: (
                                    d.location_data.relative_bounding_box.width
                                    * d.location_data.relative_bounding_box.height
                                ),
                            )
                            bbox = best.location_data.relative_bounding_box
                            face_w = bbox.width
                            cx = bbox.xmin + face_w / 2
                            cy = bbox.ymin + bbox.height / 2
                            face_looking = (
                                face_w > 0.12 and 0.3 < cx < 0.7 and cy < 0.65
                            )
                            face_present = True

                            # Coordenadas píxel
                            x1 = max(0, int(bbox.xmin * w))
                            y1 = max(0, int(bbox.ymin * h))
                            x2 = min(w - 1, x1 + int(bbox.width * w))
                            y2 = min(h - 1, y1 + int(bbox.height * h))

                            # Verde = mirando, amarillo-cyan = solo presente
                            bc = (0, 255, 80) if face_looking else (0, 200, 200)
                            cl, t = 15, 2  # corner length, thickness

                            # 4 esquinas × 2 segmentos
                            for (px, py), (dx, dy) in [
                                ((x1, y1), (cl, 0)),
                                ((x1, y1), (0, cl)),
                                ((x2, y1), (-cl, 0)),
                                ((x2, y1), (0, cl)),
                                ((x1, y2), (cl, 0)),
                                ((x1, y2), (0, -cl)),
                                ((x2, y2), (-cl, 0)),
                                ((x2, y2), (0, -cl)),
                            ]:
                                cv2.line(
                                    frame, (px, py), (px + dx, py + dy), bc, t
                                )

                    # ── Estabilidad del gesto ──────────────────────────────
                    if current_gesture is None:
                        _stable.clear()
                        gesture_name = ""
                        progress = 0.0
                    else:
                        key = current_gesture.value
                        for k in list(_stable):
                            if k != key:
                                del _stable[k]
                        _stable[key] = _stable.get(key, 0) + 1
                        progress = min(1.0, _stable[key] / STABLE_FRAMES)
                        gesture_name = key.upper().replace("_", " ")

                    # ── Texto del gesto en top-left ────────────────────────
                    if gesture_name:
                        cv2.putText(
                            frame,
                            gesture_name,
                            (10, 35),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.9,
                            (0, 255, 80),
                            2,
                            cv2.LINE_AA,
                        )

                    # ── Barra de estabilidad en bottom ─────────────────────
                    bar_max = int(w * 0.4)
                    bar_filled = int(bar_max * progress)
                    cv2.rectangle(
                        frame, (10, h - 18), (10 + bar_max, h - 8), (50, 50, 50), -1
                    )
                    if bar_filled > 0:
                        cv2.rectangle(
                            frame,
                            (10, h - 18),
                            (10 + bar_filled, h - 8),
                            (0, 200, 255),
                            -1,
                        )

                    # ── Guardar frame anotado ──────────────────────────────
                    with self._lock:
                        self._pending_frame = frame.copy()
                        self._last_gesture_name = gesture_name
                        self._face_present = face_present
                        self._face_looking = face_looking

            finally:
                if hands is not None:
                    hands.close()
                if face_det is not None:
                    face_det.close()
                cap.release()

        # ── Pump (hilo principal, 20 fps) ─────────────────────────────────────

        def _pump(self) -> None:
            """
            Actualiza NSImageView y label de estado.
            Llamado desde NSTimer en el hilo principal.
            """
            # Leer estado bajo lock
            with self._lock:
                frame = self._pending_frame
                gesture_name = self._last_gesture_name
                face_present = self._face_present
                face_looking = self._face_looking

            # ── Actualizar imagen ──────────────────────────────────────────
            if frame is not None:
                try:
                    import cv2

                    ok, buf = cv2.imencode(
                        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75]
                    )
                    if ok:
                        raw = buf.tobytes()
                        nsdata = AppKit.NSData.dataWithBytes_length_(raw, len(raw))
                        nsimage = AppKit.NSImage.alloc().initWithData_(nsdata)
                        if nsimage is not None:
                            self._image_view.setImage_(nsimage)
                except Exception:
                    pass

            # ── Construir texto de estado ──────────────────────────────────
            parts: list[str] = []

            # Estado de cara — usar camera_ctx externo si está disponible
            if self._camera_ctx is not None:
                ext_looking = getattr(self._camera_ctx, "looking_at_camera", False)
                ext_present = getattr(self._camera_ctx, "user_present", False)
                if ext_looking:
                    parts.append("MIRANDO")
                elif ext_present:
                    parts.append("PRESENTE")
                else:
                    parts.append("AUSENTE")
            else:
                # Fallback: estado detectado por el propio monitor
                if face_looking:
                    parts.append("MIRANDO")
                elif face_present:
                    parts.append("PRESENTE")
                else:
                    parts.append("AUSENTE")

            # Gesto detectado
            if gesture_name:
                parts.append(f"✋ {gesture_name}")

            # Estado pausa del gesture_ctrl
            if self._gesture_ctrl is not None:
                if getattr(self._gesture_ctrl, "is_paused", False):
                    parts.append("⏸ PAUSADO")

            # Objetos del camera_ctx
            if self._camera_ctx is not None:
                obj = getattr(self._camera_ctx, "object_context", "")
                if obj:
                    # Truncar si es muy largo
                    obj_short = obj[:60] + "…" if len(obj) > 60 else obj
                    parts.append(f"obj: {obj_short}")

            self._status_label.setStringValue_(
                "  |  ".join(parts) if parts else "Sin datos"
            )

except ImportError:
    # Entorno sin PyObjC (CLI, tests, servidor web)

    class VisionMonitor:  # type: ignore[no-redef]
        """Stub para entornos sin PyObjC."""

        def __init__(self, camera_index: int = 0) -> None:
            pass

        def start(self, gesture_ctrl: Any = None, camera_ctx: Any = None) -> None:
            pass

        def stop(self) -> None:
            pass
