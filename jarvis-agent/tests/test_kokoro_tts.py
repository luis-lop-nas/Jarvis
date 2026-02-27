"""
tests/test_kokoro_tts.py

Tests unitarios para el engine Kokoro TTS.
kokoro-onnx se mockea — no se requiere GPU ni el modelo descargado.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from jarvis.voice.tts import (
    TTS,
    TTSConfig,
    _KokoroEngine,
    _split_long_text,
)


# ─────────────────────────────────────────────────────────────────────────────
# _split_long_text
# ─────────────────────────────────────────────────────────────────────────────


class TestSplitLongText:
    def test_short_text_unchanged(self):
        text = "Hola mundo."
        result = _split_long_text(text, max_chars=500)
        assert result == [text]

    def test_long_text_split_at_sentence_boundary(self):
        # Crea texto > 500 chars con frases claramente separadas
        sentence = "Esta es una frase de prueba suficientemente larga. "
        text = sentence * 12  # ~600 chars
        parts = _split_long_text(text, max_chars=500)
        assert len(parts) >= 2
        for part in parts:
            assert len(part) <= 500 + len(sentence)  # no se corta a mitad de frase

    def test_empty_text_returns_list_with_empty(self):
        result = _split_long_text("", max_chars=500)
        assert result == [""]

    def test_text_exactly_at_limit_not_split(self):
        text = "a" * 500
        result = _split_long_text(text, max_chars=500)
        assert result == [text]

    def test_text_one_over_limit_split(self):
        # Texto de 501 chars con separador de frase en el centro
        text = "Primera oración corta. " + "b" * 480
        result = _split_long_text(text, max_chars=500)
        assert len(result) >= 2

    def test_spanish_accents_preserved(self):
        text = "¡Hola! ¿Cómo estás? Bien, gracias. "
        result = _split_long_text(text, max_chars=500)
        combined = " ".join(result)
        assert "Cómo" in combined
        assert "estás" in combined


# ─────────────────────────────────────────────────────────────────────────────
# _KokoroEngine — carga y descarga
# ─────────────────────────────────────────────────────────────────────────────


class TestKokoroEngineLoad:
    def test_import_error_returns_false(self):
        """Si kokoro-onnx no está instalado, load() retorna False."""
        engine = _KokoroEngine()
        with patch.dict("sys.modules", {"kokoro_onnx": None}):
            result = engine.load("ef_dora", 1.0, "es")
        assert result is False
        assert engine.loaded is False

    def test_successful_load(self, tmp_path):
        """Carga exitosa con modelo fake en tmp_path."""
        # Crear ficheros de modelo falsos
        (tmp_path / "kokoro-v1.0.onnx").write_bytes(b"\x00" * 8)
        (tmp_path / "voices-v1.0.bin").write_bytes(b"\x00" * 8)

        mock_kokoro_class = MagicMock()
        mock_instance = MagicMock()
        mock_kokoro_class.return_value = mock_instance
        mock_instance.create.return_value = (np.zeros(1000, dtype=np.float32), 22050)

        mock_kokoro_mod = MagicMock()
        mock_kokoro_mod.Kokoro = mock_kokoro_class

        with patch.dict("sys.modules", {"kokoro_onnx": mock_kokoro_mod}):
            engine = _KokoroEngine(model_dir=tmp_path)
            result = engine.load("ef_dora", 1.0, "es")

        assert result is True
        assert engine.loaded is True

    def test_download_called_when_files_missing(self, tmp_path):
        """Si los ficheros no existen, se llama a _download()."""
        mock_kokoro_mod = MagicMock()
        mock_kokoro_mod.Kokoro.return_value = MagicMock(
            create=MagicMock(return_value=(np.zeros(100, dtype=np.float32), 22050))
        )

        with patch.dict("sys.modules", {"kokoro_onnx": mock_kokoro_mod}):
            engine = _KokoroEngine(model_dir=tmp_path)
            with patch.object(engine, "_download", return_value=True) as mock_dl:
                # Crear ficheros DESPUÉS del mock de _download para simular que
                # _download "descargó" los ficheros
                def _fake_download():
                    (tmp_path / "kokoro-v1.0.onnx").write_bytes(b"\x00" * 4)
                    (tmp_path / "voices-v1.0.bin").write_bytes(b"\x00" * 4)
                    return True
                mock_dl.side_effect = _fake_download
                engine.load("ef_dora", 1.0, "es")
            mock_dl.assert_called_once()

    def test_download_skipped_when_files_exist(self, tmp_path):
        """Si los ficheros ya existen, no se descarga."""
        (tmp_path / "kokoro-v1.0.onnx").write_bytes(b"\x00" * 8)
        (tmp_path / "voices-v1.0.bin").write_bytes(b"\x00" * 8)

        mock_kokoro_mod = MagicMock()
        mock_kokoro_mod.Kokoro.return_value = MagicMock(
            create=MagicMock(return_value=(np.zeros(100, dtype=np.float32), 22050))
        )

        with patch.dict("sys.modules", {"kokoro_onnx": mock_kokoro_mod}):
            engine = _KokoroEngine(model_dir=tmp_path)
            with patch.object(engine, "_download") as mock_dl:
                engine.load("ef_dora", 1.0, "es")
            mock_dl.assert_not_called()

    def test_download_failure_returns_false(self, tmp_path):
        """Si la descarga falla, load() retorna False."""
        mock_kokoro_mod = MagicMock()
        mock_kokoro_mod.Kokoro = MagicMock()

        with patch.dict("sys.modules", {"kokoro_onnx": mock_kokoro_mod}):
            engine = _KokoroEngine(model_dir=tmp_path)
            with patch.object(engine, "_download", return_value=False):
                result = engine.load("ef_dora", 1.0, "es")
        assert result is False

    def test_create_raises_if_not_loaded(self):
        """create() lanza RuntimeError si el modelo no está cargado."""
        engine = _KokoroEngine()
        with pytest.raises(RuntimeError, match="no está cargado"):
            engine.create("hola", "ef_dora", 1.0, "es")


# ─────────────────────────────────────────────────────────────────────────────
# _KokoroEngine — descarga HTTP (mockeada)
# ─────────────────────────────────────────────────────────────────────────────


class TestKokoroDownload:
    def test_download_creates_files(self, tmp_path):
        fake_data = b"\xff" * 100
        mock_response = MagicMock()
        mock_response.headers = {"content-length": str(len(fake_data))}
        mock_response.iter_content.return_value = [fake_data]
        mock_response.raise_for_status = MagicMock()

        engine = _KokoroEngine(model_dir=tmp_path)
        with (
            patch("requests.get", return_value=mock_response),
            patch.object(engine, "_MIN_SIZES", {"kokoro-v1.0.onnx": 1, "voices-v1.0.bin": 1}),
        ):
            result = engine._download()

        assert result is True
        assert (tmp_path / "kokoro-v1.0.onnx").exists()
        assert (tmp_path / "voices-v1.0.bin").exists()

    def test_download_skips_existing_files(self, tmp_path):
        (tmp_path / "kokoro-v1.0.onnx").write_bytes(b"\x00")
        (tmp_path / "voices-v1.0.bin").write_bytes(b"\x00")

        engine = _KokoroEngine(model_dir=tmp_path)
        with patch("requests.get") as mock_get:
            result = engine._download()

        mock_get.assert_not_called()
        assert result is True

    def test_download_http_error_returns_false(self, tmp_path):
        import requests

        engine = _KokoroEngine(model_dir=tmp_path)
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            result = engine._download()

        assert result is False

    def test_download_cleans_partial_file_on_error(self, tmp_path):
        """Si la descarga falla, el fichero parcial se elimina."""
        import requests

        engine = _KokoroEngine(model_dir=tmp_path)

        call_count = [0]
        def _get_side_effect(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Primera descarga (onnx) — éxito
                resp = MagicMock()
                resp.headers = {"content-length": "4"}
                resp.iter_content.return_value = [b"\x00\x00\x00\x00"]
                resp.raise_for_status = MagicMock()
                return resp
            # Segunda descarga (voices.bin) — fallo
            raise requests.RequestException("red caída")

        with (
            patch("requests.get", side_effect=_get_side_effect),
            patch.object(engine, "_MIN_SIZES", {"kokoro-v1.0.onnx": 1, "voices-v1.0.bin": 1}),
        ):
            result = engine._download()

        assert result is False
        # El fichero de voces parcial debe haber sido eliminado
        assert not (tmp_path / "voices-v1.0.bin").exists()


# ─────────────────────────────────────────────────────────────────────────────
# TTS con engine="kokoro" (integración)
# ─────────────────────────────────────────────────────────────────────────────


def _make_kokoro_cfg(**kwargs) -> TTSConfig:
    defaults = dict(
        engine="kokoro",
        kokoro_voice="ef_dora",
        kokoro_speed=1.0,
        kokoro_language="es",
    )
    defaults.update(kwargs)
    return TTSConfig(**defaults)


def _make_mock_engine(samples=None, sr=22050) -> _KokoroEngine:
    """Crea un _KokoroEngine ya cargado con síntesis mockeada."""
    if samples is None:
        samples = np.zeros(22050, dtype=np.float32)  # 1 segundo de silencio
    engine = _KokoroEngine()
    engine.loaded = True
    engine._kokoro = MagicMock()
    engine._kokoro.create.return_value = (samples, sr)
    return engine


class TestTTSKokoro:
    def _make_tts(self, **kwargs) -> TTS:
        cfg = _make_kokoro_cfg(**kwargs)
        tts = TTS.__new__(TTS)
        tts.cfg = cfg
        tts._current_proc = None
        tts._speech_thread = None
        tts._stop_event = threading.Event()
        tts._kokoro = _make_mock_engine()
        return tts

    def test_speak_calls_kokoro_create(self):
        tts = self._make_tts()
        with patch("sounddevice.play"), patch("sounddevice.wait"):
            result = tts.speak("Hola mundo.")
        tts._kokoro._kokoro.create.assert_called_once()
        assert result["command"] == "kokoro"
        assert result["returncode"] == 0

    def test_speak_passes_voice_speed_lang(self):
        tts = self._make_tts(
            kokoro_voice="em_alex", kokoro_speed=1.2, kokoro_language="en-us"
        )
        with patch("sounddevice.play"), patch("sounddevice.wait"):
            tts.speak("Hello world.")
        call_kwargs = tts._kokoro._kokoro.create.call_args
        assert call_kwargs.kwargs["voice"] == "em_alex"
        assert call_kwargs.kwargs["speed"] == 1.2
        assert call_kwargs.kwargs["lang"] == "en-us"

    def test_speak_empty_text_returns_without_synthesis(self):
        tts = self._make_tts()
        result = tts.speak("")
        tts._kokoro._kokoro.create.assert_not_called()
        assert result["returncode"] == 0

    def test_speak_stops_when_stop_event_set(self):
        tts = self._make_tts()
        tts._stop_event.set()
        with patch("sounddevice.play") as mock_play, patch("sounddevice.wait"):
            tts.speak("Nunca se reproducirá.")
        mock_play.assert_not_called()

    def test_speak_fallback_macos_on_synthesis_error(self):
        tts = self._make_tts()
        tts._kokoro._kokoro.create.side_effect = RuntimeError("error de síntesis")
        with patch.object(tts, "_speak_macos", return_value={"command": "say"}) as mock_say:
            tts.speak("Fallo.")
        mock_say.assert_called_once()

    def test_speak_splits_long_text(self):
        """Textos > 500 chars se dividen en varios segmentos."""
        tts = self._make_tts()
        long_text = ("Esta es una frase suficientemente larga para forzar la división. " * 10)
        assert len(long_text) > 500
        with patch("sounddevice.play"), patch("sounddevice.wait"):
            tts.speak(long_text)
        # Se debe haber llamado a create más de una vez
        assert tts._kokoro._kokoro.create.call_count >= 2

    def test_speak_spanish_accents(self):
        """Tildes y caracteres especiales del español no crashean."""
        tts = self._make_tts()
        with patch("sounddevice.play"), patch("sounddevice.wait"):
            tts.speak("¡Hola! ¿Cómo estás? Estoy mucho más que bien, ¡gracias!")
        assert tts._kokoro._kokoro.create.called

    def test_speak_english_voice(self):
        """Voz inglesa am_michael con lang en-us."""
        tts = self._make_tts(kokoro_voice="am_michael", kokoro_language="en-us")
        with patch("sounddevice.play"), patch("sounddevice.wait"):
            tts.speak("Hello, how are you doing today?")
        call_kwargs = tts._kokoro._kokoro.create.call_args.kwargs
        assert call_kwargs["voice"] == "am_michael"
        assert call_kwargs["lang"] == "en-us"

    def test_stop_calls_sd_stop(self):
        """stop() llama sd.stop() para cortar reproducción sounddevice."""
        tts = self._make_tts()
        with patch("sounddevice.stop") as mock_sd_stop:
            tts.stop()
        mock_sd_stop.assert_called_once()

    def test_is_speaking_false_when_idle(self):
        tts = self._make_tts()
        assert tts.is_speaking is False

    def test_is_speaking_true_while_speaking(self):
        tts = self._make_tts()
        ev = threading.Event()

        def _slow_play(samples, sr):
            ev.wait(timeout=3.0)

        with patch("sounddevice.play", side_effect=_slow_play), patch("sounddevice.wait"):
            tts.speak_nonblocking("Texto largo que tarda.")
            time.sleep(0.05)
            assert tts.is_speaking is True
            ev.set()
            tts.wait()

    def test_speak_nonblocking_returns_immediately(self):
        tts = self._make_tts()
        ev = threading.Event()

        def _slow_play(samples, sr):
            ev.wait(timeout=3.0)

        t0 = time.time()
        with patch("sounddevice.play", side_effect=_slow_play), patch("sounddevice.wait"):
            tts.speak_nonblocking("Texto.")
            elapsed = time.time() - t0
        assert elapsed < 0.5
        ev.set()
        tts.wait()


# ─────────────────────────────────────────────────────────────────────────────
# TTS — fallback cuando Kokoro no está disponible
# ─────────────────────────────────────────────────────────────────────────────


class TestTTSKokoroFallback:
    def test_falls_back_to_macos_when_kokoro_import_fails(self):
        """Si kokoro-onnx no está instalado, el engine cae a macos."""
        cfg = TTSConfig(engine="kokoro")
        with patch.dict("sys.modules", {"kokoro_onnx": None}):
            tts = TTS(cfg)
        assert tts.cfg.engine == "macos"
        assert tts._kokoro is None

    def test_falls_back_to_macos_when_download_fails(self, tmp_path):
        """Si la descarga del modelo falla, el engine cae a macos."""
        import requests

        cfg = TTSConfig(engine="kokoro", kokoro_model_dir=str(tmp_path))
        mock_kokoro_mod = MagicMock()
        with patch.dict("sys.modules", {"kokoro_onnx": mock_kokoro_mod}):
            with patch("requests.get", side_effect=requests.RequestException("red caída")):
                tts = TTS(cfg)
        assert tts.cfg.engine == "macos"
        assert tts._kokoro is None


# ─────────────────────────────────────────────────────────────────────────────
# TTSConfig defaults
# ─────────────────────────────────────────────────────────────────────────────


class TestTTSConfigDefaults:
    def test_default_engine_is_kokoro(self):
        cfg = TTSConfig()
        assert cfg.engine == "kokoro"

    def test_default_kokoro_voice_is_ef_dora(self):
        cfg = TTSConfig()
        assert cfg.kokoro_voice == "ef_dora"

    def test_default_speed_is_one(self):
        cfg = TTSConfig()
        assert cfg.kokoro_speed == 1.0

    def test_default_language_is_es(self):
        cfg = TTSConfig()
        assert cfg.kokoro_language == "es"

    def test_custom_voice_assignment(self):
        cfg = TTSConfig(kokoro_voice="am_michael", kokoro_language="en-us")
        assert cfg.kokoro_voice == "am_michael"
        assert cfg.kokoro_language == "en-us"
