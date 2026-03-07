from Workspace import config


class QueryClassifier:
    """쿼리 분류 유틸리티 (정적 메서드)"""

    @staticmethod
    def is_wake_word(text: str) -> bool:
        text_lower = text.lower()
        return any(wake in text_lower for wake in config.WAKE_WORDS)

    @staticmethod
    def extract_command(text: str) -> str | None:
        text_lower = text.lower()
        for wake in config.WAKE_WORDS:
            if wake in text_lower:
                idx = text_lower.find(wake) + len(wake)
                cmd = text[idx:].strip().lstrip(",").lstrip()
                if len(cmd) > 2:
                    return cmd
        return None

    @staticmethod
    def is_calendar_query(text: str) -> bool:
        text_lower = text.lower()

        exclude = ["weather", "날씨", "news", "뉴스", "temperature", "기온"]
        if any(kw in text_lower for kw in exclude):
            return False

        has_specific = any(kw in text_lower for kw in config.CALENDAR_KEYWORDS)

        time_keywords = ["오늘", "내일", "이번주", "today", "tomorrow", "this week", "next week"]
        has_time = any(kw in text_lower for kw in time_keywords)

        return has_specific or (has_time and not any(kw in text_lower for kw in exclude))


WakeWordDetector = QueryClassifier
