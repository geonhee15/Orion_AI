import subprocess
import os
import datetime
import unicodedata
from anthropic import Anthropic
from tavily import TavilyClient
from pynput import keyboard
from dotenv import load_dotenv
from jamo import jamo_to_hcj

# 1. 환경 설정 및 API 로드
load_dotenv()
# .env 파일에 ANTHROPIC_API_KEY와 TAVILY_API_KEY가 있어야 해!
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

START_TRIGGER = "123enter"
EXIT_TRIGGER = "123exit"
AI_NAME = "Orion"
PROFILE_FILE = "user_profile.txt"

class OrionBot:
    def __init__(self):
        self.is_active = False
        self.full_input = ""
        self.short_term_memory = []
        self.load_personal_profile()

    def load_personal_profile(self):
        """건희의 정보를 로드하여 시스템 지침 설정"""
        extra_info = ""
        if os.path.exists(PROFILE_FILE):
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                extra_info = f.read()
        
        self.system_prompt = (
            f"당신은 건희의 베프이자 전용 AI 비서 '{AI_NAME}'이야! ㅋㅋ\n"
            f"[건희 정보]\n{extra_info}\n"
            "핵심 지침:\n"
            "1. 무조건 '반말'로 친구처럼 밝게 말해줘!\n"
            "2. 답변은 알림창용이니까 무조건 '한 문장'으로 아주 짧고 핵심만 말해.\n"
            "3. 검색 결과가 있으면 구체적인 준비물 리스트나 숫자를 반드시 포함해.\n"
            "4. '알아볼게'라고 미루지 말고 검색된 내용을 즉시 요약해서 알려줘.\n"
            "5. 이전 대화 맥락을 기억해서 자연스럽게 이어가줘."
        )

    def fix_hangul(self, text):
        """맥북 자소 분리(ㅅㅣㄱㅏㄱ) 현상 교정"""
        try:
            combined = jamo_to_hcj(text)
            return unicodedata.normalize('NFC', combined)
        except:
            return unicodedata.normalize('NFC', text)

    def search_web(self, query):
        """Tavily AI 전문 검색 엔진 가동"""
        try:
            print(f"🌐 Tavily 전문 검색 엔진 가동 중: {query}")
            response = tavily.search(query=query, search_depth="advanced", max_results=3)
            return "\n".join([r['content'] for r in response['results']])
        except Exception as e:
            return f"검색 엔진 에러 났어 ㅠㅠ: {e}"

    def get_ai_response(self, user_text):
        try:
            user_text = self.fix_hangul(user_text)
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

            # [단계 1: Claude의 의도 분석 및 검색어 생성]
            # 모델 명칭을 latest로 수정해서 404 에러 방지!
            thought_res = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=150,
                messages=[{"role": "user", "content": f"사용자 질문: '{user_text}'\n검색이 필요하면 'SEARCH: [영어 검색어]'라고만 답하고, 아니면 'NO'라고 답해."}]
            )
            thought = thought_res.content[0].text.strip()
            
            context = ""
            if "SEARCH:" in thought.upper():
                search_query = thought.split(":", 1)[1].strip()
                context = f"\n\n[실시간 정보]: {self.search_web(search_query)}"

            # [단계 2: 최종 답변 생성]
            messages = [{"role": m["role"], "content": m["content"]} for m in self.short_term_memory]
            messages.append({"role": "user", "content": f"현재시각: {now_str}. {context}\n질문: {user_text}"})

            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=300,
                system=self.system_prompt,
                messages=messages
            )
            answer = response.content[0].text.strip()

            # 기억 업데이트
            self.short_term_memory.append({"role": "user", "content": user_text})
            self.short_term_memory.append({"role": "assistant", "content": answer})
            if len(self.short_term_memory) > 10: self.short_term_memory = self.short_term_memory[-10:]
            
            return answer
        except Exception as e:
            return f"오리온 두뇌 렉 걸림 ㅠㅠ: {str(e)}"

    def on_press(self, key):
        try:
            if hasattr(key, 'char') and key.char is not None:
                self.full_input += key.char
            elif key == keyboard.Key.enter:
                self.full_input += "enter"
            elif key == keyboard.Key.backspace:
                self.full_input = self.full_input[:-1]

            if not self.is_active:
                if self.full_input.endswith(START_TRIGGER):
                    self.is_active = True
                    self.full_input = ""
                    subprocess.run(["osascript", "-e", f'display notification "오리온 가동! 건희야 왔어? ㅋㅋ" with title "{AI_NAME}"'])
            
            elif self.full_input.endswith(EXIT_TRIGGER):
                self.is_active = False
                self.full_input = ""
                subprocess.run(["osascript", "-e", f'display notification "나 퇴근할게! 나중에 봐 ㅎㅎ" with title "{AI_NAME}"'])

            elif self.is_active and key == keyboard.Key.enter:
                query = self.fix_hangul(self.full_input.replace("enter", "").strip())
                if query:
                    print(f"💬 건희 질문: {query}")
                    subprocess.run(["osascript", "-e", f'display notification "생각 중... 잠시만! ㅋㅋ" with title "{AI_NAME}"'])
                    answer = self.get_ai_response(query)
                    safe_answer = answer.replace("\"", "'")
                    subprocess.run(["osascript", "-e", f'display notification "{safe_answer}" with title "{AI_NAME}"'])
                self.full_input = ""
        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    orion = OrionBot()
    print(f"--- [{AI_NAME}] 클로드+타빌리 엔진 가동 중 ---")
    with keyboard.Listener(on_press=orion.on_press) as listener:
        listener.join()