import os
import subprocess
import tempfile
import time
import threading
import platform
import shutil
import wave
import numpy as np
import requests
from Workspace import config


class TextToSpeech:
    """ElevenLabs 스트리밍 TTS — 오디오 레벨 기반 비주얼라이저 연동"""

    def __init__(self, music_player=None):
        self.music_player = music_player
        self.is_speaking = False
        self.last_spoke_time = 0
        self.stream_url = f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}/stream"
        self._audio_player = self._get_audio_player()
        # UI 콜백
        self.on_amplitude = None   # (float) 0.0~1.0 실시간 오디오 레벨

    def _get_audio_player(self):
        system = platform.system()
        if system == "Darwin":
            return "afplay"
        elif system == "Linux":
            for player in ["mpg123", "ffplay", "mpv"]:
                if shutil.which(player):
                    return player
            return None
        return None

    def _extract_amplitude_envelope(self, mp3_path):
        """MP3 → WAV 변환 → 프레임별 RMS amplitude envelope 추출 (30fps)"""
        wav_path = mp3_path.replace(".mp3", ".wav")
        try:
            # macOS afconvert로 MP3 → WAV 변환
            result = subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16", mp3_path, wav_path],
                capture_output=True, timeout=10,
            )
            if result.returncode != 0:
                print(f"[TTS] afconvert failed: {result.stderr.decode()[:100]}")
                return []

            with wave.open(wav_path, "rb") as wf:
                n_frames = wf.getnframes()
                rate = wf.getframerate()
                n_channels = wf.getnchannels()
                raw = wf.readframes(n_frames)

            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if n_channels > 1:
                audio = audio.reshape(-1, n_channels).mean(axis=1)

            # 30fps로 RMS 계산
            fps = 30
            chunk_size = max(1, rate // fps)
            envelope = []
            for i in range(0, len(audio), chunk_size):
                chunk = audio[i : i + chunk_size]
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                envelope.append(rms)

            # 0.0 ~ 1.0 정규화
            if envelope:
                peak = max(envelope)
                if peak > 0:
                    envelope = [v / peak for v in envelope]

            print(f"[TTS] Amplitude envelope: {len(envelope)} frames")
            return envelope

        except Exception as e:
            print(f"[TTS] Amplitude extraction error: {e}")
            return []
        finally:
            if os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass

    def _emit_amplitudes(self, envelope):
        """30fps로 amplitude 값을 UI 콜백에 전달 (재생과 동기화)"""
        interval = 1.0 / 30
        for amp in envelope:
            if not self.is_speaking:
                break
            if self.on_amplitude:
                self.on_amplitude(amp)
            time.sleep(interval)
        # 재생 종료 → 0으로
        if self.on_amplitude:
            self.on_amplitude(0.0)

    def speak(self, text):
        """스트리밍 TTS + 실시간 오디오 레벨 비주얼라이저."""
        self.is_speaking = True
        temp_path = None

        try:
            if self.music_player:
                self.music_player.duck()

            print(f"🔊 [{config.AI_NAME}]: {text}")

            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": config.ELEVENLABS_API_KEY,
            }

            data = {
                "text": text,
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "style": 0.3,
                    "use_speaker_boost": True,
                },
            }

            response = requests.post(
                self.stream_url, json=data, headers=headers, stream=True
            )

            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    for chunk in response.iter_content(chunk_size=4096):
                        if chunk:
                            f.write(chunk)
                    temp_path = f.name

                # 재생 전: amplitude envelope 추출
                envelope = self._extract_amplitude_envelope(temp_path)

                # 폴백: envelope 추출 실패 시 단순 펄스 패턴 생성
                if not envelope:
                    print("[TTS] Envelope extraction failed, using fallback pulse")
                    # MP3 파일 크기로 대략적인 재생 시간 추정 (128kbps 기준)
                    file_size = os.path.getsize(temp_path)
                    est_duration = file_size / (128 * 1000 / 8)  # bytes / (bitrate/8)
                    n_frames = int(est_duration * 30)
                    import math
                    envelope = [
                        0.5 + 0.5 * math.sin(i * 0.3) * math.sin(i * 0.07)
                        for i in range(max(n_frames, 30))
                    ]

                if not self._audio_player:
                    print(f"[TTS] No audio player available: {text}")
                else:
                    # amplitude 쓰레드 시작 (재생과 동시)
                    if self.on_amplitude and envelope:
                        amp_thread = threading.Thread(
                            target=self._emit_amplitudes,
                            args=(envelope,),
                            daemon=True,
                        )
                        amp_thread.start()

                    # 오디오 재생 (blocking)
                    if self._audio_player == "afplay":
                        subprocess.run([self._audio_player, temp_path], capture_output=True, check=True)
                    elif self._audio_player in ["mpg123", "mpv"]:
                        subprocess.run([self._audio_player, "-q", temp_path], capture_output=True, check=True)
                    elif self._audio_player == "ffplay":
                        subprocess.run([self._audio_player, "-nodisp", "-autoexit", temp_path],
                                     capture_output=True, check=True)

        except Exception as e:
            print(f"[TTS Error] {e}")
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

            if self.music_player:
                self.music_player.unduck()
            self.is_speaking = False
            self.last_spoke_time = time.time()

            # 재생 끝 → amplitude 0
            if self.on_amplitude:
                self.on_amplitude(0.0)
