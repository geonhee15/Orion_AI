import os
import datetime
import unicodedata
from anthropic import Anthropic, RateLimitError, APIConnectionError, BadRequestError
from tavily import TavilyClient
from Glass import config
from Glass.core.wake_word import QueryClassifier


class OrionBrain:
    """Orion AI 대화 엔진 - Claude + Tavily 검색"""

    def __init__(self):
        self.anthropic = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.tavily = TavilyClient(api_key=config.TAVILY_API_KEY)
        self.short_term_memory = []
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self):
        extra_info = ""
        if os.path.exists(config.PROFILE_FILE):
            with open(config.PROFILE_FILE, "r", encoding="utf-8") as f:
                extra_info = f.read()

        return (
            f"You are '{config.AI_NAME}', Geonhee's personal AI assistant.\n"
            f"[About Geonhee]\n{extra_info}\n"
            "Core rules:\n"
            "1. ALWAYS respond in English only. Never respond in Korean or any other language.\n"
            "2. The user speaks both Korean and English. You MUST understand Korean perfectly and respond in English.\n"
            "   - Example: User says '오늘 날씨 어때?' → You respond in English about today's weather.\n"
            "   - Example: User says '내일 일정 알려줘' → You respond in English about tomorrow's schedule.\n"
            "3. Like JARVIS from Iron Man - calm, intelligent, polished.\n"
            "4. Keep answers to ONE short sentence. Be concise.\n"
            "5. Remember previous conversation context.\n"
            "6. Call Geonhee 'sir', never by name.\n"
            "7. Refer to Geonhee as 'you' in second person."
        )

    def get_response(self, user_text, calendar_handler=None):
        """AI 응답 생성. calendar_handler가 있으면 캘린더 질문 처리."""
        try:
            # 캘린더 질문 체크 (통합 로직 사용)
            if calendar_handler and QueryClassifier.is_calendar_query(user_text):
                return calendar_handler(user_text)

            user_text = unicodedata.normalize("NFC", user_text)
            now = datetime.datetime.now()
            time_info = f"[현재: {now.strftime('%Y-%m-%d %H:%M')}]"

            # 검색 필요 여부 판단
            context = self._search_if_needed(user_text)

            # 대화 생성
            messages = list(self.short_term_memory)
            messages.append({"role": "user", "content": f"{time_info} {user_text} {context}"})

            response = self.anthropic.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=150,
                system=self.system_prompt,
                messages=messages,
            )
            answer = response.content[0].text.strip()

            # 메모리 업데이트
            self.short_term_memory.append({"role": "user", "content": user_text})
            self.short_term_memory.append({"role": "assistant", "content": answer})
            if len(self.short_term_memory) > 10:
                self.short_term_memory = self.short_term_memory[-10:]

            return answer
        except RateLimitError as e:
            print(f"[Brain] Rate limit: {e}")
            return "Sir, I'm receiving too many requests. Please wait a moment."
        except APIConnectionError as e:
            print(f"[Brain] API connection error: {e}")
            return "Sir, I'm having trouble connecting to my neural network."
        except BadRequestError as e:
            print(f"[Brain] Bad request: {e}")
            return "Sir, there was an error processing your request."
        except Exception as e:
            print(f"[Brain] Unexpected error: {e}")
            return f"Apologies sir, an unexpected error occurred."


    def _search_if_needed(self, user_text):
        """검색 키워드가 있으면 Tavily로 검색"""
        search_keywords = ["날씨", "뉴스", "현재", "지금", "weather", "news"]
        if not any(kw in user_text.lower() for kw in search_keywords):
            return ""

        try:
            search_res = self.anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=30,
                messages=[{"role": "user", "content": f"Generate one short English search query for: '{user_text}'. Output query only:"}],
            )
            query = search_res.content[0].text.strip()
            res = self.tavily.search(query=query, search_depth="basic", max_results=2)
            return "\n[검색결과]: " + " ".join(
                [r["content"][:200] for r in res["results"]]
            )
        except Exception:
            return ""

    def handle_calendar_query(self, text, calendar):
        """캘린더 질문을 AI가 분석해서 답변"""
        text_lower = text.lower()

        if any(w in text_lower for w in ["tomorrow", "내일"]):
            raw_events = calendar.get_raw_events(days=1)
            period = "tomorrow"
        elif any(w in text_lower for w in ["week", "이번주", "주"]):
            raw_events = calendar.get_raw_events(days=7)
            period = "this week"
        else:
            raw_events = calendar.get_raw_events(days=0)
            period = "today"

        if not raw_events or raw_events.strip() == "":
            return f"Sir, you have no events {period}."

        try:
            response = self.anthropic.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=150,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"다음은 캘린더 일정 데이터입니다:\n\n{raw_events}\n\n"
                            f"질문: {text}\n\n"
                            "Answer the question in ONE short English sentence based on the calendar data above. "
                            'Use AM/PM format for times. Always start with "Sir,".'
                        ),
                    }
                ],
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"AI 캘린더 분석 에러: {e}")
            return f"Sir, there was an error checking your {period} schedule."
