#!/usr/bin/env python3
"""
camera_preview.py — Vista en tiempo real de lo que ve Jarvis por la cámara.

Muestra:
  - Feed de cámara en vivo
  - Detección de cara (MediaPipe o Haar)
  - Estado: usuario presente / mirando / ausente
  - Descripción de objetos via Groq Vision (si GROQ_API_KEY disponible)

Uso:
    cd /Users/luichi/Documents/Jarvis/jarvis-agent
    source .venv/bin/activate
    PYTHONPATH=src python scripts/camera_preview.py
    PYTHONPATH=src python scripts/camera_preview.py --camera 0 --no-groq
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from pathlib import Path

# ── Cargar .env ──────────────────────────────────────────────────────────────
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import cv2
import numpy as np


# ── Colores estilo Jarvis ────────────────────────────────────────────────────
CYAN   = (255, 224, 0)    # BGR cyan-ish
GREEN  = (136, 255, 0)    # BGR verde
PINK   = (96, 32, 255)    # BGR pink
PURPLE = (255, 48, 138)   # BGR purple
WHITE  = (255, 255, 255)
DARK   = (16, 8, 8)


def load_face_detector():
    """Intenta MediaPipe primero, luego Haar cascade."""
    try:
        import mediapipe as mp
        mp_face = mp.solutions.face_detection.FaceDetection(
            model_selection=0, min_detection_confidence=0.6
        )
        print("✓ MediaPipe Face Detection cargado")
        return ("mediapipe", mp_face)
    except Exception as e:
        print(f"  MediaPipe no disponible: {e}")

    try:
        cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(str(cascade_path))
        if not cascade.empty():
            print("✓ OpenCV Haar Cascade cargado (fallback)")
            return ("haar", cascade)
    except Exception as e:
        print(f"  Haar cascade no disponible: {e}")

    print("⚠ Sin detector facial")
    return (None, None)


def detect_face(frame, detector_type, detector):
    """Retorna (present, looking, bbox_xyxy) o (False, False, None)."""
    if detector is None:
        return False, False, None

    h, w = frame.shape[:2]

    if detector_type == "mediapipe":
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = detector.process(rgb)
        if not results.detections:
            return False, False, None
        best = max(results.detections,
                   key=lambda d: d.location_data.relative_bounding_box.width
                               * d.location_data.relative_bounding_box.height)
        bb = best.location_data.relative_bounding_box
        x1 = int(bb.xmin * w)
        y1 = int(bb.ymin * h)
        x2 = int((bb.xmin + bb.width) * w)
        y2 = int((bb.ymin + bb.height) * h)
        face_w = bb.width
        cx = bb.xmin + face_w / 2
        cy = bb.ymin + bb.height / 2
        looking = face_w > 0.12 and 0.3 < cx < 0.7 and cy < 0.65
        return True, looking, (x1, y1, x2, y2)

    if detector_type == "haar":
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
        if len(faces) == 0:
            return False, False, None
        x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        face_w = fw / max(1.0, w)
        cx = (x + fw * 0.5) / max(1.0, w)
        cy = (y + fh * 0.5) / max(1.0, h)
        looking = face_w > 0.12 and 0.3 < cx < 0.7 and cy < 0.7
        return True, looking, (x, y, x + fw, y + fh)

    return False, False, None


def analyze_with_groq(frame, api_key: str) -> str:
    """Envía frame a Groq Vision y retorna descripción de objetos."""
    try:
        from groq import Groq
        small = cv2.resize(frame, (640, 480))
        _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
        b64 = base64.b64encode(buf.tobytes()).decode()

        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text",
                     "text": (
                         "Describe briefly the objects visible near the person "
                         "or being held by them. One short sentence max. "
                         "Reply only with the description, no preamble."
                     )},
                ],
            }],
            max_tokens=60,
            temperature=0.1,
        )
        result = resp.choices[0].message.content.strip() if resp.choices else ""
        return result if len(result) >= 4 else ""
    except Exception as e:
        return f"[error: {e}]"


def draw_overlay(frame, present, looking, bbox, obj_ctx, fps, groq_status):
    h, w = frame.shape[:2]

    # ── Bounding box cara ────────────────────────────────────────────────────
    if bbox and present:
        color = GREEN if looking else CYAN
        x1, y1, x2, y2 = bbox
        thick = 2
        # Esquinas estilo HUD
        l = min(30, (x2 - x1) // 3)
        cv2.line(frame, (x1, y1), (x1 + l, y1), color, thick)
        cv2.line(frame, (x1, y1), (x1, y1 + l), color, thick)
        cv2.line(frame, (x2, y1), (x2 - l, y1), color, thick)
        cv2.line(frame, (x2, y1), (x2, y1 + l), color, thick)
        cv2.line(frame, (x1, y2), (x1 + l, y2), color, thick)
        cv2.line(frame, (x1, y2), (x1, y2 - l), color, thick)
        cv2.line(frame, (x2, y2), (x2 - l, y2), color, thick)
        cv2.line(frame, (x2, y2), (x2, y2 - l), color, thick)

    # ── Panel inferior ───────────────────────────────────────────────────────
    panel_h = 110
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h - panel_h), (w, h), DARK, -1)
    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

    font = cv2.FONT_HERSHEY_SIMPLEX

    # Estado
    if not present:
        status_text = "AUSENTE"
        status_color = (100, 100, 100)
    elif looking:
        status_text = "MIRANDO"
        status_color = GREEN
    else:
        status_text = "PRESENTE"
        status_color = CYAN

    cv2.putText(frame, f"JARVIS VISION  |  {status_text}",
                (12, h - panel_h + 28), font, 0.65, status_color, 2)

    # Objetos
    obj_display = obj_ctx if obj_ctx else "(sin análisis)"
    cv2.putText(frame, f"Objetos: {obj_display}",
                (12, h - panel_h + 58), font, 0.5, WHITE, 1)

    # Groq status + FPS
    cv2.putText(frame, groq_status,
                (12, h - panel_h + 84), font, 0.42, (150, 150, 150), 1)
    cv2.putText(frame, f"{fps:.0f} FPS",
                (w - 80, h - panel_h + 28), font, 0.55, (100, 255, 100), 1)

    # Instrucciones
    cv2.putText(frame, "Q — salir",
                (12, h - 10), font, 0.38, (120, 120, 120), 1)

    return frame


def main():
    parser = argparse.ArgumentParser(description="Jarvis Camera Preview")
    parser.add_argument("--camera", type=int, default=int(os.environ.get("CAMERA_CONTEXT_INDEX", 0)),
                        help="Índice de cámara (default: CAMERA_CONTEXT_INDEX o 0)")
    parser.add_argument("--interval", type=float,
                        default=float(os.environ.get("CAMERA_CONTEXT_INTERVAL", 5.0)),
                        help="Segundos entre análisis Groq Vision (default: 5)")
    parser.add_argument("--no-groq", action="store_true",
                        help="Desactivar análisis Groq Vision (solo detección facial)")
    args = parser.parse_args()

    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    use_groq = bool(groq_api_key) and not args.no_groq

    print(f"\n{'='*52}")
    print("  JARVIS — Vista de cámara en tiempo real")
    print(f"{'='*52}")
    print(f"  Cámara:       {args.camera}")
    print(f"  Groq Vision:  {'✓ activo' if use_groq else '✗ desactivado (--no-groq o sin API key)'}")
    print(f"  Intervalo:    {args.interval}s")
    print(f"{'='*52}\n")

    os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"ERROR: No se pudo abrir cámara {args.camera}")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    det_type, detector = load_face_detector()

    obj_ctx = ""
    last_groq = 0.0
    groq_status = "Groq Vision: inactivo" if not use_groq else "Groq Vision: esperando..."

    t_prev = time.monotonic()
    fps = 0.0

    cv2.namedWindow("JARVIS — Vista de cámara", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("JARVIS — Vista de cámara", 960, 600)

    print("Ventana abierta. Pulsa Q para salir.\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("ERROR: no se pudo leer frame")
            break

        now = time.monotonic()
        fps = 0.9 * fps + 0.1 * (1.0 / max(0.001, now - t_prev))
        t_prev = now

        # Detección facial
        present, looking, bbox = detect_face(frame, det_type, detector)

        # Análisis Groq Vision periódico
        if use_groq and present and (now - last_groq) >= args.interval:
            last_groq = now
            groq_status = "Groq Vision: analizando..."
            cv2.imshow("JARVIS — Vista de cámara", frame)
            cv2.waitKey(1)
            obj_ctx = analyze_with_groq(frame, groq_api_key)
            if obj_ctx and not obj_ctx.startswith("[error"):
                groq_status = f"Groq Vision: actualizado {time.strftime('%H:%M:%S')}"
                print(f"  Objetos detectados: {obj_ctx}")
            elif obj_ctx.startswith("[error"):
                groq_status = f"Groq Vision: {obj_ctx}"
                obj_ctx = ""
            else:
                groq_status = "Groq Vision: sin objetos notables"

        draw_overlay(frame, present, looking, bbox, obj_ctx, fps, groq_status)
        cv2.imshow("JARVIS — Vista de cámara", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q") or key == 27:
            break

    cap.release()
    cv2.destroyAllWindows()
    print("\nPrevisualizacion cerrada.")


if __name__ == "__main__":
    main()
