"""
voice_loop.py

Loop de voz con conversación continua usando Silero VAD.
"""

from __future__ import annotations

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
    ):
        self.loop_cfg = loop_cfg or VoiceLoopConfig()
        self.workspace = Path(self.loop_cfg.workspace_dir).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.wake = WakeWordListener(wake_cfg)
        self.stt = STT(stt_cfg or STTConfig())
        self.tts = TTS(tts_cfg or TTSConfig())
        
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

    def run_forever(self, agent_fn: AgentFn) -> None:
        """Loop principal."""
        self.wake.start()
        print("👂 Escuchando wake word...\n")
        
        try:
            while True:
                print("💤 Esperando 'Jarvis'...")
                woke = self.wake.wait_for_wake(timeout_sec=None)
                
                if not woke:
                    continue

                print("✓ Wake word detectada!\n")
                self.tts.speak("Dime")
                
                if self.loop_cfg.use_vad:
                    self._conversation_mode(agent_fn)
                else:
                    # Modo clásico
                    wav_path = self.workspace / "_jarvis_input.wav"
                    self.stt.record_to_wav(wav_path, seconds=float(self.loop_cfg.record_seconds))
                    
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
