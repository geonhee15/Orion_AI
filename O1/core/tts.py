import os
import subprocess
import tempfile
import time
import platform
import shutil
import requests
from O1 import config


class TextToSpeech:
    """ElevenLabs 스트리밍 TTS — 생성하면서 바로 재생"""

    def __init__(self, music_player=None):
        self.music_player = music_player
        self.is_speaking = False
        self.last_spoke_time = 0
        self.stream_url = f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}/stream"
        self._audio_player = self._get_audio_player()

    def _get_audio_player(self):
        """플랫폼별 오디오 재생기 선택"""
        system = platform.system()

        if system == "Darwin":  # macOS
            return "afplay"
        elif system == "Linux":
            # Linux: mpg123, ffplay, mpv 등 시도
            for player in ["mpg123", "ffplay", "mpv"]:
                if shutil.which(player):
                    return player
            print("⚠️  No audio player found on Linux. Install mpg123, ffplay, or mpv.")
            return None
        elif system == "Windows":
            print("⚠️  Windows TTS playback not implemented. Install VLC or use pygame.")
            return None

        return None

    def speak(self, text):
        """스트리밍 TTS: 청크 단위로 받으면서 바로 재생."""
        self.is_speaking = True
        temp_path = None  # 임시 파일 경로 초기화

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

            # 스트리밍 요청 — 청크가 오는 대로 파일에 쓰면서 빠르게 재생
            response = requests.post(
                self.stream_url, json=data, headers=headers, stream=True
            )

            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    for chunk in response.iter_content(chunk_size=4096):
                        if chunk:
                            f.write(chunk)
                    temp_path = f.name

                # 플랫폼별 재생
                if not self._audio_player:
                    print(f"[TTS] No audio player available: {text}")
                elif self._audio_player == "afplay":
                    subprocess.run([self._audio_player, temp_path], capture_output=True, check=True)
                elif self._audio_player in ["mpg123", "mpv"]:
                    subprocess.run([self._audio_player, "-q", temp_path], capture_output=True, check=True)
                elif self._audio_player == "ffplay":
                    subprocess.run([self._audio_player, "-nodisp", "-autoexit", temp_path],
                                 capture_output=True, check=True)

        except Exception as e:
            print(f"[TTS Error] {e}")
        finally:
            # 임시 파일 안전하게 삭제
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass  # 삭제 실패 시 무시 (이미 삭제됨)

            if self.music_player:
                self.music_player.unduck()
            self.is_speaking = False
            self.last_spoke_time = time.time()
