"""
dock.py

Detecta la posición exacta de iconos del Dock usando la API de Accesibilidad de macOS.

Requiere permiso de Accesibilidad:
  Ajustes del Sistema → Privacidad y Seguridad → Accesibilidad → Terminal (o Python)

Coordenadas devueltas: sistema Cocoa (origen = esquina inferior-izquierda).
Las coordenadas AX usan top-left origin → convertimos con screen_h.

Uso:
    pos = get_dock_icon_position("Spotify", screen_h)
    if pos:
        bridge.fly_to(*pos)
"""

from __future__ import annotations

import subprocess
from typing import Optional, Tuple


def _get_dock_pid() -> Optional[int]:
    """Obtiene el PID del proceso Dock."""
    try:
        r = subprocess.run(
            ["pgrep", "-x", "Dock"],
            capture_output=True, text=True, timeout=2,
        )
        s = r.stdout.strip()
        return int(s) if s else None
    except Exception:
        return None


def _ax_to_cocoa_center(
    ax_x: float, ax_y: float,
    w: float, h: float,
    screen_h: float,
) -> Tuple[float, float]:
    """
    Convierte esquina top-left AX + tamaño → centro en coordenadas Cocoa.
    AX: (0,0) = top-left de la pantalla.
    Cocoa: (0,0) = bottom-left de la pantalla.
    """
    cx = ax_x + w / 2.0
    cy = screen_h - (ax_y + h / 2.0)
    return cx, cy


def get_dock_icon_position(
    app_name: str,
    screen_h: float,
) -> Optional[Tuple[float, float]]:
    """
    Devuelve (x, y) en coordenadas Cocoa del centro del icono de `app_name` en el Dock.
    Devuelve None si no se encuentra o no hay permisos de Accesibilidad.

    Args:
        app_name:  nombre de la app (ej: "Spotify", "Safari"). Case-insensitive.
        screen_h:  altura de la pantalla principal en puntos.
    """
    try:
        return _find_in_dock(app_name, screen_h)
    except Exception:
        return None


def _find_in_dock(app_name: str, screen_h: float) -> Optional[Tuple[float, float]]:
    try:
        import ApplicationServices as AX
    except ImportError:
        return None

    pid = _get_dock_pid()
    if pid is None:
        return None

    dock_elem = AX.AXUIElementCreateApplication(pid)

    # Nivel 1: hijos directos del proceso Dock (normalmente 1 AXList)
    err, top_children = AX.AXUIElementCopyAttributeValue(dock_elem, "AXChildren", None)
    if err != 0 or not top_children:
        return None

    name_lower = app_name.lower()

    for ax_list in top_children:
        err2, items = AX.AXUIElementCopyAttributeValue(ax_list, "AXChildren", None)
        if err2 != 0 or not items:
            continue

        for item in items:
            # ── Título ────────────────────────────────────────────────────────
            err3, title = AX.AXUIElementCopyAttributeValue(item, "AXTitle", None)
            if err3 != 0 or not title:
                continue
            if name_lower not in str(title).lower():
                continue

            # ── Posición (AXValue → CGPoint) ──────────────────────────────────
            err4, pos_val = AX.AXUIElementCopyAttributeValue(item, "AXPosition", None)
            if err4 != 0 or pos_val is None:
                continue
            ok_p, pt = AX.AXValueGetValue(pos_val, AX.kAXValueCGPointType, None)
            if not ok_p:
                continue

            # ── Tamaño (AXValue → CGSize) ─────────────────────────────────────
            err5, size_val = AX.AXUIElementCopyAttributeValue(item, "AXSize", None)
            if err5 != 0 or size_val is None:
                continue
            ok_s, sz = AX.AXValueGetValue(size_val, AX.kAXValueCGSizeType, None)
            if not ok_s:
                continue

            return _ax_to_cocoa_center(pt.x, pt.y, sz.width, sz.height, screen_h)

    return None


def check_accessibility_permission() -> bool:
    """
    Comprueba si la app tiene permiso de Accesibilidad.
    Si no lo tiene, macOS muestra el diálogo de petición de permiso.
    """
    try:
        import ApplicationServices as AX
        # AXIsProcessTrustedWithOptions muestra el diálogo si prompt=True
        opts = {"AXTrustedCheckOptionPrompt": True}
        return bool(AX.AXIsProcessTrustedWithOptions(opts))
    except Exception:
        return False
