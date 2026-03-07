import sys
import subprocess
import os
import datetime
import unicodedata
import base64
import cv2
import threading
import requests
import tempfile
import time
import mediapipe as mp
import pyautogui
import pygame
from anthropic import Anthropic
from tavily import TavilyClient
from pynput import keyboard
from dotenv import load_dotenv
from jamo import jamo_to_hcj
from google import genai
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QPushButton, QWidget, QFrame
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QObject
from PyQt6.QtGui import QImage, QPixmap
from PIL import Image

# 1. 환경 설정 및 API 로드
load_dotenv()
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
gemini_client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

START_TRIGGER = "123enter"
EXIT_TRIGGER = "123exit"
SCREEN_TRIGGER = "screenmode"
CAMERA_TRIGGER = "cameramode"
GESTURE_TRIGGER = "gesturemode"
PLAYSONG_TRIGGER = "playsong"
STOPSONG_TRIGGER = "stopsong"
IGNORE_TRIGGER = "ignore"
IGNOREX_TRIGGER = "ignorex"
AI_NAME = "Orion"
PROFILE_FILE = "user_profile.txt"
TEMP_IMAGE = "temp_capture.png"
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
MUSIC_FOLDER = "Music"

# ElevenLabs 설정
ELEVENLABS_VOICE_ID = "QYrOVogqhHWUzdZFXf0E"
ELEVENLABS_API_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

# 쓰레드 간 UI 통신을 위한 신호 관리자 (맥북 GUI 충돌 방지)
class SignalManager(QObject):
    show_camera = pyqtSignal()
    close_camera = pyqtSignal()
    show_debug = pyqtSignal()
    hide_debug = pyqtSignal()
    update_debug_frame = pyqtSignal(object)  # 프레임 전달용

# --- [음악 플레이어 클래스 - pygame 기반 실시간 볼륨 조절] ---
class MusicPlayer:
    def __init__(self):
        pygame.mixer.init()
        self.is_playing = False
        self.current_song = None
        self.current_filepath = None
        self.normal_volume = 0.2    # 기본 볼륨 (0.0 ~ 1.0)
        self.ducked_volume = 0.05   # TTS 중 볼륨 (15%)
    
    def duck(self):
        """TTS 시작 시 음악 볼륨 낮추기 (실시간, 재시작 없음)"""
        if self.is_playing:
            pygame.mixer.music.set_volume(self.ducked_volume)
            print(f"🔉 음악 볼륨 낮춤: {self.normal_volume} → {self.ducked_volume}")
    
    def unduck(self):
        """TTS 끝나면 음악 볼륨 복구 (실시간, 재시작 없음)"""
        if self.is_playing:
            pygame.mixer.music.set_volume(self.normal_volume)
            print(f"🔊 음악 볼륨 복구: {self.ducked_volume} → {self.normal_volume}")
    
    def play(self, song_name):
        """노래 재생 (무한 반복)"""
        self.stop()  # 기존 재생 중지
        
        # 파일명 매칭: 공백 → 언더스코어, 확장자 없으면 .mp3 추가
        filename = song_name.strip().replace(" ", "_")
        if not filename.lower().endswith(".mp3"):
            filename += ".mp3"
        
        filepath = os.path.join(MUSIC_FOLDER, filename)
        
        # 파일 존재 확인
        if not os.path.exists(filepath):
            # 대소문자 무시 검색
            if os.path.exists(MUSIC_FOLDER):
                for f in os.listdir(MUSIC_FOLDER):
                    if f.lower() == filename.lower():
                        filepath = os.path.join(MUSIC_FOLDER, f)
                        break
                else:
                    print(f"❌ 음악 파일 없음: {filepath}")
                    return False
            else:
                print(f"❌ Music 폴더 없음!")
                return False
        
        try:
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.set_volume(self.normal_volume)
            pygame.mixer.music.play(loops=-1)  # -1 = 무한 반복
            self.is_playing = True
            self.current_song = song_name
            self.current_filepath = filepath
            print(f"🎵 재생 시작: {filename}")
            return True
        except Exception as e:
            print(f"재생 에러: {e}")
            return False
    
    def stop(self):
        """재생 중지"""
        if self.is_playing:
            pygame.mixer.music.stop()
        self.is_playing = False
        self.current_song = None
        self.current_filepath = None
        print("🛑 음악 중지됨")

# --- [공유 카메라 매니저] ---
class SharedCamera:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized: return
        self._initialized = True
        self.cap = cv2.VideoCapture(0)
        self.lock = threading.Lock()
        self.last_frame = None
    
    def read(self):
        with self.lock:
            ret, frame = self.cap.read()
            if ret: self.last_frame = frame.copy()
            return ret, self.last_frame

# --- [제스처 인식 컨트롤러] ---
class GestureController:
    def __init__(self, shared_camera, signals):
        self.is_running = False
        self.shared_camera = shared_camera
        self.signals = signals
        self.mp_hands = mp.solutions.hands
        self.mp_draw = mp.solutions.drawing_utils
        self.hands = self.mp_hands.Hands(
            static_image_mode=False, max_num_hands=1,
            model_complexity=1, min_detection_confidence=0.5, min_tracking_confidence=0.5
        )
        self.prev_state = None
        self.stable_count = 0
        self.last_time = 0

    def start(self):
        if self.is_running: return
        self.is_running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.is_running = False

    def _run(self):
        while self.is_running:
            ret, frame = self.shared_camera.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue
            
            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.hands.process(rgb)
            
            debug_frame = frame.copy()
            if results.multi_hand_landmarks:
                for hl in results.multi_hand_landmarks:
                    self.mp_draw.draw_landmarks(debug_frame, hl, self.mp_hands.HAND_CONNECTIONS)
                    self._process_gesture(hl)
            
            # PyQt 신호를 통해 안전하게 프레임 전달
            self.signals.update_debug_frame.emit(debug_frame)
            time.sleep(0.02)

    def _process_gesture(self, hl):
        tip, pip = hl.landmark[8], hl.landmark[6]
        is_ext = pip.y - tip.y > 0.06
        curr = "UP" if is_ext else "DOWN"
        
        if curr == self.prev_state: self.stable_count += 1
        else:
            self.stable_count = 1
            self.prev_state = curr
            return

        now = time.time()
        if now - self.last_time > 0.6 and self.stable_count >= 3:
            if curr == "UP": pyautogui.scroll(12)
            else: pyautogui.scroll(-12)
            self.last_time = now

# --- [PyQt 기반 디버그 윈도우 (소형, 우하단, 항상 최상단, 클릭 투과)] ---
class DebugWindow(QMainWindow):
    def __init__(self, signals):
        super().__init__()
        # 클릭 투과 핵심: WindowTransparentForInput
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 소형 사이즈
        width, height = 120, 90
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen.width() - width - 10, screen.height() - height - 50, width, height)
        
        self.container = QFrame(self)
        self.container.setStyleSheet("background-color: rgba(0, 0, 0, 150); border-radius: 8px;")
        self.container.setFixedSize(width, height)
        
        self.label = QLabel(self.container)
        self.label.setFixedSize(width - 10, height - 10)
        self.label.move(5, 5)
        self.setCentralWidget(self.container)
        signals.update_debug_frame.connect(self.set_image)

    def set_image(self, cv_img):
        rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch*w, QImage.Format.Format_RGB888)
        self.label.setPixmap(QPixmap.fromImage(img).scaled(110, 80, Qt.AspectRatioMode.KeepAspectRatio))

# --- [리퀴드 글래스 스타일 카메라 위젯] ---
class CameraWindow(QMainWindow):
    def __init__(self, shared_camera, capture_callback):
        super().__init__()
        self.shared_camera = shared_camera
        self.capture_callback = capture_callback
        
        # 초소형 위젯 설정 (Frameless, Always on Top)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 디버깅: 화면 중앙 근처로 위치 변경
        screen = QApplication.primaryScreen().geometry()
        width, height = 115, 145
        self.setGeometry(100, 100, width, height)  # 디버깅용: 좌상단 근처
        print(f"📐 화면 크기: {screen.width()}x{screen.height()}")
        print(f"📍 창 설정 위치: (100, 100, {width}, {height})")

        # 리퀴드 글래스 프레임
        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame {
                background-color: rgba(15, 15, 22, 180);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 12px;
            }
        """)
        self.container.setFixedSize(width, height)

        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(6, 6, 6, 6)
        self.layout.setSpacing(5)

        self.image_label = QLabel()
        self.image_label.setStyleSheet("border-radius: 8px; background: #000;")
        self.image_label.setFixedSize(103, 80)
        self.layout.addWidget(self.image_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_identify = QPushButton("Identify")
        self.btn_identify.setStyleSheet("""
            QPushButton {
                background-color: rgba(60, 130, 250, 170);
                color: white;
                border-radius: 6px;
                font-size: 10px;
                font-weight: bold;
                padding: 4px;
            }
            QPushButton:hover { background-color: rgba(80, 150, 255, 220); }
        """)
        self.btn_identify.clicked.connect(self.take_photo)
        self.layout.addWidget(self.btn_identify)

        self.setCentralWidget(self.container)
        
        # 카메라 연결 확인
        if not self.shared_camera.cap.isOpened():
            print("❌ 카메라 열기 실패! 권한 확인 필요")
        else:
            print("✅ 카메라 연결 성공")
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)

    def show(self):
        """오버라이드: 디버깅 + 창 활성화 강화"""
        print("✅ CameraWindow.show() 호출됨")
        super().show()
        self.raise_()  # 창을 맨 앞으로
        self.activateWindow()  # 창 활성화
        print(f"📍 실제 창 위치: {self.geometry().x()}, {self.geometry().y()}")
        print(f"👁️ 창 visible 상태: {self.isVisible()}")

    def update_frame(self):
        ret, frame = self.shared_camera.read()
        if ret and frame is not None:
            frame = cv2.flip(frame, 1)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame.shape
            q_img = QImage(frame.data, w, h, ch * w, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img).scaled(103, 80, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(pixmap)

    def take_photo(self):
        ret, frame = self.shared_camera.read()
        if ret:
            cv2.imwrite(TEMP_IMAGE, frame)
            threading.Thread(target=self.capture_callback, daemon=True).start()

    def close_cam(self):
        print("🔴 CameraWindow.close_cam() 호출됨")
        self.hide()

# --- [메인 봇 클래스: 오리온 V6.1] ---
class OrionBot:
    def __init__(self, signal_manager, shared_camera):
        self.is_active = False
        self.screen_mode_waiting = False 
        self.ignore_mode = False  # V6.1: ignore 모드 플래그
        self.full_input = ""
        self.short_term_memory = []
        self.signals = signal_manager
        self.shared_camera = shared_camera
        self.gesture_ctrl = GestureController(shared_camera, signal_manager)
        self.gesture_active = False
        self.music_player = MusicPlayer()  # 음악 플레이어 추가
        self.load_personal_profile()

    def load_personal_profile(self):
        extra_info = ""
        if os.path.exists(PROFILE_FILE):
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                extra_info = f.read()
        
        self.system_prompt = (
            f"당신은 건희의 베프이자 전용 AI 비서 '{AI_NAME}'이야! ㅋㅋ\n"
            f"[건희 정보]\n{extra_info}\n"
            "핵심 지침:\n"
            "1. 무조건 '반말'로 친구처럼 밝게 말해줘!\n"
            "2. 답변은 알림창용이니까 무조건 '한 문장'으로 아주 짧고 핵심만 말해.\n"
            "3. 이미지 분석 시에는 아주 구체적이고 재치 있게 설명해줘.\n"
            "4. 이전 대화 맥락을 기억해서 자연스럽게 이어가줘."
        )

    def fix_hangul(self, text):
        try:
            combined = jamo_to_hcj(text)
            return unicodedata.normalize('NFC', combined)
        except:
            return unicodedata.normalize('NFC', text)

    def activate_python_app(self):
        """최소화된 파이썬 앱을 화면 맨 앞으로 강제 활성화"""
        try:
            script = 'tell application "System Events" to set frontmost of every process whose name contains "Python" to true'
            subprocess.run(["osascript", "-e", script])
            print("🔄 Python 앱 활성화 시도")
        except Exception as e:
            print(f"App Activation Error: {e}")

    def capture_screen(self):
        try:
            subprocess.run(["screencapture", "-i", "-x", TEMP_IMAGE], check=True)
            return os.path.exists(TEMP_IMAGE)
        except:
            return False

    def translate_to_english(self, korean_text):
        """한국어 텍스트를 영어로 번역"""
        try:
            response = anthropic_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=200,
                messages=[{
                    "role": "user", 
                    "content": f"Translate this Korean text to natural English. The name '건희' should be written as 'Gun-hee'. Only output the translation, nothing else:\n\n{korean_text}"
                }]
            )
            result = response.content[0].text.strip()
            
            # 혹시 모를 잘못된 표기 교정
            result = result.replace("Geonhee", "Gun-hee")
            result = result.replace("Gunhee", "Gun-hee")
            result = result.replace("Keonhee", "Gun-hee")
            result = result.replace("건희", "Gun-hee")
            
            return result
        except Exception as e:
            print(f"Translation Error: {e}")
            return korean_text

    def speak_with_elevenlabs(self, text):
        """ElevenLabs TTS로 영어 음성 출력 (비동기) + 음악 볼륨 자동 조절"""
        def _speak():
            try:
                # 🔉 TTS 시작 전 음악 볼륨 낮추기
                self.music_player.duck()
                
                # 한국어 → 영어 번역
                english_text = self.translate_to_english(text)
                print(f"[TTS] 번역됨: {english_text}")
                
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
                    # 임시 파일로 저장 후 재생
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                        f.write(response.content)
                        temp_path = f.name
                    
                    # macOS에서 afplay로 재생
                    subprocess.run(["afplay", temp_path])
                    os.remove(temp_path)
                else:
                    print(f"[TTS Error] Status: {response.status_code}, {response.text}")
                    
            except Exception as e:
                print(f"[TTS Error] {e}")
            finally:
                # 🔊 TTS 끝나면 볼륨 복구
                self.music_player.unduck()
        
        # 비동기로 실행 (메인 스레드 블로킹 방지)
        threading.Thread(target=_speak, daemon=True).start()

    def get_vision_response(self, user_text, image_path):
        """기존 스크린샷 캡처 분석 (Claude)"""
        try:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            response = anthropic_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=300,
                system=self.system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_data}},
                            {"type": "text", "text": user_text}
                        ]
                    }
                ]
            )
            if os.path.exists(image_path): os.remove(image_path)
            return response.content[0].text.strip()
        except Exception as e:
            return f"이미지 분석하다가 렉 걸렸어 ㅠㅠ: {str(e)}"

    def get_gemini_vision(self):
        """실시간 카메라 분석 (Gemini 2.0 Flash)"""
        try:
            img = Image.open(TEMP_IMAGE)

            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=[
                    self.system_prompt + "\n이 이미지를 보고 재치 있게 한 문장으로 말해줘!",
                    img
                ]
            )
            
            answer = response.text.strip()
            self.notify(answer)
            self.speak_with_elevenlabs(answer)  # TTS 추가
            
            img.close()
            if os.path.exists(TEMP_IMAGE): 
                os.remove(TEMP_IMAGE)
                
        except Exception as e:
            print(f"Gemini Vision Error: {e}")
            self.notify("모델을 못 찾겠대! 이름을 다시 확인해볼게.")

    def get_ai_response(self, user_text):
        """모든 대화/검색/사고 로직 + 시간/날씨/뉴스 강화"""
        try:
            user_text = self.fix_hangul(user_text)
            
            now = datetime.datetime.now()
            time_info = f"[현재 시각: {now.strftime('%Y년 %m월 %d일 %A %H시 %M분')}]"
            
            force_search_keywords = ["날씨", "뉴스", "오늘", "최근", "현재", "지금", "실시간", "weather", "news"]
            needs_force_search = any(kw in user_text.lower() for kw in force_search_keywords)
            
            context = ""
            
            if needs_force_search:
                search_prompt = anthropic_client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=50,
                    messages=[{"role": "user", "content": f"'{user_text}'를 검색하기 위한 영어 검색어 하나만 출력해. 예: 'Seoul weather today'"}]
                )
                query = search_prompt.content[0].text.strip()
                res = tavily.search(query=query, search_depth="advanced", max_results=3)
                context = "\n\n[실시간 정보]: " + "\n".join([r['content'] for r in res['results']])
            else:
                thought_res = anthropic_client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=100,
                    messages=[{"role": "user", "content": f"질문: '{user_text}'\n검색 필요시 'SEARCH: [영어검색어]', 불필요시 'NO'만 대답."}]
                )
                thought = thought_res.content[0].text.strip()
                
                if "SEARCH:" in thought.upper():
                    query = thought.split(":", 1)[1].strip()
                    res = tavily.search(query=query, search_depth="advanced", max_results=3)
                    context = "\n\n[실시간 정보]: " + "\n".join([r['content'] for r in res['results']])

            messages = [{"role": m["role"], "content": m["content"]} for m in self.short_term_memory]
            messages.append({"role": "user", "content": f"{time_info}\n{user_text} {context}"})

            response = anthropic_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=300,
                system=self.system_prompt,
                messages=messages
            )
            answer = response.content[0].text.strip()
            
            self.short_term_memory.append({"role": "user", "content": user_text})
            self.short_term_memory.append({"role": "assistant", "content": answer})
            if len(self.short_term_memory) > 10: self.short_term_memory.pop(0)
            
            return answer
        except Exception as e:
            return f"엔진 과부하! ㅠㅠ: {str(e)}"

    def notify(self, msg):
        subprocess.run(["osascript", "-e", f'display notification "{msg.replace("\"", "'")}" with title "{AI_NAME}"'])

    def on_press(self, key):
        try:
            if hasattr(key, 'char') and key.char:
                self.full_input += key.char
            elif key == keyboard.Key.enter:
                cmd = self.full_input.strip()
                cmd_lower = cmd.lower()
                print(f"🔤 입력된 명령: '{cmd}'")  # 디버깅
                
                if not self.is_active:
                    if cmd.endswith(START_TRIGGER):
                        self.is_active = True
                        print("🟢 오리온 활성화됨")
                        self.notify("오리온 V6.1 연결 완료!")
                        self.speak_with_elevenlabs("오리온 V6.1 연결 완료!")
                elif self.is_active:
                    # 🔇 V6.1: ignore 모드일 때는 ignorex만 처리
                    if self.ignore_mode:
                        if cmd_lower == IGNOREX_TRIGGER:
                            self.ignore_mode = False
                            print("🔊 Ignore 모드 해제됨")
                            self.notify("채팅 감지 재개!")
                            self.speak_with_elevenlabs("다시 들을게!")
                        # ignore 모드에서는 다른 모든 입력 무시
                        self.full_input = ""
                        return
                    
                    # 🔇 V6.1: ignore 모드 진입
                    if cmd_lower == IGNORE_TRIGGER:
                        self.ignore_mode = True
                        print("🔇 Ignore 모드 진입")
                        self.notify("채팅 감지 일시정지! (ignorex로 해제)")
                        self.speak_with_elevenlabs("잠깐 쉴게!")
                    
                    elif cmd.endswith(EXIT_TRIGGER):
                        self.is_active = False
                        self.ignore_mode = False  # ignore 모드도 해제
                        self.gesture_ctrl.stop()
                        self.music_player.stop()  # 음악도 중지
                        self.signals.hide_debug.emit()
                        self.signals.close_camera.emit()
                        self.notify("퇴근한다! 이따 봐!")
                        self.speak_with_elevenlabs("퇴근한다! 이따 봐!")
                    
                    # 🎵 음악 재생 명령
                    elif cmd_lower.startswith(PLAYSONG_TRIGGER):
                        song_name = cmd[len(PLAYSONG_TRIGGER):].strip()
                        if song_name:
                            if self.music_player.play(song_name):
                                self.notify(f"🎵 {song_name} 재생 중!")
                                self.speak_with_elevenlabs(f"{song_name} 틀어줄게!")
                            else:
                                self.notify(f"❌ {song_name} 파일을 못 찾겠어!")
                                self.speak_with_elevenlabs(f"{song_name} 파일이 없어!")
                        else:
                            self.notify("노래 이름을 입력해줘!")
                            self.speak_with_elevenlabs("노래 이름 알려줘!")
                    
                    # 🛑 음악 중지 명령
                    elif cmd_lower == STOPSONG_TRIGGER:
                        if self.music_player.current_song:
                            song = self.music_player.current_song
                            self.music_player.stop()
                            self.notify(f"🛑 {song} 중지!")
                            self.speak_with_elevenlabs("음악 껐어!")
                        else:
                            self.notify("재생 중인 음악이 없어!")
                            self.speak_with_elevenlabs("지금 재생 중인 음악 없어!")
                    
                    elif cmd_lower == GESTURE_TRIGGER:
                        self.gesture_active = not self.gesture_active
                        if self.gesture_active:
                            self.gesture_ctrl.start()
                            self.signals.show_debug.emit()
                            self.notify("제스처 모드 ON!")
                            self.speak_with_elevenlabs("제스처 모드 ON!")
                        else:
                            self.gesture_ctrl.stop()
                            self.signals.hide_debug.emit()
                            self.notify("제스처 모드 OFF!")
                            self.speak_with_elevenlabs("제스처 모드 OFF!")
                    elif cmd_lower == CAMERA_TRIGGER:
                        print("🎯 카메라 트리거 감지됨")
                        self.activate_python_app()
                        print("📡 show_camera 시그널 emit 전")
                        self.signals.show_camera.emit()
                        print("📡 show_camera 시그널 emit 후")
                        self.notify("카메라 모드 켠다! ㅋㅋ")
                        self.speak_with_elevenlabs("카메라 모드 켠다!")
                    elif cmd_lower == SCREEN_TRIGGER:
                        self.notify("영역 선택해!")
                        self.speak_with_elevenlabs("영역 선택해!")
                        if self.capture_screen(): self.screen_mode_waiting = True
                    else:
                        query = self.fix_hangul(cmd)
                        if query:
                            self.notify("생각 중... ㅋㅋ")
                            if self.screen_mode_waiting:
                                answer = self.get_vision_response(query, TEMP_IMAGE)
                                self.screen_mode_waiting = False
                            else:
                                answer = self.get_ai_response(query)
                            self.notify(answer)
                            self.speak_with_elevenlabs(answer)  # TTS 추가!
                self.full_input = ""
            elif key == keyboard.Key.backspace:
                self.full_input = self.full_input[:-1]
        except Exception as e:
            print(f"❌ on_press 에러: {e}")

# --- [메인 실행 루프] ---
if __name__ == "__main__":
    print("🚀 프로그램 시작")
    
    # Music 폴더 자동 생성
    if not os.path.exists(MUSIC_FOLDER):
        os.makedirs(MUSIC_FOLDER)
        print(f"📁 {MUSIC_FOLDER} 폴더 생성됨")
    
    app = QApplication(sys.argv)
    
    cam = SharedCamera()
    print("📷 SharedCamera 생성됨")
    
    sigs = SignalManager()
    print("📦 SignalManager 생성됨")
    
    orion = OrionBot(sigs, cam)
    print("🤖 OrionBot 생성됨")
    
    cam_win = CameraWindow(cam, orion.get_gemini_vision)
    print("📷 CameraWindow 생성됨")
    
    dbg_win = DebugWindow(sigs)
    print("🖥️ DebugWindow 생성됨")
    
    sigs.show_camera.connect(cam_win.show)
    sigs.close_camera.connect(cam_win.close_cam)
    sigs.show_debug.connect(dbg_win.show)
    sigs.hide_debug.connect(dbg_win.hide)
    print("🔗 시그널 연결 완료")
    
    # 제스처 항상 활성화
    orion.gesture_ctrl.start()
    orion.gesture_active = True
    dbg_win.show()
    print("👋 제스처 인식 자동 시작됨")
    
    listener = keyboard.Listener(on_press=orion.on_press)
    listener.start()
    print("⌨️ 키보드 리스너 시작됨")
    
    print(f"--- [{AI_NAME}] V6.1 + Gesture + Music + Ignore 통합 버전 가동 중 ---")
    print(f"[TTS] ElevenLabs Voice ID: {ELEVENLABS_VOICE_ID}")
    print("=" * 50)
    print("💡 '123enter' 입력 후 엔터 → 활성화")
    print("💡 'cameramode' 입력 후 엔터 → 카메라")
    print("💡 'gesturemode' 입력 후 엔터 → 제스처 토글")
    print("💡 'screenmode' 입력 후 엔터 → 스크린 캡처")
    print("🎵 'playsong [노래이름]' 입력 후 엔터 → 음악 무한 재생")
    print("🛑 'stopsong' 입력 후 엔터 → 음악 중지")
    print("🔇 'ignore' 입력 후 엔터 → 채팅 감지 일시정지 (음악은 계속)")
    print("🔊 'ignorex' 입력 후 엔터 → 채팅 감지 재개")
    print("💡 '123exit' 입력 후 엔터 → 종료")
    print("👋 제스처 인식: 항상 활성화됨 (우하단 미니뷰어)")
    print(f"📁 음악 폴더: ./{MUSIC_FOLDER}/ (여기에 mp3 파일 넣기)")
    print("=" * 50)
    
    sys.exit(app.exec())