"""
download_file.py

Herramienta para descargar archivos de internet de forma inteligente.
JARVIS puede buscar y descargar archivos automáticamente.
"""

from __future__ import annotations

import requests
import re
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse, unquote
import mimetypes


# Directorios de descarga según tipo de archivo
DOWNLOAD_LOCATIONS = {
    # Documentos
    "pdf": "~/Documents/Downloads",
    "doc": "~/Documents/Downloads",
    "docx": "~/Documents/Downloads",
    "txt": "~/Documents/Downloads",
    "rtf": "~/Documents/Downloads",

    # Imágenes
    "jpg": "~/Pictures/Downloads",
    "jpeg": "~/Pictures/Downloads",
    "png": "~/Pictures/Downloads",
    "gif": "~/Pictures/Downloads",
    "svg": "~/Pictures/Downloads",
    "webp": "~/Pictures/Downloads",

    # Videos
    "mp4": "~/Movies/Downloads",
    "mov": "~/Movies/Downloads",
    "avi": "~/Movies/Downloads",
    "mkv": "~/Movies/Downloads",

    # Audio
    "mp3": "~/Music/Downloads",
    "wav": "~/Music/Downloads",
    "flac": "~/Music/Downloads",
    "m4a": "~/Music/Downloads",

    # Código/Proyectos
    "zip": "~/Downloads/Archives",
    "tar": "~/Downloads/Archives",
    "gz": "~/Downloads/Archives",
    "rar": "~/Downloads/Archives",

    # Ejecutables/Instaladores
    "dmg": "~/Downloads/Installers",
    "pkg": "~/Downloads/Installers",
    "exe": "~/Downloads/Installers",
    "msi": "~/Downloads/Installers",

    # Default
    "default": "~/Downloads",
}


def _get_filename_from_url(url: str, content_disposition: Optional[str] = None) -> str:
    """Extrae el nombre del archivo de la URL o Content-Disposition header."""

    # Intentar obtener de Content-Disposition header
    if content_disposition:
        if "filename=" in content_disposition:
            filename = re.findall('filename="?([^"]+)"?', content_disposition)
            if filename:
                return unquote(filename[0])

    # Intentar obtener de la URL
    parsed = urlparse(url)
    path = unquote(parsed.path)

    # Obtener el último segmento de la ruta
    filename = path.split('/')[-1]

    # Si no tiene extensión o parece inválido, generar nombre
    if not filename or '.' not in filename:
        filename = f"download_{hash(url) % 10000}"

    return filename


def _get_destination_dir(filename: str) -> Path:
    """Determina el directorio de destino según el tipo de archivo."""
    ext = Path(filename).suffix.lower().lstrip('.')

    dest_dir = DOWNLOAD_LOCATIONS.get(ext, DOWNLOAD_LOCATIONS["default"])
    return Path(dest_dir).expanduser().resolve()


def _sanitize_filename(filename: str) -> str:
    """Limpia el nombre del archivo de caracteres no permitidos."""
    # Remover caracteres no permitidos
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

    # Limitar longitud
    if len(filename) > 200:
        stem = filename[:180]
        suffix = Path(filename).suffix
        filename = stem + suffix

    return filename


def run_download_file(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Descarga un archivo de internet.

    Args:
        url: URL del archivo a descargar (obligatorio)
        filename: Nombre del archivo (opcional, se detecta automáticamente)
        destination: Directorio de destino (opcional, se organiza automáticamente)
        organize: Si debe organizar automáticamente por tipo (bool, default True)
        timeout: Timeout en segundos (default 60)

    Returns:
        Dict con información de la descarga
    """
    url = str(args.get("url", "")).strip()
    if not url:
        raise ValueError("Se requiere 'url' para descargar")

    # Validar que sea una URL
    if not url.startswith(('http://', 'https://')):
        raise ValueError(f"URL inválida: {url}")

    filename = args.get("filename")
    destination = args.get("destination")
    organize = bool(args.get("organize", True))
    timeout = int(args.get("timeout", 60))

    try:
        # Headers para simular navegador
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        # Hacer request con stream para archivos grandes
        response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()

        # Obtener nombre del archivo
        if not filename:
            content_disposition = response.headers.get('Content-Disposition')
            filename = _get_filename_from_url(url, content_disposition)

            # Si aún no tiene extensión, intentar detectar por Content-Type
            if '.' not in filename:
                content_type = response.headers.get('Content-Type', '')
                ext = mimetypes.guess_extension(content_type.split(';')[0])
                if ext:
                    filename += ext

        filename = _sanitize_filename(filename)

        # Determinar directorio de destino
        if destination:
            dest_dir = Path(destination).expanduser().resolve()
        elif organize:
            dest_dir = _get_destination_dir(filename)
        else:
            dest_dir = Path("~/Downloads").expanduser().resolve()

        # Crear directorio si no existe
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Ruta completa del archivo
        file_path = dest_dir / filename

        # Si ya existe, agregar sufijo numérico
        if file_path.exists():
            counter = 1
            stem = file_path.stem
            suffix = file_path.suffix
            while file_path.exists():
                file_path = dest_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        # Descargar archivo
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

        # Obtener tamaño final
        file_size = file_path.stat().st_size
        file_size_mb = file_size / (1024 * 1024)

        return {
            "success": True,
            "url": url,
            "filename": filename,
            "path": str(file_path),
            "destination": str(dest_dir),
            "size_bytes": file_size,
            "size_mb": round(file_size_mb, 2),
            "organized": organize,
        }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Timeout: La descarga tardó demasiado",
            "url": url,
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Error de red: {str(e)}",
            "url": url,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error: {str(e)}",
            "url": url,
        }


def search_and_download(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Busca un archivo en internet y lo descarga automáticamente.

    Args:
        query: Búsqueda (ej: "Python tutorial PDF", "react logo PNG")
        file_type: Tipo de archivo (ej: "pdf", "png", "mp3", etc.)
        organize: Organizar automáticamente (bool, default True)

    Returns:
        Dict con resultados de búsqueda y descarga
    """
    from jarvis.tools.web_search import run_web_search

    query = str(args.get("query", "")).strip()
    file_type = str(args.get("file_type", "")).strip().lower()
    organize = bool(args.get("organize", True))

    if not query:
        raise ValueError("Se requiere 'query' para buscar")

    # Construir query de búsqueda optimizada
    search_query = query
    if file_type:
        search_query += f" filetype:{file_type}"

    # Buscar en web
    search_results = run_web_search({"query": search_query, "limit": 5})

    if not search_results.get("ok") or not search_results.get("results"):
        return {
            "success": False,
            "error": "No se encontraron resultados",
            "query": query,
        }

    # Intentar encontrar URLs de descarga directa
    download_urls = []

    for result in search_results["results"]:
        url = result.get("url", "")

        # Verificar si es un archivo directo
        if file_type and url.lower().endswith(f".{file_type}"):
            download_urls.append({
                "url": url,
                "title": result.get("title", ""),
                "source": result.get("source", ""),
            })

    if not download_urls:
        # Si no hay URLs directas, retornar resultados de búsqueda
        return {
            "success": False,
            "error": "No se encontraron archivos directos para descargar",
            "query": query,
            "search_results": search_results["results"][:3],
            "suggestion": "Intenta con una búsqueda más específica o proporciona una URL directa",
        }

    # Descargar el primer resultado
    best_result = download_urls[0]
    download_result = run_download_file({
        "url": best_result["url"],
        "organize": organize,
    })

    return {
        "success": download_result.get("success", False),
        "query": query,
        "file_type": file_type,
        "search_results_count": len(download_urls),
        "downloaded_from": best_result["title"],
        "download": download_result,
    }
