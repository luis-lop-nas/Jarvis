"""
run_code.py

Tool: run_code
Ejecuta código en un sandbox usando Docker (recomendado).

- Monta data/workspace dentro del contenedor
- Ejecuta un snippet o un archivo dentro del workspace
- Devuelve stdout/stderr/returncode

Requisitos:
- Docker instalado y corriendo
- Imágenes: jarvis-python:latest y jarvis-node:latest
  (las construiremos al final con sandbox/docker/*)
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _docker_available() -> bool:
    """Comprueba si Docker está disponible."""
    try:
        subprocess.run(["docker", "version"], capture_output=True, text=True, timeout=5)
        return True
    except Exception:
        return False


def _ensure_inside_workspace(workspace: Path, p: Path) -> Path:
    """Cortafuegos: asegura que p está dentro de workspace."""
    workspace = workspace.resolve()
    p = p.resolve()
    if p != workspace and workspace not in p.parents:
        raise PermissionError(f"Ruta fuera del workspace: {p}")
    return p


def _write_snippet(workspace: Path, language: str, code: str) -> Path:
    """
    Escribe el snippet como archivo dentro del workspace para ejecutarlo.
    Usamos un nombre fijo para que el agente pueda reintentar/iterar.
    """
    ext = "py" if language == "python" else "js"
    path = workspace / f"_jarvis_snippet.{ext}"
    path.write_text(code, encoding="utf-8")
    return path


def run_code(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Args:
      - language: "python" | "node" (obligatorio)
      - code: str (opcional) snippet a ejecutar
      - file: str (opcional) ruta relativa dentro del workspace a ejecutar
      - workspace_dir: str (opcional) default "data/workspace"
      - timeout_sec: int (opcional) default 30
      - image: str (opcional) override imagen docker
      - extra_args: list[str] (opcional) argumentos extra para el script

    Returns:
      {
        "language": "...",
        "image": "...",
        "executed": "...",
        "returncode": 0,
        "stdout": "...",
        "stderr": "...",
        "duration_ms": 123
      }
    """
    if not _docker_available():
        raise RuntimeError("Docker no disponible. Instala/abre Docker Desktop y reintenta.")

    language = str(args.get("language", "")).strip().lower()
    if language not in ("python", "node"):
        raise ValueError("language debe ser 'python' o 'node'.")

    workspace = Path(str(args.get("workspace_dir", "data/workspace"))).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    timeout_sec = int(args.get("timeout_sec", 30))
    code = args.get("code")
    file_in = args.get("file")
    extra_args = args.get("extra_args") or []
    if not isinstance(extra_args, list):
        extra_args = [str(extra_args)]

    if not code and not file_in:
        raise ValueError("Debes pasar 'code' o 'file'.")

    # Determinar archivo a ejecutar
    if code:
        exec_path = _write_snippet(workspace, language, str(code))
    else:
        exec_path = _ensure_inside_workspace(workspace, (workspace / str(file_in)))
        if not exec_path.exists():
            raise FileNotFoundError(f"No existe: {exec_path}")
        if exec_path.is_dir():
            raise IsADirectoryError(f"Es un directorio: {exec_path}")

    # Imagen docker por defecto
    default_image = "jarvis-python:latest" if language == "python" else "jarvis-node:latest"
    image = str(args.get("image", default_image))

    # Ruta dentro del contenedor
    container_file = str(Path("/workspace") / exec_path.name)

    # Comando dentro del contenedor
    if language == "python":
        inner_cmd: List[str] = ["python", container_file]
    else:
        inner_cmd = ["node", container_file]

    # Argumentos extra para el script
    inner_cmd.extend([str(x) for x in extra_args])

    # docker run
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{workspace}:/workspace",
        image,
        *inner_cmd,
    ]

    t0 = time.time()
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
    duration_ms = int((time.time() - t0) * 1000)

    return {
        "language": language,
        "image": image,
        "executed": exec_path.name,
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "duration_ms": duration_ms,
    }