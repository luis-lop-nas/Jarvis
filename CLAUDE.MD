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
   - **Voice**: STT (Groq Whisper) · VAD Silero ONNX (ML, sin torchaudio) con pre-buffer 1.5s · TTS (ElevenLabs / Piper / macOS say)
   - **Vision**: Análisis de pantalla con Quartz + APIs de Accesibilidad
   - **Gestures**: Control por gestos de mano con MediaPipe (opcional, `USE_GESTURES=true`)

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
│   ├── test_overlay.py           # Test visual del orb (sin daemon)
│   ├── test_overlay_daemon.py    # Test completo overlay + daemon
│   ├── test_intent_tracker.py    # Tests unitarios IntentTracker (61 tests)
│   ├── test_send_message.py      # Tests unitarios send_message (45 tests)
│   ├── test_web_agent.py         # Tests unitarios web_agent (69 tests)
│   ├── test_gesture_controller.py # Tests unitarios gesture_controller (54 tests)
│   └── test_cad_generator.py     # Tests unitarios cad_generator (63 tests)
└── src/
    └── jarvis/
        ├── config.py            # Settings centralizados (pydantic-settings)
        ├── main.py              # Entry point: --desktop / --web / --voice / CLI
        ├── autostart.py         # LaunchAgent macOS (install/uninstall)
        ├── agent/
        │   ├── runner.py        # AgentConfig (base dataclass)
        │   ├── state.py         # AgentState + truncate_history
        │   ├── tool_agent.py    # Motor principal: Claude/Gemini/Groq/Ollama
        │   ├── intent_tracker.py  # Multi-step intent: parámetros faltantes
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
        │   ├── web_agent.py     # Agente web autónomo con Playwright
        │   ├── spotify.py
        │   ├── calendar.py
        │   ├── email.py
        │   ├── send_message.py  # iMessage/WhatsApp/Telegram vía AppleScript
        │   ├── vision.py
        │   ├── code_assistant.py
        │   ├── knowledge.py
        │   ├── organize_files.py
        │   ├── download_file.py
        │   ├── system_info.py
        │   ├── datetime_tool.py
        │   ├── weather.py
        │   └── cad_generator.py # Generación 3D CAD con build123d → STL
        ├── ui/
        │   └── cli.py
        ├── vision/
        │   ├── screenshot.py
        │   ├── vision_analyzer.py
        │   ├── accessibility.py
        │   └── gesture_controller.py  # Control por gestos MediaPipe (opcional)
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
WAKE_BEEP=true                      # beep 440Hz 80ms al detectar wake word

# VAD avanzado (Silero ONNX — sin torchaudio)
VAD_ENGINE=silero                   # "silero" (default) | "rms" (legacy)
VAD_SILENCE_MS=480                  # ms de silencio para cortar grabación
VAD_PRE_BUFFER_MS=1500              # ms de ring buffer pre-wake

# Gesture control (opcional)
USE_GESTURES=false
GESTURE_COOLDOWN=1.5
GESTURE_DEBUG=false
GESTURE_CAMERA_INDEX=0
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

# Instalar dependencias opcionales
pip install -e ".[browser]"   # Playwright para web_agent
pip install -e ".[cad]"       # build123d para cad_generator
playwright install chromium   # Instalar navegador Chromium
```

## 🖥️ Overlay Desktop — Arquitectura

### Hilo principal (NSApplication)
`window.py` → `view.py` → `particles.py`

El NSApplication corre en el hilo principal. El orb se dibuja a 30fps con NSTimer. Las partículas se actualizan en el mismo timer.

### Hilo secundario (daemon)
`daemon.py` → `bridge.py` → hilo principal

El daemon corre en background. Se comunica con el overlay vía `OverlayBridge` (cola thread-safe bombeada por NSTimer cada 50ms).

### Hilo terciario (gesture controller, opcional)
`gesture_controller.py` → `daemon.trigger_queue` / `daemon.interrupt()`

El `GestureController` corre en un daemon thread independiente. Se comunica con el daemon vía la `_trigger_queue` existente y los métodos públicos `interrupt()`, `pause_gesture()`, `resume_gesture()`.

### Ciclo de interacción

```
Wake word ("Hey Jarvis")   →  beep 440Hz   → orb verde    → graba con VAD Silero
   o Ctrl+Space / botón    →  orb verde    → popup de texto / panel de chat
   o gesto V-sign          →  orb verde    → trigger de voz por gesto

Transcripción / texto      →  orb naranja  → LLM procesa con contexto automático
                                              (hora + app activa + portapapeles
                                               + intent pendiente si lo hay)
                                              (órbitas girando)

Parámetros faltantes       →  orb naranja  → IntentTracker pregunta uno a uno
                                              HUD muestra "⚙ Completando: tool"
                                              follow-up extendido a 30s

Tool visual (open_app...)  →  orb azul     → 30 partículas
                                              vuelan al Dock
                                              → se ejecuta la tool

TTS respuesta              →  orb azul     → Jarvis habla (respuesta completa)
                                              HUD muestra el texto 3.5s
Fin (sin seguimiento)      →  orb azul     → idle
  o seguimiento (6s/30s)   →  orb verde    → escucha sin wake word
```

### Clases clave del overlay

| Clase | Archivo | Responsabilidad |
|-------|---------|-----------------|
| `JarvisWindow` | `window.py` | NSWindow transparente, nivel 1000, todos los Spaces |
| `JarvisView` | `view.py` | Dibuja orb + halos + órbitas; gestiona drag |
| `ParticleSystem` | `particles.py` | Vuelos de partículas bezier (`fly_to`) |
| `OverlayBridge` | `bridge.py` | Cola IPC + `run_on_main_thread()` |
| `_SileroVAD` | `daemon.py` | Wrapper ONNX de Silero VAD (sin torchaudio); singleton; estado LSTM por sesión |
| `VisualRegistry` | `daemon.py` | ToolRegistry que intercepta tools para lanzar `fly_to` |
| `JarvisDaemon` | `daemon.py` | Wake word / hotkey / VAD / STT / LLM / TTS / follow-up |
| `_ClipboardMonitor` | `daemon.py` | Monitoriza portapapeles (1s poll, máx 250 chars) |
| `JarvisHUD` | `hud.py` | Panel subtítulos centrado, fade-out 3.5s, click-through |
| `ChatPanel` | `chat_panel.py` | Historial scrollable + campo de texto; toggle desde menú |
| `MainPanel` | `main_panel.py` | Panel liquid glass esquina inferior derecha (Quit/Voice/Type) |
| `MenuBar` | `menubar.py` | Icono ◉ J, toggle Silenciar, toggle Autostart |
| `TextInputPopup` | `text_input.py` | Popup texto para hotkey Ctrl+Space |
| `GestureController` | `gesture_controller.py` | Control por gestos de mano (daemon thread, opcional) |

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
- Muestra `⚙ Completando: tool — falta: param` cuando hay intent pendiente

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
- **Intent pendiente** si el tracker tiene parámetros ya recopilados

Formato: `[Sistema: hora: 14:30 | app activa: Safari | URL: ... | portapapeles: «...»]`
Intent: `[Intent pendiente: herramienta=send_email | parámetros ya recopilados: to='Pedro' | parámetros que faltan: subject]`

### Conversación continua (follow-up)

Tras responder, el daemon escucha sin requerir wake word (`_try_followup`).
- **Timeout normal**: 6s (conversación libre)
- **Timeout extendido**: 30s cuando `IntentTracker.is_pending() == True` (recopilando parámetros)

Si el usuario habla → nuevo turno. Si no → vuelve a idle silenciosamente.

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

### Multi-step Intent (`intent_tracker.py`)

`ToolAgent` instancia un `IntentTracker` que resuelve peticiones con parámetros incompletos mediante diálogo iterativo.

**Dos vías de detección:**

| Vía | Cuándo activa | Mecanismo |
|-----|--------------|-----------|
| **Estructural** | LLM intenta llamar una tool con params obligatorios vacíos | `check_tool_call()` intercepta antes de ejecutar |
| **Conversacional** | LLM responde con una pregunta en lugar de usar la tool | `analyze_llm_response()` detecta `?` al final |

**Flujo estructural (Groq/Ollama):**
1. LLM intenta `send_email({to: "", subject: ""})` → tracker detecta params faltantes
2. Devuelve la pregunta directamente sin añadir el tool_call al historial (evita mensajes huérfanos)
3. Daemon habla la pregunta, extiende follow-up a 30s
4. Usuario responde → context injection inyecta `[Intent pendiente: ...]` en el siguiente prompt
5. LLM llama de nuevo con el param nuevo + los ya recopilados → ejecuta

**Flujo conversacional (Claude):**
1. Claude ve params faltantes en el schema `required` y pregunta por ellos sin llamar la tool
2. Tracker detecta `?` en la respuesta → activa `dialog_mode`
3. Follow-up extendido a 30s; siguiente turno con historial completo
4. Claude llama la tool cuando tiene todos los params

**API pública de `IntentTracker`:**

| Método | Llamado desde | Propósito |
|--------|--------------|-----------|
| `check_tool_call(name, args, registry)` | `tool_agent.py` (cada backend) | Intercepta antes de ejecutar; devuelve pregunta o None |
| `on_tool_executed(name)` | `tool_agent.py` (tras ejecutar) | Limpia el intent cuando la tool completa |
| `analyze_llm_response(response)` | `daemon.py` (tras `agent.run()`) | Detecta modo diálogo por `?` al final |
| `check_user_cancel(text)` | `daemon.py` (inicio `_process_text`) | Detecta "cancela"/"olvídalo"/etc. |
| `get_context_injection()` | `daemon.py` (build del prompt) | Genera `[Intent pendiente: ...]` |
| `get_followup_timeout(default)` | `daemon.py` (`_try_followup`) | 30s si pendiente, default si no |
| `get_status_text()` | `daemon.py` (HUD) | `"⚙ Completando: tool — falta: param"` |

### Limpieza de texto para TTS (`_clean_for_speech`)

Antes de hablar, el daemon filtra:
- Bloques de código (` ``` `) e inline code
- Tags `<function=...>`
- Markdown (negritas, listas, headers)
- Frases de estado ("Enseguida, señor.", "Buscando...", "Procesando...")
- Saltos de línea → espacios

El TTS recibe la respuesta completa en una sola llamada (`speak_nonblocking`) para evitar pausas.

## 🛠️ Herramientas Disponibles (20)

| # | Tool | Descripción |
|---|------|-------------|
| 1 | `shell` | Ejecutar comandos shell |
| 2 | `filesystem` | Leer/escribir/mover/copiar archivos |
| 3 | `open_app` | Abrir apps, URLs o archivos en macOS |
| 4 | `run_code` | Ejecutar Python/Node en Docker sandbox |
| 5 | `web_search` | Búsqueda DuckDuckGo |
| 6 | `spotify` | Control de Spotify |
| 7 | `calendar` | Consultar/crear eventos de calendario |
| 8 | `send_email` | Enviar emails via Mail.app |
| 9 | `send_message` | Enviar mensajes por iMessage/WhatsApp/Telegram |
| 10 | `vision` | Analizar pantalla (describe/OCR/contexto) |
| 11 | `code_assistant` | Generar código + abrir en VS Code |
| 12 | `knowledge` | Buscar/añadir en base de conocimiento RAG |
| 13 | `organize_files` | Organizar archivos por tipo/fecha |
| 14 | `download_file` | Descargar archivos de internet |
| 15 | `search_and_download` | Buscar y descargar automáticamente |
| 16 | `system_info` | CPU, RAM, disco, batería, red, procesos |
| 17 | `datetime` | Fecha y hora actual con zona horaria |
| 18 | `weather` | Clima de cualquier ciudad (sin API key) |
| 19 | `web_agent` | Agente de navegación web autónoma con Playwright |
| 20 | `cad_generator` | Generar modelos 3D → STL con build123d |

### Tool: `send_message`

Envía mensajes de texto vía AppleScript. Los inputs se pasan como `argv` al script (nunca interpolados), eliminando cualquier riesgo de AppleScript injection.

| Plataforma | Mecanismo | Automatización |
|-----------|-----------|----------------|
| `messages` (default) | AppleScript nativo de Messages.app | 100% — sin acción del usuario |
| `whatsapp` | UI scripting vía System Events | Requiere permiso Accesibilidad |
| `telegram` | UI scripting vía System Events | Requiere permiso Accesibilidad |

**Parámetros:** `receiver` (obligatorio), `message_text` (obligatorio), `platform` (opcional)
**Alias de plataforma:** `imessage`, `sms` → messages · `wa` → whatsapp · `tg` → telegram

**Permisos macOS:**
- Messages: Ajustes → Privacidad → Automatización → Terminal → Messages ✓
- WhatsApp/Telegram: Ajustes → Privacidad → Accesibilidad → Terminal ✓

### Tool: `web_agent`

Agente autónomo de navegación web usando Playwright + Chromium. El LLM decide cada acción (clic, scroll, fill, extract…) observando screenshots + DOM en cada paso.

**Parámetros:** `task` (obligatorio), `url` (opcional), `max_steps` (default 20), `headless` (default false), `force_sensitive` (default false)

**Acciones disponibles:** `navigate`, `google_search`, `click`, `type`, `press_enter`, `scroll`, `wait`, `extract`, `done`

**Acciones sensibles** (piden confirmación): compras, login, envío de formularios, pagos, eliminar cuenta.

**Requiere:** `pip install -e ".[browser]"` + `playwright install chromium`

**LLM priority para screenshots:** Claude (vision) → Groq (texto) → Gemini (vision)

### Tool: `cad_generator`

Genera modelos 3D paramétricos a partir de lenguaje natural usando build123d. Soporta iteraciones pasando el `session_id` de la respuesta anterior.

**Parámetros:** `description` (obligatorio), `session_id` (opcional, para iterar), `max_retries` (default 3), `open_viewer` (default false)

**Flujo interno:**
1. LLM genera código build123d con `_SYSTEM_PROMPT` (ejemplos verificados)
2. Validación AST: bloquea imports peligrosos (`os`, `sys`, `subprocess`…) y llamadas (`eval`, `exec`…)
3. Inyecta `OUTPUT_STL = "..."` antes del código
4. Ejecuta en subproceso aislado (`sys.executable`) con timeout 120s
5. Si falla, reenvía el error al LLM y reintenta (hasta 3 veces)
6. Persiste `{code, stl_path, iterations}` en `~/.../models/.cad_sessions.json`

**STL guardado en:** `~/Documents/Jarvis/models/<descripcion>_<timestamp>.stl`

**Requiere:** `pip install -e ".[cad]"` (build123d con OpenCASCADE)

### Gesture Controller (`gesture_controller.py`)

Control de JARVIS por gestos de mano usando la cámara del MacBook. Activar con `USE_GESTURES=true` en `.env`.

| Gesto | Acción |
|-------|--------|
| Puño cerrado | Interrumpir TTS + LLM en curso |
| Palma abierta | Pausar/reanudar el daemon (toggle) |
| Pinza (pulgar + índice) | Confirmar acción pendiente |
| V / Victoria | Activar modo voz (trigger_voice_input) |
| Pulgar arriba | Respuesta "sí" |
| Pulgar abajo | Respuesta "no" |

**Parámetros de config:**
- `GESTURE_COOLDOWN=1.5` — segundos entre gestos consecutivos
- `GESTURE_DEBUG=false` — mostrar feed de cámara con landmarks
- `GESTURE_CAMERA_INDEX=0` — índice de cámara

**API pública del daemon (añadida para gestos):**
- `daemon.interrupt()` — detiene TTS + señala `_interrupt_event`
- `daemon.pause_gesture()` / `resume_gesture()` — pausa el wake word loop
- `daemon.trigger_queue` — cola IPC para inyectar texto/comandos

**Requiere:** `pip install mediapipe opencv-python`

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
- **VAD Silero**: clase `_SileroVAD` en `daemon.py` usa `onnxruntime` directamente sobre `~/.cache/torch/hub/.../silero_vad.onnx`. Sin `torchaudio`. ONNX inputs: `input (1,512)`, `state (2,1,128)`, `sr (int64)`. Singleton cargado lazy en primer uso. Fallback a VAD RMS si el ONNX no existe.
- **Pre-buffer wake word**: `OpenWakeWordListener` mantiene un `collections.deque` de 1.5s (≈18 chunks de 1280 muestras). Al detectar wake word, `get_prebuffer()` vuelca y limpia el deque. `_record_with_vad_silero()` rechunquea los chunks OWW (1280) → Silero (512) y los antepone a la grabación.
- **Noise floor adaptativo**: `_update_noise_floor()` aplica EMA (α=0.05) durante los primeros 1.6s de espera pre-voz. El umbral dinámico es `noise_floor × 1.5` (filtro rápido antes de invocar Silero).
- **Silencio de corte adaptativo**: 10 chunks (320ms) para frases <2s de voz; 15 chunks (480ms) para frases ≥2s. Doble condición: `silence_count >= budget AND prob < 0.25`.
- **VAD RMS legacy** (`_record_with_vad_rms`): conservado como fallback; 30 chunks × 30ms = 900ms.
- **Beep wake word**: `_play_wake_beep()` genera onda seno 440Hz 80ms con fade in/out 10ms via `sd.play(..., blocking=False)`. Desactivar con `WAKE_BEEP=false`.
- **Buenos días antes del LLM**: el check de "buenos días" y fact follow-up ocurre ANTES de `agent.run()` para evitar llamadas innecesarias a la API.
- **Coordenadas macOS**: (0,0) = esquina inferior-izquierda; AX API usa top-left → conversión en `dock.py`
- **Thread model**: NSApplication en hilo principal; daemon en thread secundario; bridge sincroniza con NSTimer cada 50ms
- **PyObjC**: usar `objc.super(Cls, self).method_()` en subclases ObjC (no `super()`)
- **AXValueGetValue**: devuelve `(bool, CGPoint/CGSize)` — completamente bridgeado en pyobjc-framework-ApplicationServices
- **MainPanel foco de texto**: `popup._show()` se llama desde el handler del click (contexto de gesto) para garantizar permiso de macOS 14+ de asignar foco al campo
- **AppleScript injection**: en `send_message.py` los strings de usuario se pasan como `argv` a `osascript -` (stdin), nunca interpolados en el cuerpo del script
- **IntentTracker**: para Groq/Ollama la intercepción es antes de añadir el tool_call al historial de mensajes (evita tool_calls huérfanos sin su tool_result)
- **Playwright stub**: `sync_playwright = None` en módulo cuando no está instalado; tests usan `patch("...._PLAYWRIGHT_AVAILABLE", True)` + mock de `sync_playwright`
- **Gesture detection orden**: PINCH → THUMB_UP/DOWN (requiere extensión lateral) → FIST → OPEN_PALM → V_SIGN. El pulgar en un puño no se clasifica como THUMB porque `fingers_up()` comprueba extensión lateral antes de la dirección vertical
- **CAD code validation**: AST walk bloquea imports fuera de `{build123d, math}` y llamadas a `{eval, exec, compile, __import__, breakpoint}`. Comprobación de presencia de `result_part` y `export_stl` por substring
- **CAD subprocess**: ejecuta con `sys.executable` (venv local) porque build123d necesita OCC que es complejo en Docker
- **CAD session context**: `~/.../models/.cad_sessions.json` — JSON con `{sessions: {session_id: {code, stl_path, iterations, updated_at}}}`
- **Gemini candidates guard**: `tool_agent.py` comprueba `if not response.candidates` antes de acceder al índice 0 (puede ser lista vacía por filtro de contenido)
- **weather.py indexing**: usa `data.get("current_condition", [])` con check explícito de lista vacía; `hourly[4]` protegido con `len(hourly) > 4`
- **web_agent fallback LLM**: respeta `USE_CLAUDE=false` también en el bloque fallback de `_detect_llm_config()`

## 🐛 Debugging

```bash
# Test Silero VAD ONNX (sin arrancar Jarvis)
PYTHONPATH=src python -c "
from jarvis.overlay.daemon import _SileroVAD
import numpy as np
vad = _SileroVAD.load()
print('prob silencio:', vad(np.zeros(512, dtype=np.float32)))
"

# Modo desktop con logs
PYTHONPATH=src python -m jarvis --desktop

# Solo overlay visual (sin daemon)
PYTHONPATH=src python tests/test_overlay.py

# Overlay + daemon completo
PYTHONPATH=src python tests/test_overlay_daemon.py

# Tests unitarios
PYTHONPATH=src pytest tests/test_intent_tracker.py -v      # 61 tests
PYTHONPATH=src pytest tests/test_send_message.py -v        # 45 tests
PYTHONPATH=src pytest tests/test_web_agent.py -v           # 69 tests
PYTHONPATH=src pytest tests/test_gesture_controller.py -v  # 54 tests
PYTHONPATH=src pytest tests/test_cad_generator.py -v       # 63 tests
PYTHONPATH=src pytest tests/ -v                            # 292 tests (todos)

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
**Versión**: 2.4.0
