"""
config.py

Configuración centralizada del proyecto.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class Paths:
    """Contenedor de rutas."""
    project_root: Path
    data_dir: Path
    logs_dir: Path
    workspace_dir: Path
    db_path: Path

    def ensure_dirs(self) -> None:
        """Crea carpetas necesarias."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """Settings tipado desde .env + variables de entorno."""

    # --- Debug / logs ---
    debug: bool = Field(default=False, alias="DEBUG")

    # --- OpenAI (legacy, por si quieres usarlo) ---
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4", alias="OPENAI_MODEL")
    openai_org: str = Field(default="", alias="OPENAI_ORG")
    openai_project: str = Field(default="", alias="OPENAI_PROJECT")

    # --- Groq API (NUEVO) ---
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    use_groq: bool = Field(default=False, alias="USE_GROQ")

    # --- Ollama (local) ---
    ollama_model: str = Field(default="llama3.2:3b", alias="OLLAMA_MODEL")

    # --- Wake word (Porcupine) ---
    porcupine_access_key: str = Field(default="", alias="PORCUPINE_ACCESS_KEY")
    wake_word: str = Field(default="jarvis", alias="WAKE_WORD")

    # --- Paths ---
    data_dir: str = Field(default="data", alias="DATA_DIR")

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)


def get_project_root() -> Path:
    """Devuelve la raíz del proyecto."""
    return Path(__file__).resolve().parents[2]


def build_paths(project_root: Path, data_dir_name: str) -> Paths:
    """Construye todas las rutas internas."""
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
    """Carga .env + settings y devuelve (settings, paths)."""
    root = project_root or get_project_root()

    env_path = root / ".env"
    load_dotenv(dotenv_path=env_path, override=False)

    settings = Settings()
    paths = build_paths(root, settings.data_dir)
    paths.ensure_dirs()

    return settings, paths
