"""
screen_context.py

Hilo daemon que:
1. Captura pantalla periódicamente (reutiliza screenshot.py)
2. Obtiene la app activa (accessibility.py) para detectar cambios de foco
3. Analiza el contenido con Groq Vision (llama-3.2-11b-vision-preview)
4. Expone get_context_snippet() thread-safe para inyectar al LLM

Activar con SCREEN_CONTEXT=true en .env (desactivado por defecto).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class ScreenContextConfig:
    enabled: bool = False
    interval_s: float = 30.0          # segundos entre capturas completas
    groq_api_key: str = ""
    focus_changes_only: bool = True   # re-analizar solo cuando cambia la app activa


class ScreenContextAnalyzer:
    """
    Analiza periódicamente la pantalla para generar una descripción concisa
    que se inyecta en el contexto del LLM.

    Expone estado thread-safe:
      - get_context_snippet() → str: "pantalla: editor VSCode editando daemon.py"

    Uso:
        cfg = ScreenContextConfig(enabled=True, groq_api_key="gsk_...")
        analyzer = ScreenContextAnalyzer(cfg)
        analyzer.start()
        # ... en _get_context() del daemon:
        snippet = analyzer.get_context_snippet()
        analyzer.stop()
    """

    def __init__(self, cfg: ScreenContextConfig) -> None:
        self.cfg = cfg
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self._snippet: str = ""
        self._last_analysis: float = 0.0

    # ── API pública ──────────────────────────────────────────────────────────

    def get_context_snippet(self) -> str:
        """
        Retorna string listo para inyectar en el contexto LLM.
        Ejemplo: "pantalla: editor VSCode editando daemon.py"
        Retorna "" si no hay análisis disponible.
        """
        with self._lock:
            return self._snippet

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="screen-context",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "ScreenContextAnalyzer iniciado (intervalo %.1fs, focus_only=%s)",
            self.cfg.interval_s,
            self.cfg.focus_changes_only,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._thread = None

    # ── Hilo interno ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        _last_app: str = ""

        while not self._stop_event.is_set():
            try:
                # Obtener app activa para detectar cambios de foco
                try:
                    from jarvis.vision.accessibility import get_active_app
                    app = get_active_app()
                    app_name = (app.get("name") or "").strip()
                except Exception:
                    app_name = ""

                now = time.monotonic()
                app_changed = self.cfg.focus_changes_only and app_name != _last_app

                should_analyze = (
                    (now - self._last_analysis) >= self.cfg.interval_s
                    or app_changed
                )

                if should_analyze:
                    _last_app = app_name
                    self._last_analysis = now
                    snippet = self._analyze(app_name)
                    with self._lock:
                        self._snippet = snippet

            except Exception as e:
                log.debug("ScreenContextAnalyzer loop error: %s", e)

            self._stop_event.wait(timeout=2.0)

    def _analyze(self, app_name: str) -> str:
        """Captura pantalla y la analiza con Groq Vision. Retorna snippet de 1 línea."""
        try:
            from jarvis.vision.screenshot import capture_screen
            _, b64 = capture_screen()
            if not b64:
                return ""
        except Exception as e:
            log.debug("ScreenContextAnalyzer: error en captura de pantalla: %s", e)
            return ""

        if not self.cfg.groq_api_key:
            # Sin API key, retornar solo nombre de app si está disponible
            if app_name and app_name not in ("Unknown",):
                return f"pantalla: {app_name}"
            return ""

        try:
            from groq import Groq

            client = Groq(api_key=self.cfg.groq_api_key)
            resp = client.chat.completions.create(
                model="llama-3.2-11b-vision-preview",
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                "Describe what is on this screen in one short sentence. "
                                "Focus on the active application and main content "
                                "(e.g., 'VSCode editing a Python file', 'Safari browsing GitHub', "
                                "'Slack conversation open'). "
                                "Be concise. Reply only with the description, no preamble."
                            ),
                        },
                    ],
                }],
                max_tokens=60,
                temperature=0.1,
            )

            if not resp.choices or not resp.choices[0].message.content:
                return ""

            result = resp.choices[0].message.content.strip()
            if len(result) < 4:
                return ""

            return f"pantalla: {result}"

        except Exception as e:
            log.debug("ScreenContextAnalyzer: Groq Vision error: %s", e)
            # Fallback: usar nombre de app sin análisis de imagen
            if app_name and app_name not in ("Unknown",):
                return f"pantalla: {app_name}"
            return ""
