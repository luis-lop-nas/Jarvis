"""
server.py

FastAPI backend para la UI web de Jarvis.
Incluye:
- Static frontend (vanilla + orb)
- SSE streaming (general y realtime)
- Session management por session_id
- TTS opcional en chunks base64
- Endpoints legacy: /ws, /transcribe, /speak
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import subprocess
import tempfile
import time
import wave
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional, Tuple
from uuid import uuid4

import numpy as np
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jarvis.agent.tool_agent import tool_agent_from_settings
from jarvis.config import load_settings
from jarvis.intents.good_morning import run_morning_briefing
from jarvis.memory.store import MemoryStore
from jarvis.voice.stt import STT, STTConfig
from jarvis.voice.tts import TTS, TTSConfig

_logger = logging.getLogger(__name__)


class ChatStreamRequest(BaseModel):
    message: str = Field(default="")
    session_id: Optional[str] = None
    tts: bool = False
    tts_enabled: Optional[bool] = None

    @property
    def wants_tts(self) -> bool:
        return bool(self.tts if self.tts_enabled is None else self.tts_enabled)


@dataclass
class SessionEntry:
    agent: Any
    session_id: str
    updated_at: float


class SessionStore:
    """Store en memoria para agentes por session_id."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = max(60, int(ttl_seconds))
        self._items: Dict[str, SessionEntry] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, requested_id: Optional[str], factory) -> Tuple[str, Any]:
        async with self._lock:
            self._cleanup_locked()
            if requested_id and requested_id in self._items:
                entry = self._items[requested_id]
                entry.updated_at = time.time()
                return entry.session_id, entry.agent

            agent = factory()
            sid = str(getattr(getattr(agent, "config", None), "session_id", "") or "")
            if not sid:
                sid = str(uuid4())
                if hasattr(agent, "config"):
                    agent.config.session_id = sid

            self._items[sid] = SessionEntry(agent=agent, session_id=sid, updated_at=time.time())
            return sid, agent

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired = [sid for sid, entry in self._items.items() if now - entry.updated_at > self._ttl]
        for sid in expired:
            self._items.pop(sid, None)


_settings = None
_paths = None
_memory_store: Optional[MemoryStore] = None
_stt: Optional[STT] = None
_tts: Optional[TTS] = None
_session_store: Optional[SessionStore] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _settings, _paths, _memory_store, _session_store

    _settings, _paths = load_settings()
    _memory_store = MemoryStore(_paths.db_path)
    _session_store = SessionStore(ttl_seconds=3600)
    _logger.info("Web server initialized")
    try:
        yield
    finally:
        if _memory_store is not None:
            _memory_store.close()


STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Jarvis Web Interface", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _new_agent():
    return tool_agent_from_settings(_settings, memory_store=_memory_store, paths=_paths)


def _ensure_stt() -> STT:
    global _stt
    if _stt is None:
        _stt = STT(
            STTConfig(
                engine=_settings.stt_engine,
                groq_api_key=_settings.groq_api_key,
                groq_model=_settings.stt_groq_model,
                whisper_model=_settings.stt_whisper_model,
            )
        )
    return _stt


def _ensure_tts() -> Optional[TTS]:
    global _tts
    if _tts is None:
        try:
            _tts = TTS(
                TTSConfig(
                    engine=_settings.tts_engine,
                    kokoro_voice=_settings.kokoro_voice,
                    kokoro_speed=_settings.kokoro_speed,
                    kokoro_language=_settings.kokoro_language,
                )
            )
        except Exception as exc:
            _logger.warning("TTS initialization failed: %s", exc)
            _tts = None
    return _tts


def _sse_line(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")


def _extract_ready_sentences(buffer: str) -> Tuple[list[str], str]:
    parts = _SENTENCE_RE.split(buffer)
    if len(parts) <= 1:
        return [], buffer
    ready = [p.strip() for p in parts[:-1] if p.strip()]
    remainder = parts[-1]
    return ready, remainder


def _synthesize_tts_chunk_b64(text: str) -> Optional[Dict[str, str]]:
    text = (text or "").strip()
    if not text:
        return None

    tts = _ensure_tts()
    if tts is None:
        return None

    try:
        # Kokoro: sintetizar directamente en memoria y codificar WAV base64.
        if getattr(tts.cfg, "engine", "") == "kokoro" and getattr(tts, "_kokoro", None) is not None:
            samples, sample_rate = tts._kokoro.create(  # type: ignore[attr-defined]
                text,
                voice=tts.cfg.kokoro_voice,
                speed=tts.cfg.kokoro_speed,
                lang=tts.cfg.kokoro_language,
            )
            arr = np.asarray(samples)
            if arr.dtype != np.int16:
                arr = np.clip(arr, -1.0, 1.0)
                arr = (arr * 32767.0).astype(np.int16)
            if arr.ndim == 1:
                arr = arr.reshape(-1, 1)

            buff = io.BytesIO()
            with wave.open(buff, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(int(sample_rate))
                wf.writeframes(arr.tobytes())
            b64 = base64.b64encode(buff.getvalue()).decode("utf-8")
            return {"audio_b64": b64, "audio_mime": "audio/wav"}

        # Fallback macOS: generar AIFF sin reproducir, convertir a WAV.
        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp_aiff:
            aiff_path = Path(tmp_aiff.name)
        wav_path = aiff_path.with_suffix(".wav")
        try:
            say_cmd = ["say", "-o", str(aiff_path), text]
            subprocess.run(say_cmd, check=True, capture_output=True, timeout=20, text=True)
            conv_cmd = ["afconvert", "-f", "WAVE", "-d", "LEI16@22050", str(aiff_path), str(wav_path)]
            subprocess.run(conv_cmd, check=True, capture_output=True, timeout=20, text=True)
            data = wav_path.read_bytes()
            return {"audio_b64": base64.b64encode(data).decode("utf-8"), "audio_mime": "audio/wav"}
        finally:
            aiff_path.unlink(missing_ok=True)
            wav_path.unlink(missing_ok=True)
    except Exception as exc:
        _logger.debug("TTS chunk synthesis failed: %s", exc)
        return None


def _build_briefing() -> Dict[str, Any]:
    now = datetime.now()
    if 6 <= now.hour < 14:
        greeting = "Buenos días"
    elif 14 <= now.hour < 21:
        greeting = "Buenas tardes"
    else:
        greeting = "Buenas noches"

    payload: Dict[str, Any] = {
        "greeting": greeting,
        "time": now.strftime("%H:%M"),
    }
    try:
        result = run_morning_briefing()
        payload["morning_text"] = result.text
        payload["morning_blocks"] = result.blocks
    except Exception:
        pass
    return payload


def _run_web_search(agent: Any, query: str) -> Dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"query": "", "answer": "", "results": [], "sources": []}

    try:
        out = agent.registry.call("web_search", {"query": query, "limit": 6})
    except Exception as exc:
        _logger.debug("web_search call failed: %s", exc)
        out = {"ok": False, "results": []}

    raw_results = list(out.get("results", [])) if isinstance(out, dict) else []
    sources = []
    for item in raw_results:
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        sources.append({"title": title, "url": url, "snippet": snippet})

    return {
        "query": query,
        "answer": "",
        "results": sources,  # compat con frontend actual
        "sources": sources,
    }


async def _stream_agent_response(
    *,
    agent: Any,
    user_text: str,
    session_id: str,
    tts_enabled: bool,
    request_id: str,
    initial_search_payload: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[str, None]:
    full_text = ""
    sentence_buffer = ""

    try:
        if initial_search_payload:
            yield _sse_line({"search_results": initial_search_payload, "session_id": session_id})

        async for token in agent.run_stream(user_text):
            full_text += token
            sentence_buffer += token
            yield _sse_line({"chunk": token, "token": token, "session_id": session_id})

            if tts_enabled:
                ready_sentences, sentence_buffer = _extract_ready_sentences(sentence_buffer)
                for sentence in ready_sentences:
                    audio = await asyncio.to_thread(_synthesize_tts_chunk_b64, sentence)
                    if audio and audio.get("audio_b64"):
                        yield _sse_line(
                            {
                                "audio_b64": audio["audio_b64"],
                                "audio_mime": audio.get("audio_mime", "audio/wav"),
                                "audio": audio["audio_b64"],  # compat frontend legacy
                                "session_id": session_id,
                            }
                        )

        if tts_enabled and sentence_buffer.strip():
            audio = await asyncio.to_thread(_synthesize_tts_chunk_b64, sentence_buffer.strip())
            if audio and audio.get("audio_b64"):
                yield _sse_line(
                    {
                        "audio_b64": audio["audio_b64"],
                        "audio_mime": audio.get("audio_mime", "audio/wav"),
                        "audio": audio["audio_b64"],
                        "session_id": session_id,
                    }
                )

        done_payload: Dict[str, Any] = {
            "done": True,
            "session_id": session_id,
            "usage": {"chars": len(full_text)},
            "meta": {"request_id": request_id},
        }
        if initial_search_payload:
            done_payload["search_results"] = {
                **initial_search_payload,
                "answer": full_text.strip(),
                "results": initial_search_payload.get("results", []),
                "sources": initial_search_payload.get("sources", []),
            }
        yield _sse_line(done_payload)
    except Exception as exc:
        _logger.exception("SSE error request_id=%s session_id=%s", request_id, session_id)
        yield _sse_line({"error": str(exc), "session_id": session_id, "request_id": request_id})
        yield _sse_line({"done": True, "session_id": session_id, "meta": {"request_id": request_id}})


@app.get("/", response_class=HTMLResponse)
async def root():
    html_file = STATIC_DIR / "index.html"
    if not html_file.exists():
        return HTMLResponse(content="<h1>Interface no encontrada</h1>", status_code=500)
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/chat/stream")
async def chat_stream(payload: ChatStreamRequest):
    request_id = str(uuid4())
    message = payload.message.strip()
    if not message:
        return JSONResponse({"detail": "Mensaje vacío"}, status_code=400)

    session_id, agent = await _session_store.get_or_create(payload.session_id, _new_agent)  # type: ignore[union-attr]
    _logger.info("chat_stream request_id=%s session_id=%s", request_id, session_id)

    stream = _stream_agent_response(
        agent=agent,
        user_text=message,
        session_id=session_id,
        tts_enabled=payload.wants_tts,
        request_id=request_id,
        initial_search_payload=None,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/chat/realtime/stream")
async def chat_realtime_stream(payload: ChatStreamRequest):
    request_id = str(uuid4())
    message = payload.message.strip()
    if not message:
        return JSONResponse({"detail": "Mensaje vacío"}, status_code=400)

    session_id, agent = await _session_store.get_or_create(payload.session_id, _new_agent)  # type: ignore[union-attr]
    _logger.info("chat_realtime_stream request_id=%s session_id=%s", request_id, session_id)

    search_payload = await asyncio.to_thread(_run_web_search, agent, message)
    if search_payload.get("results"):
        context_lines = []
        for idx, item in enumerate(search_payload["results"], start=1):
            context_lines.append(
                f"[{idx}] {item.get('title', '')}\nURL: {item.get('url', '')}\nSnippet: {item.get('snippet', '')}"
            )
        context_block = "\n\n".join(context_lines)
        enhanced_prompt = (
            f"{message}\n\n"
            "Contexto de búsqueda web (úsalo para responder y citar fuentes):\n"
            f"{context_block}\n\n"
            "Responde en español de forma breve y útil."
        )
    else:
        enhanced_prompt = message

    stream = _stream_agent_response(
        agent=agent,
        user_text=enhanced_prompt,
        session_id=session_id,
        tts_enabled=payload.wants_tts,
        request_id=request_id,
        initial_search_payload=search_payload,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    try:
        stt = _ensure_stt()
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
                ["ffmpeg", "-i", str(webm_path), "-ar", "16000", "-ac", "1", "-f", "wav", "-y", str(wav_path)],
                capture_output=True,
                timeout=10,
                text=True,
            )
            if result.returncode != 0:
                webm_path.unlink(missing_ok=True)
                return JSONResponse({"ok": False, "error": "No se pudo convertir el audio."})

            text = await asyncio.to_thread(stt.transcribe_wav, wav_path)
            webm_path.unlink(missing_ok=True)
            wav_path.unlink(missing_ok=True)
            return JSONResponse({"ok": True, "text": text})
        except subprocess.TimeoutExpired:
            webm_path.unlink(missing_ok=True)
            return JSONResponse({"ok": False, "error": "Timeout convirtiendo audio"})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"Error: {exc}"}, status_code=500)


@app.post("/speak")
async def speak_text(request: dict):
    try:
        text = str(request.get("text", "")).strip()
        if not text:
            return JSONResponse({"ok": False, "error": "Texto vacío"})
        tts = _ensure_tts()
        if tts is None:
            return JSONResponse({"ok": False, "error": "TTS no disponible"})
        result = await asyncio.to_thread(tts.speak, text)
        return JSONResponse({"ok": True, "result": result})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"Error: {exc}"}, status_code=500)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        briefing = _build_briefing()
        await websocket.send_json({"type": "briefing", "data": briefing})
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            user_message = str(payload.get("message", "")).strip()
            if not user_message:
                await websocket.send_json({"type": "error", "content": "Mensaje vacío"})
                continue

            requested_sid = payload.get("session_id")
            sid, agent = await _session_store.get_or_create(requested_sid, _new_agent)  # type: ignore[union-attr]
            await websocket.send_json({"type": "session", "session_id": sid})
            await websocket.send_json({"type": "user_message", "content": user_message})

            try:
                async for chunk in agent.run_stream(user_message):
                    await websocket.send_json({"type": "token", "content": chunk, "session_id": sid})
                await websocket.send_json({"type": "done", "session_id": sid})
            except Exception as exc:
                await websocket.send_json({"type": "error", "content": f"Error: {exc}", "session_id": sid})
    except WebSocketDisconnect:
        _logger.info("WebSocket client disconnected")
    except Exception as exc:
        _logger.exception("WebSocket error: %s", exc)
