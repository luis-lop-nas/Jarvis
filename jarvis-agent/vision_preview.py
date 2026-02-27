#!/usr/bin/env python
"""
vision_preview.py

Demo visual en tiempo real de la visión de JARVIS.

Muestra en una ventana OpenCV:
  - Feed de cámara en vivo
  - Landmarks de mano (MediaPipe Hands)
  - Gesto detectado con nombre y barra de estabilidad
  - Estado de cada dedo (extendido / doblado)
  - Detección de cara (bounding box)
  - Indicador "usuario mirando"
  - Log de gestos disparados

Ejecutar desde jarvis-agent/:
    source .venv/bin/activate
    PYTHONPATH=src python vision_preview.py

Teclas:
    Q / ESC  → salir
    M        → alternar espejo horizontal
    F        → alternar fullscreen
"""
from __future__ import annotations

import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, List, Optional, Tuple

# ── Verificar dependencias ────────────────────────────────────────────────────

try:
    import cv2
except ImportError:
    print("❌ OpenCV no instalado. Ejecuta: pip install opencv-python")
    sys.exit(1)

try:
    import mediapipe as mp
except ImportError:
    print("❌ MediaPipe no instalado. Ejecuta: pip install -e '.[gestures]'")
    sys.exit(1)

import numpy as np

# ── Importar lógica de gestos de JARVIS ──────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent / "src"))
from jarvis.vision.gesture_controller import (
    GestureEvent,
    detect_gesture,
    fingers_up,
    pinch_distance,
)

# ─────────────────────────────────────────────────────────────────────────────
# Colores JARVIS (BGR)
# ─────────────────────────────────────────────────────────────────────────────

C_BG        = (13,  8,   8)     # fondo oscuro
C_IDLE      = (224, 255, 0)     # cyan
C_LISTEN    = (136, 255, 0)     # verde
C_THINK     = (0,   225, 255)   # amarillo
C_ACT       = (96,  32,  255)   # rosa/rojo
C_FACE      = (0,   200, 0)     # verde cara
C_LANDMARK  = (255, 200, 0)     # conexiones mano
C_TIP       = (0,   100, 255)   # punta dedos
C_WHITE     = (255, 255, 255)
C_GRAY      = (160, 160, 160)
C_DARK      = (40,  40,  40)

# Color por gesto
GESTURE_COLORS = {
    GestureEvent.FIST:       (50,  50,  255),   # rojo
    GestureEvent.OPEN_PALM:  (0,   200, 0),     # verde
    GestureEvent.PINCH:      (0,   180, 255),   # naranja
    GestureEvent.V_SIGN:     (224, 255, 0),     # cyan
    GestureEvent.THUMB_UP:   (50,  220, 50),    # verde claro
    GestureEvent.THUMB_DOWN: (50,  50,  220),   # rojo-azul
}

GESTURE_EMOJIS = {
    GestureEvent.FIST:       "✊  FIST — Interrumpir",
    GestureEvent.OPEN_PALM:  "🖐  OPEN PALM — Pausar",
    GestureEvent.PINCH:      "🤌  PINCH — Confirmar",
    GestureEvent.V_SIGN:     "✌️  V SIGN — Activar voz",
    GestureEvent.THUMB_UP:   "👍  THUMB UP — Sí",
    GestureEvent.THUMB_DOWN: "👎  THUMB DOWN — No",
}

FINGER_NAMES = ["Pulgar", "Índice", "Medio", "Anular", "Meñique"]

# ─────────────────────────────────────────────────────────────────────────────
# Helpers de dibujo
# ─────────────────────────────────────────────────────────────────────────────

def put_text(
    frame: np.ndarray,
    text: str,
    pos: Tuple[int, int],
    scale: float = 0.55,
    color: Tuple[int, int, int] = C_WHITE,
    thickness: int = 1,
    shadow: bool = True,
) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    if shadow:
        cv2.putText(frame, text, (pos[0]+1, pos[1]+1), font, scale, (0,0,0), thickness+1, cv2.LINE_AA)
    cv2.putText(frame, text, pos, font, scale, color, thickness, cv2.LINE_AA)


def draw_rounded_rect(
    frame: np.ndarray,
    x1: int, y1: int, x2: int, y2: int,
    color: Tuple[int, int, int],
    alpha: float = 0.55,
    radius: int = 8,
) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (x1+radius, y1), (x2-radius, y2), color, -1)
    cv2.rectangle(overlay, (x1, y1+radius), (x2, y2-radius), color, -1)
    for cx, cy in [(x1+radius, y1+radius), (x2-radius, y1+radius),
                   (x1+radius, y2-radius), (x2-radius, y2-radius)]:
        cv2.circle(overlay, (cx, cy), radius, color, -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def draw_progress_bar(
    frame: np.ndarray,
    x: int, y: int, w: int, h: int,
    value: float,           # 0.0 – 1.0
    color_fill: Tuple[int, int, int],
    label: str = "",
) -> None:
    cv2.rectangle(frame, (x, y), (x+w, y+h), C_DARK, -1)
    cv2.rectangle(frame, (x, y), (x+w, y+h), C_GRAY, 1)
    fill_w = int(w * min(1.0, max(0.0, value)))
    if fill_w > 0:
        cv2.rectangle(frame, (x, y), (x+fill_w, y+h), color_fill, -1)
    if label:
        put_text(frame, label, (x+4, y+h-3), scale=0.38, color=C_WHITE, shadow=False)


# ─────────────────────────────────────────────────────────────────────────────
# Panel derecho: estado de dedos + gesto
# ─────────────────────────────────────────────────────────────────────────────

def draw_right_panel(
    frame: np.ndarray,
    fingers: Optional[List[bool]],
    gesture: Optional[GestureEvent],
    stable_count: int,
    stable_required: int,
    pinch_dist: float,
    log_events: Deque[str],
    handedness: Optional[str],
) -> None:
    h, w = frame.shape[:2]
    px = w - 220
    py = 10

    # Fondo semitransparente panel derecho
    draw_rounded_rect(frame, px-8, py, w-4, h-10, C_DARK, alpha=0.65)

    # ── Gesto detectado ────────────────────────────────────────────────────
    if gesture:
        col = GESTURE_COLORS.get(gesture, C_WHITE)
        label = GESTURE_EMOJIS.get(gesture, gesture.value)
        # Split en dos líneas si necesario
        parts = label.split("—", 1)
        put_text(frame, parts[0].strip(), (px, py+22), scale=0.62, color=col, thickness=2)
        if len(parts) > 1:
            put_text(frame, parts[1].strip(), (px, py+44), scale=0.48, color=C_GRAY)
    else:
        put_text(frame, "Sin gesto", (px, py+22), scale=0.55, color=C_GRAY)

    # ── Barra de estabilidad ───────────────────────────────────────────────
    py2 = py + 58
    put_text(frame, "Estabilidad:", (px, py2), scale=0.4, color=C_GRAY)
    stab_val = stable_count / max(stable_required, 1)
    col_bar = GESTURE_COLORS.get(gesture, C_IDLE) if gesture else C_DARK
    draw_progress_bar(frame, px, py2+4, 200, 12, stab_val, col_bar,
                      label=f"{stable_count}/{stable_required}")

    # ── Distancia pinch ────────────────────────────────────────────────────
    py2 += 24
    put_text(frame, f"Pinch dist: {pinch_dist:.3f}", (px, py2), scale=0.4, color=C_GRAY)
    threshold = 0.06
    draw_progress_bar(frame, px, py2+4, 200, 8,
                      1.0 - min(pinch_dist / 0.2, 1.0),
                      C_ACT if pinch_dist < threshold else C_DARK)

    # ── Estado de dedos ────────────────────────────────────────────────────
    py2 += 24
    put_text(frame, "Dedos:", (px, py2), scale=0.42, color=C_GRAY)
    py2 += 4
    if fingers:
        for i, (name, up) in enumerate(zip(FINGER_NAMES, fingers)):
            col = C_LISTEN if up else (80, 80, 80)
            symbol = "▮" if up else "▯"
            put_text(frame, f"  {symbol} {name}", (px, py2 + i*18),
                     scale=0.42, color=col)
    else:
        put_text(frame, "  (sin mano)", (px, py2), scale=0.42, color=C_GRAY)
    py2 += 5 * 18 + 4

    # ── Mano detectada ─────────────────────────────────────────────────────
    if handedness:
        put_text(frame, f"Mano: {handedness}", (px, py2), scale=0.42, color=C_THINK)
    py2 += 20

    # ── Log de gestos ──────────────────────────────────────────────────────
    put_text(frame, "─── Log ───", (px, py2), scale=0.38, color=C_GRAY)
    py2 += 16
    for i, entry in enumerate(reversed(list(log_events))):
        if py2 + 14 > h - 10:
            break
        alpha_col = max(60, 255 - i * 35)
        put_text(frame, entry, (px, py2), scale=0.37,
                 color=(alpha_col, alpha_col, alpha_col))
        py2 += 14


# ─────────────────────────────────────────────────────────────────────────────
# Panel inferior: cara y contexto
# ─────────────────────────────────────────────────────────────────────────────

def draw_bottom_panel(
    frame: np.ndarray,
    face_present: bool,
    looking: bool,
    face_box: Optional[Tuple[int,int,int,int]],
    fps: float,
    mirror: bool,
) -> None:
    h, w = frame.shape[:2]
    bh = 36
    draw_rounded_rect(frame, 0, h-bh, w-225, h, C_DARK, alpha=0.65)

    # FPS
    put_text(frame, f"FPS: {fps:.0f}", (8, h-bh+22), scale=0.48, color=C_GRAY)

    # Cara
    face_col = C_FACE if face_present else (80, 80, 80)
    face_label = "👤 Cara detectada" if face_present else "❌ Sin cara"
    put_text(frame, face_label, (70, h-bh+22), scale=0.48, color=face_col)

    if face_present:
        look_col = C_LISTEN if looking else C_THINK
        look_label = "👁 Mirando" if looking else "↪ De lado"
        put_text(frame, look_label, (230, h-bh+22), scale=0.48, color=look_col)

    # Espejo
    mirror_col = C_THINK if mirror else C_GRAY
    put_text(frame, "[M] Espejo", (390, h-bh+22), scale=0.42, color=mirror_col)
    put_text(frame, "[Q] Salir",  (480, h-bh+22), scale=0.42, color=C_GRAY)


# ─────────────────────────────────────────────────────────────────────────────
# Dibujar landmarks de mano (propio, sin depender de mp_draw)
# ─────────────────────────────────────────────────────────────────────────────

_HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),         # pulgar
    (0,5),(5,6),(6,7),(7,8),         # índice
    (0,9),(9,10),(10,11),(11,12),    # medio
    (0,13),(13,14),(14,15),(15,16),  # anular
    (0,17),(17,18),(18,19),(19,20),  # meñique
    (5,9),(9,13),(13,17),            # palma
]

_TIPS_IDX = {4, 8, 12, 16, 20}

def draw_hand_landmarks(
    frame: np.ndarray,
    landmarks: Any,
    gesture: Optional[GestureEvent],
) -> None:
    h, w = frame.shape[:2]
    pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]

    col_conn = GESTURE_COLORS.get(gesture, C_LANDMARK) if gesture else C_LANDMARK

    # Conexiones
    for a, b in _HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], col_conn, 2, cv2.LINE_AA)

    # Puntos
    for i, pt in enumerate(pts):
        r = 7 if i in _TIPS_IDX else 4
        col = C_TIP if i in _TIPS_IDX else col_conn
        cv2.circle(frame, pt, r, col, -1, cv2.LINE_AA)
        cv2.circle(frame, pt, r, C_WHITE, 1, cv2.LINE_AA)


# ─────────────────────────────────────────────────────────────────────────────
# Inicializar MediaPipe — soporta solutions API y Tasks API
# ─────────────────────────────────────────────────────────────────────────────

def init_mediapipe():
    mp_solutions = getattr(mp, "solutions", None)
    if mp_solutions is None:
        return None, None, None, None  # usaremos Tasks API

    hands_module    = mp_solutions.hands
    face_module     = mp_solutions.face_detection

    hands = hands_module.Hands(
        model_complexity=0,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.6,
        max_num_hands=1,
    )
    face_det = face_module.FaceDetection(
        model_selection=0,
        min_detection_confidence=0.6,
    )
    return mp_solutions, hands, face_det, mp_solutions.drawing_utils


def _download_model(url: str, dest: Path) -> None:
    """Descarga un modelo si no existe o está incompleto."""
    if dest.exists() and dest.stat().st_size > 500_000:
        return
    print(f"⬇  Descargando {dest.name}...")
    import urllib.request
    tmp = dest.with_suffix(".tmp")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)
    print(f"✓ {dest.name} descargado.")


def init_tasks_hand_landmarker():
    """Inicializa MediaPipe Tasks HandLandmarker (para builds modernos sin mp.solutions)."""
    model_dir = Path.home() / "Documents" / "Jarvis" / "models" / "mediapipe"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "hand_landmarker.task"
    _download_model(
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
        "hand_landmarker/float16/1/hand_landmarker.task",
        model_path,
    )
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    opts = mp_vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        num_hands=1,
        min_hand_detection_confidence=0.7,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.6,
    )
    return mp_vision.HandLandmarker.create_from_options(opts)


def init_tasks_face_detector():
    """Inicializa MediaPipe Tasks FaceDetector."""
    model_dir = Path.home() / "Documents" / "Jarvis" / "models" / "mediapipe"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "blaze_face_short_range.tflite"
    _download_model(
        "https://storage.googleapis.com/mediapipe-models/face_detector/"
        "blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
        model_path,
    )
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    opts = mp_vision.FaceDetectorOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        min_detection_confidence=0.5,
    )
    return mp_vision.FaceDetector.create_from_options(opts)


# ─────────────────────────────────────────────────────────────────────────────
# Detección de cara (MediaPipe Face Detection o Haar fallback)
# ─────────────────────────────────────────────────────────────────────────────

def detect_face(frame: np.ndarray, face_det, face_cascade, tasks_face_det=None) -> Tuple[bool, bool, Optional[Tuple[int,int,int,int]]]:
    """Devuelve (present, looking, box_xywh_px)."""
    h, w = frame.shape[:2]

    # MediaPipe Face Detection (solutions API — legacy)
    if face_det is not None:
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_det.process(rgb)
            if results and results.detections:
                best = max(results.detections, key=lambda d: (
                    d.location_data.relative_bounding_box.width *
                    d.location_data.relative_bounding_box.height
                ))
                bb = best.location_data.relative_bounding_box
                x = max(0, int(bb.xmin * w))
                y = max(0, int(bb.ymin * h))
                bw = int(bb.width  * w)
                bh = int(bb.height * h)
                cx = x + bw // 2
                cy = y + bh // 2
                looking = (bw/w > 0.12 and 0.25 < cx/w < 0.75 and cy/h < 0.65)
                return True, looking, (x, y, bw, bh)
            return False, False, None
        except Exception:
            pass

    # MediaPipe Tasks FaceDetector (builds modernos sin mp.solutions)
    if tasks_face_det is not None:
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            results = tasks_face_det.detect(mp_img)
            if results and results.detections:
                best = max(results.detections, key=lambda d: (
                    d.bounding_box.width * d.bounding_box.height
                ))
                bb = best.bounding_box
                x, y, bw, bh = bb.origin_x, bb.origin_y, bb.width, bb.height
                cx = x + bw // 2
                cy = y + bh // 2
                looking = (bw/w > 0.12 and 0.25 < cx/w < 0.75 and cy/h < 0.65)
                return True, looking, (x, y, bw, bh)
            return False, False, None
        except Exception:
            pass

    # Haar fallback
    if face_cascade is not None:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(60, 60))
        if len(faces):
            x, y, bw, bh = max(faces, key=lambda f: f[2]*f[3])
            cx = x + bw // 2
            cy = y + bh // 2
            looking = (bw/w > 0.12 and 0.25 < cx/w < 0.75 and cy/h < 0.65)
            return True, looking, (x, y, bw, bh)

    return False, False, None


def draw_face_box(frame: np.ndarray, box: Tuple[int,int,int,int], looking: bool) -> None:
    x, y, bw, bh = box
    col = C_LISTEN if looking else C_FACE
    # Esquinas estilo "reticle"
    corner = 15
    th = 2
    for (cx, cy, dx, dy) in [
        (x,    y,    1,  1),
        (x+bw, y,   -1,  1),
        (x,    y+bh, 1, -1),
        (x+bw, y+bh,-1, -1),
    ]:
        cv2.line(frame, (cx, cy), (cx + dx*corner, cy), col, th)
        cv2.line(frame, (cx, cy), (cx, cy + dy*corner), col, th)
    label = "mirando" if looking else "presente"
    put_text(frame, f"cara — {label}", (x, y-6), scale=0.42, color=col)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 58)
    print("  JARVIS Vision Preview")
    print("  Gestos + Cara — hilo principal (OpenCV seguro en macOS)")
    print("=" * 58)

    # ── Abrir cámara ──────────────────────────────────────────────────────
    import os
    os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")

    camera_index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"❌ No se pudo abrir la cámara {camera_index}.")
        print("   Ajustes → Privacidad y seguridad → Cámara → activa Terminal")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    print(f"✓ Cámara {camera_index} abierta.")

    # ── Inicializar MediaPipe ─────────────────────────────────────────────
    use_tasks = False
    mp_solutions, hands_model, face_det, mp_draw = init_mediapipe()
    hand_landmarker = None
    face_cascade = None

    tasks_face_det = None
    if mp_solutions is None:
        print("⚠  mp.solutions no disponible — usando Tasks API")
        use_tasks = True
        try:
            hand_landmarker = init_tasks_hand_landmarker()
            print("✓ Tasks HandLandmarker cargado.")
        except Exception as e:
            print(f"⚠  HandLandmarker no disponible: {e}")
        try:
            tasks_face_det = init_tasks_face_detector()
            print("✓ Tasks FaceDetector cargado.")
        except Exception as e:
            print(f"⚠  Tasks FaceDetector no disponible: {e}")
            # Haar fallback
            try:
                cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
                if cascade_path.exists():
                    face_cascade = cv2.CascadeClassifier(str(cascade_path))
                    if face_cascade.empty():
                        face_cascade = None
                    else:
                        print("✓ Haar Face Detection cargado (fallback).")
            except Exception:
                pass
    else:
        print("✓ MediaPipe solutions cargado (manos + cara).")

    # ── Estado ────────────────────────────────────────────────────────────
    STABLE_REQUIRED  = 5
    mirror           = True
    stable_counts: dict[str, int] = {}
    last_trigger     = 0.0
    COOLDOWN         = 1.5
    log_events: Deque[str] = deque(maxlen=8)

    current_gesture: Optional[GestureEvent] = None
    current_fingers: Optional[List[bool]]   = None
    current_pinch   = 1.0
    current_hand    = None
    face_present    = False
    looking         = False
    face_box        = None

    fps_t0      = time.monotonic()
    fps_count   = 0
    fps_display = 0.0

    face_check_every = 10  # analizar cara cada N frames (más lento)
    frame_num = 0

    print("\n🎥 Preview activo. Presiona Q o ESC para salir, M para espejo.\n")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            frame_num += 1

            # Espejo horizontal
            if mirror:
                frame = cv2.flip(frame, 1)

            h, w = frame.shape[:2]

            # ── Detección de mano ──────────────────────────────────────────
            raw_gesture: Optional[GestureEvent] = None
            raw_landmarks = None
            handedness_label = None

            if use_tasks and hand_landmarker:
                try:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    res = hand_landmarker.detect(mp_img)
                    if getattr(res, "hand_landmarks", None):
                        raw_landmarks = res.hand_landmarks[0]
                        if getattr(res, "handedness", None) and res.handedness[0]:
                            handedness_label = getattr(
                                res.handedness[0][0], "category_name", "Right"
                            )
                        raw_gesture = detect_gesture(raw_landmarks, handedness_label or "Right")
                except Exception:
                    pass

            elif hands_model:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                res = hands_model.process(rgb)
                rgb.flags.writeable = True
                if res.multi_hand_landmarks and res.multi_handedness:
                    hl  = res.multi_hand_landmarks[0]
                    raw_landmarks = hl.landmark
                    handedness_label = res.multi_handedness[0].classification[0].label
                    raw_gesture = detect_gesture(raw_landmarks, handedness_label)

            # Calcular estado de dedos y pinch
            if raw_landmarks:
                current_fingers = fingers_up(raw_landmarks, handedness_label or "Right")
                current_pinch   = pinch_distance(raw_landmarks)
                current_hand    = handedness_label
            else:
                current_fingers = None
                current_pinch   = 1.0
                current_hand    = None
                stable_counts.clear()

            # ── Estabilidad de gesto ───────────────────────────────────────
            if raw_gesture:
                key = raw_gesture.value
                for k in list(stable_counts):
                    if k != key:
                        stable_counts[k] = 0
                stable_counts[key] = stable_counts.get(key, 0) + 1

                if stable_counts[key] >= STABLE_REQUIRED:
                    now = time.monotonic()
                    if now - last_trigger >= COOLDOWN:
                        last_trigger = now
                        stable_counts[key] = 0
                        ts = time.strftime("%H:%M:%S")
                        label = GESTURE_EMOJIS.get(raw_gesture, raw_gesture.value)
                        log_events.append(f"[{ts}] {label}")
                        print(f"  ✋ Gesto disparado: {label}")

                current_gesture = raw_gesture
            else:
                current_gesture = None

            stable_count = stable_counts.get(
                current_gesture.value if current_gesture else "", 0
            )

            # ── Detección de cara (cada N frames) ─────────────────────────
            if frame_num % face_check_every == 0:
                face_present, looking, face_box = detect_face(
                    frame, face_det, face_cascade, tasks_face_det
                )

            # ── Dibujar ───────────────────────────────────────────────────

            # Cara
            if face_present and face_box:
                draw_face_box(frame, face_box, looking)

            # Landmarks de mano
            if raw_landmarks:
                draw_hand_landmarks(frame, raw_landmarks, current_gesture)

            # Panel derecho
            draw_right_panel(
                frame,
                fingers=current_fingers,
                gesture=current_gesture,
                stable_count=stable_count,
                stable_required=STABLE_REQUIRED,
                pinch_dist=current_pinch,
                log_events=log_events,
                handedness=current_hand,
            )

            # Panel inferior
            draw_bottom_panel(frame, face_present, looking, face_box, fps_display, mirror)

            # Título superior
            draw_rounded_rect(frame, 0, 0, 320, 34, C_DARK, alpha=0.6)
            put_text(frame, "JARVIS — Vision Preview", (8, 22),
                     scale=0.62, color=C_IDLE, thickness=2)

            # FPS
            fps_count += 1
            elapsed = time.monotonic() - fps_t0
            if elapsed >= 1.0:
                fps_display = fps_count / elapsed
                fps_count = 0
                fps_t0 = time.monotonic()

            # ── Mostrar ───────────────────────────────────────────────────
            cv2.imshow("JARVIS — Vision Preview", frame)

            key_pressed = cv2.waitKey(1) & 0xFF
            if key_pressed in (ord("q"), ord("Q"), 27):  # Q o ESC
                break
            elif key_pressed in (ord("m"), ord("M")):
                mirror = not mirror
                print(f"  Espejo: {'ON' if mirror else 'OFF'}")
            elif key_pressed in (ord("f"), ord("F")):
                # Toggle fullscreen
                prop = cv2.getWindowProperty("JARVIS — Vision Preview", cv2.WND_PROP_FULLSCREEN)
                if prop == cv2.WINDOW_FULLSCREEN:
                    cv2.setWindowProperty("JARVIS — Vision Preview",
                                          cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
                else:
                    cv2.setWindowProperty("JARVIS — Vision Preview",
                                          cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if hands_model:
            hands_model.close()
        if face_det:
            face_det.close()
        if hand_landmarker:
            hand_landmarker.close()
        if tasks_face_det:
            tasks_face_det.close()
        cv2.destroyAllWindows()
        print("\n✓ Preview cerrado.")


if __name__ == "__main__":
    main()
