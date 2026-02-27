# Jarvis

## Run Desktop

```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
source .venv/bin/activate
PYTHONPATH=src python -m jarvis --desktop
```

## Auto-Start on Login (macOS)

```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
source .venv/bin/activate
PYTHONPATH=src python -m jarvis --install-autostart
```

Check status:

```bash
PYTHONPATH=src python -m jarvis --autostart-status
```

Remove auto-start:

```bash
PYTHONPATH=src python -m jarvis --uninstall-autostart
```

Restart auto-start:

```bash
PYTHONPATH=src python -m jarvis --restart-autostart
```

Desktop doctor (permissions + autostart):

```bash
PYTHONPATH=src python -m jarvis --doctor-desktop
```

## Run Web

```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
source .venv/bin/activate
PYTHONPATH=src python -m jarvis --web --port 8000
```

Web endpoints:
- `GET /` UI web (orb + chat glass)
- `GET /health` estado backend
- `POST /chat/stream` SSE modo general
- `POST /chat/realtime/stream` SSE modo realtime (incluye `search_results`)
- `GET /ws` WebSocket legado (compatibilidad)

Notas de uso:
- La UI mantiene `session_id` automáticamente para contexto.
- TTS se envía en chunks (`audio_b64`) cuando está activo en el cliente.
- En modo Realtime se muestra panel lateral con fuentes de búsqueda.

## Engines de voz (TTS)

Jarvis usa **Kokoro** como engine TTS por defecto — síntesis neural local, sin internet, ~150 ms de latencia en Apple Silicon.

| Engine | Calidad | Conexión | Latencia | Configuración |
|--------|---------|----------|----------|---------------|
| `kokoro` | ⭐⭐⭐⭐⭐ | Offline | ~150 ms | `TTS_ENGINE=kokoro` |
| `piper` | ⭐⭐⭐ | Offline | ~250-600 ms | Requiere modelo local |
| `macos` | ⭐⭐ | Offline | ~50 ms | Sin instalación |

### Instalar Kokoro

```bash
pip install ".[kokoro]"
```

En el primer arranque, Jarvis descarga automáticamente los modelos (~300 MB) en `~/Documents/Jarvis/models/kokoro/`.

### Voces disponibles

| Idioma | Voz | Descripción |
|--------|-----|-------------|
| Español | `ef_dora` | Femenina (default) |
| Español | `em_alex` | Masculina |
| Español | `em_santa` | Masculina grave |
| Inglés (US) | `af_heart` | Femenina |
| Inglés (US) | `af_bella` | Femenina |
| Inglés (US) | `am_adam` | Masculina |
| Inglés (US) | `am_michael` | Masculina |

### Cambiar entre engines

En `.env`:

```env
# Kokoro (default, local)
TTS_ENGINE=kokoro
KOKORO_VOICE=ef_dora        # voz española femenina
KOKORO_SPEED=1.0            # 0.5 (lento) – 2.0 (rápido)
KOKORO_LANGUAGE=es          # "es" | "en-us" | "en-gb"

# macOS nativo (fallback, sin instalación)
TTS_ENGINE=macos
```

### Uso desde código

```python
from jarvis.voice.tts import TTS, TTSConfig

tts = TTS(TTSConfig(engine="kokoro", kokoro_voice="em_alex", kokoro_language="es"))
tts.speak("Hola, soy Jarvis.")          # síncrono
tts.speak_nonblocking("Procesando...")  # no bloqueante
tts.stop()                              # interrupción inmediata
```

---

## Dry-run (acciones sensibles)

Jarvis aplica dry-run por defecto antes de ejecutar acciones sensibles.

- `send_email`, `send_message`: siempre dry-run.
- `calendar`: dry-run para crear/editar/eliminar.
- `filesystem`: dry-run para operaciones potencialmente destructivas o masivas.
- `shell`: dry-run para comandos peligrosos.
- `web_agent`: dry-run en modo acción; en modo lectura ejecuta directo.

Flujo:
- Jarvis devuelve payload `type="dry_run"` con `summary`, `details`, `risk_level` y `confirm_token`.
- Usuario confirma con `sí` o `confirmar <token>`.
- Usuario cancela con `no` o `cancelar`.
- TTL de acciones pendientes: 120s por defecto.

Configuración (`.env`):

```env
DRY_RUN_ENABLED=true
DRY_RUN_TTL_SECONDS=120
DRY_RUN_ALWAYS_FOR=send_email,send_message,calendar,filesystem,shell,web_agent
DRY_RUN_MAX_ITEMS_LIST=20
DRY_RUN_SNIPPET_CHARS=300
```

Extensión:
- Ajusta lógica en `src/jarvis/agent/dry_run.py`.

## Shell Guard

`shell` usa una política central `allow | confirm | deny` en:
- `src/jarvis/tools/shell_guard.py`

Ejemplos:
- `allow`: `ls -la`
- `confirm`: `sudo ...`, `curl ... | sh`, `mv ... /System/...`
- `deny`: `rm -rf /`, fork bomb, `dd if=/dev/zero of=/dev/disk*`, `mkfs*`, `shutdown -h now`, `reboot`, `kill -9 -1`

Configuración:

```env
SHELL_GUARD_ENABLED=true
SHELL_GUARD_MODE=strict   # strict | balanced
SHELL_DENY_PATTERNS=
SHELL_CONFIRM_PATTERNS=
```

## Verifier Post-acción

Tras ejecutar una tool, Jarvis puede verificar automáticamente si el efecto esperado ocurrió.

- Implementación central: `src/jarvis/agent/verifier.py`
- Resultado por tool: `ok | fail | unknown`
- Si `fail`: se devuelve `type="action_failed"` con `verify_report` y `tool_result`.
- Si `unknown`: no bloquea por defecto (a menos que `VERIFIER_STRICT=true` en tools críticas).

Configuración:

```env
VERIFIER_ENABLED=true
VERIFIER_TIMEOUT_MS=1500
VERIFIER_MAX_ITEMS=50
VERIFIER_SAMPLE_IF_OVER=200
VERIFIER_STRICT=false
```

## Tool Schemas (Pydantic)

Validación central de entrada/salida en el dispatcher:
- `src/jarvis/tools/schemas/`
  - `base.py` (ToolOutput + normalización)
  - `errors.py` (payload de errores de validación)
  - `tool_contract.py` (ToolContract)
  - `contracts.py` (mapping de las 21 tools)

Si falla input:
- `type="tool_validation_error"`, `stage="input"` y la tool no se ejecuta.

Si falla output:
- `type="tool_validation_error"`, `stage="output"` (strict) o warning embebido (no strict).

Configuración:

```env
TOOL_SCHEMA_VALIDATION_ENABLED=true
TOOL_SCHEMA_STRICT=true
TOOL_SCHEMA_LOG_INVALID=false
```

Cómo añadir una tool nueva:
1. Crear `InputModel` y `OutputModel` en `src/jarvis/tools/schemas/contracts.py`.
2. Registrar `ToolContract` para el nombre de la tool.
3. Registrar la tool en `registry.py` (el contrato se adjunta automáticamente).
4. Añadir tests de input/output inválido y caso válido.

Fase 2 (endurecimiento progresivo):
- Revisar campos opcionales -> obligatorios tool por tool.
- Añadir `Literal`/rangos para enums y parámetros numéricos.
- Modelar `data` de `ToolOutput` de forma más específica por herramienta.


cd /Users/luichi/Documents/Jarvis/jarvis-agent                                                                                                        
  source .venv/bin/activate                                 
  PYTHONPATH=src python -m jarvis --desktop
