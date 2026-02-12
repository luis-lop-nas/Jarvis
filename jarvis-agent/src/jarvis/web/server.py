"""
server.py

Servidor web FastAPI para Jarvis con transcripción de voz.
"""

from __future__ import annotations

import json
import tempfile
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from jarvis.config import load_settings
from jarvis.agent.tool_agent import tool_agent_from_settings
from jarvis.memory.store import MemoryStore
from jarvis.voice.stt import STT, STTConfig


app = FastAPI(title="Jarvis Web Interface")

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_agent = None
_memory_store = None
_stt = None


def get_agent():
    """Inicializa el agente si no existe."""
    global _agent, _memory_store
    
    if _agent is None:
        settings, paths = load_settings()
        _memory_store = MemoryStore(paths.db_path)
        _agent = tool_agent_from_settings(settings, memory_store=_memory_store)
    
    return _agent


def get_stt():
    """Inicializa STT si no existe."""
    global _stt
    
    if _stt is None:
        _stt = STT(STTConfig())
    
    return _stt


@app.get("/", response_class=HTMLResponse)
async def root():
    """Página principal."""
    html_file = STATIC_DIR / "index.html"
    
    if not html_file.exists():
        return HTMLResponse(
            content="<h1>Interface no encontrada</h1>",
            status_code=500
        )
    
    return HTMLResponse(content=html_file.read_text())


@app.post("/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    """Transcribe audio usando Whisper."""
    import subprocess
    
    try:
        stt = get_stt()
        
        # Leer todo el contenido del archivo
        content = await audio.read()
        
        if len(content) < 1000:  # Archivo muy pequeño
            return JSONResponse({
                "ok": False,
                "error": "Audio demasiado corto o vacío"
            })
        
        # Guardar como webm temporal
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_webm:
            tmp_webm.write(content)
            webm_path = Path(tmp_webm.name)
        
        # Convertir a WAV
        wav_path = webm_path.with_suffix('.wav')
        
        try:
            # Convertir con ffmpeg
            result = subprocess.run(
                [
                    'ffmpeg', '-i', str(webm_path),
                    '-ar', '16000',
                    '-ac', '1',
                    '-f', 'wav',
                    '-y',
                    str(wav_path)
                ],
                capture_output=True,
                timeout=10,
                text=True
            )
            
            if result.returncode != 0:
                # Limpiar
                webm_path.unlink(missing_ok=True)
                return JSONResponse({
                    "ok": False,
                    "error": "No se pudo convertir el audio. Intenta grabar más tiempo."
                })
            
            # Verificar que el WAV existe y tiene contenido
            if not wav_path.exists() or wav_path.stat().st_size < 1000:
                webm_path.unlink(missing_ok=True)
                wav_path.unlink(missing_ok=True)
                return JSONResponse({
                    "ok": False,
                    "error": "Audio convertido vacío. Habla más cerca del micrófono."
                })
            
            # Transcribir
            text = stt.transcribe_wav(wav_path)
            
            # Limpiar archivos temporales
            webm_path.unlink(missing_ok=True)
            wav_path.unlink(missing_ok=True)
            
            return JSONResponse({
                "ok": True,
                "text": text
            })
            
        except subprocess.TimeoutExpired:
            webm_path.unlink(missing_ok=True)
            return JSONResponse({
                "ok": False,
                "error": "Timeout convirtiendo audio"
            })
        
    except Exception as e:
        return JSONResponse({
            "ok": False,
            "error": f"Error: {str(e)}"
        }, status_code=500)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket para chat."""
    await websocket.accept()
    agent = get_agent()
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            user_message = message_data.get("message", "").strip()
            
            if not user_message:
                await websocket.send_json({
                    "type": "error",
                    "content": "Mensaje vacío"
                })
                continue
            
            await websocket.send_json({
                "type": "user_message",
                "content": user_message
            })
            
            try:
                response = agent.run(user_message)
                
                await websocket.send_json({
                    "type": "assistant_message",
                    "content": response
                })
                
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "content": f"Error: {str(e)}"
                })
    
    except WebSocketDisconnect:
        print("Cliente desconectado")
    except Exception as e:
        print(f"Error WebSocket: {e}")


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "jarvis-web"}
