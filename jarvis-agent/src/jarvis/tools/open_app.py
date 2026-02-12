"""
open_app.py

Tool: open_app
Abre aplicaciones (y opcionalmente URLs/archivos) en macOS.

Uso típico:
- "Abre Spotify"
- "Abre Visual Studio Code"
- "Abre esta URL"

Implementación:
- macOS tiene el comando `open`:
  - open -a "App Name"           (abre una app por nombre)
  - open "https://..."           (abre URL con el navegador)
  - open "/ruta/al/archivo"      (abre archivo con app por defecto)

Esta tool devuelve un dict con:
- ok: bool (a nivel tool-runner lo envolvemos en registry, pero aquí devolvemos info útil)
- stdout/stderr/returncode y detalles del objetivo abierto.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, Optional


def run_open_app(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Abre una app o un target (url/archivo) usando `open` de macOS.

    Args esperados:
      - app: str (opcional) nombre de la app (ej: "Spotify", "Visual Studio Code")
      - target: str (opcional) url o ruta (ej: "https://google.com", "/Users/.../file.txt")
      - wait: bool (opcional, default False) si True, espera a que termine el proceso open
      - new_instance: bool (opcional, default False) intenta abrir una nueva instancia (no siempre aplica)
      - args: list[str] (opcional) argumentos extra para la aplicación (open -a App --args ...)

    Reglas:
      - Debes pasar al menos `app` o `target`.
      - Si pasas ambos, se abre `target` con esa app (si procede).
    """
    app = args.get("app")
    target = args.get("target")
    wait = bool(args.get("wait", False))
    new_instance = bool(args.get("new_instance", False))
    extra_app_args = args.get("args") or []

    if not app and not target:
        raise ValueError("Debes pasar 'app' o 'target'.")

    cmd = ["open"]

    # -n: abrir nueva instancia (cuando aplica)
    if new_instance:
        cmd.append("-n")

    # Si se especifica app, usamos -a
    if app:
        cmd.extend(["-a", str(app)])

    # Si hay target, puede ser URL o ruta
    if target:
        t = str(target).strip()

        # Expandimos ruta si parece path local
        # (si empieza por / o ~, lo tratamos como archivo)
        if t.startswith(("~", "/")):
            p = Path(t).expanduser().resolve()
            cmd.append(str(p))
        else:
            # Si no parece path, lo tratamos como URL o “string” para open
            cmd.append(t)

    # Si hay args extra para la app, se pasan con --args
    if app and extra_app_args:
        cmd.append("--args")
        cmd.extend([str(x) for x in extra_app_args])

    # Ejecutamos `open`
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    return {
        "command": cmd,
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "opened_app": str(app) if app else None,
        "opened_target": str(target) if target else None,
        "wait": wait,
        "new_instance": new_instance,
    }