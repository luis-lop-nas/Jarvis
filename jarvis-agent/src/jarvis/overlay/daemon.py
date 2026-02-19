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

from jarvis.agent.tool_agent import ToolAgent, ToolAgentConfig, tool_agent_from_settings
from jarvis.memory.store import MemoryStore
from jarvis.tools.registry import ToolRegistry, ToolSpec, build_default_registry
from jarvis.voice.stt import STT, STTConfig
from jarvis.voice.tts import TTS, TTSConfig


# ── Sentence splitter ─────────────────────────────────────────────────────────

def _split_sentences(text: str) -> List[str]:
    """
    Divide el texto en frases para TTS progresivo.
    Frases cortas (<25 chars) se agrupan con la siguiente para sonar naturales.
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
        if len(buffer) >= 25 and re.search(r'[.!?…]$', buffer):
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

    # VAD
    _VAD_CHUNK_MS     = 30
    _VAD_THRESHOLD    = 300
    _VAD_SILENCE_SEGS = 30
    _VAD_TIMEOUT_S    = 15.0
    _VAD_MAX_S        = 30.0

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

        # ── Popup de texto (hotkey)
        from jarvis.overlay.text_input import TextInputPopup
        self._text_popup = TextInputPopup(bridge)

        # ── Chat panel (se asigna desde main.py tras crear el panel)
        self._chat_panel = None

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

    def start(self) -> None:
        self._running = True
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
            elif source == "hotkey":
                self._handle_hotkey_request()
            else:
                self._handle_request()

    def _wake_word_loop(self) -> None:
        """Thread siempre activo que detecta wake word incluso mientras Jarvis habla."""
        while self._running and self._wake_listener is not None:
            try:
                detected = self._wake_listener.wait_for_wake(timeout_sec=0.5)
                if detected and self._running:
                    print("🎤 Wake word detectado")
                    self._interrupt_event.set()
                    self._trigger_queue.put("wake_word")
            except Exception as e:
                if self._running:
                    print(f"⚠️ Wake word loop error: {e}")
                time.sleep(0.5)

    # ── Grabación con VAD + VU meter ─────────────────────────────────────────

    def _record_with_vad(self, out_path: Path) -> Optional[Path]:
        """
        Graba audio con VAD y VU meter en tiempo real.
        Retorna ruta del WAV o None si fue interrumpida.
        """
        sr         = self.stt.cfg.sample_rate
        chunk_sz   = int(sr * self._VAD_CHUNK_MS / 1000)
        max_chunks = int(self._VAD_MAX_S * 1000 / self._VAD_CHUNK_MS)
        wait_chunks = int(self._VAD_TIMEOUT_S * 1000 / self._VAD_CHUNK_MS)

        frames: list[np.ndarray] = []
        voice_started = False
        silence_count = 0
        wait_count    = 0

        print("🎤 Escuchando...")
        with sd.InputStream(
            samplerate=sr,
            channels=self.stt.cfg.channels,
            dtype=self.stt.cfg.dtype,
            blocksize=chunk_sz,
        ) as stream:
            for _ in range(max_chunks):
                if not self._running or self._interrupt_event.is_set():
                    break

                chunk, _ = stream.read(chunk_sz)
                rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

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
                    if wait_count >= wait_chunks:
                        break

        self.bridge.set_audio_level(0.0)

        if self._interrupt_event.is_set():
            print("🛑 Grabación interrumpida")
            return None

        if not voice_started or not frames:
            print("⚠️ Sin voz detectada, grabando 5s fijos...")
            return self.stt.record_to_wav(out_path, seconds=5.0)

        audio = np.concatenate(frames, axis=0)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(self.stt.cfg.channels)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(audio.tobytes())

        return out_path

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

        return " | ".join(parts)

    # ── Handlers de petición ─────────────────────────────────────────────────

    def _handle_request(self) -> None:
        """Un ciclo completo: graba → transcribe → LLM → TTS + HUD."""
        self._hud.hide()
        try:
            self.bridge.set_state("listening")
            audio_path = self._record_with_vad(self._wav_path)

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

        self._process_text(text)

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
        self._process_text(text)

    def _handle_chat_text(self, text: str) -> None:
        """Chat panel: procesa texto enviado directamente (sin grabación)."""
        self._hud.hide()
        print(f"💬 Chat: «{text}»")
        # El mensaje de usuario ya fue añadido al panel por _submit_text
        self._process_text(text, from_chat_panel=True)

    def _process_text(self, text: str, from_chat_panel: bool = False) -> None:
        """
        Envía texto al LLM con contexto automático y reproduce frase a frase.
        Muestra el texto completo en el HUD mientras el TTS habla.

        from_chat_panel=True → el mensaje usuario ya está en el panel; no duplicar.
        """
        if self._interrupt_event.is_set():
            return

        try:
            self.bridge.set_state("thinking")

            # ── Añadir mensaje usuario al chat panel (si viene de voz/hotkey)
            if self._chat_panel is not None and not from_chat_panel:
                self._chat_panel.add_user_message(text)

            # ── Inyectar contexto del entorno automáticamente
            context = self._get_context()
            if context:
                augmented = f"{text}\n\n[Sistema: {context}]"
            else:
                augmented = text

            response = self.agent.run(augmented)

            if not response or self._interrupt_event.is_set():
                return

            print(f"🤖 Jarvis: «{response}»")
            self.bridge.set_state("acting")

            # ── Actualizar chat panel con la respuesta
            if self._chat_panel is not None:
                self._chat_panel.add_jarvis_message(response)

            # ── Mostrar respuesta completa en el HUD
            self._hud.show_text(response)

            # ── Hablar frase a frase (permite interrupciones entre frases)
            sentences = _split_sentences(response)
            for sentence in sentences:
                if self._interrupt_event.is_set():
                    break

                self.tts.speak_nonblocking(sentence)

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

    # ── Accesibilidad ─────────────────────────────────────────────────────────

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
            # Sensibilidad baja (0.15) para detectar independientemente del acento
            sensitivity = 0.15
            cfg = WakeWordConfig(
                engine=getattr(s, "wake_word_engine", "openwakeword"),
                oww_model=getattr(s, "wake_word_model", "hey_jarvis"),
                sensitivity=sensitivity,
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

            self._hotkey_listener = keyboard.GlobalHotKeys(
                {self.HOTKEY: on_activate}
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
