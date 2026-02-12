"""
filesystem.py

Tool: filesystem
Operaciones de archivos SOLO dentro de un workspace controlado.

Esto es tu “cortafuegos” práctico:
- El agente NO debería tocar tu sistema entero.
- Solo toca data/workspace/ (o el root_dir que le pases).

Acciones soportadas:
- write_text : escribe un archivo de texto
- read_text  : lee un archivo de texto
- list_dir   : lista contenido de un directorio
- mkdir      : crea un directorio
- exists     : comprueba si existe una ruta
- delete     : borra archivo o carpeta (opcional y peligroso)

Nota:
- La función valida que cualquier ruta resuelta esté dentro del root_dir.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional


def _resolve_in_root(root: Path, user_path: str) -> Path:
    """
    Resuelve user_path dentro de root y aplica cortafuegos:
    el path final debe estar dentro de root (evita ../ o rutas absolutas).
    """
    root = root.resolve()
    # Permitimos que el usuario pase rutas como "subdir/file.txt"
    p = (root / user_path).expanduser().resolve()

    # Cortafuegos: p debe estar dentro de root
    if p != root and root not in p.parents:
        raise PermissionError(f"Ruta fuera del workspace: {p}")
    return p


def run_filesystem(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Args esperados:
      - action: str (obligatorio) -> write_text/read_text/list_dir/mkdir/exists/delete
      - root_dir: str (opcional)  -> default "data/workspace"
      - path: str (según action)  -> ruta relativa dentro del workspace
      - content: str (solo write_text)
      - recursive: bool (solo delete) -> borrar carpetas recursivo

    Devuelve dict con detalles de la operación.
    """
    action = str(args.get("action", "")).strip().lower()
    if not action:
        raise ValueError("Falta args['action'].")

    root_dir = Path(str(args.get("root_dir", "data/workspace"))).expanduser().resolve()
    root_dir.mkdir(parents=True, exist_ok=True)

    # path es opcional para list_dir (si no viene lista root)
    user_path = args.get("path")
    target: Path = root_dir if not user_path else _resolve_in_root(root_dir, str(user_path))

    if action == "write_text":
        if not user_path:
            raise ValueError("write_text requiere args['path'].")
        content = str(args.get("content", ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "action": action,
            "path": str(target),
            "bytes": len(content.encode("utf-8")),
        }

    if action == "read_text":
        if not user_path:
            raise ValueError("read_text requiere args['path'].")
        if not target.exists():
            raise FileNotFoundError(f"No existe: {target}")
        if target.is_dir():
            raise IsADirectoryError(f"Es un directorio: {target}")
        return {
            "action": action,
            "path": str(target),
            "content": target.read_text(encoding="utf-8"),
        }

    if action == "list_dir":
        if not target.exists():
            raise FileNotFoundError(f"No existe: {target}")
        if not target.is_dir():
            raise NotADirectoryError(f"No es directorio: {target}")

        items: List[Dict[str, Any]] = []
        for child in sorted(target.iterdir()):
            items.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "is_dir": child.is_dir(),
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )

        return {
            "action": action,
            "path": str(target),
            "items": items,
        }

    if action == "mkdir":
        if not user_path:
            raise ValueError("mkdir requiere args['path'].")
        target.mkdir(parents=True, exist_ok=True)
        return {
            "action": action,
            "path": str(target),
        }

    if action == "exists":
        if not user_path:
            raise ValueError("exists requiere args['path'].")
        return {
            "action": action,
            "path": str(target),
            "exists": target.exists(),
            "is_dir": target.is_dir() if target.exists() else None,
        }

    if action == "delete":
        if not user_path:
            raise ValueError("delete requiere args['path'].")
        if not target.exists():
            return {"action": action, "path": str(target), "deleted": False, "reason": "not_found"}

        recursive = bool(args.get("recursive", False))
        if target.is_dir():
            if not recursive:
                # Evita borrar carpetas por error si no se indica recursive
                raise PermissionError("Para borrar directorios usa recursive=True.")
            shutil.rmtree(target)
        else:
            target.unlink()

        return {"action": action, "path": str(target), "deleted": True}

    raise ValueError(f"Acción no soportada: {action}")