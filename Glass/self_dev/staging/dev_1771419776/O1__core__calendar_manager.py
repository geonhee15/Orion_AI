import os
import re
import subprocess
from datetime import datetime, timedelta


class MacCalendar:
    """macOS Calendar 연동 (icalBuddy 사용)"""

    def __init__(self):
        self.icalbuddy_path = None
        self.available = self._check_icalbuddy()

    def _check_icalbuddy(self):
        paths = [
            "/usr/local/bin/icalBuddy",
            "/opt/homebrew/bin/icalBuddy",
            "/usr/bin/icalBuddy",
        ]

        for path in paths:
            if os.path.exists(path):
                self.icalbuddy_path = path
                print(f"\u2705 macOS Calendar 연결됨 ({path})")
                return True

        try:
            result = subprocess.run(["which", "icalBuddy"], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                self.icalbuddy_path = result.stdout.strip()
                print(f"\u2705 macOS Calendar 연결됨 ({self.icalbuddy_path})")
                return True
        except Exception:
            pass

        print("\u26a0\ufe0f icalBuddy 없음. 'brew install ical-buddy' 실행하세요.")
        return False

    def get_today_events(self):
        return self._get_events("eventsToday", "오늘")

    def get_tomorrow_events(self):
        return self._get_events("eventsToday+1", "내일")

    def get_week_events(self):
        return self._get_events("eventsToday+7", "이번 주")

    def get_raw_events(self, days=1):
        """원본 일정 데이터 (AI 분석용)"""
        if not self.available or not self.icalbuddy_path:
            return ""
        try:
            cmd_arg = "eventsToday" if days == 0 else f"eventsToday+{days}"
            result = subprocess.run(
                [self.icalbuddy_path, cmd_arg],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                print(f"[Calendar] icalBuddy failed: {result.stderr}")
                return ""

            return result.stdout
        except subprocess.TimeoutExpired:
            print("[Calendar] icalBuddy timeout")
            return ""
        except FileNotFoundError:
            print("[Calendar] icalBuddy not found")
            self.available = False
            return ""
        except Exception as e:
            print(f"[Calendar] Unexpected error: {e}")
            return ""

    def get_events_as_list(self, days=0):
        """Return structured event list for programmatic use.

        Returns:
            list of dicts with keys: title, start_time (datetime), end_time (datetime), location
        """
        raw = self.get_raw_events(days=days)
        if not raw or raw.strip() == "":
            return []

        parsed = self._parse_events_list(raw)
        today = datetime.now().date()
        result = []

        for event in parsed:
            title = event.get("name", "")
            location = event.get("location", "")
            time_str = event.get("time", "")
            start_dt, end_dt = self._parse_time_string(time_str, today)
            result.append({
                "title": title,
                "start_time": start_dt,
                "end_time": end_dt,
                "location": location,
            })

        return result

    def _parse_time_string(self, time_str, base_date):
        """icalBuddy 시간 문자열을 datetime 쌍으로 파싱

        다양한 형식 처리:
        - '오전 9:00 - 오전 10:00'
        - 'at 오전 9:00 - 오전 10:00'
        - 'tomorrow at 오후 2:00 - 오후 3:00'
        - '9:00 AM - 10:00 AM'
        """
        start_dt = None
        end_dt = None

        if not time_str:
            return start_dt, end_dt

        # tomorrow이면 base_date + 1
        if "tomorrow" in time_str.lower():
            base_date = base_date + timedelta(days=1)

        # 'at ' 제거
        cleaned = re.sub(r'^.*?at\s+', '', time_str, flags=re.IGNORECASE).strip()
        if not cleaned:
            cleaned = time_str

        # 시간 범위 분리 (하이픈 기준)
        parts = re.split(r'\s*-\s*', cleaned, maxsplit=1)

        start_dt = self._parse_single_time(parts[0].strip(), base_date)
        if len(parts) > 1:
            end_dt = self._parse_single_time(parts[1].strip(), base_date)

        return start_dt, end_dt

    def _parse_single_time(self, text, base_date):
        """단일 시간 텍스트를 datetime으로 변환"""
        if not text:
            return None

        # 한국어 형식: '오전 9:00' 또는 '오후 2:30'
        kr_match = re.search(r'(오전|오후)\s*(\d{1,2}):(\d{2})', text)
        if kr_match:
            period = kr_match.group(1)
            hour = int(kr_match.group(2))
            minute = int(kr_match.group(3))
            if period == "오후" and hour < 12:
                hour += 12
            elif period == "오전" and hour == 12:
                hour = 0
            try:
                return datetime.combine(base_date, datetime.min.time().replace(hour=hour, minute=minute))
            except ValueError:
                return None

        # 영어 형식: '9:00 AM' 또는 '2:30 PM'
        en_match = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)', text)
        if en_match:
            hour = int(en_match.group(1))
            minute = int(en_match.group(2))
            period = en_match.group(3).upper()
            if period == "PM" and hour < 12:
                hour += 12
            elif period == "AM" and hour == 12:
                hour = 0
            try:
                return datetime.combine(base_date, datetime.min.time().replace(hour=hour, minute=minute))
            except ValueError:
                return None

        # 24시간 형식: '14:30'
        plain_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if plain_match:
            hour = int(plain_match.group(1))
            minute = int(plain_match.group(2))
            try:
                return datetime.combine(base_date, datetime.min.time().replace(hour=hour, minute=minute))
            except ValueError:
                return None

        return None

    def get_next_event(self):
        """다음 일정 정보 (HUD 위젯용). dict 반환."""
        raw = self.get_raw_events(days=0)
        if not raw or raw.strip() == "":
            return None

        events = self._parse_events_list(raw)
        return events[0] if events else None

    def _get_events(self, cmd_arg, period):
        if not self.available or not self.icalbuddy_path:
            return None
        try:
            result = subprocess.run(
                [self.icalbuddy_path, cmd_arg], capture_output=True, text=True
            )
            return self._format_events(result.stdout, period)
        except Exception as e:
            print(f"캘린더 에러: {e}")
            return None

    def _parse_events_list(self, output):
        """icalBuddy 출력을 이벤트 리스트로 파싱"""
        if not output or output.strip() == "":
            return []

        lines = output.strip().split("\n")
        events = []
        current_event = None

        for line in lines:
            if line.strip().startswith("\u2022"):
                if current_event:
                    events.append(current_event)
                event_name = line.strip()[2:].split("(")[0].strip()
                current_event = {"name": event_name, "time": "", "location": ""}
            elif current_event:
                line = line.strip()
                if "at 오전" in line or "at 오후" in line or "tomorrow at" in line:
                    current_event["time"] = line
                elif "오전" in line or "오후" in line or re.search(r'\d{1,2}:\d{2}', line):
                    # 시간 정보가 'at' 없이 올 수도 있음
                    if not current_event["time"]:
                        current_event["time"] = line
                elif line.startswith("location:"):
                    current_event["location"] = line.replace("location:", "").strip()

        if current_event:
            events.append(current_event)
        return events

    def _format_events(self, output, period):
        events = self._parse_events_list(output)
        if not events:
            return f"Sir, {period}은 일정이 없습니다."

        formatted = []
        for e in events[:6]:
            time_str = e.get("time", "")
            if "오전" in time_str or "오후" in time_str:
                parts = time_str.split("at")
                if len(parts) > 1:
                    time_part = parts[-1].strip().split("-")[0].strip()
                    formatted.append(f"{time_part}에 {e['name']}")
                else:
                    formatted.append(e["name"])
            else:
                formatted.append(e["name"])

        return f"Sir, {period} 일정입니다. " + ", ".join(formatted) + "."
