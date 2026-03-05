"""
orchestrator.py

VoiceOrchestrator: encapsula toda la lógica de grabación con VAD.
Extraído de daemon.py para ser testeable de forma independiente.

Soporta:
  - Silero VAD (ONNX, óptima) con adaptive silence (#3)
  - Fallback por RMS si Silero no está disponible
  - Noise floor adaptativo (EMA)
  - Pre-buffer de wake word
  - VU meter callback
"""
from __future__ import annotations

import threading
import wave
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from jarvis.voice.stt import STTConfig
from jarvis.voice.vad import SileroVAD


class VoiceOrchestrator:
    """
    Gestiona la grabación de audio con VAD.
    Thread-safe: noise floor protegido con lock.
    """

    # Constantes VAD RMS (legacy — fallback)
    VAD_CHUNK_MS     = 30
    VAD_THRESHOLD    = 300
    VAD_SILENCE_SEGS = 15
    VAD_TIMEOUT_S    = 15.0
    VAD_MAX_S        = 30.0

    # Constantes VAD Silero (ML, chunks de 512 samples = 32ms a 16kHz)
    SILERO_CHUNK = 512
    SILERO_VOICE = 0.35   # prob >= 0.35 → voz activa
    SILERO_SILEN = 0.25   # prob < 0.25  → pausa suave
    SILERO_HARD  = 0.10   # prob < 0.10  → silencio absoluto
    SILENCE_SHORT = 10    # chunks para frases cortas (< 2s de voz)
    SILENCE_LONG  = 15    # chunks para frases largas (>= 2s de voz)

    # Noise floor
    NF_ALPHA = 0.05    # EMA lenta: no reacciona a picos de voz
    NF_INIT  = 200.0   # RMS inicial int16 antes de calibrar

    # VU meter: 3000 RMS ≈ voz normal conversacional
    VU_NORM = 3000.0

    def __init__(
        self,
        stt_cfg: STTConfig,
        interrupt_event: threading.Event,
        on_audio_level: Optional[Callable[[float], None]] = None,
        vad_engine: str = "silero",
    ) -> None:
        self._stt_cfg = stt_cfg
        self._interrupt_event = interrupt_event
        self._on_audio_level = on_audio_level
        self._vad_engine = vad_engine

        # Silero VAD (lazy load en primer uso)
        self._silero: Optional[SileroVAD] = None
        self._silero_loaded: bool = False

        # Noise floor adaptativo (int16 RMS)
        self._noise_floor: float = self.NF_INIT
        self._noise_floor_lock = threading.Lock()

    # ── VAD helpers ───────────────────────────────────────────────────────────

    def _get_silero(self) -> Optional[SileroVAD]:
        """Carga Silero VAD la primera vez que se necesita (lazy, thread-safe por GIL)."""
        if not self._silero_loaded:
            self._silero_loaded = True
            if self._vad_engine == "silero":
                self._silero = SileroVAD.load()
        return self._silero

    def _update_noise_floor(self, rms: float) -> None:
        """Actualiza noise floor con EMA lenta. Solo llamar durante silencio pre-voz."""
        with self._noise_floor_lock:
            self._noise_floor = (
                self.NF_ALPHA * rms + (1.0 - self.NF_ALPHA) * self._noise_floor
            )

    def _get_noise_floor(self) -> float:
        with self._noise_floor_lock:
            return self._noise_floor

    def _set_audio_level(self, rms: float) -> None:
        if self._on_audio_level is not None:
            self._on_audio_level(min(1.0, rms / self.VU_NORM))

    # ── Grabación principal ───────────────────────────────────────────────────

    def record(
        self,
        out_path: Path,
        prebuffer: Optional[list] = None,
        wait_timeout_s: Optional[float] = None,
    ) -> Optional[Path]:
        """
        Puerta de entrada: despacha a Silero VAD o RMS según disponibilidad.

        Args:
            out_path: ruta destino del fichero WAV.
            prebuffer: lista de np.ndarray int16 del ring buffer pre-wake.
            wait_timeout_s: timeout máx esperando inicio de voz. None → VAD_TIMEOUT_S.

        Returns:
            Path al WAV grabado, o None si hubo interrupción/timeout.
        """
        if wait_timeout_s is not None:
            wait_timeout_s = max(0.5, min(wait_timeout_s, 60.0))
        silero = self._get_silero()
        if silero is not None:
            return self._record_silero(out_path, wait_timeout_s, prebuffer or [], silero)
        return self._record_rms(out_path, wait_timeout_s)

    # ── Grabación Silero VAD ──────────────────────────────────────────────────

    def _record_silero(
        self,
        out_path: Path,
        wait_timeout_s: Optional[float],
        prebuffer: list,
        silero: SileroVAD,
    ) -> Optional[Path]:
        """
        Graba audio usando Silero VAD (ONNX) con adaptive silence.
        - pre-buffer: audio capturado antes de la wake word (1.5s)
        - Noise floor adaptativo: calibra el umbral al ruido ambiental
        - Adaptive silence: silencio suave +0.5 / silencio duro +1.0 por chunk
        """
        sr          = self._stt_cfg.sample_rate           # 16000
        chunk_sz    = self.SILERO_CHUNK                    # 512 samples = 32ms
        max_chunks  = int(self.VAD_MAX_S * sr / chunk_sz)
        wait_chunks = int((wait_timeout_s if wait_timeout_s is not None
                           else self.VAD_TIMEOUT_S) * sr / chunk_sz)

        frames: list        = []
        voice_started       = False
        silence_count: float = 0.0
        voice_chunks        = 0     # chunks con voz (para elegir silence budget)
        wait_count          = 0
        peak_rms            = 0.0
        silero.reset_states()
        noise_floor = self._get_noise_floor()

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
                channels=self._stt_cfg.channels,
                dtype=self._stt_cfg.dtype,
                blocksize=chunk_sz,
                device=self._stt_cfg.device,
            ) as stream:
                for _ in range(max_chunks):
                    if self._interrupt_event.is_set():
                        break

                    chunk, overflowed = stream.read(chunk_sz)
                    if overflowed:
                        continue

                    flat     = chunk.flatten()
                    rms      = float(np.sqrt(np.mean(flat.astype(np.float32) ** 2)))
                    peak_rms = max(peak_rms, rms)
                    self._set_audio_level(rms)

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

                    # ── Silero VAD ────────────────────────────────────────────
                    audio_f = flat.astype(np.float32) / 32768.0
                    try:
                        prob = silero(audio_f, sr)
                    except Exception as _vad_exc:
                        import logging as _logging
                        _logging.getLogger(__name__).warning(
                            "VAD Silero error: %s — reset estado", _vad_exc
                        )
                        silero.reset_states()
                        # Fallback RMS para este chunk
                        prob = 1.0 if rms > noise_floor * 2.5 else 0.0

                    if prob >= self.SILERO_VOICE:
                        if not voice_started:
                            print("🎙️  Voz detectada (Silero)")
                            voice_started = True
                        silence_count = 0.0
                        voice_chunks += 1
                        frames.append(chunk.copy())

                    elif voice_started:
                        frames.append(chunk.copy())
                        # Adaptive silence: silencio duro +1.0, pausa suave +0.5
                        if prob < self.SILERO_HARD:
                            silence_count += 1.0
                        elif prob < self.SILERO_SILEN:
                            silence_count += 0.5
                        # entre SILERO_SILEN y SILERO_VOICE → no incrementar

                        is_long = (voice_chunks * chunk_sz / sr) >= 2.0
                        budget  = self.SILENCE_LONG if is_long else self.SILENCE_SHORT
                        if silence_count >= budget:
                            ms = int(silence_count * chunk_sz * 1000 / sr)
                            print(f"🔇 Silencio {ms}ms — fin de voz")
                            break
                    else:
                        wait_count += 1
                        if wait_count >= wait_chunks:
                            break

            self._set_audio_level(0.0)

            if self._interrupt_event.is_set():
                print("🛑 Grabación interrumpida")
                return None

            if not voice_started or not frames:
                if wait_timeout_s is not None:
                    return None  # follow-up: silencio = el usuario no quiso hablar
                print(f"⚠️ Sin voz detectada (RMS pico={peak_rms:.1f})")
                return None

            audio = np.concatenate(frames, axis=0)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(out_path), "wb") as wf:
                wf.setnchannels(self._stt_cfg.channels)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(audio.tobytes())
            return out_path

        except Exception:
            self._set_audio_level(0.0)
            raise

    # ── Grabación RMS (fallback) ──────────────────────────────────────────────

    def _record_rms(
        self,
        out_path: Path,
        wait_timeout_s: Optional[float] = None,
    ) -> Optional[Path]:
        """
        Graba audio con VAD por RMS (legacy). Fallback si Silero no está disponible.
        """
        sr         = self._stt_cfg.sample_rate
        chunk_sz   = int(sr * self.VAD_CHUNK_MS / 1000)
        max_chunks = int(self.VAD_MAX_S * 1000 / self.VAD_CHUNK_MS)
        wait_s      = wait_timeout_s if wait_timeout_s is not None else self.VAD_TIMEOUT_S
        wait_chunks = int(wait_s * 1000 / self.VAD_CHUNK_MS)

        frames: list = []
        voice_started = False
        silence_count = 0
        wait_count    = 0
        peak_rms      = 0.0

        try:
            print("🎤 Escuchando...")
            with sd.InputStream(
                samplerate=sr,
                channels=self._stt_cfg.channels,
                dtype=self._stt_cfg.dtype,
                blocksize=chunk_sz,
                device=self._stt_cfg.device,
            ) as stream:
                for _ in range(max_chunks):
                    if self._interrupt_event.is_set():
                        break

                    chunk, _ = stream.read(chunk_sz)
                    rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                    if rms > peak_rms:
                        peak_rms = rms

                    self._set_audio_level(rms)

                    if rms >= self.VAD_THRESHOLD:
                        if not voice_started:
                            print("🎙️  Voz detectada")
                            voice_started = True
                        silence_count = 0
                        frames.append(chunk.copy())
                    elif voice_started:
                        frames.append(chunk.copy())
                        silence_count += 1
                        if silence_count >= self.VAD_SILENCE_SEGS:
                            print("🔇 Silencio — fin de voz")
                            break
                    else:
                        wait_count += 1
                        if wait_count == 100 and peak_rms < 5.0:
                            print(f"⚠️  Sin señal de audio (RMS pico: {peak_rms:.1f}). "
                                  f"Umbral VAD: {self.VAD_THRESHOLD}")
                            print("   Verifica: Ajustes → Privacidad → Micrófono → "
                                  "activa permiso para Terminal/Python")
                        if wait_count >= wait_chunks:
                            break

            self._set_audio_level(0.0)

            if self._interrupt_event.is_set():
                print("🛑 Grabación interrumpida")
                return None

            if not voice_started or not frames:
                if wait_timeout_s is not None:
                    return None
                print(f"⚠️ Sin voz detectada (RMS pico={peak_rms:.1f}, umbral={self.VAD_THRESHOLD})")
                return None

            audio = np.concatenate(frames, axis=0)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(out_path), "wb") as wf:
                wf.setnchannels(self._stt_cfg.channels)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(audio.tobytes())

            return out_path

        except Exception:
            self._set_audio_level(0.0)
            raise
