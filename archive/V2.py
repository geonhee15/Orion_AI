import subprocess
import os
import datetime
import unicodedata
import base64
from anthropic import Anthropic
from tavily import TavilyClient
from pynput import keyboard
from dotenv import load_dotenv
from jamo import jamo_to_hcj

# 1. 환경 설정 및 API 로드
load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

START_TRIGGER = "123enter"
EXIT_TRIGGER = "123exit"
SCREEN_TRIGGER = "screenmode"
AI_NAME = "Orion"
PROFILE_FILE = "user_profile.txt"
TEMP_IMAGE = "temp_capture.png"
MODEL_NAME = "claude-sonnet-4-5-20250929" # 건희가 알려준 최신 모델명!

class OrionBot:
    def __init__(self):
        self.is_active = False
        self.screen_mode_waiting = False 
        self.full_input = ""
        self.short_term_memory = []
        self.load_personal_profile()

    def load_personal_profile(self):
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
            "3. 이미지 분석 시에는 아주 구체적이고 재치 있게 설명해줘.\n"
            "4. 이전 대화 맥락을 기억해서 자연스럽게 이어가줘."
        )

    def fix_hangul(self, text):
        try:
            combined = jamo_to_hcj(text)
            return unicodedata.normalize('NFC', combined)
        except:
            return unicodedata.normalize('NFC', text)

    def capture_screen(self):
        """맥북 스크린샷 캡처 (영역 선택 모드)"""
        try:
            # -i: 영역 선택, -x: 소리 없음
            subprocess.run(["screencapture", "-i", "-x", TEMP_IMAGE], check=True)
            return os.path.exists(TEMP_IMAGE)
        except:
            return False

    def get_vision_response(self, user_text, image_path):
        """이미지 + 텍스트 멀티모달 분석"""
        try:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            response = client.messages.create(
                model=MODEL_NAME,
                max_tokens=300,
                system=self.system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_data}},
                            {"type": "text", "text": user_text}
                        ]
                    }
                ]
            )
            if os.path.exists(image_path): os.remove(image_path)
            return response.content[0].text.strip()
        except Exception as e:
            return f"이미지 분석하다가 렉 걸렸어 ㅠㅠ: {str(e)}"

    def get_ai_response(self, user_text):
        """일반 대화 및 검색 로직"""
        try:
            user_text = self.fix_hangul(user_text)
            # 검색 필요성 판단
            thought_res = client.messages.create(
                model=MODEL_NAME,
                max_tokens=100,
                messages=[{"role": "user", "content": f"질문: '{user_text}'\n검색 필요시 'SEARCH: [영어검색어]', 불필요시 'NO'만 대답."}]
            )
            thought = thought_res.content[0].text.strip()
            
            context = ""
            if "SEARCH:" in thought.upper():
                query = thought.split(":", 1)[1].strip()
                res = tavily.search(query=query, search_depth="advanced", max_results=3)
                context = "\n\n[실시간 정보]: " + "\n".join([r['content'] for r in res['results']])

            messages = [{"role": m["role"], "content": m["content"]} for m in self.short_term_memory]
            messages.append({"role": "user", "content": f"{user_text} {context}"})

            response = client.messages.create(
                model=MODEL_NAME,
                max_tokens=300,
                system=self.system_prompt,
                messages=messages
            )
            answer = response.content[0].text.strip()
            
            self.short_term_memory.append({"role": "user", "content": user_text})
            self.short_term_memory.append({"role": "assistant", "content": answer})
            return answer
        except Exception as e:
            return f"오리온 엔진 과부하! ㅠㅠ: {str(e)}"

    def on_press(self, key):
        try:
            if hasattr(key, 'char') and key.char is not None:
                self.full_input += key.char
            elif key == keyboard.Key.enter:
                cmd = self.full_input.strip()
                
                if not self.is_active:
                    if cmd.endswith(START_TRIGGER):
                        self.is_active = True
                        self.full_input = ""
                        subprocess.run(["osascript", "-e", f'display notification "오리온 V2 가동! 건희야 안녕? ㅋㅋ" with title "{AI_NAME}"'])
                
                elif cmd.endswith(EXIT_TRIGGER):
                    self.is_active = False
                    self.full_input = ""
                    subprocess.run(["osascript", "-e", f'display notification "나 퇴근한다! 이따 봐!" with title "{AI_NAME}"'])

                elif self.is_active and cmd == SCREEN_TRIGGER:
                    self.full_input = ""
                    subprocess.run(["osascript", "-e", f'display notification "화면에서 찍고 싶은 곳을 드래그해!" with title "{AI_NAME}"'])
                    if self.capture_screen():
                        self.screen_mode_waiting = True
                        subprocess.run(["osascript", "-e", f'display notification "캡처 완료! 이제 질문해봐!" with title "{AI_NAME}"'])
                    else:
                        subprocess.run(["osascript", "-e", f'display notification "캡처가 취소됐어." with title "{AI_NAME}"'])

                elif self.is_active:
                    query = self.fix_hangul(cmd)
                    if query:
                        subprocess.run(["osascript", "-e", f'display notification "생각 중... 잠깐만! ㅋㅋ" with title "{AI_NAME}"'])
                        if self.screen_mode_waiting:
                            answer = self.get_vision_response(query, TEMP_IMAGE)
                            self.screen_mode_waiting = False
                        else:
                            answer = self.get_ai_response(query)
                        
                        subprocess.run(["osascript", "-e", f'display notification "{answer.replace("\"", "'")}" with title "{AI_NAME}"'])
                    self.full_input = ""

            elif key == keyboard.Key.backspace:
                self.full_input = self.full_input[:-1]
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    orion = OrionBot()
    print(f"--- [{AI_NAME}] V2 가동 중 (Model: {MODEL_NAME}) ---")
    with keyboard.Listener(on_press=orion.on_press) as listener:
        listener.join()