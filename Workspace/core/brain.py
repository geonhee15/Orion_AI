import os
import datetime
import unicodedata
from anthropic import Anthropic, RateLimitError, APIConnectionError, BadRequestError
from tavily import TavilyClient
from Workspace import config
from Workspace.core.wake_word import QueryClassifier

_SEARCH_HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "Search_History.txt",
)


class OrionBrain:
    """Orion AI 대화 엔진 - Claude + 3단계 지식 검색"""

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
            "4. Keep answers concise — 1-3 sentences max.\n"
            "5. Remember previous conversation context.\n"
            "6. Call Geonhee 'sir', never by name.\n"
            "7. Refer to Geonhee as 'you' in second person.\n"
            "8. When [Reference] info is provided, you MUST use it to answer. Never say you don't know if reference data is given."
        )

    def get_response(self, user_text, calendar_handler=None):
        """AI 응답 생성 — 3단계 지식 검색: 프로필 → 히스토리 → 웹 검색"""
        try:
            if calendar_handler and QueryClassifier.is_calendar_query(user_text):
                return calendar_handler(user_text)

            user_text = unicodedata.normalize("NFC", user_text)
            now = datetime.datetime.now()
            time_info = f"[현재: {now.strftime('%Y-%m-%d %H:%M')}]"

            # 3단계 지식 검색
            context, source = self._lookup_knowledge(user_text)

            messages = list(self.short_term_memory)
            if context:
                messages.append({"role": "user", "content": f"{time_info} {user_text}\n\n[Reference ({source})]: {context}"})
            else:
                messages.append({"role": "user", "content": f"{time_info} {user_text}"})

            response = self.anthropic.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=200,
                system=self.system_prompt,
                messages=messages,
            )
            answer = response.content[0].text.strip()

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
            return "Apologies sir, an unexpected error occurred."

    # ─── 3단계 지식 검색 ───

    def _lookup_knowledge(self, user_text):
        """
        3단계 지식 검색:
          1) 유저 프로필 (user_profile.txt)
          2) 검색 히스토리 (Search_History.txt)
          3) 실제 웹 검색 (Tavily) → 히스토리에 저장
        Returns: (context_str, source_label) or ("", "")
        """
        # 1단계: 유저 프로필 확인
        profile_match = self._search_profile(user_text)
        if profile_match:
            print(f"📋 1단계 히트: 유저 프로필")
            return profile_match, "User Profile"

        # 2단계: 검색 히스토리 확인
        history_match = self._search_history(user_text)
        if history_match:
            print(f"📚 2단계 히트: 검색 히스토리")
            return history_match, "Search History"

        # 3단계: 실제 웹 검색
        web_result = self._search_web(user_text)
        if web_result:
            print(f"🌐 3단계: 웹 검색 완료 → 히스토리 저장")
            self._save_to_history(user_text, web_result)
            return web_result, "Web Search"

        return "", ""

    def _search_profile(self, user_text):
        """1단계: 유저 프로필에서 관련 정보 찾기"""
        if not os.path.exists(config.PROFILE_FILE):
            return None
        try:
            with open(config.PROFILE_FILE, "r", encoding="utf-8") as f:
                profile = f.read().strip()
            if not profile:
                return None

            # Claude에게 프로필에서 관련 정보 있는지 판단시킴
            res = self.anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content": (
                    f"User profile:\n{profile}\n\n"
                    f"Question: '{user_text}'\n\n"
                    "Does the profile contain info to answer this question? "
                    "If YES, extract the relevant info. If NO, reply exactly: NO_MATCH"
                )}],
            )
            answer = res.content[0].text.strip()
            if "NO_MATCH" in answer:
                return None
            print(f"  📋 프로필 매치: {answer[:80]}...")
            return answer
        except Exception as e:
            print(f"  📋 프로필 검색 에러: {e}")
            return None

    def _search_history(self, user_text):
        """2단계: Search_History.txt에서 관련 정보 찾기"""
        if not os.path.exists(_SEARCH_HISTORY_FILE):
            return None
        try:
            with open(_SEARCH_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = f.read().strip()
            if not history:
                return None

            # Claude에게 히스토리에서 관련 정보 있는지 판단시킴
            res = self.anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                messages=[{"role": "user", "content": (
                    f"Search history:\n{history}\n\n"
                    f"Question: '{user_text}'\n\n"
                    "Does the history contain info to answer this question? "
                    "If YES, extract the relevant info. If NO, reply exactly: NO_MATCH"
                )}],
            )
            answer = res.content[0].text.strip()
            if "NO_MATCH" in answer:
                return None
            print(f"  📚 히스토리 매치: {answer[:80]}...")
            return answer
        except Exception as e:
            print(f"  📚 히스토리 검색 에러: {e}")
            return None

    def _search_web(self, user_text):
        """3단계: Tavily 웹 검색"""
        try:
            # 검색 쿼리 생성
            search_res = self.anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=30,
                messages=[{"role": "user", "content": (
                    f"Generate one short English search query for: '{user_text}'. "
                    "Output the query only, nothing else:"
                )}],
            )
            query = search_res.content[0].text.strip()
            print(f"  🌐 웹 검색: '{query}'")

            res = self.tavily.search(query=query, search_depth="basic", max_results=3)
            results = res.get("results", [])
            if not results:
                print(f"  🌐 검색 결과 없음")
                return None

            context = " ".join([r["content"][:300] for r in results])
            print(f"  🌐 검색 결과 {len(results)}건")
            return context
        except Exception as e:
            print(f"  🌐 웹 검색 에러: {e}")
            return None

    def _save_to_history(self, query, result):
        """검색 결과를 Search_History.txt에 추가"""
        try:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = f"\n[{now}] Q: {query}\nA: {result[:500]}\n{'─'*40}\n"

            with open(_SEARCH_HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(entry)
            print(f"  💾 히스토리 저장 완료")
        except Exception as e:
            print(f"  💾 히스토리 저장 에러: {e}")

    def update_profile(self, user_input):
        """유저 입력을 분석해서 user_profile.txt 업데이트 (기존 정보 수정 or 새 정보 추가)"""
        try:
            profile = ""
            if os.path.exists(config.PROFILE_FILE):
                with open(config.PROFILE_FILE, "r", encoding="utf-8") as f:
                    profile = f.read()

            now = datetime.datetime.now().strftime("%Y-%m-%d")

            res = self.anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=3000,
                messages=[{"role": "user", "content": (
                    f"Current user profile:\n```\n{profile}\n```\n\n"
                    f"New info from user: \"{user_input}\"\n"
                    f"Today: {now}\n\n"
                    "Instructions:\n"
                    "1. If the new info UPDATES existing info (e.g. subscriber count changed, new school year), "
                    "modify the relevant line in-place.\n"
                    "2. If it's NEW info not in the profile, add it to the appropriate section. "
                    "If no section fits, add under [이후 기록들].\n"
                    "3. Remove any duplicate entries that say the same thing.\n"
                    "4. Keep the exact same format and section headers.\n"
                    "5. Output the COMPLETE updated profile file. Nothing else — no explanation, no markdown fences."
                )}],
            )
            updated = res.content[0].text.strip()
            # AI가 마크다운 울타리를 추가하는 경우 제거
            for fence in ["```\n", "\n```", "```"]:
                updated = updated.replace(fence, "")
            updated = updated.strip()

            with open(config.PROFILE_FILE, "w", encoding="utf-8") as f:
                f.write(updated + "\n")

            # 시스템 프롬프트 갱신
            self.system_prompt = self._build_system_prompt()

            print(f"📝 프로필 업데이트 완료: {user_input[:50]}")
            return True
        except Exception as e:
            print(f"📝 프로필 업데이트 에러: {e}")
            return False

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
