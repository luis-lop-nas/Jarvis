# JARVIS - Estado actual del proyecto

## Descripción

JARVIS es un asistente de IA para macOS con modo desktop (overlay nativo), web, CLI y voz. Integra tool use, memoria en SQLite, RAG opcional con Chroma y automatizaciones locales.

## Estructura actual

```text
Jarvis/
├── CLAUDE.MD
├── Jarvis.app/
├── jarvis-agent/
│   ├── README.md
│   ├── pyproject.toml
│   ├── .env.example
│   ├── data/
│   ├── tests/
│   └── src/jarvis/
│       ├── main.py
│       ├── config.py
│       ├── agent/
│       ├── overlay/
│       ├── tools/
│       ├── vision/
│       ├── voice/
│       ├── web/
│       ├── memory/
│       └── intents/
├── jarvis-overlay-swift/
└── sandbox/
```

## Modos de ejecución

Desde `jarvis-agent/` con entorno activo:

```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
source .venv/bin/activate
```

### Desktop (principal)

```bash
PYTHONPATH=src python -m jarvis --desktop
```

### Web

```bash
PYTHONPATH=src python -m jarvis --web --port 8000
# o equivalente:
PYTHONPATH=src uvicorn jarvis.web.server:app --host 0.0.0.0 --port 8000
```

### Voz (sin overlay)

```bash
PYTHONPATH=src python -m jarvis --voice
```

### CLI

```bash
PYTHONPATH=src python -m jarvis
```

## Flags CLI vigentes (`main.py`)

- `--desktop`
- `--web`
- `--voice`
- `--no-voice`
- `--port`
- `--debug`
- `--install-autostart`
- `--uninstall-autostart`
- `--autostart-status`
- `--restart-autostart`
- `--doctor-desktop`
- `--class-session`
- `--class-seconds`
- `--class-title`
- `--class-audio`
- `--no-class-calendar-sync`

## Arquitectura técnica (actual)

### Desktop overlay (PyObjC)

- `overlay/window.py`: ventana transparente tipo accessory app (sin Dock).
- `overlay/view.py`: orb y estados visuales (`idle`, `listening`, `thinking`, `acting`).
- `overlay/particles.py`: animaciones de partículas (`fly_to`).
- `overlay/bridge.py`: cola thread-safe entre daemon y UI.
- `overlay/daemon.py`: pipeline principal de voz, contexto, agente y tools.
- `overlay/hud.py`: subtítulos flotantes.
- `overlay/chat_panel.py`: panel de chat.
- `overlay/main_panel.py`: panel de control (Quit/Voice/Type).
- `overlay/menubar.py`: menú en barra superior.
- `overlay/text_input.py`: entrada por teclado (hotkey `Ctrl+Space`).

### Hilos principales

- Hilo principal: `NSApplication` + render del overlay.
- Hilo daemon: wake word/hotkey, grabación, STT, LLM, tools, TTS.
- Hilos auxiliares opcionales: gestos (`vision/gesture_controller.py`) y contexto de cámara (`vision/camera_context.py`).

### Voz

- STT: Groq Whisper o Whisper local (`voice/stt.py`).
- Wake word: OpenWakeWord o Porcupine (`voice/wake_word.py`).
- VAD: Silero ONNX (fallback RMS) en `overlay/daemon.py`.
- TTS: ElevenLabs, Piper o `say` de macOS (`voice/tts.py`).

### Agente

- `agent/tool_agent.py` — motor reactivo (bucles LLM hasta 8 iteraciones).
- `agent/pev_agent.py` — pipeline **Planner → Executor → Verifier** (activado con `PEV_ENABLED=true`).
- Prioridad de backends: **Claude -> Gemini -> Groq -> Ollama**.
- Memoria persistente en SQLite (`memory/store.py`).
- Intent multi-step para completar parámetros faltantes (`agent/intent_tracker.py`).
- `tool_agent_from_settings()` devuelve `PEVAgent` si `PEV_ENABLED=true`, `ToolAgent` si no.

### PEV Pipeline (Planner → Executor → Verifier)

Archivos en `agent/`:
- `pev_models.py` — `PlanStep`, `Plan`, `StepResult`, `RunState` (Pydantic + dataclasses).
- `pev_state.py` — `RunStateStore` thread-safe con TTL (default 600 s).
- `pev_prompts.py` — `PLANNER_SYSTEM_PROMPT`, `PLANNER_USER_TEMPLATE`, `SYNTHESIS_SYSTEM_PROMPT`.
- `pev_agent.py` — clase principal; misma API pública que `ToolAgent`.

Flujo:
1. **Planner**: LLM genera JSON `Plan` sin ejecutar nada (sin tools en la llamada).
2. **Executor**: itera pasos; resuelve `{{sN.field}}` entre pasos, pide confirmación para sensitivos, pausa para input de usuario.
3. **Verifier**: valida output con `verifier.py` tras cada ejecución; reintenta si `retryable=True`.
4. **Synthesizer**: resume resultados en lenguaje natural con el LLM.

Manejo de estado entre turnos (`RunStateStore`):
- `pending_confirmation_step` — esperando sí/no del usuario.
- `pending_user_input_step` — esperando dato del usuario (step `requires_user_input=True`).

Fallback: plan inválido (JSON malformado o sin `steps`) → `ToolAgent.run()` silencioso.

### Web

- FastAPI con lifespan (`web/server.py`).
- WebSocket `/ws` con streaming de tokens (`token` + `done`).
- Endpoints: `/`, `/transcribe`, `/speak`.

## Variables de entorno relevantes

Definidas en `config.py` y `.env.example`:

```env
# LLM
USE_CLAUDE=false
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6

USE_GEMINI=false
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash

USE_GROQ=true
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

OLLAMA_MODEL=llama3.2:3b

# Voz
STT_ENGINE=groq
STT_GROQ_MODEL=whisper-large-v3-turbo
STT_WHISPER_MODEL=small

TTS_ENGINE=elevenlabs
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
ELEVENLABS_MODEL=eleven_multilingual_v2

# Wake word
WAKE_WORD_ENGINE=openwakeword
WAKE_WORD_MODEL=hey_jarvis
WAKE_WORD=jarvis
WAKE_WORD_SENSITIVITY=0.5
WAKE_WORD_MIN_RMS=120
WAKE_WORD_MIN_HITS=2
WAKE_WORD_COOLDOWN=1.5
WAKE_WORD_SCORE_EMA_ALPHA=0.6
WAKE_BEEP=true
PORCUPINE_ACCESS_KEY=

# Gestos
USE_GESTURES=false
GESTURE_COOLDOWN=1.5
GESTURE_DEBUG=false
GESTURE_CAMERA_INDEX=0

# VAD + contexto cámara
VAD_ENGINE=silero
VAD_SILENCE_MS=480
VAD_PRE_BUFFER_MS=1500
CAMERA_CONTEXT=false
CAMERA_CONTEXT_INDEX=0
CAMERA_CONTEXT_INTERVAL=5.0
CAMERA_CONTEXT_FACE_ONLY=false

# General
DEBUG=false
DATA_DIR=data

# PEV Pipeline
PEV_ENABLED=false
PEV_MAX_STEPS=6
PEV_RETRY_MAX=1
PEV_STATE_TTL_SECONDS=600
PEV_VERBOSE_TRACE=false
```

## Herramientas disponibles (21)

Registro real en `src/jarvis/tools/registry.py`:

1. `shell`
2. `filesystem`
3. `open_app`
4. `run_code`
5. `web_search`
6. `spotify`
7. `calendar`
8. `send_email`
9. `send_message`
10. `vision`
11. `code_assistant`
12. `knowledge`
13. `organize_files`
14. `download_file`
15. `search_and_download`
16. `system_info`
17. `datetime`
18. `weather`
19. `web_agent`
20. `cad_generator`
21. `routines`

## Features recientes que ya están en código

- `--class-session`: graba/procesa clase, genera resumen, extrae tareas y puede crear recordatorios/eventos.
- `desktop doctor`: chequeo de autostart y permisos (`--doctor-desktop`).
- `routines` tool: lectura/edición de rutinas en `data/routines.json`.
- `camera_context`: inyección opcional de presencia/objetos captados por cámara.
- `web_agent`: navegación autónoma con Playwright y confirmación para acciones sensibles.
- **PEV Pipeline**: agente estructurado Planner → Executor → Verifier, activado con `PEV_ENABLED=true`.

## Debug y validación

```bash
# Desktop
PYTHONPATH=src python -m jarvis --desktop

# Doctor desktop
PYTHONPATH=src python -m jarvis --doctor-desktop

# Autostart
PYTHONPATH=src python -m jarvis --install-autostart
PYTHONPATH=src python -m jarvis --autostart-status
PYTHONPATH=src python -m jarvis --uninstall-autostart
PYTHONPATH=src python -m jarvis --restart-autostart

# Class session
PYTHONPATH=src python -m jarvis --class-session --class-seconds 180

# Tests
PYTHONPATH=src pytest tests/ -v
```

## Dependencias opcionales

```bash
# Browser automation (web_agent)
pip install -e ".[browser]"
playwright install chromium

# Gestos por cámara
pip install -e ".[gestures]"

# CAD
pip install -e ".[cad]"

# RAG local
pip install -e ".[rag]"
```

## Nota

- El archivo canónico en este repo es `CLAUDE.MD` (mayúsculas).
- Actualizado según estructura y código actual del proyecto.

---

Última actualización: 27 de febrero de 2026
