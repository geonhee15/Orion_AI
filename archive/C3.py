import sys
import subprocess
import os
import datetime
import unicodedata
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

# 환경 설정
load_dotenv()
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

AI_NAME = "Orion"
PROFILE_FILE = "user_profile.txt"
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
MUSIC_FOLDER = "Music"

# Wake Words
WAKE_WORDS = [
    "hey orion", "hey orian", "hey oreon", "hey orianne",
    "a orion", "a orian", "hey oryan", "hey aurion",
    "orion", "orian", "hey orient", "hey o'brien"
]

# 캘린더 키워드
CALENDAR_KEYWORDS = [
    "schedule", "calendar", "일정", "스케줄", "약속", "미팅", "meeting",
    "what do i have", "what's on", "events", "plan", "class",
    "오늘", "내일", "이번주", "today", "tomorrow", "this week", "next week"
]

# ElevenLabs
ELEVENLABS_VOICE_ID = "QYrOVogqhHWUzdZFXf0E"
ELEVENLABS_API_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"


# --- [macOS Calendar using icalBuddy] ---
class MacCalendar:
    def __init__(self):
        self.icalbuddy_path = None
        self.available = self._check_icalbuddy()
    
    def _check_icalbuddy(self):
        """icalBuddy 설치 확인 및 경로 저장"""
        # 가능한 경로들
        paths = [
            "/usr/local/bin/icalBuddy",
            "/opt/homebrew/bin/icalBuddy",
            "/usr/bin/icalBuddy"
        ]
        
        for path in paths:
            if os.path.exists(path):
                self.icalbuddy_path = path
                print(f"✅ macOS Calendar 연결됨 ({path})")
                return True
        
        # which로 찾기
        try:
            result = subprocess.run(["which", "icalBuddy"], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                self.icalbuddy_path = result.stdout.strip()
                print(f"✅ macOS Calendar 연결됨 ({self.icalbuddy_path})")
                return True
        except:
            pass
        
        print("⚠️ icalBuddy 없음. 'brew install ical-buddy' 실행하세요.")
        self.icalbuddy_path = None
        return False
    
    def get_today_events(self):
        """오늘 일정"""
        if not self.available or not self.icalbuddy_path:
            return None
        try:
            result = subprocess.run(
                [self.icalbuddy_path, "eventsToday"],
                capture_output=True, text=True
            )
            print(f"[Calendar Raw] {result.stdout[:200] if result.stdout else 'EMPTY'}...")  # 디버그
            return self._parse_events(result.stdout, "오늘")
        except Exception as e:
            print(f"캘린더 에러: {e}")
            return None
    
    def get_tomorrow_events(self):
        """내일 일정"""
        if not self.available or not self.icalbuddy_path:
            return None
        try:
            result = subprocess.run(
                [self.icalbuddy_path, "eventsToday+1"],
                capture_output=True, text=True
            )
            print(f"[Calendar Raw] {result.stdout[:200] if result.stdout else 'EMPTY'}...")  # 디버그
            return self._parse_events(result.stdout, "내일")
        except Exception as e:
            print(f"캘린더 에러: {e}")
            return None
    
    def get_week_events(self):
        """이번 주 일정"""
        if not self.available or not self.icalbuddy_path:
            return None
        try:
            result = subprocess.run(
                [self.icalbuddy_path, "eventsToday+7"],
                capture_output=True, text=True
            )
            print(f"[Calendar Raw] {result.stdout[:200] if result.stdout else 'EMPTY'}...")  # 디버그
            return self._parse_events(result.stdout, "이번 주")
        except Exception as e:
            print(f"캘린더 에러: {e}")
            return None
    
    def get_raw_events(self, days=1):
        """원본 일정 데이터 가져오기 (AI가 분석용)"""
        if not self.available or not self.icalbuddy_path:
            return ""
        try:
            if days == 0:
                cmd = [self.icalbuddy_path, "eventsToday"]
            else:
                cmd = [self.icalbuddy_path, f"eventsToday+{days}"]
            
            print(f"[Calendar CMD] {' '.join(cmd)}")  # 디버그
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(f"[Calendar Output] {result.stdout[:300] if result.stdout else 'EMPTY'}")  # 디버그
            if result.stderr:
                print(f"[Calendar Stderr] {result.stderr}")  # 디버그
            return result.stdout
        except Exception as e:
            print(f"[Calendar Error] {e}")
            return ""
    
    def _parse_events(self, output, period):
        """icalBuddy 출력 파싱"""
        if not output or output.strip() == "":
            return f"Sir, {period}은 일정이 없습니다."
        
        lines = output.strip().split('\n')
        events = []
        current_event = None
        
        for line in lines:
            # • 로 시작하면 새 이벤트
            if line.strip().startswith('•'):
                if current_event:
                    events.append(current_event)
                # 이벤트 이름 추출 (• 제거)
                event_name = line.strip()[2:].split('(')[0].strip()
                current_event = {"name": event_name, "time": "", "location": ""}
            elif current_event:
                line = line.strip()
                if "at 오전" in line or "at 오후" in line or "tomorrow at" in line:
                    # 시간 정보
                    current_event["time"] = line
                elif line.startswith("location:"):
                    current_event["location"] = line.replace("location:", "").strip()
        
        if current_event:
            events.append(current_event)
        
        if not events:
            return f"Sir, {period}은 일정이 없습니다."
        
        # 포맷팅
        formatted = []
        for e in events[:6]:  # 최대 6개
            time_str = e.get("time", "")
            # 시간 추출 (오전/오후 시간)
            if "오전" in time_str or "오후" in time_str:
                parts = time_str.split("at")
                if len(parts) > 1:
                    time_part = parts[-1].strip().split("-")[0].strip()
                    formatted.append(f"{time_part}에 {e['name']}")
                else:
                    formatted.append(e['name'])
            else:
                formatted.append(e['name'])
        
        return f"Sir, {period} 일정입니다. " + ", ".join(formatted) + "."


# --- [Music Player] ---
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


# --- [Main Orion Bot] ---
class OrionPortable:
    def __init__(self):
        self.short_term_memory = []
        self.music_player = MusicPlayer()
        self.calendar = MacCalendar()
        self.is_running = True
        self.is_speaking = False
        
        self.sample_rate = 16000
        self.channels = 1
        
        # 블루투스 이어폰 마이크 설정
        self._setup_audio_device()
        
        self.load_personal_profile()
    
    def _setup_audio_device(self):
        """블루투스 이어폰을 기본 오디오 장치로 설정"""
        try:
            devices = sd.query_devices()
            input_device = None
            
            # Cleer ARC 찾기
            for i, dev in enumerate(devices):
                if "Cleer" in dev['name'] and dev['max_input_channels'] > 0:
                    input_device = i
                    print(f"🎧 블루투스 마이크 설정: {dev['name']} (장치 {i})")
                    break
            
            if input_device is not None:
                sd.default.device[0] = input_device
            else:
                print("⚠️ Cleer ARC 없음, 기본 마이크 사용")
        except Exception as e:
            print(f"오디오 장치 설정 에러: {e}")
        
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
            "4. 건희를 부를 때 이름 대신 'sir'이라고 해.\n"
            "5. 건희를 항상 2인칭 '당신/you'로 지칭해."
        )

    def notify(self, msg):
        try:
            subprocess.run(["osascript", "-e", 
                f'display notification "{msg.replace(chr(34), chr(39))}" with title "{AI_NAME}"'],
                capture_output=True)
        except:
            pass

    def speak(self, text):
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
        try:
            response = anthropic_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=200,
                messages=[{
                    "role": "user", 
                    "content": f"Translate to natural English. '건희' = 'sir'. Output translation only:\n\n{korean_text}"
                }]
            )
            return response.content[0].text.strip()
        except:
            return korean_text

    def record_audio(self, duration=4):
        print(f"🎤 녹음 중... ({duration}초)")
        try:
            # 블루투스 마이크로 녹음
            audio_data = sd.rec(
                int(duration * self.sample_rate),
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype='float32',
                device=sd.default.device[0]  # 명시적으로 입력 장치 지정
            )
            sd.wait()
            
            volume = np.sqrt(np.mean(audio_data**2))
            print(f"📊 볼륨: {volume:.6f}")
            
            if volume < 0.001:
                return None
            
            return audio_data
        except Exception as e:
            print(f"녹음 에러: {e}")
            return None

    def to_wav_bytes(self, audio_data):
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            audio_int16 = (audio_data * 32767).astype(np.int16)
            wf.writeframes(audio_int16.tobytes())
        buffer.seek(0)
        return buffer.read()

    def transcribe(self, audio_data):
        if not OPENAI_API_KEY:
            return None
        
        try:
            wav_bytes = self.to_wav_bytes(audio_data)
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                temp_path = f.name
            
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
                print(f"📥 Whisper: '{text}'")
                return text
            return None
        except Exception as e:
            print(f"Transcribe 에러: {e}")
            return None

    def check_calendar_query(self, text):
        """캘린더 관련 질문인지 확인"""
        text_lower = text.lower()
        return any(kw in text_lower for kw in CALENDAR_KEYWORDS)

    def handle_calendar_query(self, text):
        """캘린더 질문 처리 - AI가 분석"""
        text_lower = text.lower()
        
        # 내일/이번주/오늘 판단
        if any(w in text_lower for w in ["tomorrow", "내일"]):
            raw_events = self.calendar.get_raw_events(days=1)
            period = "tomorrow"
        elif any(w in text_lower for w in ["week", "이번주", "주"]):
            raw_events = self.calendar.get_raw_events(days=7)
            period = "this week"
        else:
            raw_events = self.calendar.get_raw_events(days=0)
            period = "today"
        
        if not raw_events or raw_events.strip() == "":
            return f"Sir, {period}은 일정이 없습니다."
        
        # AI에게 일정 데이터와 질문 전달
        try:
            response = anthropic_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=150,
                messages=[{
                    "role": "user",
                    "content": f"""다음은 캘린더 일정 데이터입니다:

{raw_events}

질문: {text}

위 일정 데이터를 바탕으로 질문에 한 문장으로 간단히 답해주세요. 
시간은 오전/오후 형식으로 말해주세요.
항상 "Sir,"로 시작하고 존댓말로 답해주세요."""
                }]
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"AI 캘린더 분석 에러: {e}")
            return self.calendar.get_tomorrow_events() if "tomorrow" in text_lower else self.calendar.get_today_events()

    def get_ai_response(self, user_text):
        try:
            # 캘린더 질문 체크
            if self.check_calendar_query(user_text):
                return self.handle_calendar_query(user_text)
            
            user_text = unicodedata.normalize('NFC', user_text)
            now = datetime.datetime.now()
            time_info = f"[현재: {now.strftime('%Y-%m-%d %H:%M')}]"
            
            search_keywords = ["날씨", "뉴스", "현재", "지금", "weather", "news"]
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
        cmd = text.lower()
        
        # 종료
        if any(w in cmd for w in ["goodbye", "shut down", "turn off", "종료"]):
            self.speak("오리온 C3 작동을 중지하겠습니다. 안녕히 가세요, sir.")
            self.is_running = False
            return
        
        # 음악
        if any(w in cmd for w in ["play ", "플레이", "틀어"]):
            for kw in ["play ", "플레이 ", "틀어 ", "틀어줘 "]:
                if kw in cmd:
                    song = text[cmd.find(kw) + len(kw):].strip()
                    if song:
                        if self.music_player.play(song):
                            self.speak(f"{song} 재생하겠습니다, sir.")
                        else:
                            self.speak(f"{song} 파일을 찾을 수 없습니다, sir.")
                        return
        
        if any(w in cmd for w in ["stop music", "stop song", "음악 중지"]):
            self.music_player.stop()
            self.speak("음악을 중지했습니다, sir.")
            return
        
        # 볼륨
        if "volume up" in cmd:
            self.music_player.normal_volume = min(1.0, self.music_player.normal_volume + 0.1)
            pygame.mixer.music.set_volume(self.music_player.normal_volume)
            self.speak("볼륨을 높였습니다.")
            return
        
        if "volume down" in cmd:
            self.music_player.normal_volume = max(0.0, self.music_player.normal_volume - 0.1)
            pygame.mixer.music.set_volume(self.music_player.normal_volume)
            self.speak("볼륨을 낮췄습니다.")
            return
        
        # 일반 대화 / 캘린더
        answer = self.get_ai_response(text)
        self.notify(answer)
        self.speak(answer)

    def extract_command(self, text):
        text_lower = text.lower()
        for wake in WAKE_WORDS:
            if wake in text_lower:
                idx = text_lower.find(wake) + len(wake)
                cmd = text[idx:].strip().lstrip(',').lstrip()
                if len(cmd) > 2:
                    return cmd
        return None

    def run(self):
        print(f"\n{'='*50}")
        print(f"  🎧 {AI_NAME} C3 + macOS Calendar")
        print(f"{'='*50}")
        print(f"✅ Whisper: {'OK' if OPENAI_API_KEY else 'NO'}")
        print(f"✅ Calendar: {'OK' if self.calendar.available else 'NO'}")
        print(f"✅ 'Hey Orion'이라고 말하세요!")
        print(f"{'='*50}\n")
        
        self.notify("오리온 C3 시작됨!")
        self.speak("오리온 C3 가동되었습니다. 언제든 불러주세요, sir.")
        
        while self.is_running:
            try:
                if self.is_speaking:
                    time.sleep(0.1)
                    continue
                
                audio_data = self.record_audio(duration=4)
                
                if audio_data is None:
                    continue
                
                text = self.transcribe(audio_data)
                
                if not text or len(text.strip()) < 2:
                    continue
                
                print(f"👂 들림: '{text}'")
                
                text_lower = text.lower()
                wake_detected = any(wake in text_lower for wake in WAKE_WORDS)
                
                if wake_detected:
                    print("✨ Wake word!")
                    
                    command = self.extract_command(text)
                    
                    if command:
                        print(f"📝 명령: '{command}'")
                        self.process_command(command)
                    else:
                        self.speak("네, 말씀하세요, sir.")
                        
                        audio_data2 = self.record_audio(duration=8)
                        if audio_data2 is not None:
                            command = self.transcribe(audio_data2)
                            if command:
                                print(f"📝 명령: '{command}'")
                                self.process_command(command)
                
            except KeyboardInterrupt:
                print("\n🛑 Ctrl+C")
                break
            except Exception as e:
                print(f"⚠️ 에러: {e}")
                time.sleep(0.5)
        
        print("\n👋 오리온 C3 종료")
        self.music_player.stop()


if __name__ == "__main__":
    if not os.path.exists(MUSIC_FOLDER):
        os.makedirs(MUSIC_FOLDER)
    
    orion = OrionPortable()
    orion.run()