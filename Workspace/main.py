"""
Orion Workspace — 전체화면 AI 비서
===================================
실행: python -m Workspace.main

기능:
  1. 전체화면 PyQt6 윈도우 + GIF 비주얼라이저 (실시간 오디오 레벨 반응)
  2. 오디오 루프 (마이크 → Whisper STT → Claude → ElevenLabs TTS)
  3. 음악 재생, 캘린더 조회
  4. Wake word: "Hey Orion"
"""

import os
import sys
import subprocess
import time
import threading

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from Workspace import config
from Workspace.core.brain import OrionBrain
from Workspace.core.stt import SpeechToText
from Workspace.core.tts import TextToSpeech
from Workspace.core.calendar_manager import MacCalendar
from Workspace.core.music_player import MusicPlayer
from Workspace.core.wake_word import QueryClassifier
from Workspace.core.camera import WebcamCapture
from Workspace.core.vision import VisionAnalyzer
from Workspace.core.presence import PresenceDetector
from Workspace.ui.window import WorkspaceWindow


class OrionWorkspace:
    """Orion Workspace 오케스트레이터"""

    def __init__(self, window: WorkspaceWindow):
        # API 키 검증
        try:
            config.validate_api_keys()
        except ValueError as e:
            print(f"\n❌ {e}")
            sys.exit(1)

        self.window = window

        print(f"\n{'='*50}")
        print(f"  🖥️ {config.AI_NAME} Workspace")
        print(f"{'='*50}")

        # 코어 모듈 초기화
        self.brain = OrionBrain()
        self.stt = SpeechToText()
        self.tts = TextToSpeech()
        self.calendar = MacCalendar()
        self.music = MusicPlayer()

        # TTS에 music_player 연결 (duck/unduck)
        self.tts.music_player = self.music

        # TTS ↔ UI 연결 (실시간 오디오 레벨 → GIF 비주얼라이저)
        # 공유 변수 방식: TTS 스레드가 float 쓰기, UI 타이머가 폴링
        self.tts.on_amplitude = self._on_amplitude

        # 웹캠 + 비전 + 인체 감지
        self.camera = WebcamCapture(camera_index=config.CAMERA_INDEX, fps=config.CAMERA_FPS)
        self.vision = VisionAnalyzer()
        self.presence = PresenceDetector(
            camera=self.camera,
            on_user_arrived=self._on_user_arrived,
        )

        # Update Input 콜백 연결
        self.window.on_profile_update = self._handle_profile_update

        # 상태
        self.is_running = True

        # 상태 출력
        print(f"✅ Whisper STT: {'OK' if config.OPENAI_API_KEY else 'NO'}")
        print(f"✅ Calendar: {'OK' if self.calendar.available else 'NO'}")
        print(f"✅ Vision: {'OK' if self.vision.available else 'NO'}")
        print(f"✅ 'Hey Orion'이라고 말하세요!")
        print(f"{'='*50}\n")

    def _on_amplitude(self, value):
        """TTS 오디오 레벨 → 공유 변수에 직접 쓰기 (QTimer 불필요)"""
        self.window.set_amplitude(value)

    def _on_user_arrived(self):
        """사용자 등장 감지 → 웰컴 인사"""
        self.window.set_status("Welcome back, Sir!")
        self.tts.speak("Welcome back, Sir!")
        threading.Timer(4.0, lambda: self.window.set_status("")).start()

    def _handle_vision(self, text):
        """웹캠 스냅샷 → Gemini 비전 분석 → TTS 응답"""
        if not self.camera.available:
            self.tts.speak("Sir, the camera is not available.")
            return
        if not self.vision.available:
            self.tts.speak("Sir, vision analysis is not available.")
            return

        self.window.set_status("Analyzing what I see...")
        jpeg = self.camera.get_snapshot_jpeg()
        if not jpeg:
            self.tts.speak("Sir, I couldn't capture an image.")
            self.window.set_status("")
            return

        # 사용자 맥락이 있으면 프롬프트에 포함
        prompt = (
            "You are Orion, a JARVIS-like AI assistant. "
            f"The user asked: '{text}'. "
            "Describe what you see in this image in 1-2 concise English sentences. "
            "Start with 'Sir,'."
        )
        result = self.vision.analyze(jpeg, prompt=prompt)
        self.window.set_status(result)
        self.notify(result)
        self.tts.speak(result)
        threading.Timer(5.0, lambda: self.window.set_status("")).start()

    def _handle_profile_update(self, text):
        """Update Input에서 받은 텍스트 → 프로필 업데이트 + TTS 확인"""
        self.window.set_status(f"Updating: {text[:50]}...")
        success = self.brain.update_profile(text)
        if success:
            self.window.set_status("Profile updated.")
            self.tts.speak("Got it, sir. I'll remember that.")
        else:
            self.window.set_status("Update failed.")
            self.tts.speak("Sorry sir, I couldn't update your profile.")
        threading.Timer(4.0, lambda: self.window.set_status("")).start()

    def notify(self, msg):
        """macOS 알림"""
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{msg.replace(chr(34), chr(39))}" with title "{config.AI_NAME}"'],
                capture_output=True,
            )
        except Exception:
            pass

    def process_command(self, text):
        """음성 명령 라우팅"""
        cmd = text.lower()

        # 종료
        if any(w in cmd for w in ["goodbye", "shut down", "turn off", "종료"]):
            self.tts.speak("Shutting down Orion Workspace. Goodbye, sir.")
            self.is_running = False
            QTimer.singleShot(500, QApplication.quit)
            return

        # 음악 재생
        if any(w in cmd for w in ["play ", "플레이", "틀어"]):
            for kw in ["play ", "플레이 ", "틀어 ", "틀어줘 "]:
                if kw in cmd:
                    song = text[cmd.find(kw) + len(kw):].strip()
                    if song:
                        if self.music.play(song):
                            self.tts.speak(f"Playing {song}, sir.")
                        else:
                            self.tts.speak(f"I couldn't find {song}, sir.")
                        return

        # 음악 중지
        if any(w in cmd for w in ["stop music", "stop song", "음악 중지"]):
            self.music.stop()
            self.tts.speak("Music stopped, sir.")
            return

        # 볼륨
        if "volume up" in cmd:
            self.music.volume_up()
            self.tts.speak("Volume up, sir.")
            return
        if "volume down" in cmd:
            self.music.volume_down()
            self.tts.speak("Volume down, sir.")
            return

        # 비전 분석 — 웹캠 관련 키워드
        if any(w in cmd for w in [
            "뭐야", "뭔지", "뭐가 보여", "봐봐", "분석", "보여",
            "웹캠", "카메라", "들고 있는", "보이는",
            "what is this", "what do you see", "look at", "analyze",
            "what's this", "describe", "take a look", "webcam", "camera",
            "holding", "see this",
        ]):
            self._handle_vision(text)
            return

        # 캘린더 / 일반 대화
        def calendar_handler(t):
            return self.brain.handle_calendar_query(t, self.calendar)

        self.window.set_status("Thinking...")
        answer = self.brain.get_response(text, calendar_handler=calendar_handler)

        self.window.set_status(answer)
        self.notify(answer)
        self.tts.speak(answer)

        # 응답 후 5초 뒤 상태 초기화
        threading.Timer(5.0, lambda: self.window.set_status("")).start()

    def audio_loop(self):
        """메인 음성 처리 루프 — 연속 듣기 큐에서 음성 세그먼트 폴링"""
        while self.is_running:
            try:
                # TTS 재생 중이면 VAD 일시정지 + 큐 스킵
                if self.tts.is_speaking:
                    self.stt.paused = True
                    time.sleep(0.1)
                    continue

                # TTS 끝난 직후 — 에코 쿨다운
                since_spoke = time.time() - self.tts.last_spoke_time
                if 0 < since_spoke < config.AUDIO_ECHO_COOLDOWN_SEC:
                    self.stt.paused = True
                    time.sleep(config.AUDIO_ECHO_COOLDOWN_SEC - since_spoke)
                    # 쿨다운 끝나면 에코로 쌓인 큐 비우기
                    self.stt.flush_queue()
                    continue

                # 에코 필터 기간: 볼륨 임계값 높임
                post_tts = time.time() - self.tts.last_spoke_time < config.AUDIO_ECHO_FILTER_SEC
                self.stt.min_volume = config.AUDIO_ECHO_THRESHOLD if post_tts else config.AUDIO_NORMAL_THRESHOLD

                # VAD 활성화
                self.stt.paused = False

                # 큐에서 음성 세그먼트 대기
                audio_data = self.stt.get_speech(timeout=0.3)
                if audio_data is None:
                    continue

                text = self.stt.transcribe(audio_data)
                if not text or len(text.strip()) < 2:
                    continue

                print(f"\n{'─'*40}")
                print(f"  👂 인식: {text}")
                print(f"{'─'*40}")

                if QueryClassifier.is_wake_word(text):
                    print("  ✨ Wake word 감지!")
                    command = QueryClassifier.extract_command(text)

                    if command:
                        print(f"  📝 명령: {command}")
                        self.window.set_status(f"🎤 {command}")
                        self.process_command(command)
                    else:
                        self.tts.speak("Yes, sir. Go ahead.")
                        self.window.set_status("Listening...")

                        # 후속 명령 대기: 최대 녹음 길이 늘려서 긴 명령 수용
                        old_max = self.stt.max_duration
                        self.stt.max_duration = 15
                        audio_data2 = self.stt.get_speech(timeout=12)
                        self.stt.max_duration = old_max

                        if audio_data2 is not None:
                            command = self.stt.transcribe(audio_data2)
                            if command:
                                print(f"\n{'─'*40}")
                                print(f"  📝 명령: {command}")
                                print(f"{'─'*40}")
                                self.window.set_status(f"🎤 {command}")
                                self.process_command(command)

                        self.window.set_status("")

            except KeyboardInterrupt:
                print("\n🛑 Ctrl+C")
                self.is_running = False
                QTimer.singleShot(0, QApplication.quit)
                break
            except Exception as e:
                print(f"⚠️ 에러: {e}")
                time.sleep(0.5)

    def start(self):
        """시작 — 웹캠 + 연속 듣기 + 인사 + 오디오 루프 스레드"""
        # 웹캠 시작 + UI 연결 + 인체 감지
        if self.camera.start():
            self.window.set_webcam(self.camera)
            self.presence.start()
        else:
            print("⚠️ 웹캠 시작 실패 — 미리보기/감지 비활성화")

        # 연속 듣기 시작 (항상 오픈 마이크 스트림)
        self.stt.start_continuous()

        self.notify("Orion Workspace Online")
        self.tts.speak("Orion Workspace is now online. Call me anytime, sir.")

        # 오디오 처리 루프 (데몬 스레드)
        audio_thread = threading.Thread(target=self.audio_loop, daemon=True)
        audio_thread.start()

    def stop(self):
        """정리"""
        self.is_running = False
        self.stt.stop_continuous()
        self.presence.stop()
        self.camera.stop()
        self.music.stop()
        print("\n👋 Orion Workspace 종료")


def main():
    if not os.path.exists(config.MUSIC_FOLDER):
        os.makedirs(config.MUSIC_FOLDER)

    # PyQt6 애플리케이션
    app = QApplication(sys.argv)
    app.setApplicationName("Orion Workspace")

    # 전체화면 윈도우
    window = WorkspaceWindow()

    # 오케스트레이터
    orion = OrionWorkspace(window)

    # 윈도우 표시
    window.show()

    # 초기화 후 오디오 루프 시작 (100ms 지연 — UI 렌더링 대기)
    QTimer.singleShot(100, orion.start)

    # 종료 시 정리
    app.aboutToQuit.connect(orion.stop)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
