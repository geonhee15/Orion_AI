import sys
import subprocess
import os
import datetime
import unicodedata
import base64
import cv2
import threading
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

START_TRIGGER = "123enter"
EXIT_TRIGGER = "123exit"
SCREEN_TRIGGER = "screenmode"
CAMERA_TRIGGER = "cameramode"
AI_NAME = "Orion"
PROFILE_FILE = "user_profile.txt"
TEMP_IMAGE = "temp_capture.png"
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"

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
        
        # 앱 아이콘보다 살짝 큰 사이즈로 우측 하단 배치
        screen = QApplication.primaryScreen().geometry()
        width, height = 115, 145
        self.setGeometry(screen.width() - width - 5, screen.height() - height - 45, width, height)

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
        self.cap = cv2.VideoCapture(0)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)

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
        self.hide()

# --- [메인 봇 클래스: 오리온 V3] ---
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
        except Exception as e:
            print(f"App Activation Error: {e}")

    def capture_screen(self):
        try:
            subprocess.run(["screencapture", "-i", "-x", TEMP_IMAGE], check=True)
            return os.path.exists(TEMP_IMAGE)
        except:
            return False

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
        """실시간 카메라 분석 (Gemini 1.5 Flash) - 404 및 규격 에러 해결 버전"""
        try:
            # 1. PIL 이미지 객체 생성
            img = Image.open(TEMP_IMAGE)

            # 2. 모델 생성 및 호출
            # 모델명에서 'models/'를 제외하고 순수하게 이름만 입력해봐.
            # SDK가 내부적으로 API 버전을 맞추도록 유도함
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=[
                    self.system_prompt + "\n이 이미지를 보고 재치 있게 한 문장으로 말해줘!",
                    img
                ]
            )
            
            answer = response.text.strip()
            self.notify(answer)
            
            # 뒷정리
            img.close()
            if os.path.exists(TEMP_IMAGE): 
                os.remove(TEMP_IMAGE)
                
        except Exception as e:
            # 만약 그래도 404가 뜨면 모델명을 'gemini-1.5-flash-latest'로 바꿔보는 것도 방법이야.
            print(f"Gemini Vision Error: {e}")
            self.notify("모델을 못 찾겠대! 이름을 다시 확인해볼게.")

    def get_ai_response(self, user_text):
        """V2의 모든 대화/검색/사고 로직 복구 + 시간/날씨/뉴스 강화"""
        try:
            user_text = self.fix_hangul(user_text)
            
            # [추가] 현재 시간 정보 생성
            now = datetime.datetime.now()
            time_info = f"[현재 시각: {now.strftime('%Y년 %m월 %d일 %A %H시 %M분')}]"
            
            # [추가] 강제 검색 키워드 체크 (날씨, 뉴스 등은 무조건 검색)
            force_search_keywords = ["날씨", "뉴스", "오늘", "최근", "현재", "지금", "실시간", "weather", "news"]
            needs_force_search = any(kw in user_text.lower() for kw in force_search_keywords)
            
            context = ""
            
            if needs_force_search:
                # 강제 검색: 검색어 자동 생성
                search_prompt = anthropic_client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=50,
                    messages=[{"role": "user", "content": f"'{user_text}'를 검색하기 위한 영어 검색어 하나만 출력해. 예: 'Seoul weather today'"}]
                )
                query = search_prompt.content[0].text.strip()
                res = tavily.search(query=query, search_depth="advanced", max_results=3)
                context = "\n\n[실시간 정보]: " + "\n".join([r['content'] for r in res['results']])
            else:
                # 기존 로직: Claude 판단
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

            # 대화 메모리 로직
            messages = [{"role": m["role"], "content": m["content"]} for m in self.short_term_memory]
            # [수정] 시간 정보 + 컨텍스트 포함
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
                if not self.is_active:
                    if cmd.endswith(START_TRIGGER):
                        self.is_active = True
                        self.notify("오리온 V3 연결 완료!")
                elif self.is_active:
                    if cmd.endswith(EXIT_TRIGGER):
                        self.is_active = False
                        self.signals.close_camera.emit()
                        self.notify("퇴근한다! 이따 봐!")
                    elif cmd == CAMERA_TRIGGER:
                        # 앱 활성화 후 카메라 창 띄우기
                        self.activate_python_app()
                        self.signals.show_camera.emit()
                        self.notify("카메라 모드 켠다! ㅋㅋ")
                    elif cmd == SCREEN_TRIGGER:
                        self.notify("영역 선택해!")
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
                self.full_input = ""
            elif key == keyboard.Key.backspace:
                self.full_input = self.full_input[:-1]
        except: pass

# --- [메인 실행 루프] ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    sigs = SignalManager()
    cam_win = CameraWindow(capture_callback=None)
    
    orion = OrionBot(sigs)
    cam_win.capture_callback = orion.get_gemini_vision
    
    sigs.show_camera.connect(cam_win.show)
    sigs.close_camera.connect(cam_win.close_cam)
    
    listener = keyboard.Listener(on_press=orion.on_press)
    listener.start()
    
    print(f"--- [{AI_NAME}] V3 묵직한 맥 전용 풀버전 가동 중 ---")
    sys.exit(app.exec())