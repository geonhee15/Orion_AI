"""일정 자동 요약 & 리마인더 시스템

Background scheduler that provides:
1. Morning daily briefing at configurable time (default 08:00)
2. Per-event reminders for events within next N minutes (default 15)
"""

import time
import threading
from datetime import datetime

from O1 import config

# --- 스케줄러 설정 ---
SCHEDULE_BRIEFING_HOUR = 8          # 모닝 브리핑 시각 (24h)
SCHEDULE_BRIEFING_MINUTE = 0
SCHEDULE_REMINDER_CHECK_SEC = 300   # 리마인더 체크 간격 (5분)
SCHEDULE_REMINDER_AHEAD_MIN = 15    # 몇 분 전에 리마인드할지


class ScheduleReminder:
    """일정 자동 요약 및 리마인더 백그라운드 서비스"""

    def __init__(self, calendar, tts, brain):
        self.calendar = calendar
        self.tts = tts
        self.brain = brain

        # 이미 리마인드한 이벤트 추적 (title+start_time 조합)
        self._reminded_events = set()

        # 오늘 브리핑 완료 여부
        self._briefing_done_date = None

        # 타이머 제어
        self._stop_event = threading.Event()
        self._timer = None

    def start(self):
        """리마인더 루프 시작 (데몬 스레드)"""
        self._stop_event.clear()
        self._schedule_next_tick()
        print("\u2705 Schedule Reminder: started")

    def stop(self):
        """리마인더 루프 중단"""
        self._stop_event.set()
        if self._timer:
            self._timer.cancel()
            self._timer = None
        print("[ScheduleReminder] stopped")

    def get_schedule_summary(self):
        """오늘 일정 요약을 Claude로 생성하여 반환 (on-demand용)"""
        raw = self.calendar.get_raw_events(days=0)
        if not raw or raw.strip() == "":
            return "Sir, you have no events scheduled for today."

        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Here is today's calendar data:\n\n{raw}\n\n"
                        "Summarize today's schedule in 2-3 short English sentences. "
                        "Use AM/PM format for times. Start with 'Sir,'. "
                        "Be concise like JARVIS."
                    ),
                }],
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"[ScheduleReminder] Summary generation error: {e}")
            return "Sir, I had trouble summarizing your schedule."

    def _schedule_next_tick(self):
        """다음 틱 스케줄 (threading.Timer 사용)"""
        if self._stop_event.is_set():
            return
        self._timer = threading.Timer(SCHEDULE_REMINDER_CHECK_SEC, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self):
        """주기적 체크: 브리핑 + 리마인더"""
        if self._stop_event.is_set():
            return

        try:
            self._check_morning_briefing()
            self._check_upcoming_reminders()
        except Exception as e:
            print(f"[ScheduleReminder] Tick error: {e}")

        # 자정 지나면 리마인드 기록 초기화
        today = datetime.now().date()
        self._reminded_events = {
            key for key in self._reminded_events
            if key[1] and key[1].date() >= today
        }

        # 다음 틱 예약
        self._schedule_next_tick()

    def _check_morning_briefing(self):
        """설정된 시간에 모닝 브리핑 실행"""
        now = datetime.now()
        today = now.date()

        # 이미 오늘 브리핑 했으면 스킵
        if self._briefing_done_date == today:
            return

        # 브리핑 시간 체크 (설정 시간 ~ +체크간격 범위)
        briefing_hour = SCHEDULE_BRIEFING_HOUR
        briefing_minute = SCHEDULE_BRIEFING_MINUTE

        if now.hour == briefing_hour and briefing_minute <= now.minute < briefing_minute + (SCHEDULE_REMINDER_CHECK_SEC // 60 + 1):
            print("[ScheduleReminder] Morning briefing triggered")
            summary = self.get_schedule_summary()
            self.tts.speak(summary)
            self._briefing_done_date = today

    def _check_upcoming_reminders(self):
        """다가오는 이벤트 리마인더 체크"""
        if not self.calendar.available:
            return

        events = self.calendar.get_events_as_list(days=0)
        if not events:
            return

        now = datetime.now()

        for event in events:
            start_time = event.get("start_time")
            title = event.get("title", "")

            if not start_time or not title:
                continue

            # 리마인더 키 (중복 방지)
            reminder_key = (title, start_time)
            if reminder_key in self._reminded_events:
                continue

            # 이벤트까지 남은 시간 (분)
            delta = (start_time - now).total_seconds() / 60.0

            # 0 ~ REMINDER_AHEAD_MIN 분 이내면 리마인드
            if 0 < delta <= SCHEDULE_REMINDER_AHEAD_MIN:
                minutes_left = int(round(delta))
                if minutes_left <= 1:
                    msg = f"Sir, you have {title} starting now."
                else:
                    msg = f"Sir, you have {title} in {minutes_left} minutes."

                location = event.get("location", "")
                if location:
                    msg += f" Location: {location}."

                print(f"[ScheduleReminder] Reminder: {msg}")
                self.tts.speak(msg)
                self._reminded_events.add(reminder_key)
