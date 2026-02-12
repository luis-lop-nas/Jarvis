"""
config.py

Este módulo centraliza TODA la configuración del proyecto.

- Carga variables desde .env (si existe)
- Define rutas de trabajo (data/, logs/, workspace/, sqlite)
- Crea directorios necesarios si no existen
- Expone un objeto Settings tipado para que el resto del proyecto no
  tenga que andar leyendo variables sueltas.

Idea: todo el proyecto usa Settings y Paths; así evitamos "magia" y
reprogramar cosas cuando cambies rutas o keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------
# Rutas (Paths) del proyecto
# ---------------------------

@dataclass(frozen=True)
class Paths:
    """
    Contenedor de rutas. Lo separamos de Settings para:
    - Tener paths normalizados
    - Poder crear carpetas con un solo método
    """
    project_root: Path
    data_dir: Path
    logs_dir: Path
    workspace_dir: Path
    db_path: Path

    def ensure_dirs(self) -> None:
        """
        Crea carpetas que deben existir para ejecutar Jarvis.
        No crea la DB todavía: eso lo hará memory/store.py cuando toque.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)


# ---------------------------
# Settings (desde .env + env)
# ---------------------------

class Settings(BaseSettings):
    """
    Settings tipado. Se rellena desde:
      1) Variables de entorno del sistema
      2) Archivo .env en project_root (si existe)

    NOTA: .env NO se sube al repo por .gitignore.
    """

    # --- Debug / logs ---
    debug: bool = Field(default=False, alias="DEBUG")

    # --- OpenAI ---
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.2-codex", alias="OPENAI_MODEL")
    openai_org: str = Field(default="", alias="OPENAI_ORG")
    openai_project: str = Field(default="", alias="OPENAI_PROJECT")

    # --- Wake word (Porcupine) ---
    porcupine_access_key: str = Field(default="", alias="PORCUPINE_ACCESS_KEY")
    wake_word: str = Field(default="hey jarvis", alias="WAKE_WORD")

    # --- Paths ---
    data_dir: str = Field(default="data", alias="DATA_DIR")

    # Config de Pydantic Settings:
    # - extra="ignore": si metes variables extra en .env no peta
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)


# ---------------------------
# Funciones públicas
# ---------------------------

def get_project_root() -> Path:
    """
    Devuelve el root del proyecto de forma robusta.

    Como este archivo está en: src/jarvis/config.py
    project_root debería ser 3 niveles arriba:
      config.py -> jarvis/ -> src/ -> project_root
    """
    return Path(__file__).resolve().parents[2]


def build_paths(project_root: Path, data_dir_name: str) -> Paths:
    """
    Construye todas las rutas internas a partir de:
    - project_root (raíz del repo)
    - data_dir_name (por defecto "data", configurable en .env)

    Mantener esto aquí evita hardcodear rutas por todo el proyecto.
    """
    data_dir = (project_root / data_dir_name).resolve()
    logs_dir = data_dir / "logs"
    workspace_dir = data_dir / "workspace"
    db_path = data_dir / "jarvis.db"

    return Paths(
        project_root=project_root,
        data_dir=data_dir,
        logs_dir=logs_dir,
        workspace_dir=workspace_dir,
        db_path=db_path,
    )


def load_settings(project_root: Optional[Path] = None) -> tuple[Settings, Paths]:
    """
    Carga .env + settings y devuelve:
      (settings, paths)

    - Busca .env en la raíz del proyecto
    - Crea carpetas data/logs/workspace
    - Deja todo listo para que el resto arranque

    Se recomienda llamar esto UNA vez al inicio (main.py).
    """
    root = project_root or get_project_root()

    # Carga el .env si existe (no falla si no existe)
    env_path = root / ".env"
    load_dotenv(dotenv_path=env_path, override=False)

    settings = Settings()

    # Construimos rutas y aseguramos directorios
    paths = build_paths(root, settings.data_dir)
    paths.ensure_dirs()

    return settings, paths