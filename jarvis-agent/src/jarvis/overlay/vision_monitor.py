"""
vision_monitor.py

Ventana de debug flotante para Jarvis Desktop.

Muestra en tiempo real:
  - Feed de cámara mirroreado con landmarks de mano (MediaPipe Tasks HandLandmarker)
  - Gesto detectado (top-left) + barra de estabilidad (bottom)
  - Bounding box de cara con esquinas decorativas (OpenCV Haar)
  - Objetos detectados por Groq Vision (via camera_ctx)

Soporta MediaPipe ≥0.10 (Tasks API) y <0.10 (solutions API).
El HandLandmarker se inicializa en el hilo principal para evitar SIGTRAP en Apple Silicon.
"""
from __future__ import annotations

import os
import pathlib
import threading
import time
import urllib.request
from typing import Any, Optional

# Conexiones fijas del grafo de mano (MediaPipe 21 landmarks)
_HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]

_MODEL_URL  = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
_MODEL_PATH = pathlib.Path.home() / ".cache" / "jarvis" / "hand_landmarker.task"


def _ensure_hand_model() -> Optional[pathlib.Path]:
    """Descarga el modelo hand_landmarker.task si no está en caché. Devuelve la ruta o None."""
    if _MODEL_PATH.exists():
        return _MODEL_PATH
    try:
        _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        print("[VisionMonitor] Descargando hand_landmarker.task (~8 MB)…")
        urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
        print("[VisionMonitor] Modelo descargado OK")
        return _MODEL_PATH
    except Exception as e:
        print(f"[VisionMonitor] No se pudo descargar el modelo: {e}")
        return None


try:
    import AppKit

    # ── Timer target (NSObject) ───────────────────────────────────────────────

    class _VisionMonitorTimer(AppKit.NSObject):
        """Target del NSTimer de UI (20 fps)."""

        def pump_(self, timer: AppKit.NSTimer) -> None:  # noqa: N802
            monitor: VisionMonitor = timer.userInfo()
            if monitor is not None:
                monitor._pump()

    # ── Ventana de monitor ────────────────────────────────────────────────────

    class VisionMonitor:
        """
        Ventana NSWindow flotante con feed de cámara anotado.

        El HandLandmarker (MediaPipe Tasks) se inicializa en el hilo principal
        dentro de start() para evitar el SIGTRAP en Apple Silicon que ocurre
        al inicializarlo desde un thread daemon.
        """

        _WIN_W    = 640
        _IMG_H    = 360
        _STATUS_H =  70
        _WIN_H    = _IMG_H + _STATUS_H

        def __init__(self, camera_index: int = 0) -> None:
            self._camera_index = camera_index
            self._gesture_ctrl: Any = None
            self._camera_ctx:   Any = None

            # Landmarker inicializado en start() (hilo principal)
            self._hand_landmarker: Any = None

            self._running = False
            self._thread: Optional[threading.Thread] = None
            self._timer:  Optional[Any] = None

            self._lock                   = threading.Lock()
            self._pending_frame: Optional[Any] = None
            self._last_gesture_name: str = ""
            self._pointer_state: str     = ""   # estado del hand pointer
            self._face_present:  bool    = False
            self._face_looking:  bool    = False

            # HandPointer — control de ratón con la mano
            try:
                from jarvis.vision.hand_pointer import HandPointer
                self._hand_pointer: Any = HandPointer()
            except Exception:
                self._hand_pointer = None

            # ── Crear ventana NSWindow ─────────────────────────────────────
            sf = AppKit.NSScreen.mainScreen().frame()
            sw, sh = sf.size.width, sf.size.height

            wx = sw - self._WIN_W - 20
            wy = sh - self._WIN_H - 40

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
            win.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces)

            content = win.contentView()

            self._image_view = AppKit.NSImageView.alloc().initWithFrame_(
                AppKit.NSMakeRect(0, self._STATUS_H, self._WIN_W, self._IMG_H)
            )
            self._image_view.setImageScaling_(1)
            content.addSubview_(self._image_view)

            self._status_label = AppKit.NSTextField.alloc().initWithFrame_(
                AppKit.NSMakeRect(0, 0, self._WIN_W, self._STATUS_H)
            )
            self._status_label.setEditable_(False)
            self._status_label.setSelectable_(False)
            self._status_label.setBezeled_(False)
            self._status_label.setDrawsBackground_(True)
            self._status_label.setBackgroundColor_(
                AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.04, 0.04, 0.06, 1.0)
            )
            self._status_label.setTextColor_(AppKit.NSColor.whiteColor())
            try:
                font = AppKit.NSFont.monospacedSystemFontOfSize_weight_(12.0, AppKit.NSFontWeightRegular)
            except Exception:
                font = AppKit.NSFont.systemFontOfSize_(12.0)
            self._status_label.setFont_(font)
            self._status_label.setStringValue_("Iniciando Vision Monitor…")
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
            Inicia la captura y el timer de UI.
            DEBE llamarse desde el hilo principal (applicationDidFinishLaunching_).
            Inicializa HandLandmarker aquí para evitar SIGTRAP en Apple Silicon.
            """
            self._gesture_ctrl = gesture_ctrl
            self._camera_ctx   = camera_ctx

            # ── Inicializar HandLandmarker en el hilo principal ────────────
            self._hand_landmarker = self._init_hand_landmarker_main_thread()

            self._running = True
            self._thread = threading.Thread(
                target=self._capture_loop,
                name="jarvis-vision-monitor",
                daemon=True,
            )
            self._thread.start()

            self._timer = (
                AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    1.0 / 20.0,
                    _VisionMonitorTimer.new(),
                    "pump:",
                    self,
                    True,
                )
            )

        def _init_hand_landmarker_main_thread(self) -> Any:
            """
            Inicializa HandLandmarker de MediaPipe Tasks en el hilo principal.
            Devuelve el landmarker o None si no está disponible.
            """
            try:
                import mediapipe as mp
                # Preferir mp.solutions si existe (MediaPipe <0.10)
                if hasattr(mp, "solutions"):
                    return None   # el capture_loop lo inicializa directamente

                # MediaPipe ≥0.10: usar Tasks API
                from mediapipe.tasks.python import vision as _mpv
                from mediapipe.tasks.python.core import base_options as _mpbo

                model_path = _ensure_hand_model()
                if model_path is None:
                    return None

                options = _mpv.HandLandmarkerOptions(
                    base_options=_mpbo.BaseOptions(model_asset_path=str(model_path)),
                    num_hands=1,
                    min_hand_detection_confidence=0.65,
                    min_hand_presence_confidence=0.5,
                    min_tracking_confidence=0.5,
                    running_mode=_mpv.RunningMode.IMAGE,
                )
                landmarker = _mpv.HandLandmarker.create_from_options(options)
                print("[VisionMonitor] HandLandmarker (Tasks API) listo")
                return landmarker
            except Exception as e:
                print(f"[VisionMonitor] HandLandmarker no disponible: {e}")
                return None

        def stop(self) -> None:
            self._running = False
            if self._timer is not None:
                self._timer.invalidate()
                self._timer = None

        # ── Hilo de captura ───────────────────────────────────────────────────

        def _capture_loop(self) -> None:
            os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")

            try:
                import cv2
            except ImportError:
                print("[VisionMonitor] ⚠️ OpenCV no disponible (pip install opencv-python)")
                return

            # ── Detectores según versión de MediaPipe ─────────────────────
            hands        = None
            mp_draw      = None
            mp_hands_mod = None
            _detect_gesture = None
            use_tasks   = False

            try:
                import mediapipe as mp
                mp_sol = getattr(mp, "solutions", None)

                if mp_sol is not None:
                    # MediaPipe <0.10: API solutions
                    try:
                        from jarvis.vision.gesture_controller import detect_gesture as _dg
                        _detect_gesture = _dg
                    except ImportError:
                        pass
                    try:
                        mp_hands_mod = mp_sol.hands
                        mp_draw      = mp_sol.drawing_utils
                        hands = mp_hands_mod.Hands(
                            model_complexity=0,
                            min_detection_confidence=0.7,
                            min_tracking_confidence=0.5,
                            max_num_hands=1,
                        )
                    except Exception as e:
                        print(f"[VisionMonitor] mp.solutions Hands: {e}")

                elif self._hand_landmarker is not None:
                    # MediaPipe ≥0.10: Tasks API, landmarker ya inicializado en main thread
                    try:
                        from jarvis.vision.gesture_controller import detect_gesture as _dg
                        _detect_gesture = _dg
                    except ImportError:
                        pass
                    use_tasks = True
                    print("[VisionMonitor] Usando HandLandmarker (Tasks API)")

            except ImportError:
                pass

            # ── Haar cascade para cara (no depende de MediaPipe) ──────────
            haar_face = None
            try:
                cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                haar_face = cv2.CascadeClassifier(cascade_path)
                if haar_face.empty():
                    haar_face = None
            except Exception:
                pass

            # ── Abrir cámara ──────────────────────────────────────────────
            cap = cv2.VideoCapture(self._camera_index)
            if not cap.isOpened():
                print(f"[VisionMonitor] ⚠️ No se pudo abrir cámara {self._camera_index}")
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            _stable: dict[str, int] = {}
            STABLE_FRAMES = 5

            try:
                while self._running:
                    ret, frame = cap.read()
                    if not ret:
                        time.sleep(0.05)
                        continue

                    frame = cv2.flip(frame, 1)
                    h, w  = frame.shape[:2]

                    current_gesture = None

                    # ── Manos (mp.solutions) ──────────────────────────────
                    if hands is not None and mp_draw is not None and mp_hands_mod is not None:
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        frame_rgb.flags.writeable = False
                        hand_res = hands.process(frame_rgb)
                        frame_rgb.flags.writeable = True

                        if hand_res.multi_hand_landmarks and hand_res.multi_handedness:
                            for hand_lm, hand_info in zip(
                                hand_res.multi_hand_landmarks,
                                hand_res.multi_handedness,
                            ):
                                mp_draw.draw_landmarks(
                                    frame, hand_lm,
                                    mp_hands_mod.HAND_CONNECTIONS,
                                    mp_draw.DrawingSpec(color=(0, 255, 128), thickness=2, circle_radius=3),
                                    mp_draw.DrawingSpec(color=(255, 100, 0), thickness=2),
                                )
                                if _detect_gesture is not None:
                                    label = hand_info.classification[0].label
                                    current_gesture = _detect_gesture(hand_lm.landmark, label)

                    # ── Manos (Tasks API) ─────────────────────────────────
                    elif use_tasks and self._hand_landmarker is not None:
                        try:
                            import mediapipe as mp
                            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            mp_image  = mp.Image(
                                image_format=mp.ImageFormat.SRGB,
                                data=frame_rgb,
                            )
                            result = self._hand_landmarker.detect(mp_image)

                            if result.hand_landmarks:
                                landmarks = result.hand_landmarks[0]

                                # Dibujar conexiones
                                for s, e in _HAND_CONNECTIONS:
                                    lms = landmarks[s]
                                    lme = landmarks[e]
                                    x1, y1 = int(lms.x * w), int(lms.y * h)
                                    x2, y2 = int(lme.x * w), int(lme.y * h)
                                    cv2.line(frame, (x1, y1), (x2, y2), (255, 100, 0), 2)

                                # Dibujar landmarks
                                for lm in landmarks:
                                    cx, cy = int(lm.x * w), int(lm.y * h)
                                    cv2.circle(frame, (cx, cy), 4, (0, 255, 128), -1)

                                # Detectar gesto
                                if _detect_gesture is not None:
                                    hand_label = "Right"
                                    if result.handedness:
                                        hand_label = result.handedness[0][0].category_name
                                    current_gesture = _detect_gesture(landmarks, hand_label)
                        except Exception:
                            pass

                    # ── Cara (Haar) ───────────────────────────────────────
                    face_present = False
                    face_looking = False
                    if haar_face is not None:
                        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        faces = haar_face.detectMultiScale(
                            gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80)
                        )
                        if len(faces) > 0:
                            fx, fy, fw, fh = max(faces, key=lambda r: r[2] * r[3])
                            face_present = True
                            cx_f = (fx + fw / 2) / w
                            cy_f = (fy + fh / 2) / h
                            face_looking = fw / w > 0.15 and 0.25 < cx_f < 0.75 and cy_f < 0.7
                            bc = (0, 255, 80) if face_looking else (0, 200, 200)
                            cl, t = 18, 2
                            for (px, py), (dx, dy) in [
                                ((fx,      fy),      ( cl,   0)),
                                ((fx,      fy),      (  0,  cl)),
                                ((fx + fw, fy),      (-cl,   0)),
                                ((fx + fw, fy),      (  0,  cl)),
                                ((fx,      fy + fh), ( cl,   0)),
                                ((fx,      fy + fh), (  0, -cl)),
                                ((fx + fw, fy + fh), (-cl,   0)),
                                ((fx + fw, fy + fh), (  0, -cl)),
                            ]:
                                cv2.line(frame, (px, py), (px + dx, py + dy), bc, t)

                    # ── Estabilidad del gesto ─────────────────────────────
                    if current_gesture is None:
                        _stable.clear()
                        gesture_name = ""
                        progress     = 0.0
                    else:
                        key = current_gesture.value
                        for k in list(_stable):
                            if k != key:
                                del _stable[k]
                        _stable[key] = _stable.get(key, 0) + 1
                        progress     = min(1.0, _stable[key] / STABLE_FRAMES)
                        gesture_name = key.upper().replace("_", " ")

                    # ── HandPointer: control de ratón ──────────────────────
                    # Solo actúa cuando hay gesto estable (progress >= 1.0)
                    pointer_state = ""
                    if self._hand_pointer is not None:
                        stable_gesture = current_gesture if progress >= 1.0 else None
                        # Obtener landmarks actuales para la posición
                        _lms = None
                        try:
                            if use_tasks and self._hand_landmarker is not None:
                                import mediapipe as _mp2
                                _mp2_img = _mp2.Image(image_format=_mp2.ImageFormat.SRGB,
                                                      data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                                _r2 = self._hand_landmarker.detect(_mp2_img)
                                if _r2.hand_landmarks:
                                    _lms = _r2.hand_landmarks[0]
                        except Exception:
                            pass
                        pointer_state = self._hand_pointer.update(_lms, stable_gesture)

                    # ── Overlay: texto gesto + estado puntero ─────────────
                    overlay_txt = gesture_name
                    if pointer_state:
                        overlay_txt = f"{gesture_name}  [{pointer_state}]" if gesture_name else f"[{pointer_state}]"
                    if overlay_txt:
                        cv2.putText(
                            frame, overlay_txt, (10, 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.85,
                            (0, 255, 80), 2, cv2.LINE_AA,
                        )

                    bar_max    = int(w * 0.4)
                    bar_filled = int(bar_max * progress)
                    cv2.rectangle(frame, (10, h - 18), (10 + bar_max, h - 8), (50, 50, 50), -1)
                    if bar_filled > 0:
                        cv2.rectangle(frame, (10, h - 18), (10 + bar_filled, h - 8), (0, 200, 255), -1)

                    with self._lock:
                        self._pending_frame     = frame.copy()
                        self._last_gesture_name = gesture_name
                        self._pointer_state     = pointer_state
                        self._face_present      = face_present
                        self._face_looking      = face_looking

            finally:
                if hands is not None:
                    hands.close()
                cap.release()

        # ── Pump (hilo principal, 20 fps) ─────────────────────────────────────

        def _pump(self) -> None:
            with self._lock:
                frame         = self._pending_frame
                gesture_name  = self._last_gesture_name
                pointer_state = self._pointer_state
                face_present  = self._face_present
                face_looking  = self._face_looking

            if frame is not None:
                try:
                    import cv2
                    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok:
                        raw     = buf.tobytes()
                        nsdata  = AppKit.NSData.dataWithBytes_length_(raw, len(raw))
                        nsimage = AppKit.NSImage.alloc().initWithData_(nsdata)
                        if nsimage is not None:
                            self._image_view.setImage_(nsimage)
                except Exception:
                    pass

            # Línea 1: cara + gesto
            line1: list[str] = []
            if self._camera_ctx is not None:
                if getattr(self._camera_ctx, "looking_at_camera", False):
                    line1.append("👁 MIRANDO")
                elif getattr(self._camera_ctx, "user_present", False):
                    line1.append("🟡 PRESENTE")
                else:
                    line1.append("⬜ AUSENTE")
            else:
                if face_looking:
                    line1.append("👁 MIRANDO")
                elif face_present:
                    line1.append("🟡 PRESENTE")
                else:
                    line1.append("⬜ AUSENTE")

            if gesture_name:
                line1.append(f"✋ {gesture_name}")
            if pointer_state:
                state_icons = {
                    "HOVER": "🖱 HOVER", "DRAG": "🤏 DRAG",
                    "RCLICK": "👆 RCLICK", "SCROLL↑": "⬆ SCROLL",
                    "SCROLL↓": "⬇ SCROLL", "LIBRE": "✋ LIBRE",
                }
                line1.append(state_icons.get(pointer_state, pointer_state))

            # Línea 2: objetos detectados
            line2 = ""
            if self._camera_ctx is not None:
                obj = getattr(self._camera_ctx, "object_context", "")
                if obj:
                    obj_short = obj[:75] + "…" if len(obj) > 75 else obj
                    line2 = f"📦 {obj_short}"
                else:
                    line2 = "📦 analizando entorno…"

            status = "  |  ".join(line1)
            if line2:
                status += "\n" + line2
            self._status_label.setStringValue_(status or "Sin datos")

except ImportError:
    class VisionMonitor:  # type: ignore[no-redef]
        def __init__(self, camera_index: int = 0) -> None: pass
        def start(self, gesture_ctrl: Any = None, camera_ctx: Any = None) -> None: pass
        def stop(self) -> None: pass
