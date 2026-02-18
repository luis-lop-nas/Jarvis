"""
autostart.py

Instala / desinstala Jarvis Desktop como LaunchAgent de macOS.
Arranca automáticamente al iniciar sesión, sin terminal, sin Dock.

API:
    from jarvis.autostart import install, uninstall, is_installed
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


LABEL      = "com.jarvis.desktop"
PLIST_DIR  = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = PLIST_DIR / f"{LABEL}.plist"


def _project_root() -> Path:
    """Raíz de jarvis-agent/ (padre de src/)."""
    return Path(__file__).resolve().parents[2]


def _python_bin() -> Path:
    return _project_root() / ".venv" / "bin" / "python"


def _src_path() -> Path:
    return _project_root() / "src"


def _uid() -> str:
    return str(os.getuid())


def _build_plist() -> str:
    root   = _project_root()
    python = _python_bin()
    src    = _src_path()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>jarvis</string>
        <string>--desktop</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{root}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>{src}</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <false/>

    <key>StandardOutPath</key>
    <string>/tmp/jarvis.log</string>

    <key>StandardErrorPath</key>
    <string>/tmp/jarvis.err</string>
</dict>
</plist>
"""


def is_installed() -> bool:
    """True si el LaunchAgent está instalado."""
    return PLIST_PATH.exists()


def install() -> None:
    """Instala el LaunchAgent y lo activa en la sesión actual."""
    PLIST_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_build_plist(), encoding="utf-8")

    # Cargar en la sesión actual (macOS 10.15+)
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{_uid()}", str(PLIST_PATH)],
        check=False,   # puede fallar si ya está cargado — no es error fatal
    )
    print(f"✅ Autostart instalado: {PLIST_PATH}")


def uninstall() -> None:
    """Desactiva y elimina el LaunchAgent."""
    if PLIST_PATH.exists():
        subprocess.run(
            ["launchctl", "bootout", f"gui/{_uid()}", str(PLIST_PATH)],
            check=False,
        )
        PLIST_PATH.unlink(missing_ok=True)
        print(f"🗑️  Autostart eliminado: {PLIST_PATH}")
