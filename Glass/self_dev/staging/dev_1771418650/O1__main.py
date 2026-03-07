"""
Orion O1 -- EDITH Smart Glasses Server
======================================
실행: python -m O1.main

시작되는 것들:
  1. FastAPI 서버 (WebSocket: 글래스/테스트 클라이언트 연결)
  2. 오디오 루프 (Cleer ARC 이어폰 → Whisper STT → Claude → ElevenLabs TTS)
  3. HUD 렌더러 (240x240 EDITH 스타일 디스플레이 프레임 생성)
  4. 자가개발 엔진 (idle 시 자동으로 코드 개선)
"""

import os
import sys
import subprocess
import time
import threading
import asyncio

from O1 import config
from O1.core.brain import OrionBrain
from O1.core.stt import SpeechToText
from O1.core.tts import TextToSpeech
from O1.core.calendar_manager import MacCalendar
from O1.core.music_player import MusicPlayer
from O1.core.wake_word import QueryClassifier
from O1.self_dev.engine import SelfDevEngine

# HUD와 서버는 Phase 2/3에서 활성화
try:
    from O1.hud.renderer import HUDRenderer
    HUD_AVAILABLE = True
except ImportError:
    HUD_AVAILABLE = False

try:
    import uvicorn
    from O1.server.app import create_app
    SERVER_AVAILABLE = True
except ImportError:
    SERVER_AVAILABLE = False


class OrionO1:
    """Orion O1 메인 오케스트레이터"""

    def __init__(self):
        # API 키 검증 (최우선)
        try:
            config.validate_api_keys()
        except ValueError as e:
            print(f"\n❌ {e}")
            print("⚠️  Please check your .env file and ensure all required API keys are set.")
            sys.exit(1)

        print(f"\n{'='*50}")
        print(f"  🕶️ {config.AI_NAME} O1 - EDITH Smart Glasses")
        print(f"{'='*50}")

        # 코어 모듈 초기화
        self.brain = OrionBrain()
        self.stt = SpeechToText()
        self.tts = TextToSpeech()
        self.calendar = MacCalendar()
        self.music = MusicPlayer()

        # TTS에 music_player 연결 (duck/unduck)
        self.tts.music_player = self.music

        # HUD 렌더러 (있으면)
        self.hud = HUDRenderer() if HUD_AVAILABLE else None

        # 자가개발 엔진
        self.self_dev = SelfDevEngine(config._PROJECT_ROOT)
        self.self_dev.on_dev_complete(self._on_dev_complete)
        self.self_dev.on_dev_failed(self._on_dev_failed)

        # 후속 대화 상태
        self._followup_mode = False
        self._followup_deadline = 0
        self._pending_session_id = None
        self._applied_session_id = None

        # 상태
        self.is_running = True
        self.hud_state = {
            "ai_response": "",
            "notification": "",
            "last_heard": "",
            "listening": False,
            "thinking": False,
        }

        # 상태 출력
        print(f"✅ Whisper STT: {'OK' if config.OPENAI_API_KEY else 'NO'}")
        print(f"✅ Calendar: {'OK' if self.calendar.available else 'NO'}")
        print(f"✅ HUD Renderer: {'OK' if HUD_AVAILABLE else 'Phase 3에서 활성화'}")
        print(f"✅ FastAPI Server: {'OK' if SERVER_AVAILABLE else 'Phase 2에서 활성화'}")
        print(f"✅ Self-Dev Engine: OK")
        print(f"✅ 'Hey Orion'이라고 말하세요!")
        print(f"{'='*50}\n")

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

    def _on_dev_complete(self, session_id):
        """자가개발 완료 콜백 - 다음 사용자 상호작용 시 알림"""
        self._pending_session_id = session_id
        # 진행률 바 제거
        self.hud_state.pop("dev_progress", None)
        self.notify("Self-development complete! New improvement ready.")
        print(f"[SelfDev] Session {session_id} ready for review.")

    def _on_dev_failed(self, error_msg, is_user_task):
        """자가개발 실패 콜백 - 사용자 요청이었으면 TTS로 알림"""
        self.hud_state.pop("dev_progress", None)
        if is_user_task:
            short_err = error_msg[:80] if len(error_msg) > 80 else error_msg
            self.tts.speak(f"Sir, I wasn't able to complete the task. {short_err}")
            self.notify(f"Self-dev failed: {short_err}")
        print(f"[SelfDev] Failed: {error_msg}")

    def _check_followup(self, text):
        """후속 대화 처리. 처리됐으면 True, 아니면 False."""
        if not self._followup_mode:
            return False
        if time.time() > self._followup_deadline:
            self._followup_mode = False
            return False

        cmd = text.lower().strip()

        # 시나리오 1: 대기 중인 업데이트 → "시도하시겠어요?"
        if self._pending_session_id and not self._applied_session_id:
            if any(w in cmd for w in ["yes", "try", "sure", "go ahead", "네", "응", "해봐", "해 봐", "좋아"]):
                success = self.self_dev.apply_update(self._pending_session_id)
                if success:
                    session_info = self.self_dev.get_session_info(self._pending_session_id)
                    demo = session_info.get("demo_script", "The changes have been applied.") if session_info else "Changes applied."
                    self.tts.speak(demo)
                    self._applied_session_id = self._pending_session_id
                    self._pending_session_id = None
                    # 2차 확인 질문
                    self.tts.speak("Would you like to keep these changes, sir?")
                    self._followup_mode = True
                    self._followup_deadline = time.time() + config.SELF_DEV_FOLLOWUP_SEC
                else:
                    self.tts.speak("Sir, there was an issue applying the update.")
                    self._followup_mode = False
                return True

            elif any(w in cmd for w in ["no", "skip", "later", "아니", "나중에", "됐어"]):
                self.tts.speak("Understood, sir. I'll keep it staged for later.")
                self._pending_session_id = None
                self._followup_mode = False
                return True

        # 시나리오 2: 적용된 업데이트 → "유지하시겠어요?"
        if self._applied_session_id:
            if any(w in cmd for w in ["yes", "keep", "commit", "save", "네", "응", "유지", "좋아"]):
                success = self.self_dev.commit_update(self._applied_session_id)
                if success:
                    self.tts.speak("Changes committed permanently, sir. Update complete.")
                else:
                    self.tts.speak("Sir, the commit failed. Changes are still applied though.")
                self._applied_session_id = None
                self._followup_mode = False
                return True

            elif any(w in cmd for w in ["no", "revert", "rollback", "undo", "아니", "취소", "되돌려"]):
                success = self.self_dev.rollback_update(self._applied_session_id)
                if success:
                    self.tts.speak("Changes reverted, sir. Back to the previous version.")
                else:
                    self.tts.speak("Sir, the rollback failed. Please check manually.")
                self._applied_session_id = None
                self._followup_mode = False
                return True

        self._followup_mode = False
        return False

    def _offer_pending_update(self):
        """대기 중인 업데이트가 있으면 사용자에게 제안"""
        if not self._pending_session_id:
            return
        session_info = self.self_dev.get_session_info(self._pending_session_id)
        if not session_info:
            self._pending_session_id = None
            return
        summary = session_info.get("summary", "an improvement")
        self.tts.speak(f"Sir, while you were away, I worked on an improvement. {summary}. Would you like to try it?")
        self._followup_mode = True
        self._followup_deadline = time.time() + config.SELF_DEV_FOLLOWUP_SEC

    def _extract_music_query(self, text):
        """Extract song name from text using a single-pass keyword search.

        Returns the song name string if a music play keyword is found,
        or None if no keyword matched.
        """
        cmd = text.lower()
        # 키워드 목록: 긴 것부터 먼저 매칭 ("틀어줘 " before "틀어 ")
        music_keywords = ["틀어줘 ", "플레이 ", "틀어 ", "play "]
        for kw in music_keywords:
            idx = cmd.find(kw)
            if idx != -1:
                song = text[idx + len(kw):].strip()
                return song if song else None
        return None

    def process_command(self, text):
        """음성 명령 라우팅"""
        # 사용자 활동 기록
        self.self_dev.record_user_activity()

        cmd = text.lower()

        # 종료
        if any(w in cmd for w in ["goodbye", "shut down", "turn off", "종료"]):
            self.tts.speak("Shutting down Orion O1. Goodbye, sir.")
            self.is_running = False
            return

        # 음악 재생 - 단일 패스 키워드 감지 및 추출
        song = self._extract_music_query(text)
        if song is not None:
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

        # 캘린더 / 일반 대화
        def calendar_handler(t):
            return self.brain.handle_calendar_query(t, self.calendar)

        answer = self.brain.get_response(text, calendar_handler=calendar_handler)

        # HUD 업데이트
        self.hud_state["ai_response"] = answer

        self.notify(answer)
        self.tts.speak(answer)

    def _update_dev_progress(self):
        """HUD에 개발 진행률 동기화"""
        progress = self.self_dev.get_progress()
        if progress.get("active"):
            self.hud_state["dev_progress"] = progress
        elif "dev_progress" in self.hud_state:
            del self.hud_state["dev_progress"]

    def audio_loop(self):
        """메인 음성 감지 루프"""
        while self.is_running:
            try:
                # 개발 진행률 HUD 업데이트
                self._update_dev_progress()

                if self.tts.is_speaking:
                    time.sleep(0.1)
                    continue

                # TTS 직후 에코 방지: 쿨다운 + 높은 볼륨 임계값
                since_spoke = time.time() - self.tts.last_spoke_time
                if 0 < since_spoke < config.AUDIO_ECHO_COOLDOWN_SEC:
                    time.sleep(config.AUDIO_ECHO_COOLDOWN_SEC - since_spoke)
                    continue

                # TTS 직후 N초간: 스피커 잔향 필터, 실제 목소리만 통과
                post_tts = time.time() - self.tts.last_spoke_time < config.AUDIO_ECHO_FILTER_SEC
                vol_threshold = config.AUDIO_ECHO_THRESHOLD if post_tts else config.AUDIO_NORMAL_THRESHOLD

                audio_data = self.stt.record(duration=config.AUDIO_VAD_DURATION, min_volume=vol_threshold)
                if audio_data is None:
                    continue

                text = self.stt.transcribe(audio_data)
                if not text or len(text.strip()) < 2:
                    continue

                # 실시간 인식 텍스트 표시
                print(f"\n{'─'*40}")
                print(f"  👂 인식: {text}")
                print(f"{'─'*40}")
                self.hud_state["last_heard"] = text

                # 후속 대화 모드: wake word 없이 응답 수락
                if self._followup_mode and time.time() < self._followup_deadline:
                    if self._check_followup(text):
                        continue

                if QueryClassifier.is_wake_word(text):
                    print("  ✨ Wake word 감지!")
                    self.self_dev.record_user_activity()
                    command = QueryClassifier.extract_command(text)

                    # 대기 중인 자가개발 업데이트 알림
                    if self._pending_session_id and not self._followup_mode:
                        self._offer_pending_update()
                        # wake word만 있었으면 업데이트 제안으로 대체
                        if not command:
                            continue

                    if command:
                        # 후속 대화 체크
                        if self._check_followup(command):
                            continue

                        print(f"  📝 명령: {command}")
                        self.hud_state["thinking"] = True
                        self.hud_state["last_heard"] = command
                        self.process_command(command)
                        self.hud_state["thinking"] = False
                    else:
                        self.tts.speak("Yes, sir. Go ahead.")
                        self.hud_state["listening"] = True

                        audio_data2 = self.stt.record(duration=10)
                        if audio_data2 is not None:
                            command = self.stt.transcribe(audio_data2)
                            if command:
                                print(f"\n{'─'*40}")
                                print(f"  📝 명령: {command}")
                                print(f"{'─'*40}")
                                self.hud_state["thinking"] = True
                                self.hud_state["last_heard"] = command
                                self.process_command(command)
                                self.hud_state["thinking"] = False
                        self.hud_state["listening"] = False

            except KeyboardInterrupt:
                print("\n🛑 Ctrl+C")
                break
            except Exception as e:
                print(f"⚠️ 에러: {e}")
                time.sleep(0.5)

    def run(self):
        """메인 실행"""
        self.notify("Orion O1 Online")
        self.tts.speak("Orion O1 is now online. Call me anytime, sir.")

        # 크래시 복구: applied 상태 세션 자동 롤백
        applied = self.self_dev.has_applied_sessions()
        for session in applied:
            print(f"[SelfDev] Crash recovery: rolling back {session['session_id']}")
            self.self_dev.rollback_update(session["session_id"])

        # 사용자 기능 요청 체크 (X 버튼 → 입력창에서 저장된 요청)
        task_request = self.self_dev.check_task_request()
        if task_request:
            req_text = task_request.get("request", "")
            req_type = task_request.get("type", "user_feature")
            if req_type == "self_improve":
                self.tts.speak("Sir, starting automatic self-improvement mode.")
            else:
                short_name = req_text[:50] if len(req_text) > 50 else req_text
                self.tts.speak(f"Sir, I'm starting work on your requested feature: {short_name}")
            self.self_dev.start_user_task(task_request)
            # 처리 완료 → 파일 삭제
            try:
                os.remove(config.TASK_REQUEST_FILE)
            except OSError:
                pass

        # 완료된 자가개발 체크
        pending = self.self_dev.has_pending_updates()
        if pending:
            latest = pending[-1]
            self._pending_session_id = latest["session_id"]
            summary = latest.get("summary", "an improvement")
            self.tts.speak(
                f"Sir, while you were away, I worked on an improvement. "
                f"{summary}. Would you like to try it?"
            )
            self._followup_mode = True
            self._followup_deadline = time.time() + config.SELF_DEV_FOLLOWUP_SEC

        # 자가개발 idle 모니터링 시작
        self.self_dev.start_monitoring()

        # FastAPI 서버 시작
        if SERVER_AVAILABLE:
            app = create_app(self)
            server_thread = threading.Thread(
                target=lambda: uvicorn.run(app, host=config.WS_HOST, port=config.HTTP_PORT, log_level="warning"),
                daemon=True,
            )
            server_thread.start()
            print(f"🌐 서버 시작: http://localhost:{config.HTTP_PORT}")

        # HUD 테스트 클라이언트 자동 시작
        self._hud_process = None
        if SERVER_AVAILABLE and HUD_AVAILABLE:
            time.sleep(1)  # 서버 준비 대기
            try:
                self._hud_process = subprocess.Popen(
                    [sys.executable, "-m", "O1.client.test_hud"],
                    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                )
                print("🕶️ HUD 클라이언트 시작됨")
            except Exception as e:
                print(f"⚠️ HUD 클라이언트 시작 실패: {e}")

        # 오디오 루프 (메인 스레드)
        try:
            self.audio_loop()
        finally:
            print("\n👋 오리온 O1 종료")
            self.self_dev.stop()
            self.music.stop()
            if self._hud_process:
                self._hud_process.terminate()
                print("🕶️ HUD 클라이언트 종료됨")


def main():
    if not os.path.exists(config.MUSIC_FOLDER):
        os.makedirs(config.MUSIC_FOLDER)

    orion = OrionO1()
    orion.run()


if __name__ == "__main__":
    main()
