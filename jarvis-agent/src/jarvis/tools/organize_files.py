"""
organize_files.py

Herramienta de organización inteligente de archivos.
JARVIS puede analizar y organizar automáticamente archivos según su tipo,
nombre, fecha y contexto.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime


# Mapeo de extensiones a categorías
FILE_CATEGORIES = {
    # Documentos
    "documentos": {
        "extensions": [".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".pages"],
        "folder": "Documents",
    },
    # Imágenes
    "imagenes": {
        "extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".heic", ".webp"],
        "folder": "Pictures",
    },
    # Videos
    "videos": {
        "extensions": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v"],
        "folder": "Movies",
    },
    # Audio
    "audio": {
        "extensions": [".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"],
        "folder": "Music",
    },
    # Código
    "codigo": {
        "extensions": [".py", ".js", ".ts", ".java", ".cpp", ".c", ".h", ".go", ".rs", ".rb", ".php", ".swift", ".kt"],
        "folder": "Projects/Code",
    },
    # Comprimidos
    "comprimidos": {
        "extensions": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".dmg"],
        "folder": "Downloads/Archives",
    },
    # Instaladores
    "instaladores": {
        "extensions": [".exe", ".msi", ".pkg", ".deb", ".rpm", ".apk"],
        "folder": "Downloads/Installers",
    },
    # Hojas de cálculo
    "hojas_calculo": {
        "extensions": [".xls", ".xlsx", ".csv", ".numbers"],
        "folder": "Documents/Spreadsheets",
    },
    # Presentaciones
    "presentaciones": {
        "extensions": [".ppt", ".pptx", ".key"],
        "folder": "Documents/Presentations",
    },
}


def _categorize_file(file_path: Path) -> Optional[str]:
    """Determina la categoría de un archivo según su extensión."""
    ext = file_path.suffix.lower()

    for category, info in FILE_CATEGORIES.items():
        if ext in info["extensions"]:
            return category

    return None


def _get_destination_folder(file_path: Path, base_dir: Path, category: Optional[str]) -> Path:
    """Determina la carpeta de destino para un archivo."""

    # Si tiene categoría conocida
    if category and category in FILE_CATEGORIES:
        folder_name = FILE_CATEGORIES[category]["folder"]
        return base_dir / folder_name

    # Si no tiene categoría, a "Otros"
    return base_dir / "Others"


def _extract_date_from_filename(filename: str) -> Optional[datetime]:
    """Intenta extraer fecha del nombre del archivo."""
    # Patrones comunes: 2024-01-15, 20240115, 2024_01_15, etc.
    patterns = [
        r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})",  # YYYY-MM-DD
        r"(\d{2})[-_]?(\d{2})[-_]?(\d{4})",  # DD-MM-YYYY
    ]

    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            try:
                groups = match.groups()
                if len(groups[0]) == 4:  # YYYY-MM-DD
                    year, month, day = map(int, groups)
                else:  # DD-MM-YYYY
                    day, month, year = map(int, groups)

                return datetime(year, month, day)
            except ValueError:
                continue

    return None


def run_organize_files(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Organiza archivos automáticamente.

    Args:
        source_dir: Directorio a organizar (ej: ~/Downloads)
        dest_dir: Directorio base de destino (ej: ~/, organiza en ~/Documents, ~/Pictures, etc.)
        mode: "by_type" (por extensión) | "by_date" (por fecha) | "smart" (inteligente)
        dry_run: Solo simular, no mover archivos (default: False)
        recursive: Buscar en subdirectorios (default: False)
        patterns: Lista de patrones glob (opcional, ej: ["*.pdf", "*.jpg"])

    Returns:
        Diccionario con resultados de la organización
    """
    source_dir = Path(args.get("source_dir", "~/Downloads")).expanduser().resolve()
    dest_dir = Path(args.get("dest_dir", "~")).expanduser().resolve()
    mode = str(args.get("mode", "smart")).lower()
    dry_run = bool(args.get("dry_run", False))
    recursive = bool(args.get("recursive", False))
    patterns = args.get("patterns", ["*"])

    if not source_dir.exists():
        raise FileNotFoundError(f"Directorio no existe: {source_dir}")

    if not source_dir.is_dir():
        raise NotADirectoryError(f"No es un directorio: {source_dir}")

    # Recopilar archivos
    files_to_process: List[Path] = []

    for pattern in patterns:
        if recursive:
            files_to_process.extend(source_dir.rglob(pattern))
        else:
            files_to_process.extend(source_dir.glob(pattern))

    # Filtrar solo archivos (no directorios)
    files_to_process = [f for f in files_to_process if f.is_file()]

    # Organizar
    results = {
        "mode": mode,
        "source_dir": str(source_dir),
        "dest_dir": str(dest_dir),
        "dry_run": dry_run,
        "files_processed": 0,
        "files_moved": 0,
        "files_skipped": 0,
        "actions": [],
    }

    for file_path in files_to_process:
        results["files_processed"] += 1

        try:
            # Determinar destino según modo
            if mode == "by_type" or mode == "smart":
                category = _categorize_file(file_path)
                destination_folder = _get_destination_folder(file_path, dest_dir, category)

            elif mode == "by_date":
                # Intentar obtener fecha del nombre o de modificación
                file_date = _extract_date_from_filename(file_path.name)
                if not file_date:
                    file_date = datetime.fromtimestamp(file_path.stat().st_mtime)

                # Organizar por año/mes
                year_month = file_date.strftime("%Y/%Y-%m")
                destination_folder = dest_dir / "Organized_by_Date" / year_month

            else:
                raise ValueError(f"Modo no soportado: {mode}")

            # Ruta de destino final
            dest_path = destination_folder / file_path.name

            # Si ya existe, agregar sufijo numérico
            if dest_path.exists():
                counter = 1
                stem = file_path.stem
                suffix = file_path.suffix
                while dest_path.exists():
                    dest_path = destination_folder / f"{stem}_{counter}{suffix}"
                    counter += 1

            action_info = {
                "file": file_path.name,
                "source": str(file_path),
                "destination": str(dest_path),
                "category": category if mode != "by_date" else "by_date",
            }

            # Mover archivo (si no es dry_run)
            if not dry_run:
                destination_folder.mkdir(parents=True, exist_ok=True)
                file_path.rename(dest_path)
                results["files_moved"] += 1
                action_info["moved"] = True
            else:
                action_info["moved"] = False

            results["actions"].append(action_info)

        except Exception as e:
            results["files_skipped"] += 1
            results["actions"].append({
                "file": file_path.name,
                "error": str(e),
            })

    return results
