"""
tts.py

Text-to-Speech con múltiples engines:
- Kokoro (voz neural local)
- Piper (voz neural local)
- macOS 'say' (fallback)
"""

from __future__ import annotations

import logging
import queue as _queue_mod
import re
import shlex
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

_logger = logging.getLogger(__name__)

# Sentinel para distinguir "cola aún no leída" de None (fin de stream)
_QUEUE_EMPTY = object()

# ── URLs del modelo Kokoro ─────────────────────────────────────────────────────
_KOKORO_MODEL_DIR = Path.home() / "Documents" / "Jarvis" / "models" / "kokoro"
_KOKORO_MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/kokoro-v1.0.onnx"
)
_KOKORO_VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/voices-v1.0.bin"
)


def _split_long_text(text: str, max_chars: int = 500) -> List[str]:
    """
    Divide el texto en segmentos a límites de frase si supera max_chars.
    Garantiza que ningún segmento supere max_chars (salvo frases individuales
    que ya superen ese límite).
    """
    if len(text) <= max_chars:
        return [text]

    parts = re.split(r"(?<=[.!?…])\s+", text)
    segments: List[str] = []
    current = ""
    for part in parts:
        if current and len(current) + 1 + len(part) > max_chars:
            segments.append(current.strip())
            current = part
        else:
            current = f"{current} {part}".strip() if current else part
    if current:
        segments.append(current.strip())
    return segments or [text]


# ─────────────────────────────────────────────────────────────────────────────
# Motor Kokoro ONNX
# ─────────────────────────────────────────────────────────────────────────────

class _KokoroEngine:
    """
    Wrapper de kokoro-onnx optimizado para Apple Silicon.

    - Descarga automática de los ficheros del modelo (~300 MB en total) en primer uso.
    - Carga el modelo una sola vez en memoria.
    - Precalienta el modelo al arrancar para evitar latencia en la primera llamada.
    - `create(text, voice, speed, lang)` devuelve (samples_ndarray, sample_rate).
    """

    def __init__(self, model_dir: Optional[Path] = None) -> None:
        self._model_dir: Path = model_dir or _KOKORO_MODEL_DIR
        self._kokoro: Optional[object] = None
        self.loaded: bool = False
        self._warmup_ok: bool = False

    # ── Carga ──────────────────────────────────────────────────────────────

    def load(self, voice: str, speed: float, lang: str) -> bool:
        """
        Descarga (si es necesario) y carga el modelo Kokoro.
        Retorna True si la carga fue exitosa.
        """
        try:
            from kokoro_onnx import Kokoro  # type: ignore[import]
        except ImportError:
            _logger.warning(
                "[Kokoro] kokoro-onnx no instalado. "
                "Instala con: pip install 'jarvis-agent[kokoro]'"
            )
            return False

        model_path = self._model_dir / "kokoro-v1.0.onnx"
        voices_path = self._model_dir / "voices-v1.0.bin"

        if not model_path.exists() or not voices_path.exists():
            if not self._download():
                return False

        try:
            _logger.info("[Kokoro] Cargando modelo desde %s ...", self._model_dir)
            self._kokoro = Kokoro(str(model_path), str(voices_path))
            self.loaded = True
            _logger.info("[Kokoro] Modelo cargado correctamente.")
            self._warmup(voice, speed, lang)
            return True
        except Exception as exc:
            _logger.error("[Kokoro] Error cargando modelo: %s", exc)
            return False

    # ── Descarga ────────────────────────────────────────────────────────────

    # Tamaños mínimos esperados (en bytes) para detectar descargas incompletas
    _MIN_SIZES = {
        "kokoro-v1.0.onnx": 300 * 1024 * 1024,   # > 300 MB
        "voices-v1.0.bin":   10 * 1024 * 1024,   # > 10 MB
    }

    def _download(self) -> bool:
        """
        Descarga los ficheros del modelo si no existen. Retorna True si OK.

        Estrategia de descarga atómica:
          1. Descarga a fichero temporal (<nombre>.tmp).
          2. Muestra progreso en MB cada ~10%.
          3. Verifica que el tamaño final supera el mínimo esperado.
          4. Solo si la verificación pasa, renombra .tmp → destino final.
          5. Si algo falla o el fichero es demasiado pequeño, borra el .tmp
             y lanza una excepción descriptiva.
        """
        import requests  # ya es dependencia principal

        self._model_dir.mkdir(parents=True, exist_ok=True)

        files = [
            (_KOKORO_MODEL_URL, "kokoro-v1.0.onnx"),
            (_KOKORO_VOICES_URL, "voices-v1.0.bin"),
        ]

        _MAX_RETRIES = 3

        for url, filename in files:
            dest = self._model_dir / filename
            if dest.exists():
                continue

            tmp = dest.with_suffix(".tmp")
            tmp.unlink(missing_ok=True)  # limpiar restos de descarga anterior

            _logger.info(
                "[Kokoro] Descargando %s (puede tardar unos minutos)...", filename
            )

            success = False
            for attempt in range(_MAX_RETRIES):
                try:
                    resp = requests.get(url, stream=True, timeout=300)
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0))
                    total_mb = total / (1024 * 1024) if total else 0
                    downloaded = 0
                    last_logged_pct = -1

                    with open(tmp, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=1024 * 1024):
                            fh.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                pct = downloaded * 100 // total
                                if pct // 10 != last_logged_pct // 10:
                                    last_logged_pct = pct
                                    dl_mb = downloaded / (1024 * 1024)
                                    _logger.info(
                                        "[Kokoro] Descargando %s... %.0f MB / %.0f MB (%d%%)",
                                        filename, dl_mb, total_mb, pct,
                                    )

                    # Verificar tamaño mínimo antes de mover al destino final
                    actual_size = tmp.stat().st_size
                    min_size = self._MIN_SIZES.get(filename, 0)
                    if actual_size < min_size:
                        tmp.unlink(missing_ok=True)
                        raise RuntimeError(
                            f"Descarga incompleta: {filename} tiene {actual_size / 1024 / 1024:.1f} MB "
                            f"pero se esperan al menos {min_size / 1024 / 1024:.0f} MB. "
                            "Puede que la descarga se haya interrumpido."
                        )

                    # Mover al destino final solo cuando la descarga está 100% completa
                    tmp.rename(dest)
                    _logger.info(
                        "[Kokoro] Descarga completada: %s (%.0f MB)",
                        filename, actual_size / (1024 * 1024),
                    )
                    success = True
                    break  # éxito

                except Exception as exc:
                    tmp.unlink(missing_ok=True)
                    if attempt < _MAX_RETRIES - 1:
                        wait = 2 ** attempt  # 1s, 2s, 4s
                        _logger.warning(
                            "[Kokoro] Error descargando %s: %s — reintentando en %ds...",
                            filename, exc, wait,
                        )
                        time.sleep(wait)
                    else:
                        _logger.error("[Kokoro] Error descargando %s: %s", filename, exc)

            if not success:
                return False

        return True

    # ── Warmup ──────────────────────────────────────────────────────────────

    def _warmup(self, voice: str, speed: float, lang: str) -> None:
        """Pre-JIT del modelo con texto silencioso para reducir latencia del primer uso."""
        try:
            self._kokoro.create("hola", voice=voice, speed=speed, lang=lang)  # type: ignore[union-attr]
            self._warmup_ok = True
            _logger.debug("[Kokoro] Warmup completado.")
        except Exception as exc:
            _logger.warning("[Kokoro] Warmup falló (no crítico): %s", exc)

    # ── Síntesis ────────────────────────────────────────────────────────────

    def create(
        self, text: str, voice: str, speed: float, lang: str
    ) -> Tuple[object, int]:
        """
        Genera audio para `text`. Retorna (samples_ndarray, sample_rate).
        Lanza RuntimeError si el modelo no está cargado.
        """
        if not self.loaded or self._kokoro is None:
            raise RuntimeError("Kokoro no está cargado")
        return self._kokoro.create(text, voice=voice, speed=speed, lang=lang)  # type: ignore[union-attr]


@dataclass
class TTSConfig:
    engine: str = "kokoro"  # kokoro, piper, macos
    voice_model: Optional[str] = None  # Piper: ruta al .onnx
    voice: Optional[str] = None       # macOS: nombre de voz
    rate: Optional[int] = None        # macOS: velocidad (palabras/min)
    # Kokoro (TTS local, Apple Silicon)
    kokoro_voice: str = "ef_dora"      # Voces ES: ef_dora, em_alex, em_santa
    kokoro_speed: float = 1.0          # Velocidad de síntesis (0.5 – 2.0)
    kokoro_language: str = "es"        # Idioma: "es" | "en-us" | "en-gb" | etc.
    kokoro_model_dir: Optional[str] = None  # None → ~/Documents/Jarvis/models/kokoro


class TTS:
    def __init__(self, cfg: Optional[TTSConfig] = None):
        self.cfg = cfg or TTSConfig()

        # Estado de reproducción
        self._current_proc: Optional[subprocess.Popen] = None
        self._speech_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._kokoro: Optional[_KokoroEngine] = None

        # ── Kokoro (engine local por defecto) ─────────────────────────────
        if self.cfg.engine == "kokoro":
            model_dir = (
                Path(self.cfg.kokoro_model_dir)
                if self.cfg.kokoro_model_dir
                else None
            )
            kokoro = _KokoroEngine(model_dir=model_dir)
            if kokoro.load(
                voice=self.cfg.kokoro_voice,
                speed=self.cfg.kokoro_speed,
                lang=self.cfg.kokoro_language,
            ):
                self._kokoro = kokoro
            else:
                print("⚠️ Kokoro no disponible. Usando macOS 'say'.")
                self.cfg.engine = "macos"

        # ── Piper ─────────────────────────────────────────────────────────
        if self.cfg.engine == "piper" and not self.cfg.voice_model:
            default_voice = Path("data/voices/es_ES-davefx-medium.onnx")
            if default_voice.exists():
                self.cfg.voice_model = str(default_voice)
            else:
                print("⚠️ Voz Piper no encontrada. Usando macOS 'say'")
                self.cfg.engine = "macos"

        if self.cfg.engine not in {"kokoro", "piper", "macos"}:
            print(f"⚠️ Engine TTS no soportado ({self.cfg.engine}). Usando macOS 'say'.")
            self.cfg.engine = "macos"

    def speak(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            return {"command": "", "returncode": 0, "stdout": "", "stderr": ""}

        if self.cfg.engine == "kokoro" and self._kokoro is not None:
            return self._speak_kokoro(text)
        elif self.cfg.engine == "piper" and self.cfg.voice_model:
            return self._speak_piper(text)
        else:
            return self._speak_macos(text)

    def _speak_kokoro(self, text: str) -> dict:
        """
        Sintetiza y reproduce audio con Kokoro ONNX.

        Si el texto supera 500 chars, lo divide en segmentos a límites de frase
        antes de sintetizar para evitar timeouts. Cada segmento se reproduce
        con sounddevice de forma interruptible.
        """
        import sounddevice as sd

        segments = _split_long_text(text, max_chars=500)

        for segment in segments:
            if self._stop_event.is_set():
                break
            segment = segment.strip()
            if not segment:
                continue

            t0 = time.monotonic()
            try:
                samples, sr = self._kokoro.create(  # type: ignore[union-attr]
                    segment,
                    voice=self.cfg.kokoro_voice,
                    speed=self.cfg.kokoro_speed,
                    lang=self.cfg.kokoro_language,
                )
            except Exception as exc:
                _logger.error("[Kokoro] Síntesis falló: %s — fallback macOS", exc)
                return self._speak_macos(text)

            elapsed_ms = (time.monotonic() - t0) * 1000
            _logger.debug(
                "[Kokoro] Síntesis %.0fms para %d chars", elapsed_ms, len(segment)
            )

            if self._stop_event.is_set():
                break

            try:
                sd.play(samples, sr)
                # Polling interruptible en lugar de sd.wait() bloqueante
                chunk_duration = len(samples) / sr
                deadline = time.monotonic() + chunk_duration + 1.0
                while time.monotonic() < deadline:
                    if self._stop_event.wait(timeout=0.05):
                        sd.stop()
                        break
                    try:
                        if not sd.get_stream().active:
                            break
                    except Exception:
                        break
            except Exception as exc:
                _logger.warning("[Kokoro] Error reproduciendo audio: %s", exc)

        return {"command": "kokoro", "returncode": 0, "stdout": "", "stderr": ""}

    def _speak_piper(self, text: str) -> dict:
        """Habla usando Piper TTS."""
        try:
            # Crear archivo temporal para el WAV
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                wav_path = tmp.name
            
            # Ejecutar piper con echo | piper
            piper_cmd = f'echo {shlex.quote(text)} | piper --model {shlex.quote(self.cfg.voice_model)} --output_file {shlex.quote(wav_path)}'
            
            process = subprocess.run(
                piper_cmd,
                shell=True,
                capture_output=True,
                timeout=30,
            )
            
            if process.returncode != 0:
                print(f"⚠️ Error Piper: {process.stderr.decode()}")
                Path(wav_path).unlink(missing_ok=True)
                return self._speak_macos(text)
            
            # Reproducir con afplay (interruptible)
            proc = subprocess.Popen(
                ["afplay", wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._current_proc = proc
            proc.wait()
            self._current_proc = None

            Path(wav_path).unlink(missing_ok=True)

            return {
                "command": "piper → afplay",
                "returncode": proc.returncode,
                "stdout": "",
                "stderr": "",
            }
            
        except Exception as e:
            print(f"⚠️ Error Piper: {e}. Usando macOS 'say'")
            return self._speak_macos(text)

    # ── API no-bloqueante ──────────────────────────────────────────────────────

    def speak_nonblocking(self, text: str) -> None:
        """Inicia TTS en background sin bloquear. Usa stop() para interrumpir."""
        self.stop()
        self._stop_event.clear()
        self._speech_thread = threading.Thread(
            target=self.speak, args=(text,), daemon=True
        )
        self._speech_thread.start()

    def stop(self) -> None:
        """Para el TTS inmediatamente."""
        self._stop_event.set()
        proc = self._current_proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
            self._current_proc = None
        # Parar sounddevice (usado por Kokoro)
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        t = self._speech_thread
        if t is not None and t.is_alive():
            t.join(timeout=0.3)
        self._speech_thread = None

    def wait(self) -> None:
        """Espera a que termine el TTS actual."""
        t = self._speech_thread
        if t is not None and t.is_alive():
            t.join()

    @property
    def is_speaking(self) -> bool:
        """True si el TTS está reproduciendo audio."""
        t = self._speech_thread
        return t is not None and t.is_alive()

    def speak_all(
        self,
        sentences: List[str],
        *,
        interrupt_event: Optional[threading.Event] = None,
    ) -> None:
        """
        Habla una lista de frases en secuencia.
        Respeta _stop_event y el interrupt_event externo.
        """
        if not sentences:
            return

        def _interrupted() -> bool:
            if self._stop_event.is_set():
                return True
            if interrupt_event is not None and interrupt_event.is_set():
                return True
            return False

        for sentence in sentences:
            if _interrupted():
                return
            if not sentence.strip():
                continue
            self._stop_event.clear()
            self.speak(sentence)

    # ── API de streaming: consume frases desde una Queue ─────────────────────

    def speak_queued(
        self,
        sentence_queue: "_queue_mod.Queue[Optional[str]]",
        interrupt_event: Optional[threading.Event] = None,
        on_first_audio: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Consume frases de una Queue y las reproduce en secuencia.

        Protocolo de la cola:
          - str  → frase a reproducir
          - None → fin de stream (centinela)

        Llama on_first_audio() justo antes de reproducir el primer audio (métrica de latencia).
        Respeta _stop_event e interrupt_event.
        """
        def _interrupted() -> bool:
            if self._stop_event.is_set():
                return True
            if interrupt_event is not None and interrupt_event.is_set():
                return True
            return False

        first_played = False
        while True:
            if _interrupted():
                return
            try:
                sentence = sentence_queue.get(timeout=0.1)
            except _queue_mod.Empty:
                continue
            if sentence is None:
                return  # fin de stream
            if not sentence.strip():
                continue
            if not first_played:
                first_played = True
                if on_first_audio:
                    on_first_audio()
            self._stop_event.clear()
            self.speak(sentence)

    def speak_streaming(
        self,
        sentence_queue: "_queue_mod.Queue[Optional[str]]",
        interrupt_event: Optional[threading.Event] = None,
        on_first_audio: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Versión no-bloqueante de speak_queued().
        Inicia la reproducción en un thread daemon y retorna inmediatamente.
        Usar is_speaking para saber si sigue activo, stop() para interrumpir.
        """
        self.stop()
        self._stop_event.clear()
        self._speech_thread = threading.Thread(
            target=self.speak_queued,
            args=(sentence_queue, interrupt_event, on_first_audio),
            daemon=True,
        )
        self._speech_thread.start()

    def _speak_macos(self, text: str) -> dict:
        """Fallback a macOS 'say'."""
        cmd = ["say"]
        if self.cfg.voice:
            cmd += ["-v", self.cfg.voice]
        if self.cfg.rate is not None:
            cmd += ["-r", str(int(self.cfg.rate))]
        cmd.append(text)

        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._current_proc = proc
        proc.wait()
        self._current_proc = None

        return {
            "command": " ".join(shlex.quote(x) for x in cmd),
            "returncode": proc.returncode,
            "stdout": "",
            "stderr": "",
        }
