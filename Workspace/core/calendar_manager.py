import os
import subprocess


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
                print(f"✅ macOS Calendar 연결됨 ({path})")
                return True

        try:
            result = subprocess.run(["which", "icalBuddy"], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                self.icalbuddy_path = result.stdout.strip()
                print(f"✅ macOS Calendar 연결됨 ({self.icalbuddy_path})")
                return True
        except Exception:
            pass

        print("⚠️ icalBuddy 없음. 'brew install ical-buddy' 실행하세요.")
        return False

    def get_today_events(self):
        return self._get_events("eventsToday", "오늘")

    def get_tomorrow_events(self):
        return self._get_events("eventsToday+1", "내일")

    def get_week_events(self):
        return self._get_events("eventsToday+7", "이번 주")

    def get_raw_events(self, days=1):
        if not self.available or not self.icalbuddy_path:
            return ""
        try:
            cmd_arg = "eventsToday" if days == 0 else f"eventsToday+{days}"
            result = subprocess.run(
                [self.icalbuddy_path, cmd_arg],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return ""
            return result.stdout
        except subprocess.TimeoutExpired:
            return ""
        except FileNotFoundError:
            self.available = False
            return ""
        except Exception:
            return ""

    def get_next_event(self):
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
        if not output or output.strip() == "":
            return []

        lines = output.strip().split("\n")
        events = []
        current_event = None

        for line in lines:
            if line.strip().startswith("•"):
                if current_event:
                    events.append(current_event)
                event_name = line.strip()[2:].split("(")[0].strip()
                current_event = {"name": event_name, "time": "", "location": ""}
            elif current_event:
                line = line.strip()
                if "at 오전" in line or "at 오후" in line or "tomorrow at" in line:
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
