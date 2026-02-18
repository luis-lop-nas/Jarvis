"""
server.py

Servidor web FastAPI para Jarvis con transcripción de voz y streaming.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from jarvis.config import load_settings
from jarvis.agent.tool_agent import tool_agent_from_settings
from jarvis.memory.store import MemoryStore
from jarvis.voice.stt import STT, STTConfig
from jarvis.voice.tts import TTS, TTSConfig

_agent = None
_stt = None
_tts = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa todos los componentes al arrancar el servidor."""
    global _agent, _stt, _tts

    settings, paths = load_settings()

    memory_store = MemoryStore(paths.db_path)
    _agent = tool_agent_from_settings(settings, memory_store=memory_store)

    _stt = STT(STTConfig(
        engine=settings.stt_engine,
        groq_api_key=settings.groq_api_key,
        groq_model=settings.stt_groq_model,
        whisper_model=settings.stt_whisper_model,
    ))

    _tts = TTS(TTSConfig(
        engine=settings.tts_engine,
        elevenlabs_api_key=settings.elevenlabs_api_key,
        elevenlabs_voice_id=settings.elevenlabs_voice_id,
        elevenlabs_model=settings.elevenlabs_model,
    ))

    print("✅ Jarvis inicializado y listo")
    yield


STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Jarvis Web Interface", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_briefing() -> Dict[str, Any]:
    """Genera el briefing de bienvenida con hora, estado del sistema."""
    now = datetime.now()
    hour = now.hour

    # Saludo según hora
    if 6 <= hour < 14:
        greeting = "Buenos días"
    elif 14 <= hour < 21:
        greeting = "Buenas tardes"
    else:
        greeting = "Buenas noches"

    day_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    month_names = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]

    day_name = day_names[now.weekday()]
    month_name = month_names[now.month - 1]
    date_human = f"{day_name} {now.day} de {month_name} de {now.year}"
    time_str = now.strftime("%H:%M")

    # Info de sistema (psutil si disponible)
    system: Dict[str, Any] = {}
    try:
        import psutil
        vm = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.3)
        bat = psutil.sensors_battery()
        system = {
            "cpu_pct": round(cpu, 1),
            "ram_pct": round(vm.percent, 1),
            "ram_used_gb": round(vm.used / 1e9, 1),
        }
        if bat:
            system["battery_pct"] = round(bat.percent, 1)
            system["battery_plugged"] = bat.power_plugged
    except ImportError:
        pass
    except Exception:
        pass

    return {
        "greeting": greeting,
        "time": time_str,
        "date": date_human,
        "system": system,
    }


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root():
    """Página principal."""
    html_file = STATIC_DIR / "index.html"
    if not html_file.exists():
        return HTMLResponse(content="<h1>Interface no encontrada</h1>", status_code=500)
    return HTMLResponse(content=html_file.read_text())


@app.post("/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    """Transcribe audio usando Whisper."""
    try:
        stt = _stt
        content = await audio.read()

        if len(content) < 1000:
            return JSONResponse({"ok": False, "error": "Audio demasiado corto o vacío"})

        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_webm:
            tmp_webm.write(content)
            webm_path = Path(tmp_webm.name)

        wav_path = webm_path.with_suffix(".wav")

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    "ffmpeg", "-i", str(webm_path),
                    "-ar", "16000", "-ac", "1", "-f", "wav", "-y",
                    str(wav_path),
                ],
                capture_output=True,
                timeout=10,
                text=True,
            )

            if result.returncode != 0:
                webm_path.unlink(missing_ok=True)
                return JSONResponse({"ok": False, "error": "No se pudo convertir el audio."})

            if not wav_path.exists() or wav_path.stat().st_size < 1000:
                webm_path.unlink(missing_ok=True)
                wav_path.unlink(missing_ok=True)
                return JSONResponse({"ok": False, "error": "Audio convertido vacío."})

            text = await asyncio.to_thread(stt.transcribe_wav, wav_path)
            webm_path.unlink(missing_ok=True)
            wav_path.unlink(missing_ok=True)

            return JSONResponse({"ok": True, "text": text})

        except subprocess.TimeoutExpired:
            webm_path.unlink(missing_ok=True)
            return JSONResponse({"ok": False, "error": "Timeout convirtiendo audio"})

    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Error: {str(e)}"}, status_code=500)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket para chat con streaming de tokens."""
    await websocket.accept()

    # Briefing proactivo al conectar
    try:
        briefing = _build_briefing()
        await websocket.send_json({"type": "briefing", "data": briefing})
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)

            user_message = message_data.get("message", "").strip()
            if not user_message:
                await websocket.send_json({"type": "error", "content": "Mensaje vacío"})
                continue

            await websocket.send_json({"type": "user_message", "content": user_message})

            try:
                # Streaming: enviar chunks token a token
                async for chunk in _agent.run_stream(user_message):
                    await websocket.send_json({"type": "token", "content": chunk})

                # Señal de fin de respuesta
                await websocket.send_json({"type": "done"})

            except Exception as e:
                await websocket.send_json({"type": "error", "content": f"Error: {str(e)}"})

    except WebSocketDisconnect:
        print("Cliente desconectado")
    except Exception as e:
        print(f"Error WebSocket: {e}")


@app.post("/speak")
async def speak_text(request: dict):
    """Convierte texto a voz usando TTS."""
    try:
        text = request.get("text", "").strip()
        if not text:
            return JSONResponse({"ok": False, "error": "Texto vacío"})

        result = await asyncio.to_thread(_tts.speak, text)

        if result.get("returncode") == 0:
            return JSONResponse({"ok": True, "message": "Audio reproducido"})
        else:
            return JSONResponse({"ok": False, "error": result.get("stderr", "Error desconocido")})

    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Error: {str(e)}"}, status_code=500)


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "jarvis-web"}
