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

    # --- Anthropic Claude (cerebro principal) ---
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")
    use_claude: bool = Field(default=False, alias="USE_CLAUDE")

    # --- Google Gemini ---
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")
    use_gemini: bool = Field(default=False, alias="USE_GEMINI")

    # --- Groq API (STT + fallback LLM) ---
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    use_groq: bool = Field(default=False, alias="USE_GROQ")

    # --- Ollama (local) ---
    ollama_model: str = Field(default="llama3.2:3b", alias="OLLAMA_MODEL")

    # --- Wake word ---
    wake_word_engine: str = Field(default="openwakeword", alias="WAKE_WORD_ENGINE")  # openwakeword | porcupine
    wake_word_model: str = Field(default="hey_jarvis", alias="WAKE_WORD_MODEL")      # modelo oww
    wake_word_sensitivity: float = Field(default=0.5, alias="WAKE_WORD_SENSITIVITY")
    wake_word_debug: bool = Field(default=False, alias="WAKE_WORD_DEBUG")
    wake_word_min_rms: float = Field(default=120.0, alias="WAKE_WORD_MIN_RMS")
    wake_word_min_hits: int = Field(default=2, alias="WAKE_WORD_MIN_HITS")
    wake_word_cooldown: float = Field(default=1.5, alias="WAKE_WORD_COOLDOWN")
    wake_word_score_ema_alpha: float = Field(default=0.6, alias="WAKE_WORD_SCORE_EMA_ALPHA")
    porcupine_access_key: str = Field(default="", alias="PORCUPINE_ACCESS_KEY")      # solo si engine=porcupine
    wake_word: str = Field(default="jarvis", alias="WAKE_WORD")

    # --- STT ---
    stt_engine: str = Field(default="groq", alias="STT_ENGINE")  # groq | local
    stt_groq_model: str = Field(default="whisper-large-v3-turbo", alias="STT_GROQ_MODEL")
    stt_whisper_model: str = Field(default="small", alias="STT_WHISPER_MODEL")

    # --- ElevenLabs TTS ---
    elevenlabs_api_key: str = Field(default="", alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = Field(default="", alias="ELEVENLABS_VOICE_ID")
    elevenlabs_model: str = Field(default="eleven_multilingual_v2", alias="ELEVENLABS_MODEL")
    tts_engine: str = Field(default="elevenlabs", alias="TTS_ENGINE")  # elevenlabs, piper, macos

    # --- Gesture control ---
    use_gestures: bool = Field(default=False, alias="USE_GESTURES")
    gesture_cooldown: float = Field(default=1.5, alias="GESTURE_COOLDOWN")
    gesture_debug: bool = Field(default=False, alias="GESTURE_DEBUG")
    gesture_camera_index: int = Field(default=0, alias="GESTURE_CAMERA_INDEX")

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
