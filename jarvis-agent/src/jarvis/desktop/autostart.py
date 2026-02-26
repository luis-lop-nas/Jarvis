"""
autostart.py

Gestiona autoarranque de Jarvis Desktop en macOS usando LaunchAgent.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_LABEL = "com.jarvis.agent.desktop"


@dataclass(frozen=True)
class AutostartStatus:
    installed: bool
    loaded: bool
    plist_path: Path
    label: str
    error: str = ""


def default_plist_path(label: str = DEFAULT_LABEL) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def build_launch_agent_plist(
    *,
    label: str,
    project_root: Path,
    python_executable: str,
    logs_dir: Path,
) -> Dict[str, Any]:
    project_root = project_root.resolve()
    logs_dir = logs_dir.resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = logs_dir / "jarvis-launchagent.out.log"
    stderr_log = logs_dir / "jarvis-launchagent.err.log"

    return {
        "Label": label,
        "ProgramArguments": [python_executable, "-m", "jarvis", "--desktop"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "WorkingDirectory": str(project_root),
        "EnvironmentVariables": {
            "PYTHONPATH": str(project_root / "src"),
        },
        "StandardOutPath": str(stdout_log),
        "StandardErrorPath": str(stderr_log),
        "ProcessType": "Interactive",
    }


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def _launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def install_launch_agent(
    *,
    project_root: Path,
    logs_dir: Path,
    label: str = DEFAULT_LABEL,
    plist_path: Optional[Path] = None,
    python_executable: Optional[str] = None,
) -> tuple[bool, str, Path]:
    if sys.platform != "darwin":
        return False, "Autoarranque soportado solo en macOS.", default_plist_path(label)

    plist = plist_path or default_plist_path(label)
    plist.parent.mkdir(parents=True, exist_ok=True)

    payload = build_launch_agent_plist(
        label=label,
        project_root=project_root,
        python_executable=python_executable or sys.executable,
        logs_dir=logs_dir,
    )
    plist.write_bytes(plistlib.dumps(payload))

    domain = _launchctl_domain()
    _run(["launchctl", "bootout", domain, str(plist)])
    res = _run(["launchctl", "bootstrap", domain, str(plist)])
    if res.returncode != 0:
        fallback = _run(["launchctl", "load", str(plist)])
        if fallback.returncode != 0:
            err = (res.stderr or fallback.stderr or "launchctl error").strip()
            return False, f"No se pudo cargar LaunchAgent: {err}", plist

    return True, f"Autoarranque instalado ({label}).", plist


def uninstall_launch_agent(
    *,
    label: str = DEFAULT_LABEL,
    plist_path: Optional[Path] = None,
) -> tuple[bool, str, Path]:
    if sys.platform != "darwin":
        return False, "Autoarranque soportado solo en macOS.", default_plist_path(label)

    plist = plist_path or default_plist_path(label)
    domain = _launchctl_domain()

    _run(["launchctl", "bootout", domain, str(plist)])
    _run(["launchctl", "unload", str(plist)])

    if plist.exists():
        plist.unlink(missing_ok=True)

    return True, f"Autoarranque eliminado ({label}).", plist


def restart_launch_agent(
    *,
    project_root: Path,
    logs_dir: Path,
    label: str = DEFAULT_LABEL,
    plist_path: Optional[Path] = None,
    python_executable: Optional[str] = None,
) -> tuple[bool, str, Path]:
    ok_un, msg_un, plist = uninstall_launch_agent(label=label, plist_path=plist_path)
    if not ok_un:
        return False, msg_un, plist

    ok_in, msg_in, plist = install_launch_agent(
        project_root=project_root,
        logs_dir=logs_dir,
        label=label,
        plist_path=plist_path,
        python_executable=python_executable,
    )
    if not ok_in:
        return False, msg_in, plist

    return True, f"Autoarranque reiniciado ({label}).", plist


def get_autostart_status(
    *,
    label: str = DEFAULT_LABEL,
    plist_path: Optional[Path] = None,
) -> AutostartStatus:
    plist = plist_path or default_plist_path(label)
    installed = plist.exists()
    if sys.platform != "darwin":
        return AutostartStatus(
            installed=installed,
            loaded=False,
            plist_path=plist,
            label=label,
            error="No macOS",
        )

    domain = _launchctl_domain()
    probe = _run(["launchctl", "print", f"{domain}/{label}"])
    loaded = probe.returncode == 0
    err = ""
    if probe.returncode != 0 and probe.stderr:
        err = probe.stderr.strip()

    return AutostartStatus(
        installed=installed,
        loaded=loaded,
        plist_path=plist,
        label=label,
        error=err,
    )
