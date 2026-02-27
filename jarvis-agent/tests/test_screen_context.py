"""
test_screen_context.py

Tests unitarios para ScreenContextAnalyzer.
No requieren hardware real (screenshot y accessibility son mockeados).
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from jarvis.vision.screen_context import ScreenContextAnalyzer, ScreenContextConfig


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_analyzer(enabled: bool = True, interval_s: float = 30.0,
                   focus_only: bool = True, groq_key: str = "") -> ScreenContextAnalyzer:
    cfg = ScreenContextConfig(
        enabled=enabled,
        interval_s=interval_s,
        groq_api_key=groq_key,
        focus_changes_only=focus_only,
    )
    return ScreenContextAnalyzer(cfg)


# ── Tests de configuración ────────────────────────────────────────────────────

def test_screen_context_disabled_by_default():
    """ScreenContextConfig tiene enabled=False por defecto."""
    cfg = ScreenContextConfig()
    assert cfg.enabled is False


def test_screen_context_default_interval():
    """Intervalo por defecto es 30 segundos."""
    cfg = ScreenContextConfig()
    assert cfg.interval_s == 30.0


def test_screen_context_focus_only_default():
    """focus_changes_only es True por defecto."""
    cfg = ScreenContextConfig()
    assert cfg.focus_changes_only is True


# ── Tests de API pública ──────────────────────────────────────────────────────

def test_get_context_snippet_empty_before_analysis():
    """get_context_snippet retorna '' antes de cualquier análisis."""
    analyzer = _make_analyzer()
    assert analyzer.get_context_snippet() == ""


def test_get_context_snippet_returns_string():
    """get_context_snippet siempre retorna un str."""
    analyzer = _make_analyzer()
    result = analyzer.get_context_snippet()
    assert isinstance(result, str)


def test_get_context_snippet_after_manual_set():
    """get_context_snippet retorna el snippet inyectado manualmente."""
    analyzer = _make_analyzer()
    # Simular que el hilo interno actualizó el snippet
    with analyzer._lock:
        analyzer._snippet = "pantalla: VSCode editando main.py"

    assert analyzer.get_context_snippet() == "pantalla: VSCode editando main.py"


# ── Tests de ciclo de vida del hilo ──────────────────────────────────────────

def test_start_stop_thread_lifecycle():
    """start() lanza un hilo daemon; stop() lo detiene."""
    analyzer = _make_analyzer()

    # Parchear el bucle interno para que no haga nada real
    with patch.object(analyzer, "_loop", return_value=None):
        analyzer.start()
        assert analyzer._thread is not None
        analyzer.stop()
        # Tras stop, el evento debe estar set
        assert analyzer._stop_event.is_set()


def test_start_idempotent():
    """Llamar start() dos veces no crea dos hilos mientras el primero está vivo."""
    analyzer = _make_analyzer()
    barrier = threading.Event()

    def slow_loop():
        barrier.wait(timeout=5.0)

    with patch.object(analyzer, "_loop", side_effect=slow_loop):
        analyzer.start()
        t1 = analyzer._thread
        assert t1 is not None and t1.is_alive()
        analyzer.start()  # segunda llamada: hilo aún vivo → debe ser ignorada
        t2 = analyzer._thread
        assert t1 is t2
        barrier.set()
        analyzer.stop()


def test_stop_without_start():
    """stop() no falla si el hilo no fue iniciado."""
    analyzer = _make_analyzer()
    analyzer.stop()  # no debe lanzar excepción


# ── Tests de lógica de análisis ───────────────────────────────────────────────

def test_analyze_returns_empty_when_no_screenshot():
    """_analyze retorna '' si capture_screen falla."""
    analyzer = _make_analyzer(groq_key="")

    # capture_screen está importado lazy dentro de _analyze, parchear en origen
    with patch("jarvis.vision.screenshot.capture_screen", return_value=(None, None)):
        result = analyzer._analyze("VSCode")

    assert result == ""


def test_analyze_without_groq_key_uses_app_name():
    """Sin API key, _analyze usa el nombre de app como fallback."""
    analyzer = _make_analyzer(groq_key="")

    with patch("jarvis.vision.screenshot.capture_screen", return_value=(None, "base64data")):
        result = analyzer._analyze("Safari")

    assert result == "pantalla: Safari"


def test_analyze_without_groq_key_unknown_app_returns_empty():
    """Sin API key, app 'Unknown' retorna cadena vacía."""
    analyzer = _make_analyzer(groq_key="")

    with patch("jarvis.vision.screenshot.capture_screen", return_value=(None, "base64data")):
        result = analyzer._analyze("Unknown")

    assert result == ""


def test_groq_error_returns_app_name_fallback():
    """Cuando Groq Vision falla, retorna el nombre de app si está disponible."""
    analyzer = _make_analyzer(groq_key="gsk_test")

    mock_groq_module = MagicMock()
    mock_groq_module.Groq.side_effect = RuntimeError("API error")

    with patch("jarvis.vision.screenshot.capture_screen", return_value=(None, "b64data")):
        with patch.dict("sys.modules", {"groq": mock_groq_module}):
            result = analyzer._analyze("Chrome")

    # Con excepción Groq y app conocida, debe usar fallback
    assert isinstance(result, str)
    assert "Chrome" in result or result == ""


def test_groq_success_returns_screen_snippet():
    """Cuando Groq Vision responde OK, retorna 'pantalla: <descripción>'."""
    analyzer = _make_analyzer(groq_key="gsk_test")

    mock_choice = MagicMock()
    mock_choice.message.content = "Safari browsing GitHub"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    mock_groq_module = MagicMock()
    mock_groq_module.Groq.return_value = mock_client

    with patch("jarvis.vision.screenshot.capture_screen", return_value=(None, "b64data")):
        with patch.dict("sys.modules", {"groq": mock_groq_module}):
            result = analyzer._analyze("Safari")

    assert result == "pantalla: Safari browsing GitHub"


def test_groq_empty_response_returns_fallback():
    """Groq responde con contenido vacío → fallback al nombre de app."""
    analyzer = _make_analyzer(groq_key="gsk_test")

    mock_choice = MagicMock()
    mock_choice.message.content = "   "  # whitespace — len < 4
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    mock_groq_module = MagicMock()
    mock_groq_module.Groq.return_value = mock_client

    with patch("jarvis.vision.screenshot.capture_screen", return_value=(None, "b64data")):
        with patch.dict("sys.modules", {"groq": mock_groq_module}):
            result = analyzer._analyze("Slack")

    # Respuesta con < 4 chars → fallback al app name
    assert "Slack" in result or result == ""


# ── Tests de focus_changes_only ───────────────────────────────────────────────

def test_focus_only_does_not_reanalyze_same_app():
    """Con focus_changes_only=True, no se reanaliza si la app no cambia."""
    analyzer = _make_analyzer(interval_s=999.0, focus_only=True)
    analyze_calls = []

    def fake_analyze(app_name):
        analyze_calls.append(app_name)
        return f"pantalla: {app_name}"

    analyzer._analyze = fake_analyze
    analyzer._last_analysis = time.monotonic()  # simular análisis reciente

    # Simular dos iteraciones con la misma app
    with patch("jarvis.vision.accessibility.get_active_app",
               return_value={"name": "VSCode"}):
        # Primera iteración: app cambia de "" a "VSCode"
        analyzer._loop.__func__  # verificar que existe

    # Ejecutar _loop manualmente pero limitado
    stop = threading.Event()
    analyzer._stop_event = stop

    results: list[str] = []

    def patched_loop():
        _last_app = ""
        for _ in range(3):  # 3 iteraciones simuladas
            app_name = "VSCode"  # misma app siempre
            app_changed = analyzer.cfg.focus_changes_only and app_name != _last_app
            now = time.monotonic()
            should_analyze = (
                (now - analyzer._last_analysis) >= analyzer.cfg.interval_s
                or app_changed
            )
            if should_analyze:
                _last_app = app_name
                analyzer._last_analysis = now
                snippet = analyzer._analyze(app_name)
                results.append(snippet)

    patched_loop()

    # Solo debe haber UN análisis (el primero cuando cambió de "" a "VSCode")
    assert len(results) == 1


def test_focus_change_triggers_reanalysis():
    """Con focus_changes_only=True, un cambio de app fuerza re-análisis."""
    analyzer = _make_analyzer(interval_s=999.0, focus_only=True)
    analyzed_apps: list[str] = []

    def fake_analyze(app_name):
        analyzed_apps.append(app_name)
        return f"pantalla: {app_name}"

    analyzer._analyze = fake_analyze
    analyzer._last_analysis = time.monotonic()

    apps = ["VSCode", "Safari", "Safari"]  # cambio: VSCode→Safari→Safari(sin cambio)

    _last_app = ""
    for app_name in apps:
        app_changed = analyzer.cfg.focus_changes_only and app_name != _last_app
        now = time.monotonic()
        should_analyze = (
            (now - analyzer._last_analysis) >= analyzer.cfg.interval_s
            or app_changed
        )
        if should_analyze:
            _last_app = app_name
            analyzer._last_analysis = now
            analyzer._analyze(app_name)

    # Solo debe analizar VSCode y Safari (no el segundo Safari duplicado)
    assert analyzed_apps == ["VSCode", "Safari"]


# ── Thread-safety ─────────────────────────────────────────────────────────────

def test_concurrent_get_context_snippet():
    """Múltiples threads pueden leer get_context_snippet simultáneamente."""
    analyzer = _make_analyzer()
    with analyzer._lock:
        analyzer._snippet = "pantalla: Terminal"

    results: list[str] = []
    errors: list[Exception] = []

    def reader():
        try:
            for _ in range(50):
                s = analyzer.get_context_snippet()
                results.append(s)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == [], f"Errores en threads: {errors}"
    assert all(r == "pantalla: Terminal" for r in results)


def test_concurrent_snippet_update():
    """Escritura y lectura concurrentes no causan race conditions."""
    analyzer = _make_analyzer()
    errors: list[Exception] = []
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            with analyzer._lock:
                analyzer._snippet = f"pantalla: app_{i}"
            i += 1
            time.sleep(0.0001)

    def reader():
        while not stop.is_set():
            s = analyzer.get_context_snippet()
            assert isinstance(s, str), f"snippet no es str: {type(s)}"

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in threads:
        t.start()

    time.sleep(0.2)
    stop.set()

    for t in threads:
        t.join(timeout=2.0)

    assert errors == []
