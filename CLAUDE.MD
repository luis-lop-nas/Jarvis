# JARVIS - Advanced AI Assistant

## 📋 Descripción del Proyecto

JARVIS (Just A Rather Very Intelligent System) es un asistente de IA con overlay visual nativo en macOS, voz, visión y gestión de conocimiento mediante RAG. Corre en segundo plano sin Dock ni ventana visible.

## 🏗️ Arquitectura del Sistema

### Modos de uso

| Modo | Comando | Descripción |
|------|---------|-------------|
| **Desktop** *(principal)* | `python -m jarvis --desktop` | Overlay nativo macOS, voz + hotkey, sin Dock |
| **Web** | `python -m jarvis --web` | FastAPI + WebSocket, interfaz en navegador |
| **CLI** | `python -m jarvis` | Terminal interactivo con Rich |
| **Voz** | `python -m jarvis --voice` | Solo voz + wake word, sin overlay |

### Componentes Principales

1. **Overlay Desktop (PyObjC — modo principal)**
   - Orb animado flotante sobre todas las apps (NSWindow click-through)
   - Estados: `idle` (azul) · `listening` (verde) · `thinking` (naranja + órbitas) · `acting` (azul eléctrico)
   - Partículas bezier animadas (`fly_to`) antes de ejecutar tools visuales
   - Drag del orb con el ratón a cualquier posición
   - Popup de texto con `Ctrl+Space` (alternativa a voz)
   - Icono `◉ J` en la barra de menú con toggle Silenciar y Autostart
   - **HUD de subtítulos** (`hud.py`) — panel centrado en parte inferior con la respuesta completa
   - **Panel de chat** (`chat_panel.py`) — historial scrollable + campo de texto
   - **Panel de control** (`main_panel.py`) — liquid glass en esquina inferior derecha (Quit / Voice / Type)

2. **Backend (Python)**
   - FastAPI para servidor web (modo `--web`)
   - Motor LLM con prioridad: Claude → Gemini → Groq → Ollama
   - Sistema RAG con ChromaDB
   - Memoria persistente en SQLite

3. **Capacidades de IA**
   - **Claude (Anthropic)**: Motor principal con tool use nativo
   - **Gemini (Google)**: Alternativa cloud con tool use nativo
   - **Groq API**: `llama-3.3-70b-versatile` — motor activo (gratis, 14.400 req/día)
   - **Ollama**: Fallback local (`llama3.2:3b`)
   - **Voice**: STT (Groq Whisper + VAD por energía) · TTS (ElevenLabs / Piper / macOS say)
   - **Vision**: Análisis de pantalla con Quartz + APIs de Accesibilidad

## 📁 Estructura del Proyecto

```
jarvis-agent/
├── .env                     # Variables de entorno (API keys)
├── .env.example
├── pyproject.toml
├── data/                    # Datos en tiempo de ejecución (NO en git)
│   ├── jarvis.db            # SQLite — memoria persistente
│   ├── knowledge/           # ChromaDB vector database
│   ├── logs/
│   └── workspace/           # Archivos temporales del agente
├── tests/
│   ├── test_overlay.py      # Test visual del orb (sin daemon)
│   └── test_overlay_daemon.py  # Test completo overlay + daemon
└── src/
    └── jarvis/
        ├── config.py            # Settings centralizados (pydantic-settings)
        ├── main.py              # Entry point: --desktop / --web / --voice / CLI
        ├── autostart.py         # LaunchAgent macOS (install/uninstall)
        ├── agent/
        │   ├── runner.py        # AgentConfig (base dataclass)
        │   ├── state.py         # AgentState + truncate_history
        │   ├── tool_agent.py    # Motor principal: Claude/Gemini/Groq/Ollama
        │   └── prompts.py       # SYSTEM_PROMPT + SYSTEM_PROMPT_GROQ
        ├── knowledge/
        │   └── knowledge_base.py  # RAG con ChromaDB + sentence-transformers
        ├── memory/
        │   ├── schema.sql
        │   └── store.py         # MemoryStore — SQLite thread-safe
        ├── overlay/             # ── Overlay Desktop (PyObjC) ──
        │   ├── window.py        # NSWindow transparente, float sobre todo
        │   ├── view.py          # JarvisView: orb + órbitas + drag
        │   ├── particles.py     # ParticleSystem: fly_to bezier
        │   ├── bridge.py        # IPC thread-safe daemon ↔ overlay
        │   ├── dock.py          # Posición exacta de iconos del Dock (AX API)
        │   ├── daemon.py        # Voz/texto + LLM + tools + hooks visuales
        │   ├── hud.py           # HUD flotante de subtítulos (respuesta completa)
        │   ├── chat_panel.py    # Panel de chat con historial scrollable
        │   ├── main_panel.py    # Panel liquid glass (Quit/Voice/Type)
        │   ├── menubar.py       # Icono ◉ J en barra de menú
        │   └── text_input.py    # Popup texto (hotkey Ctrl+Space)
        ├── tools/
        │   ├── registry.py      # ToolRegistry + VisualRegistry (fly_to hooks)
        │   ├── shell.py
        │   ├── filesystem.py
        │   ├── open_app.py
        │   ├── run_code.py
        │   ├── web_search.py
        │   ├── spotify.py
        │   ├── calendar.py
        │   ├── email.py
        │   ├── vision.py
        │   ├── code_assistant.py
        │   ├── knowledge.py
        │   ├── organize_files.py
        │   ├── download_file.py
        │   ├── system_info.py
        │   ├── datetime_tool.py
        │   └── weather.py
        ├── ui/
        │   └── cli.py
        ├── vision/
        │   ├── screenshot.py
        │   ├── vision_analyzer.py
        │   └── accessibility.py
        ├── voice/
        │   ├── stt.py           # STT (Groq Whisper / local Whisper)
        │   ├── tts.py           # TTS (ElevenLabs / Piper / macOS say)
        │   ├── wake_word.py     # OpenWakeWord / Porcupine
        │   └── voice_loop.py    # Loop principal de voz (modo --voice)
        └── web/
            ├── server.py        # FastAPI server (lifespan pattern)
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

USE_GEMINI=false
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

## 🚀 Arrancar Jarvis

```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
source .venv/bin/activate

# Modo Desktop (recomendado)
PYTHONPATH=src python -m jarvis --desktop

# Modo Web
PYTHONPATH=src uvicorn jarvis.web.server:app --host 0.0.0.0 --port 8000
# Abrir: http://localhost:8000
```

## 🖥️ Overlay Desktop — Arquitectura

### Hilo principal (NSApplication)
`window.py` → `view.py` → `particles.py`

El NSApplication corre en el hilo principal. El orb se dibuja a 30fps con NSTimer. Las partículas se actualizan en el mismo timer.

### Hilo secundario (daemon)
`daemon.py` → `bridge.py` → hilo principal

El daemon corre en background. Se comunica con el overlay vía `OverlayBridge` (cola thread-safe bombeada por NSTimer cada 50ms).

### Ciclo de interacción

```
Wake word ("Hey Jarvis")   →  orb verde    → graba con VAD
   o Ctrl+Space / botón    →  orb verde    → popup de texto / panel de chat

Transcripción / texto      →  orb naranja  → LLM procesa con contexto automático
                                              (hora + app activa + portapapeles)
                                              (órbitas girando)

Tool visual (open_app...)  →  orb azul     → 30 partículas
                                              vuelan al Dock
                                              → se ejecuta la tool

TTS respuesta              →  orb azul     → Jarvis habla (respuesta completa)
                                              HUD muestra el texto 3.5s
Fin (sin seguimiento)      →  orb azul     → idle
  o seguimiento (6s)       →  orb verde    → escucha sin wake word
```

### Clases clave del overlay

| Clase | Archivo | Responsabilidad |
|-------|---------|-----------------|
| `JarvisWindow` | `window.py` | NSWindow transparente, nivel 1000, todos los Spaces |
| `JarvisView` | `view.py` | Dibuja orb + halos + órbitas; gestiona drag |
| `ParticleSystem` | `particles.py` | Vuelos de partículas bezier (`fly_to`) |
| `OverlayBridge` | `bridge.py` | Cola IPC + `run_on_main_thread()` |
| `VisualRegistry` | `daemon.py` | ToolRegistry que intercepta tools para lanzar `fly_to` |
| `JarvisDaemon` | `daemon.py` | Wake word / hotkey / VAD / STT / LLM / TTS / follow-up |
| `_ClipboardMonitor` | `daemon.py` | Monitoriza portapapeles (1s poll, máx 250 chars) |
| `JarvisHUD` | `hud.py` | Panel subtítulos centrado, fade-out 3.5s, click-through |
| `ChatPanel` | `chat_panel.py` | Historial scrollable + campo de texto; toggle desde menú |
| `MainPanel` | `main_panel.py` | Panel liquid glass esquina inferior derecha (Quit/Voice/Type) |
| `MenuBar` | `menubar.py` | Icono ◉ J, toggle Silenciar, toggle Autostart |
| `TextInputPopup` | `text_input.py` | Popup texto para hotkey Ctrl+Space |

### Estados del orb

| Estado | Color | Animación |
|--------|-------|-----------|
| `idle` | Azul `(0, 0.71, 1)` | Pulso suave |
| `listening` | Verde `(0, 0.95, 0.5)` | Pulso rápido + anillo |
| `thinking` | Naranja `(1, 0.6, 0)` | Anillo + 2 órbitas contra-rotantes |
| `acting` | Azul brillante `(0, 0.85, 1)` | Órbitas + partículas fly_to |

### Panel de control — MainPanel (`main_panel.py`)

Panel liquid glass (NSVisualEffectView material HUD) en la esquina inferior derecha.
Entra deslizándose desde fuera de pantalla con ease-out quint + fade en 340ms.
Tres botones píldora con icono bezier y etiqueta:

| Botón | Icono | Acción |
|-------|-------|--------|
| **Quit** | × | `os.kill(pid, SIGKILL)` |
| **Voice** | waveform 5 barras | `daemon.trigger_voice_input()` |
| **Type** | cursor I-beam | Popup de texto (garantía de foco en gesto) |

Botón × circular aparece al hover sobre el panel glass (fade 0→1 en 150ms).

### HUD de subtítulos — JarvisHUD (`hud.py`)

- Fondo oscuro `(0.03, 0.03, 0.09, 0.91)` con borde azul eléctrico `(0, 0.71, 1, 0.5)`
- Texto 15pt Light, hasta 6 líneas con word wrap; ancho fijo 600px centrado
- Icono `◈` identificador de Jarvis en azul
- Click-through (`setIgnoresMouseEvents_(True)`)
- Fade-out automático 3.5s tras fin del TTS (`schedule_hide()`)
- Oculto inmediatamente si hay interrupción (`hide()`)

### Panel de chat — ChatPanel (`chat_panel.py`)

- Historial scrollable de mensajes usuario/Jarvis con estética oscura + borde azul
- Campo de texto en parte inferior; Enter para enviar
- Draggable desde cualquier zona libre
- Toggle desde menú `◉ J`
- Thread-safe: `add_user_message()` / `add_jarvis_message()` desde cualquier thread

### Contexto automático en peticiones

Cada petición al LLM inyecta automáticamente:
- **Hora actual** (`datetime.now().strftime('%H:%M')`)
- **App activa** y título de ventana (Accessibility API)
- **URL** si el navegador tiene una página abierta
- **Portapapeles** (si hay >5 chars, primeros 200 chars)

Formato: `[Sistema: hora: 14:30 | app activa: Safari | URL: ... | portapapeles: «...»]`

### Conversación continua (follow-up)

Tras responder, el daemon escucha 6s sin requerir wake word (`_try_followup`).
Si el usuario habla → nuevo turno de conversación.
Si no hay voz → vuelve a idle silenciosamente.

### Detección de posición del Dock (`dock.py`)

Usa la API de Accesibilidad de macOS (`ApplicationServices.AXUIElementCreateApplication`) para encontrar la posición exacta de cada icono en el Dock. Las partículas vuelan al píxel exacto del icono antes de abrir la app.

Requiere permiso en: **Ajustes → Privacidad y Seguridad → Accesibilidad → Terminal ✓**

### Autostart (`autostart.py`)

Instala un LaunchAgent en `~/Library/LaunchAgents/com.jarvis.desktop.plist`. Activable desde el menú `◉ J → Arrancar al inicio`.

## 🧠 Motor de Agente

**Prioridad:** Claude → Gemini → Groq → Ollama

- Schemas de tools cacheados en `__init__` (`_cached_claude_tools`, etc.)
- Historial truncado a 20 mensajes (`truncate_history`)
- En modo desktop, `VisualRegistry` intercepta `open_app`, `shell`, `code_assistant`, `organize_files` para lanzar `fly_to` antes de ejecutar
- **Dos prompts:** `SYSTEM_PROMPT` (Claude/Gemini/Ollama) y `SYSTEM_PROMPT_GROQ` (compacto, evita confundir el function calling de llama)

### Limpieza de texto para TTS (`_clean_for_speech`)

Antes de hablar, el daemon filtra:
- Bloques de código (` ``` `) e inline code
- Tags `<function=...>`
- Markdown (negritas, listas, headers)
- Frases de estado ("Enseguida, señor.", "Buscando...", "Procesando...")
- Saltos de línea → espacios

El TTS recibe la respuesta completa en una sola llamada (`speak_nonblocking`) para evitar pausas.

## 🛠️ Herramientas Disponibles (17)

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
| `system_info` | CPU, RAM, disco, batería, red, procesos |
| `datetime` | Fecha y hora actual con zona horaria |
| `weather` | Clima de cualquier ciudad (sin API key) |

## 🔌 WebSocket API (modo --web)

**Cliente → Servidor:** `{ "message": "texto" }`

**Servidor → Cliente:** `{ "type": "user_message"|"assistant_message"|"error", "content": "..." }`

**Endpoints REST:**
- `GET /` — Interfaz web
- `GET /health` — Health check
- `POST /transcribe` — STT multipart/form-data
- `POST /speak` — TTS: `{ "text": "..." }`

## ⚡ Detalles de Implementación

- **FastAPI lifespan**: usa `@asynccontextmanager` (no el deprecated `@on_event`)
- **VAD**: grabación por energía RMS, para al detectar ~0.9s de silencio (threshold 300, int16)
- **Coordenadas macOS**: (0,0) = esquina inferior-izquierda; AX API usa top-left → conversión en `dock.py`
- **Thread model**: NSApplication en hilo principal; daemon en thread secundario; bridge sincroniza con NSTimer cada 50ms
- **PyObjC**: usar `objc.super(Cls, self).method_()` en subclases ObjC (no `super()`)
- **AXValueGetValue**: devuelve `(bool, CGPoint/CGSize)` — completamente bridgeado en pyobjc-framework-ApplicationServices
- **MainPanel foco de texto**: `popup._show()` se llama desde el handler del click (contexto de gesto) para garantizar permiso de macOS 14+ de asignar foco al campo

## 🐛 Debugging

```bash
# Modo desktop con logs
PYTHONPATH=src python -m jarvis --desktop

# Solo overlay visual (sin daemon)
PYTHONPATH=src python tests/test_overlay.py

# Overlay + daemon completo
PYTHONPATH=src python tests/test_overlay_daemon.py

# Web con debug
PYTHONPATH=src uvicorn jarvis.web.server:app --log-level debug

# Test posición Dock
python -c "
import sys; sys.path.insert(0, 'src')
from jarvis.overlay.dock import get_dock_icon_position
print(get_dock_icon_position('Finder', 1440.0))
"

# Logs de autostart
tail -f /tmp/jarvis.log
tail -f /tmp/jarvis.err
```

## 👤 Autor

**Luichi** — Desarrollador principal

---

**Última actualización**: Febrero 2026
**Versión**: 2.1.0
