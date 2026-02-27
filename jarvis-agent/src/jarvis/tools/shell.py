"""
shell.py

Tool: shell
Ejecuta comandos del sistema en macOS.

Objetivo:
- Permitir a Jarvis ejecutar tareas reales usando la terminal:
  - navegar carpetas, git, instalar deps, lanzar scripts, etc.

Seguridad:
- Todos los comandos pasan por analyze_shell_command() en shell_guard.py.
  - "deny"    → bloqueado inmediatamente (sin ejecución).
  - "confirm" → devuelve dry_run al agente; el usuario debe confirmar
                ANTES de que se ejecute (gestionado en tool_agent.py).
  - "allow"   → se ejecuta directamente.
- El parámetro allow_dangerous fue eliminado: la política de confirmación
  se gestiona exclusivamente por el agente (tool_agent._maybe_build_dry_run),
  nunca por los args generados por el LLM.
- stdout/stderr se truncan a MAX_OUTPUT_CHARS para evitar volcar datos enormes.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from jarvis.tools.shell_guard import analyze_shell_command

# Límite de salida: evita que stdout/stderr enormes saturen el contexto del LLM
MAX_OUTPUT_CHARS = 20_000


def run_shell(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ejecuta un comando en la shell.

    Args esperados (en el dict):
      - command: str (obligatorio)
      - cwd: str (opcional) directorio de trabajo
      - timeout_sec: int (opcional, default 30)
      - env: dict (opcional) variables de entorno extra
      - shell: bool (opcional, default True) ejecuta como shell string (zsh)

    Note: el parámetro `allow_dangerous` fue eliminado. La política de
    confirmación la gestiona el agente (tool_agent._maybe_build_dry_run).

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
    use_shell = bool(args.get("shell", True))

    # Guardia central: deny → bloqueado; confirm → el agente lo maneja antes de llegar aquí
    decision = analyze_shell_command(
        command,
        cwd=str(args.get("cwd", "") or ""),
        mode=str(args.get("shell_guard_mode", "strict")),
        deny_patterns=args.get("shell_deny_patterns") or [],
        confirm_patterns=args.get("shell_confirm_patterns") or [],
    )
    if decision.decision == "deny":
        return {
            "ok": False,
            "type": "deny",
            "error": (
                f"Bloqueado por seguridad: {decision.reason}. "
                "Indica una ruta/acción específica y segura para continuar."
            ),
            "risk_level": decision.risk_level,
            "matches": decision.matches,
            "command": decision.normalized_command,
        }
    # Para comandos "confirm": el agente debería haberlos interceptado antes con
    # _maybe_build_dry_run. Si llegan aquí, los bloqueamos igualmente como precaución.
    if decision.decision == "confirm":
        return {
            "ok": False,
            "type": "dry_run",
            "requires_confirmation": True,
            "error": "Comando sensible; requiere confirmación previa del usuario.",
            "risk_level": decision.risk_level,
            "reason": decision.reason,
            "matches": decision.matches,
            "command": decision.normalized_command,
            "cwd": str(args.get("cwd", "") or ""),
        }

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
        # Requiere que command esté "tokenizado".
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

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""

    # Truncar salidas muy largas para no saturar el contexto del LLM
    truncated = False
    if len(stdout) > MAX_OUTPUT_CHARS:
        stdout = stdout[:MAX_OUTPUT_CHARS] + f"\n[... salida truncada a {MAX_OUTPUT_CHARS} chars]"
        truncated = True
    if len(stderr) > MAX_OUTPUT_CHARS:
        stderr = stderr[:MAX_OUTPUT_CHARS] + f"\n[... stderr truncado a {MAX_OUTPUT_CHARS} chars]"
        truncated = True

    result: Dict[str, Any] = {
        "command": command,
        "cwd": str(cwd_path) if cwd_path else None,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms,
    }
    if truncated:
        result["truncated"] = True
    return result
