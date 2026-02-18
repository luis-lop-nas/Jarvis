# JARVIS - Advanced AI Assistant

## 📋 Descripción del Proyecto

JARVIS (Just A Rather Very Intelligent System) es un asistente de IA avanzado con interfaz web interactiva, capacidades de voz, visión por computadora y gestión de conocimiento mediante RAG.

## 🏗️ Arquitectura del Sistema

### Componentes Principales

1. **Frontend Web (Interfaz Visual)**
   - Nube de puntos 3D interactiva (1200 partículas esféricas + 200 flotantes)
   - Animaciones suaves con física de partículas
   - Barra de búsqueda dinámica
   - Chat en tiempo real via WebSocket

2. **Backend (Python)**
   - FastAPI para servidor web
   - WebSocket para comunicación en tiempo real
   - Motor LLM con prioridad: Claude → Gemini → Groq → Ollama
   - Sistema RAG con ChromaDB
   - Memoria persistente en SQLite

3. **Capacidades de IA**
   - **Claude (Anthropic)**: Motor principal con tool use nativo
   - **Gemini (Google)**: Alternativa cloud con tool use nativo (no disponible en EU free tier)
   - **Groq API**: `llama-3.3-70b-versatile` — motor activo actualmente (gratis, 14.400 req/día)
   - **Ollama**: Fallback local (`llama3.2:3b` instalado)
   - **Voice**: STT (Groq Whisper) y TTS (ElevenLabs / macOS)
   - **Vision**: Análisis de pantalla con Quartz + APIs de accesibilidad

## 📁 Estructura del Proyecto

```
jarvis-agent/
├── .env                     # Variables de entorno (API keys)
├── .env.example             # Plantilla de .env
├── pyproject.toml           # Dependencias y configuración del paquete
├── README.md
├── data/                    # Datos en tiempo de ejecución (NO en git)
│   ├── jarvis.db            # SQLite — memoria persistente de sesiones
│   ├── knowledge/           # ChromaDB vector database
│   ├── knowledge_seed/      # Documentos iniciales para la KB
│   ├── logs/                # Logs de sesiones CLI
│   ├── voices/              # Modelos TTS locales (Piper)
│   └── workspace/           # Workspace del agente para archivos temporales
├── sandbox/
│   └── docker/              # Dockerfiles para sandbox de ejecución de código
│       ├── Dockerfile.python
│       └── Dockerfile.node
├── scripts/                 # Scripts de utilidad
│   ├── init_knowledge.py    # Inicializa la base de conocimiento
│   └── generate_knowledge_base.py
├── tests/                   # Tests (vacío, listo para crecer)
└── src/
    └── jarvis/
        ├── __init__.py
        ├── config.py            # Settings centralizados (pydantic-settings)
        ├── main.py              # Entry point: --web / --voice / CLI
        ├── agent/
        │   ├── runner.py        # AgentConfig (base dataclass)
        │   ├── state.py         # AgentState + truncate_history + helpers
        │   ├── tool_agent.py    # Motor principal: Claude/Gemini/Groq/Ollama
        │   └── prompts.py       # SYSTEM_PROMPT de JARVIS
        ├── knowledge/
        │   └── knowledge_base.py  # RAG con ChromaDB + sentence-transformers
        ├── memory/
        │   ├── schema.sql       # Schema SQLite (sessions, messages, tool_events)
        │   └── store.py         # MemoryStore — conexión persistente, thread-safe
        ├── tools/
        │   ├── registry.py      # ToolRegistry + build_default_registry()
        │   ├── shell.py         # Ejecutar comandos shell
        │   ├── filesystem.py    # Operaciones de archivos
        │   ├── open_app.py      # Abrir apps/URLs en macOS
        │   ├── run_code.py      # Ejecutar Python/Node en Docker sandbox
        │   ├── web_search.py    # Búsqueda web (DuckDuckGo)
        │   ├── spotify.py       # Control de Spotify
        │   ├── calendar.py      # Consultar/crear eventos
        │   ├── email.py         # Enviar emails via Mail.app
        │   ├── vision.py        # Análisis de pantalla
        │   ├── code_assistant.py # Generar código + abrir en VS Code
        │   ├── knowledge.py     # Wrapper tool para knowledge_base
        │   ├── organize_files.py # Organizar archivos automáticamente
        │   └── download_file.py  # Descargar archivos de internet
        ├── ui/
        │   └── cli.py           # CLI interactivo con Rich
        ├── vision/
        │   ├── screenshot.py    # Captura de pantalla (Quartz)
        │   ├── vision_analyzer.py # Análisis con LLM
        │   └── accessibility.py # Contexto de app activa (macOS)
        ├── voice/
        │   ├── stt.py           # Speech-to-Text (Groq Whisper / local)
        │   ├── tts.py           # Text-to-Speech (ElevenLabs / Piper / macOS)
        │   ├── wake_word.py     # Detección wake word (OpenWakeWord / Porcupine)
        │   └── voice_loop.py    # Loop principal de voz
        └── web/
            ├── server.py        # FastAPI server
            └── static/
                ├── index.html
                ├── style.css
                └── app.js
```

## ⚙️ Configuración (.env)

```env
# LLM principal (activar solo uno)
USE_CLAUDE=false
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-sonnet-4-6

USE_GEMINI=false                    # No disponible en EU (free tier = 0)
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.0-flash

USE_GROQ=true                       # ACTIVO — llama-3.3-70b-versatile
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile

# STT / TTS
STT_ENGINE=groq
STT_GROQ_MODEL=whisper-large-v3-turbo
TTS_ENGINE=elevenlabs
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...

# Wake word
WAKE_WORD_ENGINE=openwakeword
WAKE_WORD=jarvis
```

## 🚀 Arrancar el Servidor

```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
source .venv/bin/activate
PYTHONPATH=src uvicorn jarvis.web.server:app --host 0.0.0.0 --port 8000
```

Abrir: `http://localhost:8000`

El servidor inicializa agente + STT + TTS en el evento `startup` de FastAPI (no en el primer mensaje).

## 🖥️ Modos de Uso

```bash
# Web (recomendado)
python -m jarvis --web --port 8000

# CLI interactivo
python -m jarvis

# Voz con wake word
python -m jarvis --voice
```

## 🔌 WebSocket API

**Cliente → Servidor:**
```json
{ "message": "texto del usuario" }
```

**Servidor → Cliente:**
```json
{ "type": "user_message" | "assistant_message" | "error", "content": "..." }
```

**Endpoints REST:**
- `GET /` — Interfaz web
- `GET /health` — Health check
- `POST /transcribe` — Transcribir audio (multipart/form-data)
- `POST /speak` — TTS: `{ "text": "..." }`

## 🧠 Motor de Agente (tool_agent.py)

**Prioridad de motores:** Claude → Gemini → Groq → Ollama

Cada motor tiene su propio método `_run_with_*`. Los schemas de herramientas se precalculan en `__init__` y se cachean (`_cached_claude_tools`, `_cached_groq_tools`, etc.).

El historial se trunca a los últimos **20 mensajes** en cada llamada (`truncate_history` de `state.py`).

## 🧱 Módulos Clave

### `agent/state.py`
- `AgentState` — historial en memoria (memoria corta de la sesión)
- `truncate_history(history, max_messages=20)` — evita que el contexto crezca sin límite
- `count_tokens_estimate(messages)` — estimación rápida de tokens

### `agent/runner.py`
- `AgentConfig` — dataclass base con `debug: bool`

### `memory/store.py`
- `MemoryStore` — conexión SQLite persistente con `threading.Lock`
- Tablas: `sessions`, `messages`, `tool_events`
- WAL mode habilitado para concurrencia

### `tools/registry.py`
- `ToolRegistry` — registro central de herramientas
- `build_default_registry()` — construye el registro con las 14 tools disponibles

## 🛠️ Herramientas Disponibles (14)

| Tool | Descripción |
|------|-------------|
| `shell` | Ejecutar comandos shell |
| `filesystem` | Leer/escribir/mover/copiar archivos |
| `open_app` | Abrir apps, URLs o archivos en macOS |
| `run_code` | Ejecutar Python/Node en Docker sandbox |
| `web_search` | Búsqueda DuckDuckGo |
| `spotify` | Control de Spotify |
| `calendar` | Consultar/crear eventos de calendario |
| `send_email` | Enviar emails via Mail.app |
| `vision` | Analizar pantalla (describe/OCR/contexto) |
| `code_assistant` | Generar código + abrir en VS Code |
| `knowledge` | Buscar/añadir en base de conocimiento RAG |
| `organize_files` | Organizar archivos por tipo/fecha |
| `download_file` | Descargar archivos de internet |
| `search_and_download` | Buscar y descargar automáticamente |

## 🎨 Sistema Visual (Frontend)

**Nube de Puntos 3D:**
- 1200 partículas en distribución de Fibonacci (esfera)
- 200 partículas flotantes ambientales
- Física individual por partícula (rotación, velocidad, comportamiento)
- 40% de partículas reaccionan al ratón (optimización)

**Estados:**
1. `idle` — Esfera al 80%, centro de pantalla, movimiento casi imperceptible
2. `compact` — Al hacer click, compacta al 100% (~2s)
3. `active` — Al escribir, se mueve arriba-izquierda y vibra orgánicamente

**Paleta de colores:**
| Elemento | Color |
|----------|-------|
| Azul eléctrico | `#00B4FF` / `RGB(0, 180, 255)` |
| Azul brillante | `#64DCFF` / `RGB(100, 220, 255)` |
| Núcleo | `#FFFFFF` |
| Fondo | `#000000` |

## ⚡ Optimizaciones Backend Aplicadas

- **Startup FastAPI**: agente + STT + TTS se inicializan al arrancar el servidor, no en el primer mensaje
- **`load_settings()` único**: una sola lectura del `.env` al inicio
- **ffmpeg async**: conversión de audio en `asyncio.to_thread` (no bloquea el event loop)
- **Schemas cacheados**: `_cached_claude_tools`, `_cached_gemini_tools`, `_cached_ollama_tools` precalculados en `__init__`
- **Historial truncado**: máximo 20 mensajes enviados al LLM (evita latencia en sesiones largas)
- **SQLite persistente**: una sola conexión con `threading.Lock` en lugar de abrir/cerrar por operación

## 🐛 Debugging

```bash
# Ver logs del servidor en consola (uvicorn)
PYTHONPATH=src uvicorn jarvis.web.server:app --log-level debug

# Logs de sesiones CLI
ls data/logs/

# Health check
curl http://localhost:8000/health

# Test WebSocket rápido
python -c "
import asyncio, websockets, json
async def t():
    async with websockets.connect('ws://localhost:8000/ws') as ws:
        await ws.send(json.dumps({'message': 'hola'}))
        print(await ws.recv())
asyncio.run(t())
"
```

## 🔮 Próximas Mejoras

- [ ] Reconocimiento de voz en web (MediaRecorder → /transcribe)
- [ ] Streaming de respuestas (SSE o WS chunked)
- [ ] Tests unitarios en `tests/`
- [ ] Historial de conversaciones visible en UI
- [ ] Mobile responsive
- [ ] Exportar conversaciones

## 👤 Autor

**Luichi** — Desarrollador principal

---

**Última actualización**: Febrero 2026
**Versión**: 1.1.0
