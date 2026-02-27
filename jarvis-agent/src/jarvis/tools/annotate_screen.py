"""
annotate_screen.py

Tool LLM para dibujar anotaciones visuales sobre la pantalla.
Solo disponible en modo desktop (requiere AnnotationOverlay activo).

Tipos soportados:
  circle — círculo en coordenadas normalizadas [0,1] desde top-left
  arrow  — flecha de (x,y) a (x2,y2)
  rect   — rectángulo de (x,y) a (x2,y2)
  text   — texto en coordenadas normalizadas

Colores: red, yellow, green, blue, white, orange, purple
"""
from __future__ import annotations

from typing import Any, Dict


def annotate_screen(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Dibuja anotaciones visuales sobre la pantalla.

    Args esperados:
        annotations (list): Lista de dicts con campos:
            type (str): "circle" | "arrow" | "rect" | "text"
            x, y (float): posición normalizada [0,1] top-left
            x2, y2 (float): extremo para arrow/rect (opcional)
            radius (float): radio en px para circle (default 40)
            label (str): etiqueta o texto (opcional)
            color (str): nombre de color (default "red")
            thickness (float): grosor de línea (default 3.0)
        duration_s (float): segundos de visibilidad (default 10)
        clear_previous (bool): limpiar anotaciones anteriores (default false)

    Returns:
        {"ok": bool, "result": str} | {"ok": False, "error": str}
    """
    from jarvis.overlay import annotation as _ann

    overlay = _ann.get_instance()
    if overlay is None:
        return {
            "ok": False,
            "error": (
                "Overlay de anotaciones no disponible. "
                "Solo funciona en modo desktop (--desktop)."
            ),
        }

    clear = bool(args.get("clear_previous", False))
    if clear:
        overlay.clear()

    duration_s = float(args.get("duration_s", 10.0))
    annotations = args.get("annotations", [])

    if not isinstance(annotations, list):
        return {"ok": False, "error": "El campo 'annotations' debe ser una lista."}

    count = 0
    errors: list[str] = []

    for spec in annotations:
        if not isinstance(spec, dict):
            continue
        try:
            overlay.add_annotation(
                type=str(spec.get("type", "circle")),
                x=float(spec.get("x", 0.5)),
                y=float(spec.get("y", 0.5)),
                x2=float(spec.get("x2", 0.0)),
                y2=float(spec.get("y2", 0.0)),
                radius=float(spec.get("radius", 40.0)),
                text=str(spec.get("label", spec.get("text", ""))),
                color=str(spec.get("color", "red")),
                thickness=float(spec.get("thickness", 3.0)),
                duration_s=duration_s,
            )
            count += 1
        except Exception as e:
            errors.append(str(e))

    if count == 0 and not clear:
        msg = f"No se añadieron anotaciones. Errores: {errors}" if errors else "Lista de anotaciones vacía."
        return {"ok": False, "error": msg}

    result_msg = f"{count} anotación(es) añadida(s) por {duration_s:.0f}s"
    if clear:
        result_msg = f"Anotaciones anteriores limpiadas. {result_msg}"

    return {"ok": True, "result": result_msg}
