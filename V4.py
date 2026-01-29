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
AI_NAME = "Orion"
PROFILE_FILE = "user_profile.txt"
TEMP_IMAGE = "temp_capture.png"
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"

# ElevenLabs 설정
ELEVENLABS_VOICE_ID = "QYrOVogqhHWUzdZFXf0E"
ELEVENLABS_API_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

# 쓰레드 간 UI 통신을 위한 신호 관리자 (맥북 GUI 충돌 방지)
class SignalManager(QObject):
    show_camera = pyqtSignal()
    close_camera = pyqtSignal()

# --- [리퀴드 글래스 스타일 카메라 위젯] ---
class CameraWindow(QMainWindow):
    def __init__(self, capture_callback):
        super().__init__()
        self.capture_callback = capture_callback
        
        # 초소형 위젯 설정 (Frameless, Always on Top)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 디버깅: 화면 중앙 근처로 위치 변경
        screen = QApplication.primaryScreen().geometry()
        width, height = 115, 145
        self.setGeometry(screen.widthx) - width - 5, screen.height() - height - 45, width, height)
        # self.setGeometry(100, 100, width, height)  # 디버깅용: 좌상단 근처
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
        
        # 카메라 초기화 + 디버깅
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
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
        ret, frame = self.cap.read()
        if ret:
            frame = cv2.flip(frame, 1)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame.shape
            q_img = QImage(frame.data, w, h, ch * w, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img).scaled(103, 80, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(pixmap)

    def take_photo(self):
        ret, frame = self.cap.read()
        if ret:
            cv2.imwrite(TEMP_IMAGE, frame)
            threading.Thread(target=self.capture_callback, daemon=True).start()

    def close_cam(self):
        print("🔴 CameraWindow.close_cam() 호출됨")
        self.hide()

# --- [메인 봇 클래스: 오리온 V4] ---
class OrionBot:
    def __init__(self, signal_manager):
        self.is_active = False
        self.screen_mode_waiting = False 
        self.full_input = ""
        self.short_term_memory = []
        self.signals = signal_manager
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
        """ElevenLabs TTS로 영어 음성 출력 (비동기)"""
        def _speak():
            try:
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
        """V2의 모든 대화/검색/사고 로직 복구 + 시간/날씨/뉴스 강화"""
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
                print(f"🔤 입력된 명령: '{cmd}'")  # 디버깅
                
                if not self.is_active:
                    if cmd.endswith(START_TRIGGER):
                        self.is_active = True
                        print("🟢 오리온 활성화됨")
                        self.notify("오리온 V4 연결 완료!")
                        self.speak_with_elevenlabs("오리온 V4 연결 완료!")
                elif self.is_active:
                    if cmd.endswith(EXIT_TRIGGER):
                        self.is_active = False
                        self.signals.close_camera.emit()
                        self.notify("퇴근한다! 이따 봐!")
                        self.speak_with_elevenlabs("퇴근한다! 이따 봐!")
                    elif cmd == CAMERA_TRIGGER:
                        print("🎯 카메라 트리거 감지됨")
                        self.activate_python_app()
                        print("📡 show_camera 시그널 emit 전")
                        self.signals.show_camera.emit()
                        print("📡 show_camera 시그널 emit 후")
                        self.notify("카메라 모드 켠다! ㅋㅋ")
                        self.speak_with_elevenlabs("카메라 모드 켠다!")
                    elif cmd == SCREEN_TRIGGER:
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
    app = QApplication(sys.argv)
    
    sigs = SignalManager()
    print("📦 SignalManager 생성됨")
    
    cam_win = CameraWindow(capture_callback=None)
    print("📷 CameraWindow 생성됨")
    
    orion = OrionBot(sigs)
    print("🤖 OrionBot 생성됨")
    
    cam_win.capture_callback = orion.get_gemini_vision
    
    sigs.show_camera.connect(cam_win.show)
    sigs.close_camera.connect(cam_win.close_cam)
    print("🔗 시그널 연결 완료")
    
    listener = keyboard.Listener(on_press=orion.on_press)
    listener.start()
    print("⌨️ 키보드 리스너 시작됨")
    
    print(f"--- [{AI_NAME}] V4 디버그 버전 가동 중 ---")
    print(f"[TTS] ElevenLabs Voice ID: {ELEVENLABS_VOICE_ID}")
    print("=" * 50)
    print("💡 '123enter' 입력 후 엔터 → 활성화")
    print("💡 'cameramode' 입력 후 엔터 → 카메라")
    print("=" * 50)
    
    sys.exit(app.exec())