"""
logging_setup.py

Configuración centralizada de logging para JARVIS.

Características:
- Dos handlers: consola (INFO+) y fichero rotativo (DEBUG+).
- Rotación automática: máximo 10 MB por fichero, 5 ficheros de backup.
- Fichero: ~/Documents/Jarvis/logs/jarvis.log  (o paths.logs_dir si se pasa).
- Formato de fichero: JSON-like para facilitar parsing por herramientas externas.
- Formato de consola: legible por humanos.
- Silencia librerías ruidosas (httpx, httpcore, anthropic, groq, sounddevice).

Uso:
    from jarvis.logging_setup import setup_logging
    setup_logging(debug=False, logs_dir=paths.logs_dir)
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import time
from pathlib import Path
from typing import Optional

# Directorio de logs por defecto (si no se pasa logs_dir)
_DEFAULT_LOG_DIR = Path.home() / "Documents" / "Jarvis" / "logs"
_LOG_FILENAME = "jarvis.log"

# Rotación: 10 MB × 5 ficheros = máximo 50 MB en disco
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5

# Librerías que generan demasiado ruido en DEBUG
_NOISY_LOGGERS = [
    "httpx",
    "httpcore",
    "httpcore.connection",
    "httpcore.http11",
    "anthropic",
    "groq",
    "openai",
    "urllib3",
    "sounddevice",
    "matplotlib",
    "PIL",
]


class _JsonFormatter(logging.Formatter):
    """
    Formatter que emite cada línea de log como JSON.
    Facilita el parsing con herramientas como jq, Datadog, etc.
    """

    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False)


class _HumanFormatter(logging.Formatter):
    """Formatter legible para la consola."""
    _COLORS = {
        "DEBUG": "\033[37m",     # gris
        "INFO": "\033[0m",       # normal
        "WARNING": "\033[33m",   # amarillo
        "ERROR": "\033[31m",     # rojo
        "CRITICAL": "\033[1;31m",
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        base = super().format(record)
        return f"{color}{base}{self._RESET}"


def setup_logging(
    debug: bool = False,
    logs_dir: Optional[Path] = None,
) -> None:
    """
    Configura el sistema de logging global de JARVIS.

    Llamar una sola vez al inicio de main().

    Args:
        debug:    Si True, establece nivel DEBUG en consola y fichero.
        logs_dir: Directorio donde guardar jarvis.log. Si None, usa el default.
    """
    log_dir = Path(logs_dir) if logs_dir else _DEFAULT_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / _LOG_FILENAME

    root_level = logging.DEBUG if debug else logging.INFO

    # Limpiar handlers previos (p.ej. si se llama varias veces en tests)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(root_level)

    # ── Handler de consola ────────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(root_level)
    console.setFormatter(
        _HumanFormatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(console)

    # ── Handler de fichero rotativo ───────────────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(log_file),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # fichero siempre captura DEBUG
    file_handler.setFormatter(_JsonFormatter())
    root.addHandler(file_handler)

    # ── Silenciar librerías ruidosas ──────────────────────────────────────
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("jarvis").setLevel(root_level)
    logging.getLogger(__name__).info(
        "Logging inicializado — nivel=%s fichero=%s",
        logging.getLevelName(root_level),
        log_file,
    )
