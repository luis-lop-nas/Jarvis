"""
voice_loop.py

Loop de voz con conversación continua usando Silero VAD.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
import wave

import numpy as np
import sounddevice as sd

from jarvis.voice.wake_word import WakeWordConfig, WakeWordListener
from jarvis.voice.stt import STT, STTConfig
from jarvis.voice.tts import TTS, TTSConfig
from jarvis.voice.gaze_trigger import GazeTriggerConfig, GazeTriggerMonitor


AgentFn = Callable[[str], str]


@dataclass
class VoiceLoopConfig:
    workspace_dir: str = "data/workspace"
    record_seconds: float = 6.0
    conversation_timeout: float = 30.0
    use_vad: bool = True


class VoiceLoop:
    def __init__(
        self,
        *,
        wake_cfg: WakeWordConfig,
        stt_cfg: Optional[STTConfig] = None,
        tts_cfg: Optional[TTSConfig] = None,
        loop_cfg: Optional[VoiceLoopConfig] = None,
        gaze_cfg: Optional[GazeTriggerConfig] = None,
    ):
        self.loop_cfg = loop_cfg or VoiceLoopConfig()
        self.workspace = Path(self.loop_cfg.workspace_dir).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.wake = WakeWordListener(wake_cfg)
        self.stt = STT(stt_cfg or STTConfig())
        self.tts = TTS(tts_cfg or TTSConfig())

        # ── Gaze trigger (opcional) ──────────────────────────────────────────
        self._gaze_event: threading.Event = threading.Event()
        self._gaze_monitor: Optional[GazeTriggerMonitor] = None
        if gaze_cfg and gaze_cfg.enabled:
            self._gaze_monitor = GazeTriggerMonitor(
                config=gaze_cfg,
                wake_listener=self.wake,
                on_trigger=self._gaze_event.set,  # señaliza el loop principal
            )
        
        self.vad_model = None
        self._torch = None
        if self.loop_cfg.use_vad:
            try:
                import torch
                self._torch = torch
                print("📥 Cargando modelo Silero VAD...")
                self.vad_model, utils = torch.hub.load(
                    repo_or_dir='snakers4/silero-vad',
                    model='silero_vad',
                    force_reload=False,
                    onnx=False
                )
                self.get_speech_timestamps = utils[0]
                print("✅ VAD cargado - Conversación continua activada")
            except Exception as e:
                print(f"⚠️ Error cargando VAD: {e}")
                self.loop_cfg.use_vad = False

    def _detect_speech_vad(self, timeout: float = 5.0) -> Optional[np.ndarray]:
        """
        Graba audio hasta detectar silencio con VAD.
        Usa chunks de 512 samples (32ms a 16kHz) como requiere Silero VAD.
        """
        if not self.vad_model:
            return None
        
        sample_rate = 16000
        chunk_samples = 512  # Tamaño requerido por Silero VAD para 16kHz
        
        audio_chunks = []
        silence_chunks = 0
        max_silence_chunks = 22  # ~0.7s de silencio (22 * 32ms) — más responsive
        speech_started = False
        
        print("🎤 Escuchando... (habla ahora)")
        start_time = time.time()
        
        try:
            stream = sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype='int16',
                blocksize=chunk_samples,
            )
            stream.start()
            
            while True:
                if time.time() - start_time > timeout:
                    print("⏱️ Timeout")
                    stream.stop()
                    stream.close()
                    return None
                
                # Leer exactamente 512 samples
                audio_chunk, overflowed = stream.read(chunk_samples)
                
                if overflowed:
                    continue
                
                # Convertir a float32 [-1, 1]
                audio_float = audio_chunk.astype(np.float32).flatten() / 32768.0
                
                # VAD necesita exactamente 512 samples
                if len(audio_float) != 512:
                    continue
                
                # Detectar voz
                audio_tensor = self._torch.from_numpy(audio_float)
                speech_prob = self.vad_model(audio_tensor, sample_rate).item()
                
                if speech_prob > 0.6:  # Voz detectada (umbral subido para menos falsos positivos)
                    if not speech_started:
                        speech_started = True
                        print("🗣️ Voz detectada")
                    
                    audio_chunks.append(audio_chunk)
                    silence_chunks = 0
                else:  # Silencio
                    if speech_started:
                        silence_chunks += 1
                        audio_chunks.append(audio_chunk)
                        
                        if silence_chunks >= max_silence_chunks:
                            print("✅ Fin de habla")
                            stream.stop()
                            stream.close()
                            
                            if len(audio_chunks) > 0:
                                return np.concatenate(audio_chunks, axis=0)
                            return None
                        
        except Exception as e:
            print(f"⚠️ Error VAD: {e}")
            return None

    def _detect_speech_rms(self, timeout: float = 6.0) -> Optional[np.ndarray]:
        """
        Fallback sin Silero: espera voz y corta cuando detecta silencio sostenido.
        """
        sample_rate = 16000
        chunk_samples = 512
        silence_chunks = 0
        max_silence_chunks = 25  # ~0.8s
        speech_started = False
        wait_start = time.time()
        max_total_seconds = 20.0
        audio_chunks = []

        print("🎤 Escuchando... (habla ahora)")

        try:
            stream = sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                blocksize=chunk_samples,
            )
            stream.start()

            while True:
                if not speech_started and time.time() - wait_start > timeout:
                    print("⏱️ Timeout esperando voz")
                    stream.stop()
                    stream.close()
                    return None

                audio_chunk, overflowed = stream.read(chunk_samples)
                if overflowed:
                    continue

                audio_flat = audio_chunk.astype(np.float32).flatten()
                rms = float(np.sqrt(np.mean(audio_flat ** 2)))

                if rms >= 300.0:
                    if not speech_started:
                        speech_started = True
                        speech_start = time.time()
                        print("🗣️ Voz detectada")
                    audio_chunks.append(audio_chunk)
                    silence_chunks = 0
                    continue

                if speech_started:
                    audio_chunks.append(audio_chunk)
                    silence_chunks += 1

                    if silence_chunks >= max_silence_chunks or (time.time() - speech_start) >= max_total_seconds:
                        print("✅ Fin de habla")
                        stream.stop()
                        stream.close()
                        if audio_chunks:
                            return np.concatenate(audio_chunks, axis=0)
                        return None
        except Exception as e:
            print(f"⚠️ Error VAD RMS: {e}")
            return None

    def _conversation_mode(self, agent_fn: AgentFn) -> None:
        """Modo conversación continua."""
        print("\n💬 Modo conversación activado")
        print(f"   (Volveré a wake si hay {self.loop_cfg.conversation_timeout}s de silencio)\n")
        
        last_interaction = time.time()
        
        while True:
            if time.time() - last_interaction > self.loop_cfg.conversation_timeout:
                print(f"\n⏱️ {self.loop_cfg.conversation_timeout}s sin actividad")
                print("→ Volviendo a modo wake\n")
                return
            
            audio_data = self._detect_speech_vad(timeout=self.loop_cfg.conversation_timeout)
            
            if audio_data is None:
                print("→ Volviendo a modo wake\n")
                return
            
            last_interaction = time.time()
            
            # Guardar WAV
            wav_path = self.workspace / "_jarvis_input.wav"
            with wave.open(str(wav_path), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_data.tobytes())
            
            # Transcribir
            text = self.stt.transcribe_wav(wav_path).strip()
            
            if not text or "no he detectado" in text.lower() or text.startswith("Error"):
                print(f"⚠️ {text}")
                self.tts.speak("No te he entendido")
                continue
            
            print(f"📝 Tú: {text}\n")
            
            # Comandos de salida
            if any(word in text.lower() for word in ["adiós", "hasta luego", "chao", "terminar", "salir"]):
                self.tts.speak("Hasta luego")
                print("👋 Saliendo de conversación\n")
                return
            
            # Procesar
            print("🤔 Procesando...")
            response = agent_fn(text)
            print(f"💬 Jarvis: {response}\n")
            
            self.tts.speak(response)
            print("─" * 60)

    def _play_gaze_beep(self) -> None:
        """Pitido corto de confirmación para gaze trigger (sin TTS — el usuario ya habla)."""
        try:
            t    = np.linspace(0, 0.07, int(22050 * 0.07), endpoint=False)
            beep = (0.22 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
            sd.play(beep, 22050, blocking=False)
        except Exception:
            pass  # el beep es opcional

    def _wait_for_activation(self) -> bool:
        """
        Espera wake word O gaze trigger, lo que ocurra primero.
        Usa polling con timeout finito para poder:
          - comprobar el gaze event
          - renderizar el debug frame de cámara desde el hilo principal (macOS requiere esto)
        Devuelve True si se activó por gaze.
        """
        debug = self._gaze_monitor is not None and self._gaze_monitor._cfg.debug
        window_open = False

        while True:
            if self._gaze_event.is_set():
                self._gaze_event.clear()
                if window_open:
                    try:
                        import cv2
                        cv2.destroyWindow("Jarvis \u2014 Gaze Monitor")
                    except Exception:
                        pass
                return True

            if self.wake.wait_for_wake(timeout_sec=0.1):
                if window_open:
                    try:
                        import cv2
                        cv2.destroyWindow("Jarvis \u2014 Gaze Monitor")
                    except Exception:
                        pass
                return False

            # ── Renderizar frame de debug desde el hilo principal ────────────
            if debug and self._gaze_monitor is not None:
                frame = self._gaze_monitor.get_debug_frame()
                if frame is not None:
                    import cv2
                    cv2.imshow("Jarvis \u2014 Gaze Monitor", frame)
                    key = cv2.waitKey(1) & 0xFF
                    window_open = True
                    if key == ord("q"):
                        cv2.destroyWindow("Jarvis \u2014 Gaze Monitor")
                        debug = False   # desactivar tras cerrar

    def run_forever(self, agent_fn: AgentFn) -> None:
        """Loop principal."""
        try:
            self.wake.start()
        except KeyboardInterrupt:
            print("\n👋 Saliendo (inicio interrumpido)...")
            return
        except Exception as e:
            print(f"⚠️ No se pudo iniciar wake word: {e}")
            print("   Revisa permisos de micrófono y WAKE_WORD_DEVICE en .env")
            return

        # Arrancar gaze trigger después del wake listener (necesita latest_rms activo)
        if self._gaze_monitor is not None:
            self._gaze_monitor.start()

        print("👂 Escuchando (wake word o gaze trigger)...\n")

        try:
            while True:
                print("💤 Esperando activación...")
                by_gaze = self._wait_for_activation()

                if by_gaze:
                    # Usuario ya está hablando → pitido corto, sin TTS "Dime"
                    self._play_gaze_beep()
                    print("👁  Gaze activado — escuchando...\n")
                else:
                    print("✓ Wake word detectada!\n")
                    self.tts.speak("Dime")

                if self.loop_cfg.use_vad:
                    self._conversation_mode(agent_fn)
                else:
                    wav_path   = self.workspace / "_jarvis_input.wav"
                    audio_data = self._detect_speech_rms(
                        timeout=float(self.loop_cfg.record_seconds)
                    )

                    if audio_data is None:
                        self.tts.speak("No te he oído")
                        continue

                    with wave.open(str(wav_path), "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16000)
                        wf.writeframes(audio_data.tobytes())

                    text = self.stt.transcribe_wav(wav_path).strip()

                    if not text or text.startswith("Error"):
                        self.tts.speak("No te he entendido")
                        continue

                    print(f"📝 {text}\n")
                    response = agent_fn(text)
                    print(f"💬 {response}\n")
                    self.tts.speak(response)

        except KeyboardInterrupt:
            print("\n👋 Saliendo...")
        finally:
            self.wake.stop()
            if self._gaze_monitor is not None:
                self._gaze_monitor.stop()
