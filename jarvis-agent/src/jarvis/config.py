"""
config.py

Configuración centralizada del proyecto.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

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
    wake_word_device: Optional[int] = Field(default=None, alias="WAKE_WORD_DEVICE")
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

    # --- TTS (engine principal + ElevenLabs) ---
    tts_engine: str = Field(default="kokoro", alias="TTS_ENGINE")  # kokoro, elevenlabs, piper, macos
    elevenlabs_api_key: str = Field(default="", alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = Field(default="", alias="ELEVENLABS_VOICE_ID")
    elevenlabs_model: str = Field(default="eleven_multilingual_v2", alias="ELEVENLABS_MODEL")

    # --- Kokoro TTS (local, Apple Silicon) ---
    kokoro_voice: str = Field(default="ef_dora", alias="KOKORO_VOICE")
    kokoro_speed: float = Field(default=1.0, alias="KOKORO_SPEED")
    kokoro_language: str = Field(default="es", alias="KOKORO_LANGUAGE")

    # --- Gesture control ---
    use_gestures: bool = Field(default=False, alias="USE_GESTURES")
    gesture_cooldown: float = Field(default=1.5, alias="GESTURE_COOLDOWN")
    gesture_debug: bool = Field(default=False, alias="GESTURE_DEBUG")
    gesture_camera_index: int = Field(default=0, alias="GESTURE_CAMERA_INDEX")

    # --- VAD avanzado (Silero + pre-buffer + adaptive noise) ---
    vad_engine: str        = Field(default="silero", alias="VAD_ENGINE")           # "silero" | "rms"
    vad_silence_ms: int    = Field(default=480,       alias="VAD_SILENCE_MS")      # ms de silencio para cortar
    vad_pre_buffer_ms: int = Field(default=1500,      alias="VAD_PRE_BUFFER_MS")   # ms de ring buffer pre-wake
    wake_beep: bool        = Field(default=True,      alias="WAKE_BEEP")           # beep al detectar wake word

    # --- Camera context (face detection + object analysis) ---
    camera_context_enabled: bool  = Field(default=False, alias="CAMERA_CONTEXT")
    camera_context_index: int     = Field(default=0,     alias="CAMERA_CONTEXT_INDEX")
    camera_context_interval_s: float = Field(default=5.0, alias="CAMERA_CONTEXT_INTERVAL")
    camera_context_face_only: bool   = Field(default=False, alias="CAMERA_CONTEXT_FACE_ONLY")

    # --- Paths ---
    data_dir: str = Field(default="data", alias="DATA_DIR")

    # --- Confirm policy ---
    confirm_policy_enabled: bool = Field(default=True, alias="CONFIRM_POLICY_ENABLED")
    confirm_ttl_seconds: int = Field(default=120, alias="CONFIRM_TTL_SECONDS")
    confirm_always_for: List[str] = Field(default_factory=list, alias="CONFIRM_ALWAYS_FOR")

    # --- Dry run (acciones sensibles) ---
    dry_run_enabled: bool = Field(default=True, alias="DRY_RUN_ENABLED")
    dry_run_ttl_seconds: int = Field(default=120, alias="DRY_RUN_TTL_SECONDS")
    dry_run_always_for: List[str] = Field(default_factory=list, alias="DRY_RUN_ALWAYS_FOR")
    dry_run_max_items_list: int = Field(default=20, alias="DRY_RUN_MAX_ITEMS_LIST")
    dry_run_snippet_chars: int = Field(default=300, alias="DRY_RUN_SNIPPET_CHARS")

    # --- Shell guard ---
    shell_guard_enabled: bool = Field(default=True, alias="SHELL_GUARD_ENABLED")
    shell_guard_mode: str = Field(default="strict", alias="SHELL_GUARD_MODE")
    shell_deny_patterns: List[str] = Field(default_factory=list, alias="SHELL_DENY_PATTERNS")
    shell_confirm_patterns: List[str] = Field(default_factory=list, alias="SHELL_CONFIRM_PATTERNS")

    # --- Verifier ---
    verifier_enabled: bool = Field(default=True, alias="VERIFIER_ENABLED")
    verifier_timeout_ms: int = Field(default=1500, alias="VERIFIER_TIMEOUT_MS")
    verifier_max_items: int = Field(default=50, alias="VERIFIER_MAX_ITEMS")
    verifier_sample_if_over: int = Field(default=200, alias="VERIFIER_SAMPLE_IF_OVER")
    verifier_strict: bool = Field(default=False, alias="VERIFIER_STRICT")

    # --- Tool schema validation ---
    tool_schema_validation_enabled: bool = Field(default=True, alias="TOOL_SCHEMA_VALIDATION_ENABLED")
    tool_schema_strict: bool = Field(default=True, alias="TOOL_SCHEMA_STRICT")
    tool_schema_log_invalid: bool = Field(default=False, alias="TOOL_SCHEMA_LOG_INVALID")

    # --- PEV Pipeline (Planner → Executor → Verifier) ---
    pev_enabled: bool = Field(default=False, alias="PEV_ENABLED")
    pev_max_steps: int = Field(default=6, alias="PEV_MAX_STEPS")
    pev_retry_max: int = Field(default=1, alias="PEV_RETRY_MAX")
    pev_state_ttl_seconds: int = Field(default=600, alias="PEV_STATE_TTL_SECONDS")
    pev_verbose_trace: bool = Field(default=False, alias="PEV_VERBOSE_TRACE")

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
