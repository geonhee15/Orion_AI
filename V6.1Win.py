# -*- coding: utf-8 -*-
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
from PIL import Image, ImageGrab
from winotify import Notification, audio

# Windows window activation
try:
    import win32gui
    import win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    print("[WARN] pywin32 not installed - window activation limited")

# 1. Environment & API Setup
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

# ElevenLabs Config
ELEVENLABS_VOICE_ID = "QYrOVogqhHWUzdZFXf0E"
ELEVENLABS_API_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

# Signal Manager for thread-safe UI communication
class SignalManager(QObject):
    show_camera = pyqtSignal()
    close_camera = pyqtSignal()
    show_debug = pyqtSignal()
    hide_debug = pyqtSignal()
    update_debug_frame = pyqtSignal(object)

# --- [Music Player - pygame based with realtime volume control] ---
class MusicPlayer:
    def __init__(self):
        pygame.mixer.init()
        self.is_playing = False
        self.current_song = None
        self.current_filepath = None
        self.normal_volume = 0.2
        self.ducked_volume = 0.05
    
    def duck(self):
        """Lower volume when TTS starts"""
        if self.is_playing:
            pygame.mixer.music.set_volume(self.ducked_volume)
            print(f"[Music] Volume ducked: {self.normal_volume} -> {self.ducked_volume}")
    
    def unduck(self):
        """Restore volume when TTS ends"""
        if self.is_playing:
            pygame.mixer.music.set_volume(self.normal_volume)
            print(f"[Music] Volume restored: {self.ducked_volume} -> {self.normal_volume}")
    
    def play(self, song_name):
        """Play song (infinite loop)"""
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
                    print(f"[Error] Music file not found: {filepath}")
                    return False
            else:
                print(f"[Error] Music folder not found!")
                return False
        
        try:
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.set_volume(self.normal_volume)
            pygame.mixer.music.play(loops=-1)
            self.is_playing = True
            self.current_song = song_name
            self.current_filepath = filepath
            print(f"[Music] Playing: {filename}")
            return True
        except Exception as e:
            print(f"[Error] Play error: {e}")
            return False
    
    def stop(self):
        """Stop playback"""
        if self.is_playing:
            pygame.mixer.music.stop()
        self.is_playing = False
        self.current_song = None
        self.current_filepath = None
        print("[Music] Stopped")

# --- [Shared Camera Manager] ---
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
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Windows: DirectShow
        self.lock = threading.Lock()
        self.last_frame = None
    
    def read(self):
        with self.lock:
            ret, frame = self.cap.read()
            if ret: self.last_frame = frame.copy()
            return ret, self.last_frame

# --- [Gesture Controller] ---
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

# --- [Debug Window (small, bottom-right, always on top, click-through)] ---
class DebugWindow(QMainWindow):
    def __init__(self, signals):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        width, height = 120, 90
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen.width() - width - 10, screen.height() - height - 80, width, height)
        
        self.container = QFrame(self)
        self.container.setStyleSheet("background-color: rgba(0, 0, 0, 150); border-radius: 8px;")
        self.container.setFixedSize(width, height)
        
        self.label = QLabel(self.container)
        self.label.setFixedSize(width - 10, height - 10)
        self.label.move(5, 5)
        self.setCentralWidget(self.container)
        signals.update_debug_frame.connect(self.set_image)
        
        self._set_click_through()

    def _set_click_through(self):
        """Set click-through on Windows"""
        if WIN32_AVAILABLE:
            try:
                hwnd = int(self.winId())
                extended_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                win32gui.SetWindowLong(
                    hwnd, 
                    win32con.GWL_EXSTYLE, 
                    extended_style | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
                )
            except Exception as e:
                print(f"[Error] Click-through setup failed: {e}")

    def set_image(self, cv_img):
        rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch*w, QImage.Format.Format_RGB888)
        self.label.setPixmap(QPixmap.fromImage(img).scaled(110, 80, Qt.AspectRatioMode.KeepAspectRatio))

# --- [Camera Window - Liquid Glass Style] ---
class CameraWindow(QMainWindow):
    def __init__(self, shared_camera, capture_callback):
        super().__init__()
        self.shared_camera = shared_camera
        self.capture_callback = capture_callback
        
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        screen = QApplication.primaryScreen().geometry()
        width, height = 115, 145
        self.setGeometry(100, 100, width, height)
        print(f"[Camera] Screen size: {screen.width()}x{screen.height()}")

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
        
        if not self.shared_camera.cap.isOpened():
            print("[Error] Camera open failed!")
        else:
            print("[Camera] Connected")
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)

    def show(self):
        print("[Camera] Window shown")
        super().show()
        self.raise_()
        self.activateWindow()

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
        print("[Camera] Window closed")
        self.hide()

# --- [Main Bot Class: Orion V6.1 Windows] ---
class OrionBot:
    def __init__(self, signal_manager, shared_camera):
        self.is_active = False
        self.screen_mode_waiting = False 
        self.ignore_mode = False
        self.full_input = ""
        self.short_term_memory = []
        self.signals = signal_manager
        self.shared_camera = shared_camera
        self.gesture_ctrl = GestureController(shared_camera, signal_manager)
        self.gesture_active = False
        self.music_player = MusicPlayer()
        self.load_personal_profile()

    def load_personal_profile(self):
        extra_info = ""
        if os.path.exists(PROFILE_FILE):
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                extra_info = f.read()
        
        # Korean system prompt (this is sent to AI, not console)
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
        """Bring Python app to front (Windows)"""
        if not WIN32_AVAILABLE:
            print("[WARN] pywin32 not available - skip activation")
            return
            
        try:
            def callback(hwnd, hwnds):
                title = win32gui.GetWindowText(hwnd).lower()
                if "python" in title or "orion" in title:
                    hwnds.append(hwnd)
                return True
            
            hwnds = []
            win32gui.EnumWindows(callback, hwnds)
            
            for hwnd in hwnds:
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(hwnd)
                except:
                    pass
            print("[App] Python app activated")
        except Exception as e:
            print(f"[Error] App activation: {e}")

    def capture_screen(self):
        """Windows screenshot capture"""
        try:
            screenshot = ImageGrab.grab()
            screenshot.save(TEMP_IMAGE)
            return os.path.exists(TEMP_IMAGE)
        except Exception as e:
            print(f"[Error] Screenshot: {e}")
            try:
                screenshot = pyautogui.screenshot()
                screenshot.save(TEMP_IMAGE)
                return os.path.exists(TEMP_IMAGE)
            except:
                return False

    def translate_to_english(self, korean_text):
        """Translate Korean text to English"""
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
            
            result = result.replace("Geonhee", "Gun-hee")
            result = result.replace("Gunhee", "Gun-hee")
            result = result.replace("Keonhee", "Gun-hee")
            result = result.replace("건희", "Gun-hee")
            
            return result
        except Exception as e:
            print(f"[Error] Translation: {e}")
            return korean_text

    def speak_with_elevenlabs(self, text):
        """ElevenLabs TTS (Windows) - pygame only"""
        def _speak():
            try:
                self.music_player.duck()
                
                english_text = self.translate_to_english(text)
                print(f"[TTS] Translated: {english_text}")
                
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
                    
                    try:
                        was_playing = self.music_player.is_playing
                        current_song = self.music_player.current_filepath
                        
                        if was_playing:
                            pygame.mixer.music.pause()
                        
                        pygame.mixer.music.load(temp_path)
                        pygame.mixer.music.set_volume(1.0)
                        pygame.mixer.music.play()
                        
                        while pygame.mixer.music.get_busy():
                            time.sleep(0.1)
                        
                        if was_playing and current_song:
                            pygame.mixer.music.load(current_song)
                            pygame.mixer.music.set_volume(self.music_player.normal_volume)
                            pygame.mixer.music.play(loops=-1)
                            
                    except Exception as e:
                        print(f"[Error] pygame TTS: {e}")
                    
                    try:
                        time.sleep(0.3)
                        os.remove(temp_path)
                    except:
                        pass
                else:
                    print(f"[TTS Error] Status: {response.status_code}")
                    
            except Exception as e:
                print(f"[TTS Error] {e}")
            finally:
                self.music_player.unduck()
        
        threading.Thread(target=_speak, daemon=True).start()

    def get_vision_response(self, user_text, image_path):
        """Screenshot analysis (Claude)"""
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
            return f"Image analysis error: {str(e)}"

    def get_gemini_vision(self):
        """Realtime camera analysis (Gemini 2.0 Flash)"""
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
            self.speak_with_elevenlabs(answer)
            
            img.close()
            if os.path.exists(TEMP_IMAGE): 
                os.remove(TEMP_IMAGE)
                
        except Exception as e:
            print(f"[Error] Gemini Vision: {e}")
            self.notify("Model not found!")

    def get_ai_response(self, user_text):
        """All conversation/search logic"""
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
                context = "\n\n[Realtime Info]: " + "\n".join([r['content'] for r in res['results']])
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
                    context = "\n\n[Realtime Info]: " + "\n".join([r['content'] for r in res['results']])

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
            return f"Engine error: {str(e)}"

    def notify(self, msg):
        """Windows 11 native notification (winotify)"""
        try:
            if len(msg) > 200:
                msg = msg[:197] + "..."
            
            toast = Notification(
                app_id=AI_NAME,
                title=AI_NAME,
                msg=msg,
                duration="short"
            )
            toast.set_audio(audio.Default, loop=False)
            toast.show()
            
        except Exception as e:
            print(f"[Error] Notification: {e}")
            print(f"[{AI_NAME}] {msg}")

    def on_press(self, key):
        try:
            if hasattr(key, 'char') and key.char:
                self.full_input += key.char
            elif key == keyboard.Key.enter:
                cmd = self.full_input.strip()
                cmd_lower = cmd.lower()
                print(f"[Input] '{cmd}'")
                
                if not self.is_active:
                    if cmd.endswith(START_TRIGGER):
                        self.is_active = True
                        print("[Orion] Activated")
                        self.notify("Orion V6.1 Windows Connected!")
                        self.speak_with_elevenlabs("오리온 V6.1 연결 완료!")
                elif self.is_active:
                    if self.ignore_mode:
                        if cmd_lower == IGNOREX_TRIGGER:
                            self.ignore_mode = False
                            print("[Mode] Ignore OFF")
                            self.notify("Chat detection resumed!")
                            self.speak_with_elevenlabs("다시 들을게!")
                        self.full_input = ""
                        return
                    
                    if cmd_lower == IGNORE_TRIGGER:
                        self.ignore_mode = True
                        print("[Mode] Ignore ON")
                        self.notify("Chat detection paused! (ignorex to resume)")
                        self.speak_with_elevenlabs("잠깐 쉴게!")
                    
                    elif cmd.endswith(EXIT_TRIGGER):
                        self.is_active = False
                        self.ignore_mode = False
                        self.gesture_ctrl.stop()
                        self.music_player.stop()
                        self.signals.hide_debug.emit()
                        self.signals.close_camera.emit()
                        self.notify("Goodbye! See you later!")
                        self.speak_with_elevenlabs("퇴근한다! 이따 봐!")
                    
                    elif cmd_lower.startswith(PLAYSONG_TRIGGER):
                        song_name = cmd[len(PLAYSONG_TRIGGER):].strip()
                        if song_name:
                            if self.music_player.play(song_name):
                                self.notify(f"Playing: {song_name}")
                                self.speak_with_elevenlabs(f"{song_name} 틀어줄게!")
                            else:
                                self.notify(f"File not found: {song_name}")
                                self.speak_with_elevenlabs(f"{song_name} 파일이 없어!")
                        else:
                            self.notify("Enter song name!")
                            self.speak_with_elevenlabs("노래 이름 알려줘!")
                    
                    elif cmd_lower == STOPSONG_TRIGGER:
                        if self.music_player.current_song:
                            song = self.music_player.current_song
                            self.music_player.stop()
                            self.notify(f"Stopped: {song}")
                            self.speak_with_elevenlabs("음악 껐어!")
                        else:
                            self.notify("No music playing!")
                            self.speak_with_elevenlabs("지금 재생 중인 음악 없어!")
                    
                    elif cmd_lower == GESTURE_TRIGGER:
                        self.gesture_active = not self.gesture_active
                        if self.gesture_active:
                            self.gesture_ctrl.start()
                            self.signals.show_debug.emit()
                            self.notify("Gesture Mode ON!")
                            self.speak_with_elevenlabs("제스처 모드 ON!")
                        else:
                            self.gesture_ctrl.stop()
                            self.signals.hide_debug.emit()
                            self.notify("Gesture Mode OFF!")
                            self.speak_with_elevenlabs("제스처 모드 OFF!")
                    
                    elif cmd_lower == CAMERA_TRIGGER:
                        print("[Trigger] Camera")
                        self.activate_python_app()
                        self.signals.show_camera.emit()
                        self.notify("Camera Mode ON!")
                        self.speak_with_elevenlabs("카메라 모드 켠다!")
                    
                    elif cmd_lower == SCREEN_TRIGGER:
                        self.notify("Capturing screen...")
                        self.speak_with_elevenlabs("스크린 캡처할게!")
                        if self.capture_screen():
                            self.screen_mode_waiting = True
                            self.notify("Captured! Enter your question.")
                        else:
                            self.notify("Capture failed!")
                    
                    else:
                        query = self.fix_hangul(cmd)
                        if query:
                            self.notify("Thinking...")
                            if self.screen_mode_waiting:
                                answer = self.get_vision_response(query, TEMP_IMAGE)
                                self.screen_mode_waiting = False
                            else:
                                answer = self.get_ai_response(query)
                            self.notify(answer)
                            self.speak_with_elevenlabs(answer)
                self.full_input = ""
            elif key == keyboard.Key.backspace:
                self.full_input = self.full_input[:-1]
        except Exception as e:
            print(f"[Error] on_press: {e}")

# --- [Main Execution] ---
if __name__ == "__main__":
    print("=" * 50)
    print(f"[{AI_NAME}] V6.1 Windows 11 Starting...")
    print("=" * 50)
    
    # Create Music folder
    if not os.path.exists(MUSIC_FOLDER):
        os.makedirs(MUSIC_FOLDER)
        print(f"[Folder] {MUSIC_FOLDER} created")
    
    app = QApplication(sys.argv)
    
    cam = SharedCamera()
    print("[Init] SharedCamera OK")
    
    sigs = SignalManager()
    print("[Init] SignalManager OK")
    
    orion = OrionBot(sigs, cam)
    print("[Init] OrionBot OK")
    
    cam_win = CameraWindow(cam, orion.get_gemini_vision)
    print("[Init] CameraWindow OK")
    
    dbg_win = DebugWindow(sigs)
    print("[Init] DebugWindow OK")
    
    sigs.show_camera.connect(cam_win.show)
    sigs.close_camera.connect(cam_win.close_cam)
    sigs.show_debug.connect(dbg_win.show)
    sigs.hide_debug.connect(dbg_win.hide)
    print("[Init] Signals connected")
    
    # Gesture always active
    orion.gesture_ctrl.start()
    orion.gesture_active = True
    dbg_win.show()
    print("[Init] Gesture recognition started")
    
    listener = keyboard.Listener(on_press=orion.on_press)
    listener.start()
    print("[Init] Keyboard listener started")
    
    print("=" * 50)
    print(f"[TTS] ElevenLabs Voice ID: {ELEVENLABS_VOICE_ID}")
    print("=" * 50)
    print("Commands:")
    print("  '123enter' + Enter -> Activate")
    print("  'cameramode' + Enter -> Camera")
    print("  'gesturemode' + Enter -> Gesture toggle")
    print("  'screenmode' + Enter -> Screen capture")
    print("  'playsong [name]' + Enter -> Play music")
    print("  'stopsong' + Enter -> Stop music")
    print("  'ignore' + Enter -> Pause chat detection")
    print("  'ignorex' + Enter -> Resume chat detection")
    print("  '123exit' + Enter -> Exit")
    print("=" * 50)
    print("[Gesture] Always active (mini viewer bottom-right)")
    print(f"[Music] Folder: ./{MUSIC_FOLDER}/ (put mp3 files here)")
    print("=" * 50)
    
    sys.exit(app.exec())