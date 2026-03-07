from Glass import config


class QueryClassifier:
    """쿼리 분류 유틸리티 (정적 메서드)"""

    @staticmethod
    def is_wake_word(text: str) -> bool:
        """Wake word 감지"""
        text_lower = text.lower()
        return any(wake in text_lower for wake in config.WAKE_WORDS)

    @staticmethod
    def extract_command(text: str) -> str | None:
        """Wake word 뒤의 명령어 추출. 없으면 None 반환."""
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
        """캘린더 관련 질문인지 확인 (통합 로직)"""
        text_lower = text.lower()

        # 비캘린더 키워드 제외
        exclude = ["weather", "날씨", "news", "뉴스", "temperature", "기온"]
        if any(kw in text_lower for kw in exclude):
            return False

        # 캘린더 전용 키워드 체크
        has_specific = any(kw in text_lower for kw in config.CALENDAR_KEYWORDS)

        # 시간 키워드 체크
        time_keywords = ["오늘", "내일", "이번주", "today", "tomorrow", "this week", "next week"]
        has_time = any(kw in text_lower for kw in time_keywords)

        return has_specific or (has_time and not any(kw in text_lower for kw in exclude))

    @staticmethod
    def is_delivery_query(text: str) -> bool:
        """배달 관련 질문인지 확인"""
        text_lower = text.lower()
        return any(kw in text_lower for kw in config.DELIVERY_KEYWORDS)


# 하위 호환성을 위한 별칭
WakeWordDetector = QueryClassifier
