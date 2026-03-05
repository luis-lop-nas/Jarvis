"""
daemon.py

Proceso daemon que conecta voz + LLM + tools con el overlay visual.

Corre COMPLETAMENTE en threads secundarios.
El hilo principal está ocupado con NSApplication (el overlay).

Ciclo:
  1. Espera wake word ("Jarvis") o hotkey (Ctrl+Space) — siempre activo
  2. Si Jarvis estaba hablando → interrumpe inmediatamente
  3. orb → "listening" → graba audio con VAD + VU meter en tiempo real
  4. Transcribe con STT
  5. orb → "thinking" → envía al LLM con contexto automático (app, clipboard, hora)
  6. LLM responde (puede usar tools con animación fly_to)
  7. orb → "acting" → TTS habla la respuesta frase a frase
  8. HUD muestra el texto completo de la respuesta
  9. Cada frase se puede interrumpir con nueva invocación
 10. orb → "idle", HUD desaparece tras 3.5s
"""

from __future__ import annotations

import queue as _queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import sounddevice as sd

from jarvis.agent.circuit_breaker import LLMCircuitBreaker
from jarvis.agent.tool_agent import ToolAgent, ToolAgentConfig, tool_agent_from_settings
from jarvis.memory.store import MemoryStore
from jarvis.tools.registry import ToolRegistry, ToolSpec, build_default_registry
from jarvis.voice.stt import STT, STTConfig
from jarvis.voice.tts import TTS, TTSConfig
from jarvis.voice.orchestrator import VoiceOrchestrator
from jarvis.intents.good_morning import run_morning_briefing, answer_fact_follow_up
from jarvis.vision.camera_context import CameraContextAnalyzer, CameraContextConfig
from jarvis.vision.screen_context import ScreenContextAnalyzer, ScreenContextConfig


# ── Limpieza de texto para TTS ────────────────────────────────────────────────

# Patrones que NO deben pronunciarse
_RE_FUNC_TAG    = re.compile(r'<function[^>]*>.*?</function\s*>', re.DOTALL)
_RE_FUNC_SELF   = re.compile(r'<function[^/]*/>', re.DOTALL)
_RE_CODE_BLOCK  = re.compile(r'```[\s\S]*?```')
_RE_INLINE_CODE = re.compile(r'`[^`]+`')
_RE_MARKDOWN_HD = re.compile(r'#+\s+')
_RE_BOLD_ITAL   = re.compile(r'[*_]{1,3}([^*_]+)[*_]{1,3}')
_RE_BULLET      = re.compile(r'^\s*[-*•]\s+', re.MULTILINE)
_RE_NUMBERED    = re.compile(r'^\s*\d+\.\s+', re.MULTILINE)
_RE_BRACKET_ANN = re.compile(r'\[\s*(?:usa|ejecuta|herramienta|tool|function|Sistema)[^\]]*\]', re.IGNORECASE)
_RE_NEWLINES    = re.compile(r'\n+')       # cualquier salto de línea → espacio
_RE_MULTI_SP    = re.compile(r' {2,}')    # espacios múltiples → uno

# Frases de "estado" que el modelo dice antes de ejecutar herramientas.
# No deben pronunciarse: suenan como narración de comandos.
_RE_STATUS_PHRASE = re.compile(
    r'(?:^|\.\s*)(?:(?:Enseguida|Procesando|En marcha|Buscando|Ejecutando|Consultando|'
    r'Implementando|De inmediato|Por supuesto|Como ordene|Ciertamente|'
    r'Muy bien|Entendido)[,.]?\s*(?:señor[.,…]?)?\s*[.…]*\s*)',
    re.IGNORECASE,
)


def _clean_for_speech(text: str) -> str:
    """
    Limpia el texto para TTS:
    - Elimina bloques de código, markdown, tags <function=...>
    - Elimina frases de estado ("Enseguida, señor. Buscando...")
    - Convierte listas en frases seguidas
    - Colapsa saltos de línea y espacios extra
    """
    t = text
    t = _RE_FUNC_TAG.sub('', t)
    t = _RE_FUNC_SELF.sub('', t)
    t = _RE_CODE_BLOCK.sub('', t)
    t = _RE_INLINE_CODE.sub('', t)
    t = _RE_BRACKET_ANN.sub('', t)
    t = _RE_MARKDOWN_HD.sub('', t)
    t = _RE_BOLD_ITAL.sub(r'\1', t)
    t = _RE_BULLET.sub('', t)
    t = _RE_NUMBERED.sub('', t)
    t = _RE_NEWLINES.sub(' ', t)        # colapsa todos los saltos de línea
    t = _RE_STATUS_PHRASE.sub('', t)   # quitar "Enseguida, señor." etc.
    t = _RE_MULTI_SP.sub(' ', t)
    return t.strip()


# ── Sentence splitter ─────────────────────────────────────────────────────────

def _split_sentences(text: str) -> List[str]:
    """
    Divide el texto en chunks para TTS progresivo.
    Chunk mínimo de 120 chars → menos llamadas a API → menos huecos entre frases.
    """
    if not text:
        return []
    parts = re.split(r'(?<=[.!?…])\s+', text.strip())
    sentences: List[str] = []
    buffer = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        buffer = (buffer + " " + part).strip() if buffer else part
        if len(buffer) >= 120 and re.search(r'[.!?…]$', buffer):
            sentences.append(buffer)
            buffer = ""
    if buffer:
        sentences.append(buffer)
    return sentences if sentences else [text.strip()]


# ── Clipboard monitor ─────────────────────────────────────────────────────────

class _ClipboardMonitor:
    """
    Monitoriza el portapapeles macOS en background.
    Actualiza self.text cada segundo con el contenido actual (texto plano).
    Thread-safe para lectura de `text`.
    """
    _POLL     = 1.0    # segundos entre sondeos
    _MAX_LEN  = 250    # máximo de caracteres a guardar

    def __init__(self) -> None:
        self._text = ""
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="jarvis-clipboard", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    @property
    def text(self) -> str:
        """Contenido actual del portapapeles (máx _MAX_LEN chars)."""
        return self._text

    def _loop(self) -> None:
        try:
            import AppKit
            while self._running:
                try:
                    pb = AppKit.NSPasteboard.generalPasteboard()
                    content = pb.stringForType_(AppKit.NSPasteboardTypeString) or ""
                    if content != self._text:
                        self._text = content[:self._MAX_LEN]
                except Exception:
                    pass
                time.sleep(self._POLL)
        except Exception as e:
            print(f"⚠️ Clipboard monitor error: {e}")


# ── Registry con hooks visuales ───────────────────────────────────────────────

_VISUAL_TOOLS = {"open_app", "shell", "code_assistant", "organize_files"}


class VisualRegistry(ToolRegistry):
    """
    ToolRegistry que intercepta tools visuales para lanzar
    la animación de partículas antes de ejecutarlas.
    """

    def __init__(self, bridge, screen_w: float, screen_h: float) -> None:
        super().__init__()
        self._bridge   = bridge
        self._screen_w = screen_w
        self._screen_h = screen_h

    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name in _VISUAL_TOOLS and self._bridge is not None:
            self._fly_and_wait(name, args)
        return super().call(name, args)

    def _fly_and_wait(self, tool_name: str, args: Dict[str, Any]) -> None:
        tx, ty = self._target_for(tool_name, args)
        done = threading.Event()
        self._bridge.fly_to(tx, ty, callback=done.set)
        done.wait(timeout=1.5)

    def _target_for(self, tool_name: str, args: Dict[str, Any]) -> tuple[float, float]:
        sw, sh = self._screen_w, self._screen_h
        if tool_name == "open_app":
            app_name = args.get("app", "")
            if app_name:
                pos = self._dock_position(app_name)
                if pos is not None:
                    return pos
            return sw * 0.5, 40.0
        if tool_name == "shell":
            return sw * 0.25, sh * 0.75
        if tool_name == "code_assistant":
            pos = self._dock_position("Visual Studio Code")
            return pos if pos is not None else (sw * 0.5, sh * 0.5)
        return sw * 0.5, sh * 0.5

    def _dock_position(self, app_name: str) -> Optional[tuple[float, float]]:
        try:
            from jarvis.overlay.dock import get_dock_icon_position
            return get_dock_icon_position(app_name, self._screen_h)
        except Exception:
            return None


# ── Daemon principal ──────────────────────────────────────────────────────────

class JarvisDaemon:
    """
    Daemon que une voz, LLM y overlay.
    Instanciar desde el hilo principal; arrancar con start().
    """

    HOTKEY = "<ctrl>+<space>"

    # Conversación continua: espera máxima por voz de seguimiento
    _FOLLOWUP_TIMEOUT_S = 6.0

    # Gaze trigger: activar escucha cuando el usuario mira la cámara y habla
    _GAZE_VOICE_CHUNKS = 2   # chunks consecutivos con voz antes de disparar (~0.3s)

    # Debounce cross-trigger: evita doble activación wake + gaze simultáneos
    _ACTIVATION_DEBOUNCE_S = 1.0

    def __init__(
        self,
        bridge,
        screen_w: float,
        screen_h: float,
        settings: Any,
        paths: Any,
    ) -> None:
        self.bridge = bridge
        self._settings = settings          # guardar para wake word config
        self._running = False
        self._main_thread: Optional[threading.Thread] = None

        # ── Interrupción y cola de triggers
        self._interrupt_event = threading.Event()
        self._trigger_queue: _queue.Queue = _queue.Queue()

        # ── Registry visual
        registry = VisualRegistry(bridge, screen_w, screen_h)
        default = build_default_registry()
        for name, spec in default.list().items():
            registry.register(spec)

        # ── Agente LLM
        memory_store = MemoryStore(paths.db_path)
        self.agent = tool_agent_from_settings(
            settings,
            registry=registry,
            memory_store=memory_store,
            paths=paths,
        )

        # ── STT
        _stt_cfg = STTConfig(
            engine=getattr(settings, "stt_engine", "groq"),
            groq_api_key=getattr(settings, "groq_api_key", ""),
            groq_model=getattr(settings, "stt_groq_model", "whisper-large-v3-turbo"),
        )
        self.stt = STT(_stt_cfg)
        self._wav_path = paths.workspace_dir / "_jarvis_mic.wav"

        # ── TTS
        self.tts = TTS(TTSConfig(
            engine=getattr(settings, "tts_engine", "kokoro"),
            kokoro_voice=getattr(settings, "kokoro_voice", "ef_dora"),
            kokoro_speed=getattr(settings, "kokoro_speed", 1.0),
            kokoro_language=getattr(settings, "kokoro_language", "es"),
        ))

        # ── HUD (panel flotante de subtítulos)
        from jarvis.overlay.hud import JarvisHUD
        self._hud = JarvisHUD(bridge)

        # ── Clipboard monitor
        self._clipboard = _ClipboardMonitor()
        self._clipboard.start()

        # ── Wake word y hotkey
        self._wake_listener = None
        self._wake_ok = False
        self._hotkey_listener = None
        self._is_recording = False   # True mientras graba (suprime re-trigger de wake word)
        self._gesture_paused = False # True cuando un gesto ha pausado la escucha

        # ── Popup de texto (hotkey)
        from jarvis.overlay.text_input import TextInputPopup
        self._text_popup = TextInputPopup(bridge)

        # ── Chat panel (se asigna desde main.py tras crear el panel)
        self._chat_panel = None

        # ── Circuit breaker para el LLM
        # 3 fallos consecutivos → espera 30s antes de reintentar
        self._llm_cb = LLMCircuitBreaker(failure_threshold=3, recovery_timeout=30.0)

        # ── VoiceOrchestrator (VAD + grabación)
        self._orchestrator = VoiceOrchestrator(
            stt_cfg=_stt_cfg,
            interrupt_event=self._interrupt_event,
            on_audio_level=lambda lvl: self.bridge.set_audio_level(lvl),
            vad_engine=getattr(settings, "vad_engine", "silero"),
        )

        # ── Debounce cross-trigger (wake word + gaze simultáneos)
        self._last_activation_ts: float = 0.0
        self._activation_lock = threading.Lock()

        # Caché de contexto: evita llamar a la Accessibility API en cada request
        self._context_cache: str = ""
        self._context_cache_ts: float = 0.0
        self._CONTEXT_CACHE_TTL: float = 2.0  # segundos

        # ── Gaze trigger
        self._gaze_trigger_enabled: bool = bool(
            getattr(settings, "gaze_trigger_enabled", False)
        )
        self._gaze_rms_threshold: float = float(
            getattr(settings, "gaze_trigger_rms_threshold", 400.0)
        )
        self._gaze_cooldown: float = float(
            getattr(settings, "gaze_trigger_cooldown", 3.0)
        )

        # ── Camera context (face detection + object analysis via Groq Vision)
        # Se activa si camera_context_enabled=true O si gaze_trigger_enabled=true
        self._camera_ctx: Optional[CameraContextAnalyzer] = None
        _need_camera = (
            getattr(settings, "camera_context_enabled", False)
            or self._gaze_trigger_enabled
        )
        if _need_camera:
            _cam_cfg = CameraContextConfig(
                enabled=True,
                camera_index=getattr(settings, "camera_context_index", 0),
                interval_s=getattr(settings, "camera_context_interval_s", 5.0),
                # gaze trigger solo necesita cara, no objetos (a menos que camera_context también esté activo)
                face_only=(
                    getattr(settings, "camera_context_face_only", False)
                    or (self._gaze_trigger_enabled and not getattr(settings, "camera_context_enabled", False))
                ),
                groq_api_key=getattr(settings, "groq_api_key", ""),
            )
            self._camera_ctx = CameraContextAnalyzer(_cam_cfg)

        # ── Screen context (análisis periódico de pantalla)
        self._screen_ctx: Optional[ScreenContextAnalyzer] = None
        if getattr(settings, "screen_context_enabled", False):
            _sc_cfg = ScreenContextConfig(
                enabled=True,
                interval_s=getattr(settings, "screen_context_interval_s", 30.0),
                groq_api_key=getattr(settings, "groq_api_key", ""),
                focus_changes_only=getattr(settings, "screen_context_focus_only", True),
            )
            self._screen_ctx = ScreenContextAnalyzer(_sc_cfg)

        # ── Meeting mode (silencia TTS cuando hay app de videollamada activa)
        self._meeting_mode_enabled: bool = bool(
            getattr(settings, "meeting_mode_enabled", False)
        )
        self._meeting_mode_apps: list[str] = list(
            getattr(settings, "meeting_mode_apps",
                    ["zoom", "microsoft teams", "google meet", "facetime", "webex", "discord"])
        )
        self._in_meeting_mode: bool = False

    # ── Arranque / parada ─────────────────────────────────────────────────────

    def set_chat_panel(self, panel) -> None:
        """Conecta el panel de chat. Llamar antes de app.run()."""
        self._chat_panel = panel

    def submit_text(self, text: str) -> None:
        """
        Envía texto desde el chat panel al daemon. Thread-safe.
        Puede llamarse desde cualquier thread.
        """
        self._trigger_queue.put(("chat_text", text))

    def trigger_voice_input(self) -> None:
        """
        Inicia grabación de voz desde el panel principal. Thread-safe.
        Puede llamarse desde cualquier thread.
        """
        self._interrupt_event.set()
        self._trigger_queue.put("voice_panel")

    def trigger_text_input(self) -> None:
        """
        Abre el popup de entrada de texto. Thread-safe.
        Puede llamarse desde cualquier thread.
        """
        self._interrupt_event.set()
        self._trigger_queue.put("hotkey")

    def enqueue_gesture_event(self, action: str) -> None:
        """
        Encola una acción de gesto para procesarla en el loop principal.
        Usa trigger_queue para mantener un único pipeline de eventos.
        """
        if not action:
            return
        self._trigger_queue.put(("gesture", action))

    def interrupt(self) -> None:
        """
        Interrumpe el TTS/grabación en curso sin iniciar una nueva petición.
        Usado por el gesto de puño cerrado. Thread-safe.
        """
        self._interrupt_event.set()
        self.tts.stop()

    def pause_gesture(self) -> None:
        """Pausa la escucha (activado por gesto palma abierta). Thread-safe."""
        self._gesture_paused = True
        print("⏸  Jarvis pausado por gesto")

    def resume_gesture(self) -> None:
        """Reanuda la escucha (activado por segundo gesto palma abierta). Thread-safe."""
        self._gesture_paused = False
        print("▶  Jarvis reanudado por gesto")

    def start(self) -> None:
        self._running = True
        if self._camera_ctx:
            self._camera_ctx.start()
        if self._screen_ctx:
            self._screen_ctx.start()
        if self._meeting_mode_enabled:
            threading.Thread(
                target=self._meeting_mode_loop,
                name="jarvis-meeting",
                daemon=True,
            ).start()
        if self._gaze_trigger_enabled:
            threading.Thread(
                target=self._gaze_voice_loop,
                name="jarvis-gaze",
                daemon=True,
            ).start()
        self._main_thread = threading.Thread(
            target=self._run, name="jarvis-daemon", daemon=True
        )
        self._main_thread.start()

    def stop(self) -> None:
        self._running = False
        self._interrupt_event.set()
        self._trigger_queue.put("__stop__")
        self.tts.stop()
        self._clipboard.stop()
        if self._camera_ctx:
            self._camera_ctx.stop()
        if self._screen_ctx:
            self._screen_ctx.stop()
        self._hud.hide()
        if self._wake_listener is not None:
            try:
                self._wake_listener.stop()
            except Exception:
                pass
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass

    # ── Loop principal ────────────────────────────────────────────────────────

    def _run(self) -> None:
        self._request_accessibility()
        self._request_microphone_permission()
        self._setup_hotkey()
        self._wake_ok = self._start_wake_word()

        mode = "wake word" if self._wake_ok else "hotkey"
        print(f"🟢 Daemon activo — escuchando por {mode} ({self.HOTKEY})")

        # Thread siempre activo para detectar wake word (incluso mientras habla)
        if self._wake_ok:
            threading.Thread(
                target=self._wake_word_loop, name="jarvis-wake", daemon=True
            ).start()

        while self._running:
            try:
                source = self._trigger_queue.get(timeout=0.05)
            except _queue.Empty:
                continue

            if source == "__stop__" or not self._running:
                break

            # Interrumpir TTS/grabación en curso
            self._interrupt_event.set()
            self.tts.stop()
            time.sleep(0.05)
            self._interrupt_event.clear()

            if isinstance(source, tuple) and source[0] == "chat_text":
                self._handle_chat_text(source[1])
            elif isinstance(source, tuple) and source[0] == "gesture":
                self._handle_gesture_event(source[1])
            elif source == "hotkey":
                self._handle_hotkey_request()
            elif source == "gaze_trigger":
                self._handle_request(source_label="gaze")
            else:
                self._handle_request()

    def _handle_gesture_event(self, action: str) -> None:
        """Gestiona acciones de gesto encoladas desde GestureController."""
        action = (action or "").strip().lower()
        if action == "interrupt":
            if self._is_recording or self.tts.is_speaking:
                self.interrupt()
            return
        if action == "pause":
            self.pause_gesture()
            return
        if action == "resume":
            self.resume_gesture()
            return
        if action == "voice":
            self.trigger_voice_input()
            return
        _has_pending = (
            self.agent.has_pending_confirmation()
            or self.agent.intent_tracker.is_pending()
        )
        if action == "confirm":
            if _has_pending:
                self.submit_text("sí, confirmo")
            return
        if action == "yes":
            if _has_pending:
                self.submit_text("sí")
            return
        if action == "no":
            if _has_pending:
                self.submit_text("no, cancela")
            return

        print(f"⚠️ Acción de gesto desconocida: {action}")

    def _play_wake_beep(self) -> None:
        """Beep 440Hz 80ms no-bloqueante — feedback auditivo inmediato tipo Siri."""
        if not getattr(self._settings, "wake_beep", True):
            return
        try:
            t    = np.linspace(0, 0.08, int(16000 * 0.08), endpoint=False)
            beep = (np.sin(2 * np.pi * 440 * t) * 0.25).astype(np.float32)
            fade = int(16000 * 0.01)  # 10ms fade in/out para evitar clicks
            beep[:fade]  *= np.linspace(0, 1, fade)
            beep[-fade:] *= np.linspace(1, 0, fade)
            sd.play(beep, samplerate=16000, blocking=False)
        except Exception:
            pass  # El beep es opcional; nunca bloquear el flujo

    def _wake_word_loop(self) -> None:
        """Thread siempre activo que detecta wake word incluso mientras Jarvis habla."""
        while self._running and self._wake_listener is not None:
            # No detectar mientras grabamos o la escucha está pausada por gesto
            if self._is_recording or self._gesture_paused:
                time.sleep(0.1)
                continue
            try:
                detected = self._wake_listener.wait_for_wake(timeout_sec=0.5)
                if detected and self._running:
                    self._play_wake_beep()          # feedback auditivo inmediato
                    print("🎤 Wake word detectado")
                    self._try_activate("wake_word")
                    # Cooldown: el modelo mantiene puntuación alta varios chunks
                    # → esperar para evitar que el mismo «Hey Jarvis» dispare dos veces
                    time.sleep(self._ACTIVATION_DEBOUNCE_S + 0.5)
            except Exception as e:
                if self._running:
                    print(f"⚠️ Wake word loop error: {e}")
                time.sleep(0.5)

    def _gaze_voice_loop(self) -> None:
        """
        Thread daemon: activa Jarvis automáticamente cuando el usuario mira la cámara
        y empieza a hablar, sin necesitar decir el wake word.

        Lógica:
          1. Verifica que `_camera_ctx.looking_at_camera` sea True (cara frontal detectada)
          2. Lee el RMS del último chunk procesado por el wake word listener (sin nuevo stream)
          3. Si el RMS supera el umbral durante _GAZE_VOICE_CHUNKS consecutivos → dispara
          4. Cooldown independiente para evitar re-activaciones rápidas
        """
        import logging as _logging
        _log = _logging.getLogger(__name__)

        consecutive_voice = 0
        last_trigger_ts = 0.0

        _log.info("Gaze trigger activo (umbral RMS=%.0f, cooldown=%.1fs)",
                  self._gaze_rms_threshold, self._gaze_cooldown)

        while self._running:
            time.sleep(0.15)

            # No interferir con grabación activa ni pausa por gesto
            if self._is_recording or self._gesture_paused:
                consecutive_voice = 0
                continue

            # Cooldown entre activaciones
            if time.monotonic() - last_trigger_ts < self._gaze_cooldown:
                continue

            # ── Condición 1: usuario mirando la cámara ────────────────────────
            if not (self._camera_ctx and self._camera_ctx.looking_at_camera):
                consecutive_voice = 0
                continue

            # ── Condición 2: hay voz en el micrófono ─────────────────────────
            # Reutilizamos el RMS que ya computa el wake word listener (sin nuevo stream)
            if self._wake_listener is None:
                consecutive_voice = 0
                continue

            rms = self._wake_listener.latest_rms
            if rms >= self._gaze_rms_threshold:
                consecutive_voice += 1
                if consecutive_voice >= self._GAZE_VOICE_CHUNKS:
                    consecutive_voice = 0
                    last_trigger_ts = time.monotonic()
                    _log.info("👁 Gaze trigger: cara detectada + RMS=%.0f — activando", rms)
                    print(f"👁️ Gaze trigger — mirando a cámara y hablando (RMS={rms:.0f})")
                    self._play_wake_beep()
                    self._try_activate("gaze_trigger")
            else:
                consecutive_voice = 0

    # ── Grabación con VAD + VU meter ─────────────────────────────────────────

    # ── Activation debounce ───────────────────────────────────────────────────

    def _try_activate(self, source: str) -> bool:
        """
        Intenta activar Jarvis desde una fuente (wake_word, gaze_trigger, hotkey).
        Retorna False si ya hubo una activación reciente (debounce cross-trigger).
        """
        now = time.monotonic()
        with self._activation_lock:
            if now - self._last_activation_ts < self._ACTIVATION_DEBOUNCE_S:
                return False
            self._last_activation_ts = now
        self._interrupt_event.set()
        self._trigger_queue.put(source)
        return True

    # ── Grabación con VAD + VU meter ─────────────────────────────────────────

    def _record_with_vad(
        self,
        out_path: Path,
        wait_timeout_s: Optional[float] = None,
        prebuffer: Optional[list] = None,
    ) -> Optional[Path]:
        """Wrapper delegando a VoiceOrchestrator."""
        self._is_recording = True
        try:
            return self._orchestrator.record(out_path, prebuffer, wait_timeout_s)
        finally:
            self._is_recording = False

    # ── Context injection ─────────────────────────────────────────────────────

    def _get_context(self) -> str:
        """
        Genera una línea de contexto del entorno actual para inyectar al LLM.
        Incluye: hora, app activa, URL (si navegador), portapapeles (si hay texto).
        La parte de app/ventana/URL se cachea 2s para evitar llamadas repetidas
        a la Accessibility API de macOS en requests seguidos.
        """
        now = time.monotonic()
        parts: List[str] = []

        # Hora actual (siempre fresca — es barata)
        parts.append(f"hora: {datetime.now().strftime('%H:%M')}")

        # App activa via Accessibility API — con caché TTL
        if now - self._context_cache_ts < self._CONTEXT_CACHE_TTL:
            cached = self._context_cache
        else:
            cached = ""
            try:
                from jarvis.vision.accessibility import get_active_app
                app = get_active_app()
                name = app.get("name", "")
                if name and name not in ("Unknown", "Jarvis"):
                    app_parts: List[str] = [f"app activa: {name}"]
                    title = (app.get("window_title") or "").strip()
                    if title and title != name:
                        app_parts.append(f"ventana: {title[:60]}")
                    url = (app.get("url") or "").strip()
                    if url:
                        app_parts.append(f"URL: {url[:80]}")
                    cached = " | ".join(app_parts)
            except Exception:
                pass
            self._context_cache = cached
            self._context_cache_ts = now

        if cached:
            parts.append(cached)

        # Portapapeles (solo si hay texto relevante)
        clip = self._clipboard.text.strip()
        if len(clip) > 5:
            clip_display = clip[:200].replace("\n", " ↵ ")
            parts.append(f'portapapeles: «{clip_display}»')

        # Camera context (presencia del usuario y objetos detectados)
        if self._camera_ctx:
            cam_snippet = self._camera_ctx.get_context_snippet()
            if cam_snippet:
                parts.append(cam_snippet)

        # Screen context (descripción de la pantalla activa)
        if self._screen_ctx:
            sc_snippet = self._screen_ctx.get_context_snippet()
            if sc_snippet:
                parts.append(sc_snippet)

        return " | ".join(parts)

    # ── Handlers de petición ─────────────────────────────────────────────────

    def _handle_request(self, source_label: str = "wake") -> None:
        """Un ciclo completo: graba → transcribe → LLM → TTS + HUD."""
        if source_label == "gaze":
            print("👁️ Escuchando (activado por mirada + voz)")
        self._hud.hide()
        try:
            self.bridge.set_state("listening")
            # Recoger audio pre-wake del ring buffer (captura lo que se dijo
            # justo después/durante la wake word antes de abrir el stream)
            prebuffer = self._wake_listener.get_prebuffer() if self._wake_listener else []
            audio_path = self._record_with_vad(self._wav_path, prebuffer=prebuffer)

            if audio_path is None:
                self.bridge.set_state("idle")
                return

            self.bridge.set_state("thinking")
            text = self.stt.transcribe_wav(audio_path)

            if not text or "no he detectado" in text.lower():
                print("⚠️ Sin voz detectada")
                self.bridge.set_state("idle")
                return

            print(f"👂 Escuché: «{text}»")

        except Exception as e:
            print(f"⚠️ Error grabando/transcribiendo: {e}")
            self.bridge.set_state("idle")
            return

        self._process_text(text, _allow_followup=True)

    def _handle_hotkey_request(self) -> None:
        """Hotkey: muestra popup de texto y procesa la entrada."""
        self._hud.hide()
        self.bridge.set_state("listening")
        print("⌨️  Popup de texto abierto")

        text = self._text_popup.show_and_wait()

        if not text:
            print("⚠️ Popup cancelado o sin texto")
            self.bridge.set_state("idle")
            return

        print(f"⌨️  Escrito: «{text}»")
        self._process_text(text, _allow_followup=True)

    def _handle_chat_text(self, text: str) -> None:
        """Chat panel: procesa texto enviado directamente (sin grabación)."""
        self._hud.hide()
        print(f"💬 Chat: «{text}»")
        # El mensaje de usuario ya fue añadido al panel por _submit_text
        self._process_text(text, from_chat_panel=True)

    def _try_followup(self) -> None:
        """
        Ventana de seguimiento: tras responder, escucha hasta _FOLLOWUP_TIMEOUT_S
        sin requerir wake word. Si el usuario habla → nuevo turno de conversación.
        Si no → vuelve a idle silenciosamente.
        """
        if not self._running or self._interrupt_event.is_set():
            return

        # Extended timeout when the tracker is collecting parameters
        followup_s = self.agent.intent_tracker.get_followup_timeout(
            default=self._FOLLOWUP_TIMEOUT_S
        )
        print(f"👂 Esperando seguimiento ({followup_s:.0f}s)...")
        self.bridge.set_state("listening")

        audio_path = self._record_with_vad(
            self._wav_path, wait_timeout_s=followup_s
        )

        if audio_path is None or self._interrupt_event.is_set():
            self.bridge.set_state("idle")
            return

        self.bridge.set_state("thinking")
        try:
            text = self.stt.transcribe_wav(audio_path)
        except Exception as e:
            print(f"⚠️ STT error en follow-up: {e}")
            self.bridge.set_state("idle")
            return

        if not text or "no he detectado" in text.lower():
            self.bridge.set_state("idle")
            return

        print(f"👂 Follow-up: «{text}»")
        # El mensaje de usuario va al chat panel desde aquí para no duplicarlo
        if self._chat_panel is not None:
            self._chat_panel.add_user_message(text)
        self._process_text(text, from_chat_panel=True, _allow_followup=True)

    def _process_text(self, text: str, from_chat_panel: bool = False, _allow_followup: bool = False) -> None:
        """
        Envía texto al LLM con contexto automático y reproduce frase a frase.
        Muestra el texto completo en el HUD mientras el TTS habla.

        from_chat_panel=True → el mensaje usuario ya está en el panel; no duplicar.
        _allow_followup=True → tras responder, escucha brevemente por seguimiento.
        """
        if self._interrupt_event.is_set():
            return

        try:
            self.bridge.set_state("thinking")

            # ── Añadir mensaje usuario al chat panel (si viene de voz/hotkey)
            if self._chat_panel is not None and not from_chat_panel:
                self._chat_panel.add_user_message(text)

            # ── Cancelación de intent pendiente (antes de inyectar contexto)
            self.agent.intent_tracker.check_user_cancel(text)

            # ── Inyectar contexto del entorno + intent pendiente
            context = self._get_context()
            intent_ctx = self.agent.intent_tracker.get_context_injection()
            if context:
                augmented = f"{text}\n\n[Sistema: {context}]"
            else:
                augmented = text
            if intent_ctx:
                augmented = f"{augmented}\n{intent_ctx}"

            # ── Intención local: "buenos días" (briefing) — antes del LLM ──
            text_norm = (text or "").strip().lower()
            if "buenos días" in text_norm or "buenos dias" in text_norm:
                response = run_morning_briefing().text

                self.agent.intent_tracker.analyze_llm_response(response)

                if not response or self._interrupt_event.is_set():
                    return

                print(f"🤖 Jarvis (briefing): «{response}»")
                self.bridge.set_state("acting")

                if self._chat_panel is not None:
                    self._chat_panel.add_jarvis_message(response)

                self._hud.show_text(response)

                speech_text = _clean_for_speech(response)
                if not speech_text:
                    self.bridge.set_state("idle")
                    return

                if not self._interrupt_event.is_set():
                    if self._in_meeting_mode:
                        print("🎙 Modo reunión: TTS omitido (briefing)")
                    else:
                        self.tts.speak_nonblocking(speech_text)
                        while self.tts.is_speaking:
                            if self._interrupt_event.is_set():
                                self.tts.stop()
                                break
                            time.sleep(0.05)

                return

            # ── Follow-up del dato random ("¿por qué?", "explícame") — antes del LLM ──
            fact_reply = answer_fact_follow_up(text)
            if fact_reply:
                response = fact_reply

                self.agent.intent_tracker.analyze_llm_response(response)

                if not response or self._interrupt_event.is_set():
                    return

                print(f"🤖 Jarvis (fact follow-up): «{response}»")
                self.bridge.set_state("acting")

                if self._chat_panel is not None:
                    self._chat_panel.add_jarvis_message(response)

                self._hud.show_text(response)

                speech_text = _clean_for_speech(response)
                if not speech_text:
                    self.bridge.set_state("idle")
                    return

                if not self._interrupt_event.is_set():
                    if self._in_meeting_mode:
                        print("🎙 Modo reunión: TTS omitido (fact reply)")
                    else:
                        self.tts.speak_nonblocking(speech_text)
                        while self.tts.is_speaking:
                            if self._interrupt_event.is_set():
                                self.tts.stop()
                                break
                            time.sleep(0.05)

                return

            # ── Circuit breaker: si el LLM ha fallado repetidamente, esperar
            if not self._llm_cb.allow_call():
                remaining = int(self._llm_cb._timeout - (time.time() - (self._llm_cb._opened_at or 0)))
                response = (
                    f"El servicio de IA no está disponible temporalmente. "
                    f"Reintentando en ~{max(0, remaining)}s."
                )
                self.bridge.set_state("error")
                self._hud.show_text(response)
                return

            # ── LLM streaming: habla frase a frase conforme el LLM genera ──────
            response_parts: List[str] = []
            sentence_q: _queue.Queue[Optional[str]] = _queue.Queue()

            # Hilo TTS: consume frases de la cola sin gaps entre ellas
            _tts_thread: Optional[threading.Thread] = None
            if not self._in_meeting_mode:
                def _tts_worker() -> None:
                    self.tts.speak_queued(
                        sentence_q,
                        interrupt_event=self._interrupt_event,
                    )
                _tts_thread = threading.Thread(
                    target=_tts_worker, name="tts-queue", daemon=True
                )
                _tts_thread.start()

            def _on_sentence(sentence: str) -> None:
                """Callback llamado por run_sentences() para cada frase lista."""
                if self._interrupt_event.is_set():
                    return
                speech = _clean_for_speech(sentence)
                if not speech:
                    return

                # Primera frase → cambiar a "acting" inmediatamente
                if not response_parts:
                    self.bridge.set_state("acting")

                response_parts.append(sentence)

                if not self._in_meeting_mode:
                    sentence_q.put(speech)

            try:
                response = self.agent.run_sentences(
                    augmented,
                    on_sentence=_on_sentence,
                    interrupt_event=self._interrupt_event,
                )
                self._llm_cb.record_success()
            except Exception as llm_err:
                self._llm_cb.record_failure()
                sentence_q.put(None)  # desbloquear worker TTS
                if _tts_thread:
                    _tts_thread.join(timeout=2)
                raise llm_err

            # ── Actualizar tracker con la respuesta completa del LLM
            self.agent.intent_tracker.analyze_llm_response(response)

            if not response or self._interrupt_event.is_set():
                sentence_q.put(None)
                if _tts_thread:
                    _tts_thread.join(timeout=2)
                return

            print(f"🤖 Jarvis: «{response}»")
            if not response_parts:
                # run_sentences no llamó _on_sentence (respuesta vacía o tool-only)
                self.bridge.set_state("acting")

            # ── Actualizar chat panel y HUD con respuesta completa
            if self._chat_panel is not None:
                self._chat_panel.add_jarvis_message(response)

            intent_status = self.agent.intent_tracker.get_status_text()
            hud_text = f"{intent_status}\n\n{response}" if intent_status else response
            self._hud.show_text(hud_text)

            # ── Si no se habló nada, encolar la respuesta completa
            if not response_parts and not self._interrupt_event.is_set():
                speech_text = _clean_for_speech(response)
                if speech_text:
                    if self._in_meeting_mode:
                        print("🎙 Modo reunión: TTS omitido")
                    elif not self._interrupt_event.is_set():
                        sentence_q.put(speech_text)

            # Señalar fin de stream y esperar a que el TTS termine
            sentence_q.put(None)
            if _tts_thread:
                _tts_thread.join(timeout=30)

        except Exception as e:
            print(f"⚠️ Error procesando texto: {e}")
            # Feedback auditivo del error al usuario
            try:
                if not self._interrupt_event.is_set() and not self._in_meeting_mode:
                    self.tts.speak_nonblocking("Lo siento, ocurrió un error.")
                    _t0 = time.monotonic()
                    while self.tts.is_speaking and (time.monotonic() - _t0) < 5:
                        time.sleep(0.05)
            except Exception:
                pass
        finally:
            self.tts.stop()
            self.bridge.set_audio_level(0.0)
            self.bridge.set_state("idle")
            # HUD: ocultar inmediatamente si hubo interrupción, si no → fade out
            if self._interrupt_event.is_set():
                self._hud.hide()
            else:
                self._hud.schedule_hide()

        # Ventana de seguimiento (fuera del finally para no bloquear el idle)
        if _allow_followup and not self._interrupt_event.is_set():
            self._try_followup()

    # ── Meeting mode ──────────────────────────────────────────────────────────

    def _meeting_mode_loop(self) -> None:
        """Detecta apps de videollamada → silencia TTS automáticamente."""
        import logging as _log
        _ml = _log.getLogger(__name__)
        while self._running:
            try:
                from jarvis.vision.accessibility import get_active_app
                app = get_active_app()
                app_name = (app.get("name") or "").lower()

                is_meeting = any(m in app_name for m in self._meeting_mode_apps)

                if is_meeting != self._in_meeting_mode:
                    self._in_meeting_mode = is_meeting
                    if is_meeting:
                        _ml.info("Modo reunión ACTIVO: %s", app.get("name"))
                        self._hud.show_text("🎙 Modo reunión: TTS silenciado")
                    else:
                        _ml.info("Modo reunión DESACTIVADO")
                        self._hud.show_text("🔊 Modo reunión: TTS restaurado")
            except Exception:
                pass
            time.sleep(5.0)

    # ── Accesibilidad ─────────────────────────────────────────────────────────

    def _request_microphone_permission(self) -> None:
        """Verifica y solicita permiso de micrófono en macOS (AVFoundation)."""
        try:
            import AVFoundation
            status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
                AVFoundation.AVMediaTypeAudio
            )
            # 0=notDetermined, 1=restricted, 2=denied, 3=authorized
            if status == 3:
                print("✅ Permiso de micrófono: autorizado")
                return
            if status == 2:
                print("❌ Permiso de micrófono DENEGADO")
                print("   Ve a: Ajustes del Sistema → Privacidad y Seguridad → Micrófono")
                print("   y activa el permiso para Terminal (o Python)")
                return
            if status == 0:
                print("⏳ Solicitando permiso de micrófono...")
                done = threading.Event()

                def _handler(granted):
                    if granted:
                        print("✅ Permiso de micrófono concedido")
                    else:
                        print("❌ Permiso de micrófono denegado por el usuario")
                        print("   Actívalo en: Ajustes → Privacidad → Micrófono → Terminal")
                    done.set()

                AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    AVFoundation.AVMediaTypeAudio, _handler
                )
                done.wait(timeout=30)
        except Exception as e:
            # AVFoundation no disponible o no necesario — ignorar silenciosamente
            print(f"ℹ️  Verificación de permiso de micrófono: {e}")

    def _request_accessibility(self) -> None:
        try:
            from jarvis.overlay.dock import check_accessibility_permission
            granted = check_accessibility_permission()
            if granted:
                print("✅ Permiso de Accesibilidad concedido — Dock tracking activo")
            else:
                print("⚠️  Accesibilidad no concedida — partículas usarán posición estimada")
        except Exception:
            pass

    # ── Wake word ─────────────────────────────────────────────────────────────

    def _start_wake_word(self) -> bool:
        try:
            from jarvis.voice.wake_word import WakeWordConfig, WakeWordListener
            s = self._settings
            sensitivity = float(getattr(s, "wake_word_sensitivity", 0.5))
            cfg = WakeWordConfig(
                engine=getattr(s, "wake_word_engine", "openwakeword"),
                oww_model=getattr(s, "wake_word_model", "hey_jarvis"),
                sensitivity=sensitivity,
                debug=bool(getattr(s, "wake_word_debug", False)),
                oww_min_rms=float(getattr(s, "wake_word_min_rms", 120.0)),
                oww_min_consecutive_hits=int(getattr(s, "wake_word_min_hits", 2)),
                oww_activation_cooldown_sec=float(getattr(s, "wake_word_cooldown", 1.5)),
                oww_score_ema_alpha=float(getattr(s, "wake_word_score_ema_alpha", 0.6)),
                access_key=getattr(s, "porcupine_access_key", "") or "",
                keyword=getattr(s, "wake_word", "jarvis"),
            )
            self._wake_listener = WakeWordListener(cfg)
            self._wake_listener.start()
            print(f"🎤 Wake word activo: '{cfg.oww_model}' (sensibilidad={sensitivity:.2f})")
            return True
        except Exception as e:
            print(f"⚠️ Wake word no disponible ({e}). Usando solo hotkey.")
            return False

    # ── Hotkey ────────────────────────────────────────────────────────────────

    def _setup_hotkey(self) -> None:
        try:
            from pynput import keyboard

            def on_activate():
                print("⌨️  Hotkey detectada")
                self._try_activate("hotkey")

            # pynput >= 1.8 añade argumento 'injected' a los callbacks.
            # Envolver on_activate para aceptar cualquier firma.
            def on_activate_compat(*args, **kwargs):
                on_activate()

            self._hotkey_listener = keyboard.GlobalHotKeys(
                {self.HOTKEY: on_activate_compat}
            )
            self._hotkey_listener.start()
            print(f"⌨️  Hotkey registrada: {self.HOTKEY}")
        except Exception as e:
            print(f"⚠️ Hotkey no disponible: {e}")


# ── Helper para construir el daemon desde settings ────────────────────────────

def build_daemon(bridge, screen_w: float, screen_h: float) -> JarvisDaemon:
    from jarvis.config import load_settings
    settings, paths = load_settings()
    return JarvisDaemon(bridge, screen_w, screen_h, settings, paths)
