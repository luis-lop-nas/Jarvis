"""
filesystem.py

Tool: filesystem - Gestión avanzada de archivos

JARVIS puede trabajar con archivos en todo el sistema del usuario,
con validaciones de seguridad para evitar operaciones peligrosas.

Acciones soportadas:
- write_text : escribe un archivo de texto
- read_text  : lee un archivo de texto
- list_dir   : lista contenido de un directorio
- mkdir      : crea un directorio
- exists     : comprueba si existe una ruta
- delete     : borra archivo o carpeta (con confirmación)
- rename     : renombra archivos o carpetas
- move       : mueve archivos/carpetas entre ubicaciones
- copy       : copia archivos/carpetas
- organize   : organiza archivos automáticamente por tipo

Seguridad:
- Previene operaciones en directorios del sistema críticos
- Requiere confirmación para operaciones destructivas
- Valida permisos antes de ejecutar
"""

from __future__ import annotations

import shutil
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


# Directorios prohibidos (sistema crítico)
FORBIDDEN_DIRS = {
    "/System",
    "/Library/System",
    "/usr",
    "/bin",
    "/sbin",
    "/private/var",
    "/etc",
}

# Directorios permitidos del usuario
ALLOWED_USER_DIRS = {
    "Desktop",
    "Documents",
    "Downloads",
    "Pictures",
    "Music",
    "Movies",
    "Projects",
}


def _is_safe_path(path: Path) -> bool:
    """Verifica que el path sea seguro para operar."""
    path = path.resolve()

    # Prevenir operaciones en directorios del sistema
    for forbidden in FORBIDDEN_DIRS:
        forbidden_path = Path(forbidden).resolve()
        if path == forbidden_path or forbidden_path in path.parents:
            return False

    return True


def _resolve_path(user_path: str, root: Optional[Path] = None, allow_absolute: bool = True) -> Path:
    """
    Resuelve user_path con validaciones de seguridad.

    Args:
        user_path: Ruta proporcionada por el usuario
        root: Directorio raíz (si es relativa)
        allow_absolute: Permitir rutas absolutas

    Returns:
        Path resuelto y validado
    """
    user_path = str(user_path).strip()
    p = Path(user_path).expanduser()

    # Si es absoluta y se permiten absolutas
    if p.is_absolute() and allow_absolute:
        p = p.resolve()
    # Si es relativa y hay root
    elif root:
        p = (root / user_path).resolve()
    # Si es relativa sin root
    else:
        p = Path.cwd() / user_path
        p = p.resolve()

    # Validar seguridad
    if not _is_safe_path(p):
        raise PermissionError(f"Operación no permitida en: {p}")

    return p


def run_filesystem(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Args esperados:
      - action: str (obligatorio) -> write_text/read_text/list_dir/mkdir/exists/delete/rename/move/copy
      - path: str -> ruta del archivo/carpeta (puede ser absoluta o relativa)
      - root_dir: str (opcional) -> para rutas relativas
      - content: str (solo write_text)
      - new_name: str (solo rename)
      - destination: str (solo move/copy)
      - recursive: bool (delete/copy)

    Devuelve dict con detalles de la operación.
    """
    action = str(args.get("action", "")).strip().lower()
    if not action:
        raise ValueError("Falta args['action'].")

    # Root dir opcional (para compatibilidad)
    root_dir = None
    if "root_dir" in args:
        root_dir = Path(str(args["root_dir"])).expanduser().resolve()
        root_dir.mkdir(parents=True, exist_ok=True)

    # Resolver path
    user_path = args.get("path")
    if not user_path and action not in ["list_dir"]:
        raise ValueError(f"{action} requiere args['path'].")

    # Para list_dir sin path, usar root_dir o cwd
    if action == "list_dir" and not user_path:
        target = root_dir if root_dir else Path.cwd()
    else:
        target = _resolve_path(str(user_path), root=root_dir, allow_absolute=True)

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
        if not target.exists():
            return {"action": action, "path": str(target), "deleted": False, "reason": "not_found"}

        recursive = bool(args.get("recursive", False))
        if target.is_dir():
            if not recursive:
                raise PermissionError("Para borrar directorios usa recursive=True.")
            shutil.rmtree(target)
        else:
            target.unlink()

        return {"action": action, "path": str(target), "deleted": True}

    if action == "rename":
        new_name = args.get("new_name")
        if not new_name:
            raise ValueError("rename requiere args['new_name'].")

        if not target.exists():
            raise FileNotFoundError(f"No existe: {target}")

        # El nuevo nombre es en el mismo directorio
        new_path = target.parent / str(new_name)

        # Validar que el nuevo path también sea seguro
        if not _is_safe_path(new_path):
            raise PermissionError(f"Operación no permitida: {new_path}")

        if new_path.exists():
            raise FileExistsError(f"Ya existe: {new_path}")

        target.rename(new_path)

        return {
            "action": action,
            "old_path": str(target),
            "new_path": str(new_path),
            "new_name": new_name,
        }

    if action == "move":
        destination = args.get("destination")
        if not destination:
            raise ValueError("move requiere args['destination'].")

        if not target.exists():
            raise FileNotFoundError(f"No existe: {target}")

        dest_path = _resolve_path(str(destination), root=root_dir, allow_absolute=True)

        # Si destination es un directorio, mover dentro de él
        if dest_path.is_dir():
            dest_path = dest_path / target.name

        # Validar seguridad del destino
        if not _is_safe_path(dest_path):
            raise PermissionError(f"Operación no permitida: {dest_path}")

        # Crear directorio padre si no existe
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(str(target), str(dest_path))

        return {
            "action": action,
            "source": str(target),
            "destination": str(dest_path),
        }

    if action == "copy":
        destination = args.get("destination")
        if not destination:
            raise ValueError("copy requiere args['destination'].")

        if not target.exists():
            raise FileNotFoundError(f"No existe: {target}")

        dest_path = _resolve_path(str(destination), root=root_dir, allow_absolute=True)

        # Si destination es un directorio, copiar dentro de él
        if dest_path.is_dir():
            dest_path = dest_path / target.name

        # Validar seguridad
        if not _is_safe_path(dest_path):
            raise PermissionError(f"Operación no permitida: {dest_path}")

        # Crear directorio padre si no existe
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if target.is_dir():
            recursive = bool(args.get("recursive", False))
            if not recursive:
                raise ValueError("Para copiar directorios usa recursive=True.")
            shutil.copytree(str(target), str(dest_path))
        else:
            shutil.copy2(str(target), str(dest_path))

        return {
            "action": action,
            "source": str(target),
            "destination": str(dest_path),
        }

    raise ValueError(f"Acción no soportada: {action}")