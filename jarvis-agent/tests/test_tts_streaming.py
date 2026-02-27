"""
tests/test_tts_streaming.py

Tests para el pipeline de streaming TTS:
- _emit_sentences: segmentación de frases
- TTS.speak_queued / speak_streaming: consumo de cola y reproducción
"""
from __future__ import annotations

import queue
import threading
import time
from typing import List, Optional
from unittest.mock import patch


from jarvis.agent.tool_agent import _emit_sentences
from jarvis.voice.tts import TTS, TTSConfig


# ─────────────────────────────────────────────────────────────────────────────
# _emit_sentences (helper de tool_agent)
# ─────────────────────────────────────────────────────────────────────────────


class TestEmitSentences:
    def test_no_separator_returns_buffer_unchanged(self):
        emitted: List[str] = []
        first = [False]
        remainder = _emit_sentences("Hola cómo", emitted.append, first)
        assert remainder == "Hola cómo"
        assert emitted == []

    def test_first_sentence_emitted_immediately(self):
        emitted: List[str] = []
        first = [False]
        remainder = _emit_sentences("Hola. Segunda", emitted.append, first)
        assert "Hola." in emitted[0]
        assert "Segunda" in remainder
        assert first[0] is True

    def test_subsequent_sentences_accumulated_to_min_chars(self):
        """Frases posteriores se acumulan hasta min_chars antes de emitir."""
        emitted: List[str] = []
        first = [True]  # ya se emitió la primera
        # 3 frases cortas (< 50 chars cada par), pero juntas suman más de 50
        buf = "Ok. Si. Claro. Siguiente parte larga que supera el mínimo. Fin"
        _emit_sentences(buf, emitted.append, first, min_chars=50)
        # Debería haberse emitido algo
        assert len(emitted) >= 1

    def test_empty_buffer_returns_empty(self):
        emitted: List[str] = []
        first = [False]
        remainder = _emit_sentences("", emitted.append, first)
        assert remainder == ""
        assert emitted == []

    def test_multiple_sentence_boundaries(self):
        emitted: List[str] = []
        first = [False]
        buf = "Primera frase. Segunda frase. "
        _emit_sentences(buf, emitted.append, first, min_chars=1)
        # Ambas frases deben haberse emitido o acumulado
        assert first[0] is True
        assert len(emitted) >= 1

    def test_exclamation_and_question_are_boundaries(self):
        emitted: List[str] = []
        first = [False]
        buf = "¿Cómo estás? Bien, gracias. "
        _emit_sentences(buf, emitted.append, first, min_chars=1)
        assert first[0] is True
        assert len(emitted) >= 1

    def test_remainder_contains_last_incomplete_sentence(self):
        emitted: List[str] = []
        first = [False]
        buf = "Primera frase. Segunda incompleta"
        remainder = _emit_sentences(buf, emitted.append, first, min_chars=1)
        assert "Segunda incompleta" in remainder


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_tts(engine: str = "macos") -> TTS:
    cfg = TTSConfig(engine=engine)
    return TTS(cfg)


def _fill_queue(q: "queue.Queue[Optional[str]]", sentences: List[Optional[str]]) -> None:
    """Llena la cola con las frases y el centinela None al final."""
    for s in sentences:
        q.put(s)


# ─────────────────────────────────────────────────────────────────────────────
# speak_queued — motor macOS (mocked)
# ─────────────────────────────────────────────────────────────────────────────


class TestSpeakQueuedMacos:
    def test_empty_queue_with_none_sentinel_returns_immediately(self):
        tts = _make_tts("macos")
        q: "queue.Queue[Optional[str]]" = queue.Queue()
        q.put(None)  # centinela inmediato
        # No debe colgar
        with patch.object(tts, "_speak_macos", return_value={}) as mock_speak:
            tts.speak_queued(q)
        mock_speak.assert_not_called()

    def test_speaks_sentences_in_order(self):
        tts = _make_tts("macos")
        q: "queue.Queue[Optional[str]]" = queue.Queue()
        spoken: List[str] = []
        _fill_queue(q, ["Primera.", "Segunda.", None])

        with patch.object(tts, "_speak_macos", side_effect=lambda t: spoken.append(t) or {}):
            tts.speak_queued(q)

        assert spoken == ["Primera.", "Segunda."]

    def test_interrupt_event_stops_playback(self):
        tts = _make_tts("macos")
        q: "queue.Queue[Optional[str]]" = queue.Queue()
        interrupt = threading.Event()
        # No ponemos nada en la cola; interrumpimos desde fuera
        interrupt.set()
        # speak_queued debe retornar rápidamente
        t0 = time.time()
        tts.speak_queued(q, interrupt_event=interrupt)
        elapsed = time.time() - t0
        assert elapsed < 1.0

    def test_on_first_audio_called_before_first_sentence(self):
        tts = _make_tts("macos")
        q: "queue.Queue[Optional[str]]" = queue.Queue()
        _fill_queue(q, ["Hola.", None])
        called: List[bool] = []
        with patch.object(tts, "_speak_macos", return_value={}):
            tts.speak_queued(q, on_first_audio=lambda: called.append(True))
        assert called == [True]

    def test_on_first_audio_called_only_once(self):
        tts = _make_tts("macos")
        q: "queue.Queue[Optional[str]]" = queue.Queue()
        _fill_queue(q, ["A.", "B.", None])
        calls: List[int] = [0]
        def _cb():
            calls[0] += 1
        with patch.object(tts, "_speak_macos", return_value={}):
            tts.speak_queued(q, on_first_audio=_cb)
        assert calls[0] == 1

    def test_blank_sentences_skipped(self):
        tts = _make_tts("macos")
        q: "queue.Queue[Optional[str]]" = queue.Queue()
        spoken: List[str] = []
        _fill_queue(q, ["", "  ", "Hola.", None])
        with patch.object(tts, "_speak_macos", side_effect=lambda t: spoken.append(t) or {}):
            tts.speak_queued(q)
        assert spoken == ["Hola."]


# ─────────────────────────────────────────────────────────────────────────────
# speak_streaming — no-bloqueante
# ─────────────────────────────────────────────────────────────────────────────


class TestSpeakStreaming:
    def test_returns_immediately(self):
        tts = _make_tts("macos")
        q: "queue.Queue[Optional[str]]" = queue.Queue()
        q.put(None)
        t0 = time.time()
        tts.speak_streaming(q)
        elapsed = time.time() - t0
        assert elapsed < 0.5  # retorna sin bloquear
        tts.wait()

    def test_is_speaking_true_while_active(self):
        tts = _make_tts("macos")
        q: "queue.Queue[Optional[str]]" = queue.Queue()
        ev = threading.Event()

        def _slow_speak(text: str) -> dict:
            ev.wait(timeout=2.0)
            return {}

        with patch.object(tts, "_speak_macos", side_effect=_slow_speak):
            q.put("Hola.")
            q.put(None)
            tts.speak_streaming(q)
            time.sleep(0.05)
            assert tts.is_speaking is True
            ev.set()
            tts.wait()

    def test_stop_interrupts_streaming(self):
        tts = _make_tts("macos")
        q: "queue.Queue[Optional[str]]" = queue.Queue()
        ev = threading.Event()

        def _slow_speak(text: str) -> dict:
            ev.wait(timeout=2.0)
            return {}

        with patch.object(tts, "_speak_macos", side_effect=_slow_speak):
            q.put("Texto largo...")
            q.put(None)
            tts.speak_streaming(q)
            time.sleep(0.05)
            tts.stop()
            ev.set()
            # Tras stop, is_speaking debe resolverse rápido
            tts.wait()
            assert not tts.is_speaking

    def test_latency_callback_fires(self):
        tts = _make_tts("macos")
        q: "queue.Queue[Optional[str]]" = queue.Queue()
        _fill_queue(q, ["Hola.", None])
        fired: List[bool] = []
        with patch.object(tts, "_speak_macos", return_value={}):
            tts.speak_streaming(q, on_first_audio=lambda: fired.append(True))
            tts.wait()
        assert fired == [True]
