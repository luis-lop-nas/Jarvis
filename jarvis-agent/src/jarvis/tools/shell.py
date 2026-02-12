"""
shell.py

Tool: shell
Ejecuta comandos del sistema en macOS.

Objetivo:
- Permitir a Jarvis ejecutar tareas reales usando la terminal:
  - navegar carpetas
  - git
  - instalar deps
  - lanzar scripts
  - etc.

Seguridad (tu “cortafuegos”):
- Por defecto permite casi todo, PERO bloquea patrones muy destructivos por error.
- Puedes desactivar el firewall desde args: {"allow_dangerous": True}
  (más adelante lo controlaremos desde settings/política).

IMPORTANTE:
- Esta tool ejecuta comandos en tu máquina. Úsala con cabeza.
- Aun con “permiso total”, un mínimo de protección evita borrados accidentales.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# Lista corta de patrones extremadamente peligrosos (cortafuegos básico)
# Nota: esto es intencionalmente simple. Luego lo haremos más robusto.
DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=",
    ":(){ :|:& };:",  # fork bomb clásica
    "shutdown",
    "reboot",
    "halt",
    "nvram",
]


def _is_dangerous(command: str) -> bool:
    """Detecta si un comando contiene un patrón peligroso básico."""
    cmd = command.lower().strip()
    return any(pat in cmd for pat in DANGEROUS_PATTERNS)


def run_shell(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ejecuta un comando en la shell.

    Args esperados (en el dict):
      - command: str (obligatorio)
      - cwd: str (opcional) directorio de trabajo
      - timeout_sec: int (opcional, default 30)
      - env: dict (opcional) variables de entorno extra
      - allow_dangerous: bool (opcional, default False) desactiva firewall básico
      - shell: bool (opcional, default True) ejecuta como shell string (zsh)
        * Nota: usar shell=True permite pipes/redirecciones, etc.

    Returns:
      {
        "command": "...",
        "cwd": "...",
        "returncode": 0,
        "stdout": "...",
        "stderr": "...",
        "duration_ms": 123
      }
    """
    command = str(args.get("command", "")).strip()
    if not command:
        raise ValueError("Falta args['command'].")

    cwd = args.get("cwd")
    timeout_sec = int(args.get("timeout_sec", 30))
    env_extra = args.get("env") or {}
    allow_dangerous = bool(args.get("allow_dangerous", False))
    use_shell = bool(args.get("shell", True))

    # Cortafuegos básico
    if (not allow_dangerous) and _is_dangerous(command):
        raise RuntimeError(
            "Comando bloqueado por cortafuegos básico (muy destructivo). "
            "Si de verdad quieres ejecutarlo, pasa allow_dangerous=True."
        )

    # Directorio de trabajo (si lo pasan)
    cwd_path: Optional[Path] = None
    if cwd:
        cwd_path = Path(str(cwd)).expanduser().resolve()
        if not cwd_path.exists():
            raise FileNotFoundError(f"cwd no existe: {cwd_path}")
        if not cwd_path.is_dir():
            raise NotADirectoryError(f"cwd no es un directorio: {cwd_path}")

    # Entorno: heredamos y añadimos extras
    env = os.environ.copy()
    for k, v in env_extra.items():
        env[str(k)] = str(v)

    # Medir tiempo
    t0 = time.time()

    # Ejecutar
    # use_shell=True: permite pipes, &&, redirecciones...
    # En macOS normalmente la shell es zsh.
    if use_shell:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd_path) if cwd_path else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            executable="/bin/zsh",
        )
    else:
        # Ejecuta sin shell: más seguro (sin interpretación).
        # Requiere que command esté “tokenizado”.
        parts: List[str] = shlex.split(command)
        completed = subprocess.run(
            parts,
            shell=False,
            cwd=str(cwd_path) if cwd_path else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )

    duration_ms = int((time.time() - t0) * 1000)

    return {
        "command": command,
        "cwd": str(cwd_path) if cwd_path else None,
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "duration_ms": duration_ms,
    }