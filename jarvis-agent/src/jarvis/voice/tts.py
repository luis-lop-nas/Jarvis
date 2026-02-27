"""
tts.py

Text-to-Speech con múltiples engines:
- ElevenLabs (voz personalizada de alta calidad)
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
from dataclasses import dataclass, field
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

    def _download(self) -> bool:
        """Descarga los ficheros del modelo si no existen. Retorna True si OK."""
        import requests  # ya es dependencia principal

        self._model_dir.mkdir(parents=True, exist_ok=True)

        files = [
            (_KOKORO_MODEL_URL, "kokoro-v1.0.onnx"),
            (_KOKORO_VOICES_URL, "voices-v1.0.bin"),
        ]

        for url, filename in files:
            dest = self._model_dir / filename
            if dest.exists():
                continue
            _logger.info("[Kokoro] Descargando %s (puede tardar unos minutos)...", filename)
            try:
                resp = requests.get(url, stream=True, timeout=300)
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded * 100 // total
                            if pct % 10 == 0:
                                _logger.info("[Kokoro] %s: %d%%", filename, pct)
                _logger.info("[Kokoro] Descarga completada: %s", filename)
            except Exception as exc:
                _logger.error("[Kokoro] Error descargando %s: %s", filename, exc)
                dest.unlink(missing_ok=True)
                return False

        return True

    # ── Warmup ──────────────────────────────────────────────────────────────

    def _warmup(self, voice: str, speed: float, lang: str) -> None:
        """Pre-JIT del modelo con texto silencioso para reducir latencia del primer uso."""
        try:
            self._kokoro.create("hola", voice=voice, speed=speed, lang=lang)  # type: ignore[union-attr]
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
    engine: str = "kokoro"  # kokoro, elevenlabs, piper, macos
    voice_model: Optional[str] = None  # Piper: ruta al .onnx
    voice: Optional[str] = None       # macOS: nombre de voz
    rate: Optional[int] = None        # macOS: velocidad (palabras/min)
    # ElevenLabs
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None
    elevenlabs_model: str = "eleven_multilingual_v2"
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

        # ── ElevenLabs ────────────────────────────────────────────────────
        if self.cfg.engine == "elevenlabs":
            if not self.cfg.elevenlabs_api_key or not self.cfg.elevenlabs_voice_id:
                print("⚠️ ElevenLabs no configurado. Intentando Piper...")
                self.cfg.engine = "piper"

        # ── Piper ─────────────────────────────────────────────────────────
        if self.cfg.engine == "piper" and not self.cfg.voice_model:
            default_voice = Path("data/voices/es_ES-davefx-medium.onnx")
            if default_voice.exists():
                self.cfg.voice_model = str(default_voice)
            else:
                print("⚠️ Voz Piper no encontrada. Usando macOS 'say'")
                self.cfg.engine = "macos"

    def speak(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            return {"command": "", "returncode": 0, "stdout": "", "stderr": ""}

        if self.cfg.engine == "kokoro" and self._kokoro is not None:
            return self._speak_kokoro(text)
        elif self.cfg.engine == "elevenlabs":
            return self._speak_elevenlabs(text)
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
                sd.wait()  # bloqueante; sd.stop() desde otro hilo retorna aquí
            except Exception as exc:
                _logger.warning("[Kokoro] Error reproduciendo audio: %s", exc)

        return {"command": "kokoro", "returncode": 0, "stdout": "", "stderr": ""}

    def _speak_elevenlabs(self, text: str) -> dict:
        """Habla usando ElevenLabs TTS (SDK v2.x)."""
        try:
            from elevenlabs.types import VoiceSettings
            from elevenlabs.client import ElevenLabs

            client = ElevenLabs(api_key=self.cfg.elevenlabs_api_key)

            # Generar audio como stream de chunks MP3
            audio_iter = client.text_to_speech.convert(
                voice_id=self.cfg.elevenlabs_voice_id,
                text=text,
                model_id=self.cfg.elevenlabs_model,
                output_format="mp3_44100_128",
                voice_settings=VoiceSettings(
                    stability=0.5,
                    similarity_boost=0.75,
                    style=0.0,
                    use_speaker_boost=True,
                ),
            )

            # Escribir en archivo temporal y reproducir con afplay (interruptible)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                mp3_path = f.name
                for chunk in audio_iter:
                    if self._stop_event.is_set():
                        break
                    f.write(chunk)

            if self._stop_event.is_set():
                Path(mp3_path).unlink(missing_ok=True)
                return {"command": "elevenlabs", "returncode": 0, "stdout": "stopped", "stderr": ""}

            proc = subprocess.Popen(
                ["afplay", mp3_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._current_proc = proc
            proc.wait()
            self._current_proc = None
            Path(mp3_path).unlink(missing_ok=True)

            return {
                "command": "elevenlabs → afplay",
                "returncode": proc.returncode,
                "stdout": "",
                "stderr": "",
            }

        except ImportError:
            print("⚠️ elevenlabs no instalado. Instala con: pip install elevenlabs")
            return self._speak_macos(text)
        except Exception as e:
            print(f"⚠️ Error ElevenLabs: {e}. Usando fallback...")
            return self._speak_macos(text)

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
        # Parar sounddevice (usado por ElevenLabs)
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

    # ── Prefetch + reproducción encadenada ───────────────────────────────────

    def _fetch_elevenlabs_audio(self, text: str) -> Optional[str]:
        """
        Descarga audio ElevenLabs a un archivo temporal.
        Retorna la ruta del MP3 o None si falla / fue interrumpido.
        """
        try:
            from elevenlabs.types import VoiceSettings
            from elevenlabs.client import ElevenLabs

            client = ElevenLabs(api_key=self.cfg.elevenlabs_api_key)
            audio_iter = client.text_to_speech.convert(
                voice_id=self.cfg.elevenlabs_voice_id,
                text=text,
                model_id=self.cfg.elevenlabs_model,
                output_format="mp3_44100_128",
                voice_settings=VoiceSettings(
                    stability=0.5,
                    similarity_boost=0.75,
                    style=0.0,
                    use_speaker_boost=True,
                ),
            )
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                mp3_path = f.name
                for chunk in audio_iter:
                    if self._stop_event.is_set():
                        Path(mp3_path).unlink(missing_ok=True)
                        return None
                    f.write(chunk)
            return mp3_path
        except Exception as e:
            print(f"⚠️ ElevenLabs prefetch error: {e}")
            return None

    def speak_all(
        self,
        sentences: List[str],
        *,
        interrupt_event: Optional[threading.Event] = None,
    ) -> None:
        """
        Habla una lista de frases minimizando los huecos entre ellas.
        Para ElevenLabs: pre-descarga la siguiente frase mientras reproduce la actual.
        Para otros motores: habla secuencialmente.
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

        if self.cfg.engine != "elevenlabs":
            for s in sentences:
                if _interrupted():
                    return
                self._stop_event.clear()
                self.speak(s)
            return

        # ── ElevenLabs: prefetch encadenado ──────────────────────────────────

        def _fetch_async(text: str, result_q: _queue_mod.Queue) -> None:
            result_q.put(self._fetch_elevenlabs_audio(text))

        # Arrancar descarga del primer chunk inmediatamente
        current_q: _queue_mod.Queue = _queue_mod.Queue(maxsize=1)
        threading.Thread(
            target=_fetch_async, args=(sentences[0], current_q), daemon=True
        ).start()

        for i, _sentence in enumerate(sentences):
            if _interrupted():
                return

            # Arrancar descarga del siguiente chunk antes de que acabe el actual
            next_q: Optional[_queue_mod.Queue] = None
            if i + 1 < len(sentences) and not _interrupted():
                next_q = _queue_mod.Queue(maxsize=1)
                threading.Thread(
                    target=_fetch_async, args=(sentences[i + 1], next_q), daemon=True
                ).start()

            # Esperar a que el audio del chunk actual esté listo
            audio_path: Optional[str] = current_q.get()

            if audio_path is None or _interrupted():
                current_q = next_q  # type: ignore[assignment]
                continue

            # Reproducir con afplay
            self._stop_event.clear()
            proc = subprocess.Popen(
                ["afplay", audio_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._current_proc = proc

            while proc.poll() is None:
                if _interrupted():
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break
                time.sleep(0.05)

            self._current_proc = None
            Path(audio_path).unlink(missing_ok=True)

            # Avanzar a la cola del siguiente chunk
            current_q = next_q  # type: ignore[assignment]

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

        Para ElevenLabs: pre-descarga la siguiente frase mientras reproduce la actual.
        Para otros motores: reproducción secuencial.
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

        if self.cfg.engine != "elevenlabs":
            # Motor no-ElevenLabs: reproducción secuencial directa
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
            return

        # ── ElevenLabs: prefetch encadenado ──────────────────────────────────

        def _fetch_async(text: str, result_q: "_queue_mod.Queue[Optional[str]]") -> None:
            result_q.put(self._fetch_elevenlabs_audio(text))

        # Cola donde iremos acumulando (sentence, audio_queue) pares
        # Cargamos el primer item de sentence_queue y arrancamos su descarga
        pending: List[tuple] = []  # List[(sentence_text, audio_result_queue)]

        def _maybe_prefetch_next() -> None:
            """Lee la siguiente frase disponible y arranca su descarga si no está ya pendiente."""
            while len(pending) < 2:
                try:
                    sentence = sentence_queue.get_nowait()
                except _queue_mod.Empty:
                    break
                if sentence is None:
                    pending.append((None, None))  # marca de fin
                    break
                if not sentence.strip():
                    continue
                rq: "_queue_mod.Queue[Optional[str]]" = _queue_mod.Queue(maxsize=1)
                threading.Thread(target=_fetch_async, args=(sentence, rq), daemon=True).start()
                pending.append((sentence, rq))

        # Arrancar primera descarga
        _maybe_prefetch_next()

        while True:
            if _interrupted():
                return

            # Asegurarnos de tener al menos un item
            if not pending:
                # Esperar a que llegue algo
                try:
                    sentence = sentence_queue.get(timeout=0.1)
                except _queue_mod.Empty:
                    if _interrupted():
                        return
                    continue
                if sentence is None:
                    return  # fin de stream
                if not sentence.strip():
                    continue
                rq = _queue_mod.Queue(maxsize=1)
                threading.Thread(target=_fetch_async, args=(sentence, rq), daemon=True).start()
                pending.append((sentence, rq))

            sentence_text, audio_rq = pending.pop(0)

            if sentence_text is None:
                return  # fin de stream

            # Arrancar prefetch del siguiente mientras esperamos este audio
            _maybe_prefetch_next()

            # Esperar a que el audio esté listo
            audio_path: Optional[str] = audio_rq.get()

            if audio_path is None or _interrupted():
                if audio_path:
                    from pathlib import Path as _Path
                    _Path(audio_path).unlink(missing_ok=True)
                continue  # intentar siguiente

            if not first_played:
                first_played = True
                if on_first_audio:
                    on_first_audio()

            # Reproducir con afplay
            self._stop_event.clear()
            proc = subprocess.Popen(
                ["afplay", audio_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._current_proc = proc

            while proc.poll() is None:
                if _interrupted():
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break
                # Aprovechamos la reproducción para prefetch del siguiente
                _maybe_prefetch_next()
                time.sleep(0.05)

            self._current_proc = None
            Path(audio_path).unlink(missing_ok=True)

            if _interrupted():
                return

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
