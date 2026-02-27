from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Optional

from fastapi.testclient import TestClient

import jarvis.web.server as web_server


def _read_sse_data_blocks(body: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payloads.append(json.loads(line[6:]))
    return payloads


class _FakeAgent:
    def __init__(self, tokens: list[str], *, session_id: str = "sess-1", search_results: Optional[list[dict[str, str]]] = None):
        self._tokens = tokens
        self.config = type("Cfg", (), {"session_id": session_id})()
        self.registry = type("Reg", (), {"call": lambda *_args, **_kwargs: {"ok": True, "results": search_results or []}})()

    async def run_stream(self, _text: str) -> AsyncGenerator[str, None]:
        for tok in self._tokens:
            yield tok


def test_health_returns_healthy():
    with TestClient(web_server.app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"


def test_root_serves_html():
    with TestClient(web_server.app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "<!DOCTYPE html>" in r.text


def test_chat_stream_emits_chunk_and_done():
    fake_agent = _FakeAgent(tokens=["Hola", " mundo"], session_id="sse-123")
    original_factory = web_server._new_agent
    try:
        with TestClient(web_server.app) as client:
            web_server._new_agent = lambda: fake_agent
            r = client.post("/chat/stream", json={"message": "hola", "session_id": None, "tts": False})
            assert r.status_code == 200
            events = _read_sse_data_blocks(r.text)
            assert any(ev.get("chunk") == "Hola" for ev in events)
            assert any(ev.get("done") is True and ev.get("session_id") == "sse-123" for ev in events)
    finally:
        web_server._new_agent = original_factory


def test_chat_realtime_stream_emits_search_results():
    fake_results = [
        {"title": "Result 1", "url": "https://example.com/1", "snippet": "Snippet 1"},
        {"title": "Result 2", "url": "https://example.com/2", "snippet": "Snippet 2"},
    ]
    fake_agent = _FakeAgent(tokens=["Respuesta realtime"], session_id="rt-123", search_results=fake_results)
    original_factory = web_server._new_agent
    try:
        with TestClient(web_server.app) as client:
            web_server._new_agent = lambda: fake_agent
            r = client.post("/chat/realtime/stream", json={"message": "qué pasa", "session_id": None, "tts": False})
            assert r.status_code == 200
            events = _read_sse_data_blocks(r.text)
            sr_events = [ev for ev in events if "search_results" in ev]
            assert sr_events, "Debe emitir al menos un bloque search_results"
            assert sr_events[0]["search_results"]["results"][0]["title"] == "Result 1"
            assert any(ev.get("done") is True and ev.get("session_id") == "rt-123" for ev in events)
    finally:
        web_server._new_agent = original_factory
