# JARVIS — Guía para Claude Code

## Descripción

Asistente de IA personal para macOS con modos desktop (overlay nativo PyObjC), web (FastAPI), CLI y voz. Integra tool use con 22 herramientas, memoria en SQLite, pipeline estructurado PEV opcional y automatizaciones locales.

---

## Directorio de trabajo y entorno

```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
source .venv/bin/activate
```

---

## Modos de ejecución

```bash
PYTHONPATH=src python -m jarvis --desktop        # Overlay macOS (modo principal)
PYTHONPATH=src python -m jarvis --web --port 8000 # Servidor FastAPI
PYTHONPATH=src python -m jarvis --voice           # Voz con wake word, sin overlay
PYTHONPATH=src python -m jarvis --no-voice        # CLI solo texto
PYTHONPATH=src python -m jarvis                   # CLI interactivo (con voz si config)
```

---

## Estructura del código

```
src/jarvis/
├── main.py               — Entry point, parseo de flags CLI
├── config.py             — Settings Pydantic + Paths (dataclass frozen)
├── logging_setup.py      — RotatingFileHandler (10MB×5) + consola ANSI
├── autostart.py          — LaunchAgent plist macOS
│
├── agent/
│   ├── tool_agent.py     — Agente reactivo (bucles LLM hasta 8 iter., multi-backend)
│   ├── pev_agent.py      — Pipeline Planner → Executor → Verifier
│   ├── pev_models.py     — Pydantic v2: PlanStep, Plan, StepResult, RunState
│   ├── pev_state.py      — RunStateStore thread-safe con TTL (600s default)
│   ├── pev_prompts.py    — System prompts planificador y sintetizador
│   ├── circuit_breaker.py — LLMCircuitBreaker: 3 fallos → OPEN 30s → HALF_OPEN
│   ├── confirm_policy.py — Política de confirmación para tools sensibles
│   ├── dry_run.py        — Preview de acciones antes de ejecutar
│   ├── intent_tracker.py — Multi-step intent: recopila parámetros faltantes
│   ├── prompt_guard.py   — Detección de prompt injection + metacaracteres en args
│   ├── prompts.py        — System prompts del agente
│   ├── verifier.py       — Validación post-ejecución de cada tool
│   ├── pending_actions.py
│   ├── runner.py
│   └── state.py
│
├── overlay/
│   ├── daemon.py         — Bucle de voz + LLM + tools (hilo daemon principal)
│   ├── view.py           — JarvisView: nube de 80 partículas, spring physics
│   ├── window.py         — NSWindow fullscreen transparente, nivel 1000 ← NO TOCAR
│   ├── particles.py      — fly_to bezier, trails, colores por estado
│   ├── bridge.py         — Cola thread-safe daemon ↔ UI (pump 50ms) ← NO TOCAR
│   ├── hud.py            — Panel subtítulos, color de acento sincronizado con estado
│   ├── main_panel.py     — Panel control: QUIT / VOICE / TYPE (liquid glass)
│   ├── chat_panel.py     — Panel de chat
│   ├── text_input.py     — Entrada teclado (hotkey Ctrl+Space)
│   ├── menubar.py        — Menú en barra superior macOS
│   ├── dock.py           — Integración con Dock
│   └── swift_bridge.py   — Interop Swift: token auth, límite 64KB/mensaje
│
├── voice/
│   ├── wake_word.py      — OpenWakeWord o Porcupine
│   ├── stt.py            — Groq Whisper o Whisper local
│   ├── tts.py            — ElevenLabs, Piper o macOS say
│   ├── vad.py            — SileroVAD singleton (ONNX, sin torch)
│   ├── orchestrator.py   — VoiceOrchestrator: VAD + grabación + noise floor EMA
│   └── voice_loop.py     — Bucle de audio principal
│
├── vision/
│   ├── gesture_controller.py — MediaPipe Hands: 6 gestos, hilo daemon, cooldown 1.5s
│   ├── camera_context.py     — Detección de cara + análisis de objetos vía Groq Vision
│   ├── screenshot.py         — Captura de pantalla vía Quartz (macOS)
│   ├── vision_analyzer.py    — Análisis de imagen con Groq Vision
│   └── accessibility.py      — AX framework macOS
│
├── web/
│   ├── server.py         — FastAPI + WebSocket streaming (/ws: token + done)
│   └── static/           — Frontend HTML/CSS/JS
│
├── memory/
│   ├── store.py          — SQLite: historial de conversación y metadata
│   └── schema.sql
│
├── knowledge/
│   └── knowledge_base.py — Base de conocimiento local con embeddings
│
├── intents/
│   ├── class_session.py  — Graba clase → transcribe → resume → extrae tareas → calendar
│   └── good_morning.py   — Briefing matutino: clima, agenda, noticias, rutinas
│
├── tools/
│   ├── registry.py       — ToolRegistry + build_default_registry() (21 tools)
│   ├── shell.py          — Comandos de terminal (MAX_OUTPUT_CHARS=20000)
│   ├── filesystem.py     — Leer/escribir/listar/mover/copiar (MAX 10MB, bloquea /etc ~/.ssh)
│   ├── open_app.py       — Abrir apps, URLs, archivos en macOS
│   ├── run_code.py       — Sandbox Docker Python/Node (--network=none --memory=256m)
│   ├── web_search.py     — Búsqueda web sin API key
│   ├── web_agent.py      — Automatización Playwright con bucle LLM
│   ├── spotify.py        — Control de Spotify
│   ├── calendar.py       — macOS Calendar: consultar/crear eventos
│   ├── email.py          — Mail.app: enviar/borradores
│   ├── send_message.py   — iMessage / WhatsApp / Telegram
│   ├── vision.py         — Analizar/describir/leer pantalla (OCR)
│   ├── code_assistant.py — Generar y editar código
│   ├── knowledge.py      — Base de conocimiento: buscar/añadir/eliminar
│   ├── organize_files.py — Organización inteligente por tipo/fecha/ML
│   ├── download_file.py  — Descarga + auto-organización (incluye search_and_download)
│   ├── system_info.py    — CPU, RAM, disco, batería, red, uptime
│   ├── datetime_tool.py  — Fecha y hora actual con timezone
│   ├── weather.py        — Previsión meteorológica sin API key
│   ├── cad_generator.py  — Modelos 3D con build123d → STL
│   ├── routines.py       — Rutinas diarias (data/routines.json)
│   ├── shell_guard.py    — Análisis de seguridad de comandos shell
│   └── schemas/          — Contratos Pydantic input/output por tool
│
└── desktop/
    ├── autostart.py      — LaunchAgent plist (install/uninstall/status)
    └── doctor.py         — Health check: permisos, micrófono, cámara, accesibilidad
```

---

## Herramientas registradas (22)

`shell` · `filesystem` · `open_app` · `run_code` · `web_search` · `web_agent` · `spotify` · `calendar` · `send_email` · `send_message` · `vision` · `code_assistant` · `knowledge` · `organize_files` · `download_file` · `search_and_download` · `system_info` · `datetime` · `weather` · `cad_generator` · `routines` · `annotate_screen`

---

## Agente

### Backends LLM (prioridad de uso)

**Claude → Gemini → Groq → Ollama**

`tool_agent_from_settings()` devuelve `PEVAgent` si `PEV_ENABLED=true`, o `ToolAgent` si no.

### ToolAgent (modo por defecto)

Bucles reactivos LLM hasta 8 iteraciones. `_execute_tool()` aplica `prompt_guard` antes de ejecutar cualquier tool. Múltiples tool calls se ejecutan en paralelo con `ThreadPoolExecutor` vía `_run_tool_calls_parallel()` (Groq, Ollama y streaming).

**LLM Streaming**: `run_sentences()` emite frases vía callback `on_sentence` mientras el LLM genera. Daemon usa `speak_queued()` con una `Queue` para reproducir frases sin gaps entre ellas (LLM y TTS corren en paralelo).

### PEVAgent (`PEV_ENABLED=true`)

Misma API pública que ToolAgent (`run`, `run_stream`, `intent_tracker`). Flujo:

1. **Planner** — LLM genera JSON `Plan` sin ejecutar nada
2. **Executor** — itera pasos; resuelve `{{sN.field}}` entre pasos; pide confirmación para steps `sensitive=True`; pausa para `requires_user_input=True`
3. **Verifier** — valida output tras cada ejecución; reintenta si `retryable=True`
4. **Synthesizer** — resume resultados en lenguaje natural

Estado entre turnos en `RunStateStore` (TTL 600s):
- `pending_confirmation_step` → esperando sí/no del usuario
- `pending_user_input_step` → esperando dato del usuario

Fallback: plan JSON inválido o sin `steps` → `ToolAgent.run()` silencioso.

### Seguridad en capas

| Capa | Módulo | Función |
|------|--------|---------|
| Prompt injection | `prompt_guard.py` | Detecta role-override, exfil, path traversal en args |
| Shell guard | `shell_guard.py` | allow / confirm / deny por patrones de riesgo |
| Dry-run | `dry_run.py` | Preview antes de ejecutar tools sensibles |
| Confirm policy | `confirm_policy.py` | Gestiona confirmaciones TTL del usuario |
| Filesystem | `filesystem.py` | Bloquea `/etc`, `/usr`, `~/.ssh`, `~/.aws`, `~/.gnupg`, etc. |
| Docker sandbox | `run_code.py` | `--network=none --memory=256m --cpus=0.5 --read-only` |
| IPC bridge | `swift_bridge.py` | Token auth `secrets.token_hex(32)` + límite 64KB/msg |
| Circuit breaker | `circuit_breaker.py` | 3 fallos → OPEN 30s → HALF_OPEN → CLOSED |

---

## Overlay visual (estilo Cloud Entity)

Paletas de color por estado:

| Estado | Color A | Color B |
|--------|---------|---------|
| `idle` | cyan `(0,1,0.878)` | purple `(0.482,0.188,1)` |
| `listening` | green `(0,1,0.533)` | cyan |
| `thinking` | yellow `(1,0.882,0)` | orange `(1,0.549,0)` |
| `acting` | pink `(1,0.125,0.376)` | purple `(0.545,0,1)` |

`view.set_state()` sincroniza automáticamente el color del HUD vía `hud.set_accent_color()`.

En `main.py`: `view.set_hud(daemon._hud)` después de crear el daemon.

API pública de `JarvisView` (no renombrar): `set_state`, `set_audio_level`, `attach_particles`, `set_window`, `set_orb_click_handler`, `set_position`, `set_hud`, `orb_position`.

---

## Control por gestos (`USE_GESTURES=true`)

MediaPipe Hands en hilo daemon separado. Cooldown 1.5s entre gestos, 5 frames estables para confirmar:

| Gesto | Acción en daemon |
|-------|-----------------|
| Puño cerrado | `interrupt()` — para TTS/grabación |
| Palma abierta | Toggle `pause_gesture()` / `resume_gesture()` |
| Pinch (pulgar+índice) | `submit_text("sí, confirmo")` |
| V (dos dedos) | `trigger_voice_input()` — voz sin wake word |
| Pulgar arriba | `submit_text("sí")` |
| Pulgar abajo | `submit_text("no, cancela")` |

`GESTURE_DEBUG=true` abre preview OpenCV con landmarks en tiempo real.

Comunicación vía `enqueue_gesture_event(action)` → `_trigger_queue` del daemon.

---

## Variables de entorno

```env
# LLM
USE_CLAUDE=false          ANTHROPIC_API_KEY=        ANTHROPIC_MODEL=claude-sonnet-4-6
USE_GEMINI=false          GEMINI_API_KEY=            GEMINI_MODEL=gemini-2.0-flash
USE_GROQ=true             GROQ_API_KEY=              GROQ_MODEL=llama-3.3-70b-versatile
OLLAMA_MODEL=llama3.2:3b

# STT / TTS
STT_ENGINE=groq           STT_GROQ_MODEL=whisper-large-v3-turbo
TTS_ENGINE=elevenlabs     ELEVENLABS_API_KEY=        ELEVENLABS_VOICE_ID=
ELEVENLABS_MODEL=eleven_multilingual_v2

# Wake word
WAKE_WORD_ENGINE=openwakeword   WAKE_WORD=jarvis          WAKE_WORD_SENSITIVITY=0.5
WAKE_WORD_MIN_RMS=120           WAKE_WORD_MIN_HITS=2      WAKE_BEEP=true
WAKE_WORD_COOLDOWN=1.5          WAKE_WORD_SCORE_EMA_ALPHA=0.6
PORCUPINE_ACCESS_KEY=

# VAD
VAD_ENGINE=silero         VAD_SILENCE_MS=480         VAD_PRE_BUFFER_MS=1500

# Gestos
USE_GESTURES=false        GESTURE_COOLDOWN=1.5       GESTURE_DEBUG=false
GESTURE_CAMERA_INDEX=0

# Cámara contextual
CAMERA_CONTEXT=false      CAMERA_CONTEXT_INDEX=0     CAMERA_CONTEXT_INTERVAL=5.0
CAMERA_CONTEXT_FACE_ONLY=false

# Seguridad
DRY_RUN_ENABLED=true
DRY_RUN_ALWAYS_FOR=send_email,send_message,calendar,filesystem,shell,web_agent
SHELL_GUARD_ENABLED=true  SHELL_GUARD_MODE=strict
CONFIRM_POLICY_ENABLED=true    CONFIRM_TTL_SECONDS=120
VERIFIER_ENABLED=true     VERIFIER_TIMEOUT_MS=1500
TOOL_SCHEMA_VALIDATION_ENABLED=true

# PEV Pipeline
PEV_ENABLED=false         PEV_MAX_STEPS=6            PEV_RETRY_MAX=1
PEV_STATE_TTL_SECONDS=600 PEV_VERBOSE_TRACE=false

# General
DEBUG=false               DATA_DIR=data
```

---

## Tests

```bash
PYTHONPATH=src python -m pytest tests/ -v
PYTHONPATH=src python -m pytest tests/ --cov=jarvis --cov-report=term-missing
PYTHONPATH=src python -m pytest tests/test_gesture_controller.py -v
```

~30 ficheros de test, 618 tests. Cobertura mínima configurada: 70%. Los tests de overlay requieren display; el resto no necesitan hardware real.

---

## Flags CLI

| Flag | Descripción |
|------|-------------|
| `--desktop` | Overlay macOS (modo principal) |
| `--web` | Servidor FastAPI |
| `--voice` | Voz con wake word, sin overlay |
| `--no-voice` | Solo CLI |
| `--port N` | Puerto web (default 8000) |
| `--debug` | Logging verbose |
| `--install-autostart` | Registrar LaunchAgent macOS |
| `--uninstall-autostart` | Eliminar LaunchAgent |
| `--autostart-status` | Estado del autostart |
| `--restart-autostart` | Reinstalar autostart |
| `--doctor-desktop` | Health check de permisos del sistema |
| `--class-session` | Grabar y procesar clase |
| `--class-seconds N` | Duración de grabación (default 180s) |
| `--class-title T` | Identificador de la clase |
| `--class-audio PATH` | Usar WAV existente en lugar de grabar |
| `--no-class-calendar-sync` | Sin sincronización a Calendario |

---

## Dependencias opcionales

```bash
pip install -e ".[gestures]"   # MediaPipe + OpenCV (gestos de mano)
pip install -e ".[browser]"    # Playwright (web_agent)
playwright install chromium
pip install -e ".[cad]"        # build123d (cad_generator)
pip install -e ".[rag]"        # ChromaDB (knowledge base con embeddings)
pip install -e ".[dev]"        # pytest, ruff, mypy, black, pre-commit
```

---

## Convenciones

- Python 3.11+, src layout (`PYTHONPATH=src` siempre)
- Pydantic v2: usar `@field_validator` + `@classmethod`, nunca `@validator`
- Imports tardíos para dependencias opcionales (mediapipe, playwright, build123d, cv2)
- `logging.getLogger(__name__)` en producción, nunca `print()`
- Tests sin hardware real: cámara, micrófono y MediaPipe siempre mockeados
- Pre-commit activo: ruff (linting) + black (formato) + mypy (módulos críticos) + detect-private-key

---

Última actualización: 5 de marzo de 2026
