"""Work Assistant — hhheeelllppp 트리거로 Chrome 페이지 분석 & 자동 채우기

글로벌 키보드 모니터링 → Chrome 내용 추출 → Claude 분석 → 알림 → 자동 작업
모든 작업은 백그라운드 스레드에서 실행 (audio_loop 차단 없음)
"""

import time
import threading
import subprocess
import json

from anthropic import Anthropic
from O1 import config

# pynput 로드 (없으면 비활성화)
try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

# 트리거 패턴
_TRIGGER = config.WORK_ASSISTANT_TRIGGER  # "hhheeelllppp"
_VALID_CHARS = set(_TRIGGER)  # {'h', 'e', 'l', 'p'}


# ─── Chrome 헬퍼 (AppleScript 기반) ───

class _ChromeHelper:
    """Chrome 브라우저 인터랙션 (모든 작업 AppleScript 경유)"""

    def get_tab_info(self):
        """활성 Chrome 탭 title/URL 반환"""
        script = '''
        tell application "Google Chrome"
            set tabTitle to title of active tab of front window
            set tabURL to URL of active tab of front window
            return tabTitle & "|||" & tabURL
        end tell
        '''
        result = self._run_applescript(script)
        if result:
            parts = result.split("|||")
            return {"title": parts[0], "url": parts[1] if len(parts) > 1 else ""}
        return {"title": "", "url": ""}

    def get_page_content(self):
        """페이지 전체 텍스트 추출 (Cmd+A → Cmd+C → 클립보드)"""
        # 클립보드 백업
        saved = self.save_clipboard()

        # 클립보드 비우기 (빈 상태에서 시작해야 복사 성공 여부 확인 가능)
        self._set_clipboard("")

        # Chrome 포커스 → 잠시 대기 → 전체 선택 → 복사
        self._run_applescript('''
            tell application "Google Chrome" to activate
            delay 0.5
            tell application "System Events"
                keystroke "a" using command down
                delay 0.4
                keystroke "c" using command down
                delay 0.5
            end tell
        ''')

        # 클립보드 읽기
        content = self.save_clipboard()
        print(f"[WorkAssistant] Extracted {len(content)} chars from Chrome")

        # 선택 해제 (오른쪽 화살표 → 문서 끝으로 커서 이동)
        self._run_applescript('''
            delay 0.2
            tell application "System Events"
                key code 124
            end tell
        ''')

        # 원래 클립보드 복원
        if saved and saved != content:
            self.restore_clipboard(saved)

        return content or ""

    def paste_text(self, text):
        """클립보드에 텍스트 설정 후 Cmd+V"""
        self._set_clipboard(text)
        time.sleep(0.1)
        self._run_applescript('''
            tell application "System Events"
                keystroke "v" using command down
                delay 0.3
            end tell
        ''')

    def type_text(self, text):
        """AppleScript keystroke로 텍스트 입력 (짧은 텍스트용)"""
        escaped = text.replace('\\', '\\\\').replace('"', '\\"')
        self._run_applescript(f'''
            tell application "System Events"
                keystroke "{escaped}"
            end tell
        ''')

    def press_tab(self):
        self._run_applescript('tell application "System Events" to keystroke tab')

    def press_enter(self):
        self._run_applescript('tell application "System Events" to keystroke return')

    def save_clipboard(self):
        """현재 클립보드 텍스트 반환"""
        result = subprocess.run(
            ["osascript", "-e", "the clipboard as text"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def restore_clipboard(self, text):
        """클립보드 복원"""
        self._set_clipboard(text)

    def _set_clipboard(self, text):
        """클립보드에 텍스트 설정"""
        # pbcopy가 가장 안정적 (특수문자/개행 처리)
        proc = subprocess.Popen(
            ["pbcopy"], stdin=subprocess.PIPE,
        )
        proc.communicate(text.encode("utf-8"))

    def _run_applescript(self, script):
        """AppleScript 실행 후 stdout 반환"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception as e:
            print(f"[WorkAssistant] AppleScript error: {e}")
            return None


# ─── 분석 프롬프트 ───

_ANALYSIS_SYSTEM = """\
You are an expert academic assistant. Analyze web page content and provide \
structured analysis for automated assistance. You MUST return ONLY valid JSON. \
No markdown fences, no explanation outside the JSON."""

_ANALYSIS_USER = """\
Analyze this Chrome page content:

=== PAGE INFO ===
Title: {title}
URL: {url}

=== CONTENT ===
{content}

=== INSTRUCTIONS ===
Return a JSON object with this exact structure:
{{
  "page_type": "<math|essay|form|quiz|reading|coding|unknown>",
  "subject": "<detected subject>",
  "difficulty_level": "<estimated grade/level>",
  "language": "<primary language>",
  "summary": "<what this page is, max 200 chars, in English, start with 'This page...'>",
  "tasks": [
    {{
      "id": 1,
      "type": "<question|fill_blank|essay_prompt|calculation|multiple_choice|short_answer>",
      "question_text": "<the question>",
      "existing_answer": "<any answer already written, or null>",
      "answer": "<correct answer>",
      "work_shown": "<step-by-step work for math, outline for essays, null if N/A>"
    }}
  ],
  "writing_analysis": {{
    "detected_style": "<formal|informal|academic>",
    "vocabulary_level": "<grade level>",
    "tone": "<descriptive|argumentative|narrative|expository>"
  }},
  "fill_strategy": "<paste_all|sequential_fields|tab_navigate>"
}}

RULES:
1. For math: Show ALL work steps. Match the student's level.
2. For essays: Match detected writing style and vocabulary level. Write at student level.
3. For already-answered questions: Check correctness. If wrong, provide corrected answer.
4. Solve EVERYTHING. Leave no task unanswered.
5. The summary MUST be under 200 characters."""


# ─── 메인 클래스 ───

class WorkAssistant:
    """Work Assistant — 글로벌 키 감지 → Chrome 분석 → 자동 채우기"""

    def __init__(self, tts):
        self.tts = tts
        self.chrome = _ChromeHelper()
        self._anthropic = Anthropic(api_key=config.ANTHROPIC_API_KEY)

        # 키 감지 상태
        self._key_buffer = []
        self._buffer_lock = threading.Lock()
        self._last_key_time = 0
        self._listener = None

        # 작업 상태
        self._active = False
        self._analysis = None
        self._summary = ""
        self._page_type = ""
        self._last_trigger_time = 0

    def start(self):
        """글로벌 키보드 리스너 시작"""
        if not config.WORK_ASSISTANT_ENABLED:
            print("[WorkAssistant] Disabled in config")
            return

        if not PYNPUT_AVAILABLE:
            print("[WorkAssistant] pynput not installed — pip install pynput")
            return

        try:
            self._listener = keyboard.Listener(on_press=self._on_key_press)
            self._listener.daemon = True
            self._listener.start()
            print("[WorkAssistant] Keyboard listener started (type 'hhheeelllppp' to activate)")
        except Exception as e:
            print(f"[WorkAssistant] Failed to start listener: {e}")
            print("[WorkAssistant] macOS: System Settings → Privacy → Accessibility → Python 허용 필요")

    def stop(self):
        """리스너 정지"""
        if self._listener:
            self._listener.stop()
            self._listener = None

    # ─── 키 감지 ───

    def _on_key_press(self, key):
        """pynput 콜백 — 키 버퍼에 추가"""
        try:
            char = key.char
            if char is None:
                return
        except AttributeError:
            return

        char = char.lower()
        now = time.time()

        with self._buffer_lock:
            # h, e, l, p 외 다른 키 → 버퍼 리셋
            if char not in _VALID_CHARS:
                self._key_buffer.clear()
                return

            # 타임아웃: 5초 이상 지나면 리셋
            if self._key_buffer and (now - self._last_key_time) > config.WORK_ASSISTANT_BUFFER_TIMEOUT_SEC:
                self._key_buffer.clear()

            self._key_buffer.append(char)
            self._last_key_time = now

            # 버퍼 크기 제한
            if len(self._key_buffer) > len(_TRIGGER) * 2:
                self._key_buffer = self._key_buffer[-len(_TRIGGER):]

            # 트리거 체크
            if len(self._key_buffer) >= len(_TRIGGER):
                tail = "".join(self._key_buffer[-len(_TRIGGER):])
                if tail == _TRIGGER:
                    self._key_buffer.clear()

                    # 쿨다운 체크
                    if now - self._last_trigger_time < config.WORK_ASSISTANT_COOLDOWN_SEC:
                        return

                    # 이미 활성화 중이면 무시
                    if self._active:
                        return

                    self._last_trigger_time = now
                    # 백그라운드 스레드에서 활성화
                    threading.Thread(target=self._activate, daemon=True).start()

    # ─── 활성화 플로우 ───

    def _activate(self):
        """전체 Work Assistant 플로우 (백그라운드 스레드)"""
        self._active = True
        print("[WorkAssistant] Activated!")

        try:
            # 0. 입력된 hhheeelllppp 문자 삭제 (12자 백스페이스)
            time.sleep(0.3)  # 키 입력 완료 대기
            self.chrome._run_applescript('''
                tell application "System Events"
                    repeat 12 times
                        key code 51
                        delay 0.03
                    end repeat
                end tell
            ''')
            time.sleep(0.3)

            # 1. Chrome 내용 추출
            print("[WorkAssistant] Extracting Chrome content...")
            page_data = self._extract_chrome_content()
            if not page_data.get("content"):
                print("[WorkAssistant] No content extracted from Chrome")
                self._notify("Chrome에서 텍스트를 읽을 수 없습니다.")
                return

            # 2. Claude 분석
            print("[WorkAssistant] Analyzing content with Claude...")
            analysis = self._analyze_content(page_data)
            if not analysis:
                print("[WorkAssistant] Analysis failed")
                self._notify("분석에 실패했습니다.")
                return

            self._analysis = analysis
            self._summary = analysis.get("summary", "Analysis complete.")[:200]
            self._page_type = analysis.get("page_type", "unknown")
            print(f"[WorkAssistant] Type: {self._page_type}, Summary: {self._summary}")

            # 3. 알림 플로우 (2단계)
            proceed = self._show_notifications()
            if not proceed:
                print("[WorkAssistant] User dismissed")
                return

            # 4. 자동 채우기 실행
            print(f"[WorkAssistant] Starting auto-fill ({self._page_type})...")
            # Chrome 다시 포커스
            self.chrome._run_applescript('''
                tell application "Google Chrome" to activate
                delay 0.5
            ''')
            self._execute_work(page_data["content"])
            print("[WorkAssistant] Work complete!")
            self._notify("작업이 완료되었습니다!")

        except Exception as e:
            print(f"[WorkAssistant] Error: {e}")
            self._notify(f"오류: {str(e)[:50]}")
        finally:
            self._active = False

    def _extract_chrome_content(self):
        """Chrome 활성 탭 정보 + 내용 추출"""
        tab_info = self.chrome.get_tab_info()
        print(f"[WorkAssistant] Tab: {tab_info.get('title', '?')[:50]}")
        content = self.chrome.get_page_content()

        # 최대 길이 제한
        if len(content) > config.WORK_ASSISTANT_MAX_CONTENT_CHARS:
            content = content[:config.WORK_ASSISTANT_MAX_CONTENT_CHARS]

        return {
            "title": tab_info.get("title", ""),
            "url": tab_info.get("url", ""),
            "content": content,
        }

    def _analyze_content(self, page_data):
        """Claude Sonnet으로 페이지 딥 분석"""
        prompt = _ANALYSIS_USER.format(
            title=page_data["title"],
            url=page_data["url"],
            content=page_data["content"][:30000],  # API 토큰 제한
        )

        try:
            response = self._anthropic.messages.create(
                model=config.CLAUDE_MODEL_HEAVY,
                max_tokens=8192,
                system=_ANALYSIS_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()

            # JSON 파싱 (extract_json 유틸 사용)
            from O1.self_dev.utils import extract_json
            result = extract_json(raw, expect_type="object")
            if result:
                return result

            # 폴백: 직접 파싱
            return json.loads(raw)

        except Exception as e:
            print(f"[WorkAssistant] Analysis error: {e}")
            return None

    def _show_notifications(self):
        """2단계 macOS 다이얼로그. True면 작업 진행."""
        timeout = config.WORK_ASSISTANT_DIALOG_TIMEOUT_SEC

        # 1단계: 분석 완료 알림
        result1 = self._show_dialog(
            "페이지 분석이 완료되었습니다.",
            title="Orion Work Assistant",
            timeout=timeout,
        )
        if result1 != "확인":
            return False

        # 2단계: 요약 + 작업 제안
        summary_text = self._summary
        if len(self._summary) > 150:
            summary_text = self._summary[:147] + "..."

        result2 = self._show_dialog(
            f"{summary_text}\n\nWould you like me to work with you?",
            title="Orion Work Assistant",
            timeout=timeout,
        )
        return result2 == "확인"

    def _show_dialog(self, message, title="Orion", timeout=30):
        """macOS display dialog → 버튼 반환 ('확인' 또는 '무시')"""
        escaped_msg = message.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        script = (
            f'tell application "System Events" to display dialog '
            f'"{escaped_msg}" '
            f'buttons {{"무시", "확인"}} default button "확인" '
            f'with title "{title}" giving up after {timeout}'
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=timeout + 5,
            )
            if "확인" in result.stdout:
                return "확인"
        except Exception:
            pass
        return "무시"

    def _notify(self, msg):
        """간단한 macOS 알림"""
        safe = msg.replace('"', "'")
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe}" with title "Orion Work Assistant"'],
            capture_output=True,
        )

    def _execute_work(self, page_content):
        """타입별 자동 채우기 실행"""
        from O1.core.work_filler import ContentFiller
        filler = ContentFiller(self.chrome, self._anthropic)
        filler.execute(self._page_type, self._analysis, page_content)
