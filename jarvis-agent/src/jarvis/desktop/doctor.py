"""
doctor.py

Diagnóstico rápido de Jarvis Desktop en macOS:
- Autoarranque LaunchAgent
- Permiso de Micrófono
- Permiso de Accesibilidad
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from typing import Any, Dict, List

from jarvis.desktop.autostart import get_autostart_status


@dataclass(frozen=True)
class DesktopDoctorResult:
    platform: str
    autostart_installed: bool
    autostart_loaded: bool
    microphone: str
    accessibility: str
    issues: List[str]


def _check_microphone_permission(*, request_if_needed: bool = False) -> str:
    if sys.platform != "darwin":
        return "unsupported"
    try:
        import AVFoundation  # type: ignore

        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio
        )
        if status == 3:
            return "granted"
        if status == 0:
            if request_if_needed:
                done = threading.Event()
                granted_box = {"value": False}

                def _handler(granted: bool) -> None:
                    granted_box["value"] = bool(granted)
                    done.set()

                AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    AVFoundation.AVMediaTypeAudio, _handler
                )
                done.wait(timeout=20)
                return "granted" if granted_box["value"] else "denied"
            return "not_determined"
        if status == 2:
            return "denied"
        return "restricted"
    except Exception:
        return "unknown_missing_avfoundation"


def _check_accessibility_permission(*, prompt: bool = False) -> str:
    if sys.platform != "darwin":
        return "unsupported"
    try:
        import ApplicationServices as AX  # type: ignore

        trusted = bool(AX.AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": bool(prompt)}))
        return "granted" if trusted else "denied"
    except Exception:
        return "unknown"


def run_desktop_doctor(*, attempt_repair: bool = False) -> DesktopDoctorResult:
    st = get_autostart_status()
    try:
        mic = _check_microphone_permission(request_if_needed=attempt_repair)
    except TypeError:
        # Compatibilidad con tests/mocks viejos que no aceptan kwargs.
        mic = _check_microphone_permission()
    try:
        ax = _check_accessibility_permission(prompt=attempt_repair)
    except TypeError:
        # Compatibilidad con tests/mocks viejos que no aceptan kwargs.
        ax = _check_accessibility_permission()
    issues: List[str] = []

    if not st.installed:
        issues.append("Autoarranque no instalado.")
    if st.installed and not st.loaded:
        issues.append("LaunchAgent instalado pero no cargado.")
    if mic in ("denied", "restricted"):
        issues.append("Permiso de micrófono denegado/restringido.")
    if mic == "not_determined":
        issues.append("Permiso de micrófono pendiente de solicitar.")
    if mic == "unknown_missing_avfoundation":
        issues.append("No se puede verificar micrófono: falta pyobjc-framework-AVFoundation.")
    if ax == "denied":
        issues.append("Permiso de accesibilidad no concedido.")

    return DesktopDoctorResult(
        platform=sys.platform,
        autostart_installed=st.installed,
        autostart_loaded=st.loaded,
        microphone=mic,
        accessibility=ax,
        issues=issues,
    )


def doctor_result_to_dict(r: DesktopDoctorResult) -> Dict[str, Any]:
    return {
        "platform": r.platform,
        "autostart_installed": r.autostart_installed,
        "autostart_loaded": r.autostart_loaded,
        "microphone": r.microphone,
        "accessibility": r.accessibility,
        "issues": list(r.issues),
        "ok": len(r.issues) == 0,
    }
