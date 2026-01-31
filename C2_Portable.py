import sys
import subprocess
import os
import datetime
import unicodedata
import base64
import threading
import requests
import tempfile
import time
import pygame
import sounddevice as sd
import numpy as np
import io
import wave
from anthropic import Anthropic
from tavily import TavilyClient
from dotenv import load_dotenv
from jamo import jamo_to_hcj
from google import genai
from PIL import Image

# 1. 환경 설정 및 API 로드
load_dotenv()
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
gemini_client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

AI_NAME = "Orion"
PROFILE_FILE = "user_profile.txt"
TEMP_IMAGE = "temp_capture.png"
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
MUSIC_FOLDER = "Music"

# Wake Word 설정 (다양한 발음 변형)
WAKE_WORDS = [
    "hey orion", "hey orian", "hey oreon", "hey orianne",
    "a orion", "a orian", "hey oryan", "hey aurion",
    "orion", "orian", "hey orient", "hey o'brien"
]

# ElevenLabs 설정
ELEVENLABS_VOICE_ID = "QYrOVogqhHWUzdZFXf0E"
ELEVENLABS_API_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

# 오디오 설정
SAMPLE_RATE = 16000
CHANNELS = 1


# --- [음악 플레이어] ---
class MusicPlayer:
    def __init__(self):
        pygame.mixer.init()
        self.is_playing = False
        self.current_song = None
        self.normal_volume = 0.2
        self.ducked_volume = 0.05
    
    def duck(self):
        if self.is_playing:
            pygame.mixer.music.set_volume(self.ducked_volume)
    
    def unduck(self):
        if self.is_playing:
            pygame.mixer.music.set_volume(self.normal_volume)
    
    def play(self, song_name):
        self.stop()
        filename = song_name.strip().replace(" ", "_")
        if not filename.lower().endswith(".mp3"):
            filename += ".mp3"
        
        filepath = os.path.join(MUSIC_FOLDER, filename)
        
        if not os.path.exists(filepath):
            if os.path.exists(MUSIC_FOLDER):
                for f in os.listdir(MUSIC_FOLDER):
                    if f.lower() == filename.lower():
                        filepath = os.path.join(MUSIC_FOLDER, f)
                        break
                else:
                    return False
            else:
                return False
        
        try:
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.set_volume(self.normal_volume)
            pygame.mixer.music.play(loops=-1)
            self.is_playing = True
            self.current_song = song_name
            return True
        except:
            return False
    
    def stop(self):
        if self.is_playing:
            pygame.mixer.music.stop()
        self.is_playing = False
        self.current_song = None


# --- [메인 오리온 봇 - 휴대용 음성 전용] ---
class OrionPortable:
    def __init__(self):
        self.short_term_memory = []
        self.music_player = MusicPlayer()
        self.is_running = True
        self.is_speaking = False
        
        # 오디오 설정
        self.sample_rate = 16000
        self.channels = 1
        self.energy_threshold = 0.01  # 매우 낮은 임계값
        self.silence_duration = 1.5
        
        self.load_personal_profile()
        
    def load_personal_profile(self):
        extra_info = ""
        if os.path.exists(PROFILE_FILE):
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                extra_info = f.read()
        
        self.system_prompt = (
            f"당신은 건희의 전용 AI 비서 '{AI_NAME}'이야.\n"
            f"[건희 정보]\n{extra_info}\n"
            "핵심 지침:\n"
            "1. 무조건 '존댓말'로 마치 영화 아이언맨에 나오는 자비스처럼 차분하고 똑똑하게 말해줘.\n"
            "2. 답변은 무조건 '한 문장'으로 아주 짧고 핵심만 말해.\n"
            "3. 이전 대화 맥락을 기억해서 자연스럽게 이어가줘.\n"
            "4. 건희 대신 sir 이라고 말해."
        )

    def notify(self, msg):
        """macOS 알림"""
        try:
            subprocess.run(["osascript", "-e", 
                f'display notification "{msg.replace(chr(34), chr(39))}" with title "{AI_NAME}"'],
                capture_output=True)
        except:
            pass

    def speak(self, text):
        """ElevenLabs TTS (동기식)"""
        self.is_speaking = True
        try:
            self.music_player.duck()
            
            english_text = self.translate_to_english(text)
            print(f"🔊 [{AI_NAME}]: {english_text}")
            
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": ELEVENLABS_API_KEY
            }
            
            data = {
                "text": english_text,
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "style": 0.3,
                    "use_speaker_boost": True
                }
            }
            
            response = requests.post(ELEVENLABS_API_URL, json=data, headers=headers)
            
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    f.write(response.content)
                    temp_path = f.name
                
                subprocess.run(["afplay", temp_path], capture_output=True)
                os.remove(temp_path)
                
        except Exception as e:
            print(f"[TTS Error] {e}")
        finally:
            self.music_player.unduck()
            self.is_speaking = False

    def translate_to_english(self, korean_text):
        """한국어 → 영어 번역"""
        try:
            response = anthropic_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=200,
                messages=[{
                    "role": "user", 
                    "content": f"Translate to natural English. '건희' = 'Gun-hee'. Output translation only:\n\n{korean_text}"
                }]
            )
            result = response.content[0].text.strip()
            for old in ["Geonhee", "Gunhee", "Keonhee", "건희"]:
                result = result.replace(old, "Gun-hee")
            return result
        except:
            return korean_text

    def record_audio(self, duration=4):
        """고정 시간 동안 녹음 (간단한 방식)"""
        print(f"🎤 녹음 중... ({duration}초)")
        
        try:
            # 고정 시간 녹음
            audio_data = sd.rec(
                int(duration * self.sample_rate),
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype='float32'
            )
            sd.wait()  # 녹음 완료 대기
            
            # 볼륨 체크
            volume = np.sqrt(np.mean(audio_data**2))
            print(f"📊 볼륨: {volume:.6f}")
            
            if volume < 0.001:
                print("🔇 소리 없음")
                return None
            
            return audio_data
            
        except Exception as e:
            print(f"녹음 에러: {e}")
            return None

    def to_wav_bytes(self, audio_data):
        """numpy 배열을 WAV 바이트로 변환"""
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)
            # float32 -> int16 변환
            audio_int16 = (audio_data * 32767).astype(np.int16)
            wf.writeframes(audio_int16.tobytes())
        buffer.seek(0)
        return buffer.read()

    def transcribe(self, audio_data):
        """음성 → 텍스트 (Whisper API)"""
        if not OPENAI_API_KEY:
            print("⚠️ OPENAI_API_KEY 없음!")
            return None
        
        try:
            wav_bytes = self.to_wav_bytes(audio_data)
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                temp_path = f.name
            
            print(f"📤 Whisper API로 전송 중... ({len(wav_bytes)} bytes)")
            
            with open(temp_path, "rb") as audio_file:
                response = requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    files={"file": audio_file},
                    data={"model": "whisper-1", "language": "en", "prompt": "Hey Orion"}
                )
            os.remove(temp_path)
            
            if response.status_code == 200:
                text = response.json().get("text", "")
                print(f"📥 Whisper 결과: '{text}'")
                return text
            else:
                print(f"Whisper 에러: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Transcribe 에러: {e}")
            return None

    def get_ai_response(self, user_text):
        """AI 응답 생성"""
        try:
            user_text = unicodedata.normalize('NFC', user_text)
            now = datetime.datetime.now()
            time_info = f"[현재: {now.strftime('%Y-%m-%d %H:%M')}]"
            
            search_keywords = ["날씨", "뉴스", "오늘", "현재", "지금", "weather", "news", "today"]
            context = ""
            
            if any(kw in user_text.lower() for kw in search_keywords):
                try:
                    search_res = anthropic_client.messages.create(
                        model=CLAUDE_MODEL, max_tokens=50,
                        messages=[{"role": "user", "content": f"'{user_text}' 검색어 영어로 하나만: "}]
                    )
                    query = search_res.content[0].text.strip()
                    res = tavily.search(query=query, search_depth="basic", max_results=2)
                    context = "\n[검색결과]: " + " ".join([r['content'][:200] for r in res['results']])
                except:
                    pass

            messages = list(self.short_term_memory)
            messages.append({"role": "user", "content": f"{time_info} {user_text} {context}"})

            response = anthropic_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=150,
                system=self.system_prompt,
                messages=messages
            )
            answer = response.content[0].text.strip()
            
            self.short_term_memory.append({"role": "user", "content": user_text})
            self.short_term_memory.append({"role": "assistant", "content": answer})
            if len(self.short_term_memory) > 10:
                self.short_term_memory = self.short_term_memory[-10:]
            
            return answer
        except Exception as e:
            return f"잠시 오류가 발생했습니다: {str(e)}"

    def process_command(self, text):
        """음성 명령 처리"""
        cmd = text.lower()
        
        # 종료
        if any(w in cmd for w in ["goodbye", "shut down", "turn off", "stop listening", "종료"]):
            self.speak("오리온 C2 작동을 중지하겠습니다. 안녕히 가세요.")
            self.is_running = False
            return
        
        # 음악 재생
        if any(w in cmd for w in ["play ", "플레이", "틀어"]):
            for kw in ["play ", "플레이 ", "틀어 ", "틀어줘 "]:
                if kw in cmd:
                    song = text[cmd.find(kw) + len(kw):].strip()
                    if song:
                        if self.music_player.play(song):
                            self.speak(f"{song} 재생하겠습니다.")
                        else:
                            self.speak(f"{song} 파일을 찾을 수 없습니다.")
                        return
        
        # 음악 중지
        if any(w in cmd for w in ["stop music", "stop song", "음악 중지", "음악 꺼"]):
            self.music_player.stop()
            self.speak("음악을 중지했습니다.")
            return
        
        # 볼륨 조절
        if "volume up" in cmd or "볼륨 업" in cmd:
            self.music_player.normal_volume = min(1.0, self.music_player.normal_volume + 0.1)
            pygame.mixer.music.set_volume(self.music_player.normal_volume)
            self.speak(f"볼륨을 높였습니다.")
            return
        
        if "volume down" in cmd or "볼륨 다운" in cmd:
            self.music_player.normal_volume = max(0.0, self.music_player.normal_volume - 0.1)
            pygame.mixer.music.set_volume(self.music_player.normal_volume)
            self.speak(f"볼륨을 낮췄습니다.")
            return
        
        # 일반 대화
        answer = self.get_ai_response(text)
        self.notify(answer)
        self.speak(answer)

    def extract_command(self, text):
        """Wake word 뒤의 명령 추출"""
        text_lower = text.lower()
        for wake in WAKE_WORDS:
            if wake in text_lower:
                idx = text_lower.find(wake) + len(wake)
                cmd = text[idx:].strip()
                cmd = cmd.lstrip(',').lstrip()
                if len(cmd) > 2:
                    return cmd
        return None

    def run(self):
        """메인 루프"""
        print(f"\n{'='*50}")
        print(f"  🎧 {AI_NAME} C2 Portable - 음성 전용 모드")
        print(f"{'='*50}")
        print(f"✅ Whisper API: {'활성화' if OPENAI_API_KEY else '비활성화'}")
        print(f"✅ Sounddevice 오디오 사용")
        print(f"✅ 'Hey Orion'이라고 말하세요!")
        print(f"✅ 종료: 'Hey Orion, goodbye' 또는 Ctrl+C")
        print(f"{'='*50}\n")
        
        # 사용 가능한 오디오 장치 출력
        print("🎤 오디오 장치:")
        print(sd.query_devices())
        print(f"\n🎤 기본 입력 장치: {sd.default.device[0]}")
        print()
        
        self.notify("오리온 C2 시작됨! Hey Orion이라고 말하세요.")
        self.speak("오리온 C2 가동되었습니다. 언제든 불러주세요.")
        
        while self.is_running:
            try:
                # TTS 중이면 스킵
                if self.is_speaking:
                    time.sleep(0.1)
                    continue
                
                # 4초간 녹음
                audio_data = self.record_audio(duration=4)
                
                if audio_data is None:
                    continue
                
                # 음성 → 텍스트
                text = self.transcribe(audio_data)
                
                if not text or len(text.strip()) < 2:
                    continue
                
                print(f"👂 들림: '{text}'")
                
                # Wake word 체크
                text_lower = text.lower()
                wake_detected = any(wake in text_lower for wake in WAKE_WORDS)
                
                if wake_detected:
                    print("✨ Wake word 감지!")
                    
                    command = self.extract_command(text)
                    
                    if command:
                        print(f"📝 명령: '{command}'")
                        self.process_command(command)
                    else:
                        self.speak("네, 말씀하세요.")
                        print("⏳ 명령 대기 중...")
                        
                        # 더 긴 시간 녹음
                        audio_data2 = self.record_audio(duration=8)
                        if audio_data2 is not None:
                            command = self.transcribe(audio_data2)
                            if command:
                                print(f"📝 명령: '{command}'")
                                self.process_command(command)
                
            except KeyboardInterrupt:
                print("\n🛑 Ctrl+C 감지")
                break
            except Exception as e:
                print(f"⚠️ 에러: {e}")
                time.sleep(0.5)
        
        print("\n👋 오리온 C2 종료됨")
        self.music_player.stop()


# --- [실행] ---
if __name__ == "__main__":
    if not os.path.exists(MUSIC_FOLDER):
        os.makedirs(MUSIC_FOLDER)
    
    orion = OrionPortable()
    orion.run()