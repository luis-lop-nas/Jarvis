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
import wave
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
from jarvis.intents.good_morning import run_morning_briefing, answer_fact_follow_up
from jarvis.vision.camera_context import CameraContextAnalyzer, CameraContextConfig

# ── Silero VAD (ONNX directo, sin torchaudio) ────────────────────────────────

class _SileroVAD:
    """
    Wrapper mínimo de Silero VAD usando onnxruntime directamente.
    No requiere torchaudio ni torch.hub. Usa el ONNX cacheado en ~/.cache/torch/hub/.
    Singleton: se instancia una vez y se reutiliza en todas las grabaciones.
    """
    _ONNX_PATH = (
        Path.home() / ".cache/torch/hub/snakers4_silero-vad_master"
        / "src/silero_vad/data/silero_vad.onnx"
    )
    _instance: Optional["_SileroVAD"] = None

    def __init__(self) -> None:
        import onnxruntime as ort
        self._sess = ort.InferenceSession(
            str(self._ONNX_PATH),
            providers=["CPUExecutionProvider"],
        )
        self.reset_states()

    def reset_states(self) -> None:
        # state: shape (2, batch=1, 128) — estado LSTM del modelo
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

    def __call__(self, audio_float32: np.ndarray, sr: int = 16000) -> float:
        """audio_float32: shape (512,) float32 [-1,1]. Retorna probabilidad de voz [0,1]."""
        x = audio_float32.reshape(1, -1)
        outs = self._sess.run(None, {
            "input": x,
            "state": self._state,
            "sr":    np.array(sr, dtype=np.int64),
        })
        # outs[0] = output (1,1), outs[1] = stateN actualizado
        self._state = outs[1]
        return float(outs[0][0, 0])

    @classmethod
    def load(cls) -> Optional["_SileroVAD"]:
        if cls._instance is not None:
            return cls._instance
        try:
            if not cls._ONNX_PATH.exists():
                raise FileNotFoundError(f"ONNX no encontrado: {cls._ONNX_PATH}")
            cls._instance = cls()
            print("✅ Silero VAD cargado (ONNX, sin torchaudio)")
            return cls._instance
        except Exception as e:
            print(f"⚠️ Silero VAD no disponible ({e}). Usando VAD por RMS.")
            return None


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

    # VAD RMS (legacy — fallback si Silero no está disponible)
    _VAD_CHUNK_MS     = 30
    _VAD_THRESHOLD    = 300
    _VAD_SILENCE_SEGS = 15
    _VAD_TIMEOUT_S    = 15.0
    _VAD_MAX_S        = 30.0

    # VAD Silero (ML, chunks de 512 samples = 32ms a 16kHz)
    _SILERO_CHUNK  = 512
    _SILERO_VOICE  = 0.35   # prob >= 0.35 → voz activa (más sensible que voice_loop 0.6)
    _SILERO_SILEN  = 0.25   # prob < 0.25  → silencio definitivo
    _SILENCE_SHORT = 10     # chunks (320ms) para frases cortas (< 2s de voz)
    _SILENCE_LONG  = 15     # chunks (480ms) para frases largas (>= 2s de voz)

    # Noise floor adaptativo
    _NF_ALPHA = 0.05    # EMA lenta: no reacciona a picos de voz
    _NF_INIT  = 200.0   # RMS inicial int16 antes de calibrar

    # Conversación continua: espera máxima por voz de seguimiento
    _FOLLOWUP_TIMEOUT_S = 6.0

    # VU meter: 3000 RMS ≈ voz normal conversacional
    _VU_NORM = 3000.0

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
        self.stt = STT(STTConfig(
            engine=getattr(settings, "stt_engine", "groq"),
            groq_api_key=getattr(settings, "groq_api_key", ""),
            groq_model=getattr(settings, "stt_groq_model", "whisper-large-v3-turbo"),
        ))
        self._wav_path = paths.workspace_dir / "_jarvis_mic.wav"

        # ── TTS
        self.tts = TTS(TTSConfig(
            engine=getattr(settings, "tts_engine", "macos"),
            elevenlabs_api_key=getattr(settings, "elevenlabs_api_key", "") or None,
            elevenlabs_voice_id=getattr(settings, "elevenlabs_voice_id", "") or None,
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

        # ── Silero VAD (lazy load en primer uso)
        self._silero: Optional[_SileroVAD] = None
        self._silero_loaded: bool = False

        # ── Noise floor adaptativo (int16 RMS, actualizado durante idle)
        self._noise_floor: float = JarvisDaemon._NF_INIT
        self._noise_floor_lock = threading.Lock()

        # ── Camera context (face detection + object analysis via Groq Vision)
        self._camera_ctx: Optional[CameraContextAnalyzer] = None
        if getattr(settings, "camera_context_enabled", False):
            _cam_cfg = CameraContextConfig(
                enabled=True,
                camera_index=getattr(settings, "camera_context_index", 0),
                interval_s=getattr(settings, "camera_context_interval_s", 5.0),
                face_only=getattr(settings, "camera_context_face_only", False),
                groq_api_key=getattr(settings, "groq_api_key", ""),
            )
            self._camera_ctx = CameraContextAnalyzer(_cam_cfg)

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
                source = self._trigger_queue.get(timeout=0.5)
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
            else:
                self._handle_request()

    def _handle_gesture_event(self, action: str) -> None:
        """Gestiona acciones de gesto encoladas desde GestureController."""
        action = (action or "").strip().lower()
        if action == "interrupt":
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
        if action == "confirm":
            self.submit_text("sí, confirmo")
            return
        if action == "yes":
            self.submit_text("sí")
            return
        if action == "no":
            self.submit_text("no, cancela")
            return

        print(f"⚠️ Acción de gesto desconocida: {action}")

    # ── Silero VAD helpers ────────────────────────────────────────────────────

    def _get_silero(self) -> Optional[_SileroVAD]:
        """Carga Silero VAD la primera vez que se necesita (lazy, thread-safe por GIL)."""
        if not self._silero_loaded:
            self._silero_loaded = True
            if getattr(self._settings, "vad_engine", "silero") == "silero":
                self._silero = _SileroVAD.load()
        return self._silero

    def _update_noise_floor(self, rms: float) -> None:
        """Actualiza noise floor con EMA lenta. Solo llamar durante silencio pre-voz."""
        with self._noise_floor_lock:
            self._noise_floor = (
                self._NF_ALPHA * rms + (1.0 - self._NF_ALPHA) * self._noise_floor
            )

    def _get_noise_floor(self) -> float:
        with self._noise_floor_lock:
            return self._noise_floor

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
                    self._interrupt_event.set()
                    self._trigger_queue.put("wake_word")
                    # Cooldown: el modelo mantiene puntuación alta varios chunks
                    # → esperar 2s para evitar que el mismo «Hey Jarvis» dispare dos veces
                    time.sleep(2.0)
            except Exception as e:
                if self._running:
                    print(f"⚠️ Wake word loop error: {e}")
                time.sleep(0.5)

    # ── Grabación con VAD + VU meter ─────────────────────────────────────────

    def _record_with_vad(
        self,
        out_path: Path,
        wait_timeout_s: Optional[float] = None,
        prebuffer: Optional[list] = None,
    ) -> Optional[Path]:
        """
        Puerta de entrada: despacha a Silero VAD o RMS según disponibilidad.
        prebuffer: lista de np.ndarray int16 del ring buffer pre-wake.
        """
        silero = self._get_silero()
        if silero is not None:
            return self._record_with_vad_silero(
                out_path, wait_timeout_s, prebuffer or [], silero
            )
        return self._record_with_vad_rms(out_path, wait_timeout_s)

    def _record_with_vad_rms(self, out_path: Path, wait_timeout_s: Optional[float] = None) -> Optional[Path]:
        """
        Graba audio con VAD por RMS (legacy). Usado como fallback si Silero no está disponible.
        """
        self._is_recording = True
        sr         = self.stt.cfg.sample_rate
        chunk_sz   = int(sr * self._VAD_CHUNK_MS / 1000)
        max_chunks = int(self._VAD_MAX_S * 1000 / self._VAD_CHUNK_MS)
        wait_s      = wait_timeout_s if wait_timeout_s is not None else self._VAD_TIMEOUT_S
        wait_chunks = int(wait_s * 1000 / self._VAD_CHUNK_MS)

        frames: list[np.ndarray] = []
        voice_started = False
        silence_count = 0
        wait_count    = 0
        peak_rms      = 0.0   # para diagnóstico de permisos

        try:
            print("🎤 Escuchando...")
            with sd.InputStream(
                samplerate=sr,
                channels=self.stt.cfg.channels,
                dtype=self.stt.cfg.dtype,
                blocksize=chunk_sz,
                device=self.stt.cfg.device,
            ) as stream:
                for _ in range(max_chunks):
                    if not self._running or self._interrupt_event.is_set():
                        break

                    chunk, _ = stream.read(chunk_sz)
                    rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                    if rms > peak_rms:
                        peak_rms = rms

                    # VU meter: nivel normalizado al orb
                    self.bridge.set_audio_level(min(1.0, rms / self._VU_NORM))

                    if rms >= self._VAD_THRESHOLD:
                        if not voice_started:
                            print("🎙️  Voz detectada")
                            voice_started = True
                        silence_count = 0
                        frames.append(chunk.copy())
                    elif voice_started:
                        frames.append(chunk.copy())
                        silence_count += 1
                        if silence_count >= self._VAD_SILENCE_SEGS:
                            print("🔇 Silencio — fin de voz")
                            break
                    else:
                        wait_count += 1
                        # Diagnóstico tras 3s: si no llega señal, avisar de permisos
                        if wait_count == 100 and peak_rms < 5.0:
                            print(f"⚠️  Sin señal de audio (RMS pico: {peak_rms:.1f}). "
                                  f"Umbral VAD: {self._VAD_THRESHOLD}")
                            print("   Verifica: Ajustes → Privacidad → Micrófono → "
                                  "activa permiso para Terminal/Python")
                        if wait_count >= wait_chunks:
                            break

            self.bridge.set_audio_level(0.0)

            if self._interrupt_event.is_set():
                print("🛑 Grabación interrumpida")
                return None

            if not voice_started or not frames:
                if wait_timeout_s is not None:
                    # En modo follow-up, silencio = usuario no quiso hablar → no grabar
                    return None
                print(f"⚠️ Sin voz detectada (RMS pico={peak_rms:.1f}, umbral={self._VAD_THRESHOLD})")
                return self.stt.record_to_wav(out_path, seconds=5.0)

            audio = np.concatenate(frames, axis=0)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(out_path), "wb") as wf:
                wf.setnchannels(self.stt.cfg.channels)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(audio.tobytes())

            return out_path
        finally:
            self._is_recording = False

    def _record_with_vad_silero(
        self,
        out_path: Path,
        wait_timeout_s: Optional[float],
        prebuffer: list,
        silero: "_SileroVAD",
    ) -> Optional[Path]:
        """
        Graba audio usando Silero VAD (ONNX).
        - pre-buffer: audio capturado antes de la wake word (1.5s)
        - Noise floor adaptativo: calibra el umbral al ruido ambiental
        - Silencio de corte: 320ms (frase corta) / 480ms (frase larga)
        """
        sr          = self.stt.cfg.sample_rate          # 16000
        chunk_sz    = self._SILERO_CHUNK                # 512 samples = 32ms
        max_chunks  = int(self._VAD_MAX_S * sr / chunk_sz)
        wait_chunks = int((wait_timeout_s if wait_timeout_s is not None
                           else self._VAD_TIMEOUT_S) * sr / chunk_sz)

        frames: list        = []
        voice_started       = False
        silence_count       = 0
        voice_chunks        = 0     # chunks con voz (para elegir silence budget)
        wait_count          = 0
        peak_rms            = 0.0
        silero.reset_states()
        noise_floor = self._get_noise_floor()

        self._is_recording = True
        try:
            # ── Incorporar pre-buffer: rechunquear OWW(1280) → Silero(512) ──
            if prebuffer:
                raw = np.concatenate([c.flatten() for c in prebuffer])
                n   = (len(raw) // chunk_sz) * chunk_sz
                for i in range(0, n, chunk_sz):
                    blk = raw[i:i + chunk_sz]
                    frames.append(blk.reshape(-1, 1))
                    rms = float(np.sqrt(np.mean(blk.astype(np.float32) ** 2)))
                    if rms > noise_floor * 1.5:
                        voice_started = True
                        voice_chunks += 1
                if voice_started:
                    print(f"📼 Pre-buffer: {len(prebuffer)} chunks OWW "
                          f"→ {len(frames)} Silero (contiene voz)")

            print("🎤 Escuchando (Silero VAD)...")
            with sd.InputStream(
                samplerate=sr,
                channels=self.stt.cfg.channels,
                dtype=self.stt.cfg.dtype,
                blocksize=chunk_sz,
                device=self.stt.cfg.device,
            ) as stream:
                for _ in range(max_chunks):
                    if not self._running or self._interrupt_event.is_set():
                        break

                    chunk, overflowed = stream.read(chunk_sz)
                    if overflowed:
                        continue

                    flat     = chunk.flatten()
                    rms      = float(np.sqrt(np.mean(flat.astype(np.float32) ** 2)))
                    peak_rms = max(peak_rms, rms)
                    self.bridge.set_audio_level(min(1.0, rms / self._VU_NORM))

                    # Calibrar noise floor solo antes de que empiece la voz
                    if not voice_started:
                        self._update_noise_floor(rms)
                        noise_floor = self._get_noise_floor()

                    # Filtro rápido: sin energía → no gastar inferencia ONNX
                    if rms < noise_floor * 1.5 and not voice_started:
                        wait_count += 1
                        if wait_count == 100 and peak_rms < 5.0:
                            print("⚠️  Sin señal de audio. "
                                  "Verifica: Ajustes → Privacidad → Micrófono → Terminal ✓")
                        if wait_count >= wait_chunks:
                            break
                        continue

                    # ── Silero VAD ────────────────────────────────────────
                    audio_f = flat.astype(np.float32) / 32768.0
                    prob    = silero(audio_f, sr)

                    if prob >= self._SILERO_VOICE:
                        if not voice_started:
                            print("🎙️  Voz detectada (Silero)")
                            voice_started = True
                        silence_count = 0
                        voice_chunks += 1
                        frames.append(chunk.copy())

                    elif voice_started:
                        frames.append(chunk.copy())
                        silence_count += 1
                        # Silencio más corto para frases cortas, más largo para largas
                        is_long = (voice_chunks * chunk_sz / sr) >= 2.0
                        budget  = self._SILENCE_LONG if is_long else self._SILENCE_SHORT
                        if silence_count >= budget and prob < self._SILERO_SILEN:
                            ms = silence_count * chunk_sz * 1000 // sr
                            print(f"🔇 Silencio {ms}ms — fin de voz")
                            break
                    else:
                        wait_count += 1
                        if wait_count >= wait_chunks:
                            break

            self.bridge.set_audio_level(0.0)

            if self._interrupt_event.is_set():
                print("🛑 Grabación interrumpida")
                return None

            if not voice_started or not frames:
                if wait_timeout_s is not None:
                    return None  # follow-up: silencio = el usuario no quiso hablar
                print(f"⚠️ Sin voz detectada (RMS pico={peak_rms:.1f})")
                return self.stt.record_to_wav(out_path, seconds=5.0)

            audio = np.concatenate(frames, axis=0)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(out_path), "wb") as wf:
                wf.setnchannels(self.stt.cfg.channels)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(audio.tobytes())
            return out_path

        finally:
            self._is_recording = False

    # ── Context injection ─────────────────────────────────────────────────────

    def _get_context(self) -> str:
        """
        Genera una línea de contexto del entorno actual para inyectar al LLM.
        Incluye: hora, app activa, URL (si navegador), portapapeles (si hay texto).
        """
        parts: List[str] = []

        # Hora actual
        parts.append(f"hora: {datetime.now().strftime('%H:%M')}")

        # App activa via Accessibility API
        try:
            from jarvis.vision.accessibility import get_active_app
            app = get_active_app()
            name = app.get("name", "")
            if name and name not in ("Unknown", "Jarvis"):
                parts.append(f"app activa: {name}")
                title = (app.get("window_title") or "").strip()
                if title and title != name:
                    parts.append(f"ventana: {title[:60]}")
                url = (app.get("url") or "").strip()
                if url:
                    parts.append(f"URL: {url[:80]}")
        except Exception:
            pass

        # Portapapeles (solo si hay texto relevante)
        clip = self._clipboard.text.strip()
        if len(clip) > 5:
            # Truncar y limpiar para no contaminar el prompt
            clip_display = clip[:200].replace("\n", " ↵ ")
            parts.append(f'portapapeles: «{clip_display}»')

        # Camera context (presencia del usuario y objetos detectados)
        if self._camera_ctx:
            cam_snippet = self._camera_ctx.get_context_snippet()
            if cam_snippet:
                parts.append(cam_snippet)

        return " | ".join(parts)

    # ── Handlers de petición ─────────────────────────────────────────────────

    def _handle_request(self) -> None:
        """Un ciclo completo: graba → transcribe → LLM → TTS + HUD."""
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

            try:
                response = self.agent.run(augmented)
                self._llm_cb.record_success()
            except Exception as llm_err:
                self._llm_cb.record_failure()
                raise llm_err

            # ── Actualizar tracker con la respuesta del LLM
            self.agent.intent_tracker.analyze_llm_response(response)

            if not response or self._interrupt_event.is_set():
                return

            print(f"🤖 Jarvis: «{response}»")
            self.bridge.set_state("acting")

            # ── Actualizar chat panel con la respuesta
            if self._chat_panel is not None:
                self._chat_panel.add_jarvis_message(response)

            # ── Mostrar respuesta en HUD; añadir estado de intent si está activo
            intent_status = self.agent.intent_tracker.get_status_text()
            hud_text = f"{intent_status}\n\n{response}" if intent_status else response
            self._hud.show_text(hud_text)

            # ── Limpiar para TTS: sin markdown, sin <function=...>, sin anotaciones
            speech_text = _clean_for_speech(response)
            if not speech_text:
                self.bridge.set_state("idle")
                return

            # ── Hablar respuesta completa de una vez → sin pausas entre frases
            if not self._interrupt_event.is_set():
                self.tts.speak_nonblocking(speech_text)
                while self.tts.is_speaking:
                    if self._interrupt_event.is_set():
                        self.tts.stop()
                        break
                    time.sleep(0.05)

        except Exception as e:
            print(f"⚠️ Error procesando texto: {e}")
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
                self._interrupt_event.set()
                self._trigger_queue.put("hotkey")

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
