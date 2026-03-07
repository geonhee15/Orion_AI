import sys
import subprocess
import os
import datetime
import unicodedata
import threading
import requests
import tempfile
import time
import json
import re
import asyncio
from difflib import SequenceMatcher
import pygame
import sounddevice as sd
import numpy as np
import io
import wave
from anthropic import Anthropic
from tavily import TavilyClient
from dotenv import load_dotenv

# Playwright (배달 주문용)
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("⚠️ Playwright 없음. 배달 기능 비활성화. 'pip install playwright && playwright install chromium'")

# 환경 설정
load_dotenv()
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LOTTEEATZ_ID = os.getenv("LOTTEEATZ_ID")
LOTTEEATZ_PW = os.getenv("LOTTEEATZ_PW")

AI_NAME = "Orion"
PROFILE_FILE = "user_profile.txt"
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
MUSIC_FOLDER = "Music"
DELIVERY_CONFIG_FILE = "delivery_config.json"

# Wake Words
WAKE_WORDS = [
    "hey orion", "hey orian", "hey oreon", "hey orianne",
    "a orion", "a orian", "hey oryan", "hey aurion",
    "orion", "orian", "hey orient", "hey o'brien"
]

# 캘린더 키워드
CALENDAR_KEYWORDS = [
    "schedule", "calendar", "일정", "스케줄", "약속", "미팅", "meeting",
    "what do i have", "what's on", "events", "plan", "class",
    "오늘", "내일", "이번주", "today", "tomorrow", "this week", "next week"
]

# 배달 키워드
DELIVERY_KEYWORDS = [
    # 한국어
    "시켜", "주문", "배달", "롯데리아", "버거", "피자", "치킨",
    # 영어 (Whisper 변환 대비)
    "order", "deliver", "delivery", "lotteria", 
    "burger", "pizza", "chicken", "send me", "get me",
    "bulgogi", "korean beef", "shrimp", "cheese stick"
]

# 롯데잇츠 로그인
LOTTEEATZ_LOGIN_URL = "https://www.lotteeatz.com/member/login"

# ElevenLabs
ELEVENLABS_VOICE_ID = "QYrOVogqhHWUzdZFXf0E"
ELEVENLABS_API_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"


# --- [macOS Calendar using icalBuddy] ---
class MacCalendar:
    def __init__(self):
        self.icalbuddy_path = None
        self.available = self._check_icalbuddy()
    
    def _check_icalbuddy(self):
        paths = [
            "/usr/local/bin/icalBuddy",
            "/opt/homebrew/bin/icalBuddy",
            "/usr/bin/icalBuddy"
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
        except:
            pass
        
        print("⚠️ icalBuddy 없음. 'brew install ical-buddy' 실행하세요.")
        self.icalbuddy_path = None
        return False
    
    def get_today_events(self):
        if not self.available or not self.icalbuddy_path:
            return None
        try:
            result = subprocess.run(
                [self.icalbuddy_path, "eventsToday"],
                capture_output=True, text=True
            )
            return self._parse_events(result.stdout, "오늘")
        except Exception as e:
            print(f"캘린더 에러: {e}")
            return None
    
    def get_tomorrow_events(self):
        if not self.available or not self.icalbuddy_path:
            return None
        try:
            result = subprocess.run(
                [self.icalbuddy_path, "eventsToday+1"],
                capture_output=True, text=True
            )
            return self._parse_events(result.stdout, "내일")
        except Exception as e:
            print(f"캘린더 에러: {e}")
            return None
    
    def get_week_events(self):
        if not self.available or not self.icalbuddy_path:
            return None
        try:
            result = subprocess.run(
                [self.icalbuddy_path, "eventsToday+7"],
                capture_output=True, text=True
            )
            return self._parse_events(result.stdout, "이번 주")
        except Exception as e:
            print(f"캘린더 에러: {e}")
            return None
    
    def get_raw_events(self, days=1):
        if not self.available or not self.icalbuddy_path:
            return ""
        try:
            if days == 0:
                cmd = [self.icalbuddy_path, "eventsToday"]
            else:
                cmd = [self.icalbuddy_path, f"eventsToday+{days}"]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.stdout
        except Exception as e:
            print(f"[Calendar Error] {e}")
            return ""
    
    def _parse_events(self, output, period):
        if not output or output.strip() == "":
            return f"Sir, {period}은 일정이 없습니다."
        
        lines = output.strip().split('\n')
        events = []
        current_event = None
        
        for line in lines:
            if line.strip().startswith('•'):
                if current_event:
                    events.append(current_event)
                event_name = line.strip()[2:].split('(')[0].strip()
                current_event = {"name": event_name, "time": "", "location": ""}
            elif current_event:
                line = line.strip()
                if "at 오전" in line or "at 오후" in line or "tomorrow at" in line:
                    current_event["time"] = line
                elif line.startswith("location:"):
                    current_event["location"] = line.replace("location:", "").strip()
        
        if current_event:
            events.append(current_event)
        
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
                    formatted.append(e['name'])
            else:
                formatted.append(e['name'])
        
        return f"Sir, {period} 일정입니다. " + ", ".join(formatted) + "."


# --- [Music Player] ---
class MusicPlayer:
    def __init__(self):
        pygame.mixer.init()
        self.is_playing = False
        self.current_song = None
        self.normal_volume = 0.2
        self.ducked_volume = 0.05
    
    def duck(self):
        if self.is_playing:
            pygame.mixer.music.set_volume(self.ducked_volume)
    
    def unduck(self):
        if self.is_playing:
            pygame.mixer.music.set_volume(self.normal_volume)
    
    def play(self, song_name):
        self.stop()
        filename = song_name.strip().replace(" ", "_")
        if not filename.lower().endswith(".mp3"):
            filename += ".mp3"
        
        filepath = os.path.join(MUSIC_FOLDER, filename)
        
        if not os.path.exists(filepath):
            if os.path.exists(MUSIC_FOLDER):
                for f in os.listdir(MUSIC_FOLDER):
                    if f.lower() == filename.lower():
                        filepath = os.path.join(MUSIC_FOLDER, f)
                        break
                else:
                    return False
            else:
                return False
        
        try:
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.set_volume(self.normal_volume)
            pygame.mixer.music.play(loops=-1)
            self.is_playing = True
            self.current_song = song_name
            return True
        except:
            return False
    
    def stop(self):
        if self.is_playing:
            pygame.mixer.music.stop()
        self.is_playing = False
        self.current_song = None


# --- [롯데잇츠 배달 주문] ---
class LotteEatzOrder:
    """
    롯데잇츠 주문 자동화
    
    실제 Selectors:
    - 메뉴 클릭: a.btn-link[onclick*="selectMenu"]
    - 담기 버튼: #addCart
    - 수량 +: a.ui-spinner-up
    - 수량 -: a.ui-spinner-down
    - 장바구니로 가기: a.btn-md.btn-line-primary
    - 주문하기: #btnOrdAmt
    """
    
    def __init__(self, config_path=DELIVERY_CONFIG_FILE):
        self.config = self._load_config(config_path)
        self.playwright = None
        self.context = None
        self.page = None
        
        # 세션 저장 경로
        self.user_data_dir = os.path.expanduser("~/.lotteeatz_session")
        
        # 주문 상태
        self.current_order = {
            "address": None,
            "store": None,
            "items": [],
            "status": "idle"
        }
    
    def _load_config(self, path):
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        # 기본 설정
        default_config = {
            "addresses": {
                "송도집": {
                    "address": "인천광역시 연수구 송도동",
                    "stores": {
                        "롯데리아": {
                            "url": "https://www.lotteeatz.com/hsv/products/10/12408?lng=126.63986311482&lat=37.3974255837096",
                            "store_name": "롯데리아 센트럴파크점"
                        }
                    }
                },
                "서울집": {
                    "address": "서울특별시",
                    "stores": {}
                }
            },
            "menu_aliases": {
                "한우불고기버거": ["불고기", "한우불고기", "bulgogi", "korean beef", "korean beef bulgogi", "beef bulgogi"],
                "치킨버거": ["치킨", "chicken", "chicken burger"],
                "새우버거": ["새우", "shrimp", "shrimp burger"],
                "치즈스틱": ["치즈스틱", "cheese stick", "mozzarella"]
            }
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        return default_config
    
    def _resolve_address(self, address_query):
        address_query = address_query.lower()
        
        # 영어 별칭 매핑 (Whisper가 영어로 변환할 때 대비)
        address_aliases = {
            "송도집": ["songdo", "songdo house", "songdo jip", "songdo's", "송도"],
            "서울집": ["seoul", "seoul house", "seoul jip", "seoul's", "서울"]
        }
        
        # 먼저 별칭으로 검색
        for addr_name, aliases in address_aliases.items():
            for alias in aliases:
                if alias in address_query:
                    addr_data = self.config.get("addresses", {}).get(addr_name)
                    if addr_data:
                        return addr_name, addr_data
        
        # 기존 방식으로도 검색
        for addr_name, addr_data in self.config.get("addresses", {}).items():
            if addr_name.lower() in address_query or address_query in addr_name.lower():
                return addr_name, addr_data
        
        return None, None
    
    def _find_menu_match(self, query):
        """메뉴 이름 매칭 (별칭 포함)"""
        query_lower = query.lower()
        
        for menu_name, aliases in self.config.get("menu_aliases", {}).items():
            if query_lower in menu_name.lower():
                return menu_name
            for alias in aliases:
                if alias.lower() in query_lower or query_lower in alias.lower():
                    return menu_name
        
        return query
    
    async def start_browser(self):
        if not PLAYWRIGHT_AVAILABLE:
            return False
        
        self.playwright = await async_playwright().start()
        os.makedirs(self.user_data_dir, exist_ok=True)
        
        self.context = await self.playwright.chromium.launch_persistent_context(
            self.user_data_dir,
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="ko-KR"
        )
        
        self.page = await self.context.new_page()
        print("🌐 브라우저 시작됨")
        return True
    
    async def check_logged_in(self):
        """로그인 상태 확인"""
        try:
            # 현재 페이지 URL 확인
            current_url = self.page.url
            print(f"🔍 현재 URL: {current_url}")
            
            # 로그인 페이지로 리다이렉트 되었는지 확인
            if "login" in current_url.lower():
                print("🔐 로그인 페이지로 리다이렉트됨 - 로그인 필요")
                return False
            
            # 페이지에서 로그인 필요 여부 확인 (로그인 버튼 찾기)
            login_link = await self.page.query_selector("a[href*='/member/login']")
            if login_link:
                text = await login_link.inner_text() if login_link else ""
                if "로그인" in text:
                    print("🔐 로그인 버튼 발견 - 로그인 필요")
                    return False
            
            print("✅ 로그인 상태 확인됨")
            return True
        except Exception as e:
            print(f"로그인 체크 에러: {e}")
            return False
    
    async def ensure_logged_in(self):
        """로그인 확인 후 필요시 로그인"""
        # 먼저 메인 페이지로 가서 체크
        await self.page.goto("https://www.lotteeatz.com/eatzMain")
        await self.page.wait_for_load_state("networkidle")
        await self.page.wait_for_timeout(1500)
        
        is_logged_in = await self.check_logged_in()
        if not is_logged_in:
            success, msg = await self.login()
            return success, msg
        return True, "이미 로그인됨"
    
    async def login(self):
        """롯데잇츠 로그인"""
        if not LOTTEEATZ_ID or not LOTTEEATZ_PW:
            return False, "로그인 정보가 .env에 없습니다. LOTTEEATZ_ID, LOTTEEATZ_PW를 설정해주세요."
        
        try:
            print("🔐 로그인 시도 중...")
            
            # 로그인 페이지로 이동
            await self.page.goto(LOTTEEATZ_LOGIN_URL)
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(1500)
            
            # 아이디 입력
            id_input = await self.page.query_selector("#onlId")
            if id_input:
                await id_input.fill(LOTTEEATZ_ID)
                print("✅ 아이디 입력됨")
            else:
                return False, "아이디 입력창을 찾을 수 없습니다."
            
            # 비밀번호 입력
            pw_input = await self.page.query_selector("#password")
            if pw_input:
                await pw_input.fill(LOTTEEATZ_PW)
                print("✅ 비밀번호 입력됨")
            else:
                return False, "비밀번호 입력창을 찾을 수 없습니다."
            
            # 자동 로그인 체크
            auto_login = await self.page.query_selector("#chkAutoLogin")
            if auto_login:
                await auto_login.check()
                print("✅ 자동 로그인 체크됨")
            
            # 로그인 버튼 클릭
            login_btn = await self.page.query_selector("button.btn-md.btn-primary")
            if login_btn:
                await login_btn.click()
                print("✅ 로그인 버튼 클릭됨")
            else:
                return False, "로그인 버튼을 찾을 수 없습니다."
            
            # 로그인 완료 대기
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(2000)
            
            # 로그인 성공 확인 (로그인 페이지가 아닌지)
            current_url = self.page.url
            if "login" not in current_url.lower():
                print("✅ 로그인 성공!")
                return True, "로그인 성공"
            else:
                return False, "로그인 실패. 아이디/비밀번호를 확인해주세요."
                
        except Exception as e:
            print(f"❌ 로그인 에러: {e}")
            return False, f"로그인 실패: {str(e)}"
    
    async def close_browser(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        self.playwright = None
        self.context = None
        self.page = None
        self.current_order = {"address": None, "store": None, "items": [], "status": "idle"}
        print("🌐 브라우저 종료됨")
    
    async def navigate_to_store(self, address_name, store_type="롯데리아"):
        # 먼저 로그인 확인
        success, msg = await self.ensure_logged_in()
        if not success:
            return False, msg
        
        addr_name, addr_data = self._resolve_address(address_name)
        
        if not addr_data:
            return False, f"'{address_name}' 주소를 찾을 수 없습니다."
        
        stores = addr_data.get("stores", {})
        if store_type not in stores:
            return False, f"'{addr_name}'에 등록된 {store_type} 매장이 없습니다."
        
        store_info = stores[store_type]
        url = store_info["url"]
        
        self.current_order["address"] = addr_name
        self.current_order["store"] = store_info["store_name"]
        
        await self.page.goto(url)
        await self.page.wait_for_load_state("networkidle")
        await self.page.wait_for_timeout(3000)  # 페이지 완전 로드 대기
        
        # 로그인 페이지로 리다이렉트 되었는지 확인
        if "login" in self.page.url.lower():
            print("🔐 로그인 필요 - 리다이렉트됨")
            success, msg = await self.login()
            if not success:
                return False, msg
            # 다시 매장 페이지로
            await self.page.goto(url)
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(3000)
        
        print(f"📍 {store_info['store_name']} 페이지 로드됨")
        self.current_order["status"] = "browsing"
        
        return True, store_info["store_name"]
    
    async def search_and_add_menu(self, menu_query, quantity=1):
        """메뉴 검색 및 장바구니 추가"""
        if self.current_order["status"] != "browsing":
            return False, "먼저 매장 페이지로 이동해주세요."
        
        try:
            menu_name = self._find_menu_match(menu_query)
            print(f"🔍 메뉴 검색: '{menu_query}' → '{menu_name}'")
            
            # 페이지 로드 대기
            await self.page.wait_for_timeout(2000)
            
            # 배달 탭 클릭 (있으면)
            delivery_tab = await self.page.query_selector("a[href='#tabContentDelivery'], button:has-text('배달')")
            if delivery_tab:
                await delivery_tab.click()
                await self.page.wait_for_timeout(1000)
                print("✅ 배달 탭 선택됨")
            
            # 스크롤해서 메뉴 로드
            for scroll_y in [300, 600, 900]:
                await self.page.evaluate(f"window.scrollTo(0, {scroll_y})")
                await self.page.wait_for_timeout(500)
            
            # 메뉴 찾기
            menu_links = await self.page.query_selector_all("a.btn-link[onclick*='selectMenu']")
            print(f"📋 메뉴 개수: {len(menu_links)}")
            
            found_menu = None
            for link in menu_links:
                onclick = await link.get_attribute("onclick")
                if onclick:
                    onclick_clean = onclick.lower().replace(" ", "")
                    menu_clean = menu_name.lower().replace(" ", "")
                    query_clean = menu_query.lower().replace(" ", "")
                    
                    if menu_clean in onclick_clean or query_clean in onclick_clean:
                        found_menu = link
                        print(f"✅ 메뉴 찾음: {onclick[:50]}...")
                        break
            
            if not found_menu:
                # 부분 매칭 재시도
                for link in menu_links:
                    onclick = await link.get_attribute("onclick") or ""
                    # 불고기, bulgogi 등 키워드로 검색
                    keywords = ["불고기", "bulgogi", "치킨", "chicken", "새우", "shrimp"]
                    for kw in keywords:
                        if kw in menu_query.lower() and kw in onclick.lower():
                            found_menu = link
                            print(f"✅ 키워드 매칭: {kw}")
                            break
                    if found_menu:
                        break
            
            if not found_menu:
                return False, f"'{menu_query}' 메뉴를 찾을 수 없습니다."
            
            # 메뉴로 스크롤
            await found_menu.scroll_into_view_if_needed()
            await self.page.wait_for_timeout(500)
            
            # 메뉴 클릭 (JavaScript로 직접 실행)
            await found_menu.evaluate("el => el.click()")
            print(f"✅ 메뉴 클릭됨")
            await self.page.wait_for_timeout(2000)
            
            # 수량 설정
            if quantity > 1:
                plus_btn = await self.page.query_selector("a.ui-spinner-up")
                if plus_btn:
                    for _ in range(quantity - 1):
                        await plus_btn.click()
                        await self.page.wait_for_timeout(300)
                    print(f"✅ 수량: {quantity}개")
            
            # 장바구니 담기
            add_cart_btn = await self.page.query_selector("#addCart")
            if add_cart_btn:
                await add_cart_btn.scroll_into_view_if_needed()
                await self.page.wait_for_timeout(300)
                await add_cart_btn.click()
                print(f"✅ 장바구니 추가됨")
                await self.page.wait_for_timeout(1500)
            else:
                return False, "장바구니 버튼을 찾을 수 없습니다."
            
            self.current_order["items"].append({"name": menu_name, "quantity": quantity})
            
            return True, f"{menu_name} {quantity}개 담았습니다."
            
        except Exception as e:
            print(f"❌ 메뉴 추가 에러: {e}")
            return False, f"메뉴 추가 실패: {str(e)}"
    
    async def go_to_cart(self):
        """장바구니 페이지로 이동"""
        try:
            cart_btn = await self.page.query_selector("a.btn-md.btn-line-primary")
            if cart_btn:
                await cart_btn.click()
                await self.page.wait_for_load_state("networkidle")
                await self.page.wait_for_timeout(1500)
                print("🛒 장바구니 페이지")
                self.current_order["status"] = "cart"
                return True, "장바구니 페이지입니다."
            else:
                return False, "장바구니 버튼을 찾을 수 없습니다."
        except Exception as e:
            return False, f"장바구니 이동 실패: {str(e)}"
    
    async def go_to_checkout(self):
        """결제 페이지로 이동 (결제 직전까지)"""
        try:
            if self.current_order["status"] != "cart":
                success, msg = await self.go_to_cart()
                if not success:
                    return False, msg
            
            # 주문하기 버튼 클릭
            order_btn = await self.page.query_selector("#btnOrdAmt")
            if order_btn:
                await order_btn.click()
                await self.page.wait_for_load_state("networkidle")
                await self.page.wait_for_timeout(2000)
                print("💳 결제 페이지")
                self.current_order["status"] = "checkout"
                return True, "결제 페이지를 열었습니다. 직접 결제를 진행해주세요, sir."
            else:
                return False, "주문하기 버튼을 찾을 수 없습니다."
        except Exception as e:
            return False, f"주문 페이지 이동 실패: {str(e)}"
    
    def get_order_summary(self):
        if not self.current_order["items"]:
            return "장바구니가 비어있습니다."
        
        items_str = ", ".join([
            f"{item['name']} {item['quantity']}개" 
            for item in self.current_order["items"]
        ])
        
        return f"{self.current_order['store']}에서 {items_str}"


class DeliveryManager:
    """Orion 통합용 배달 관리자"""
    
    def __init__(self):
        self.lotteeatz = LotteEatzOrder()
        self.is_browser_open = False
    
    async def process_order_command(self, command):
        if not PLAYWRIGHT_AVAILABLE:
            return "Sir, 배달 기능을 사용하려면 Playwright를 설치해주세요."
        
        command_lower = command.lower()
        
        # 주소 파싱 (영어 별칭 지원)
        address_aliases = {
            "송도집": ["songdo", "songdo house", "songdo jip", "songdo's", "송도"],
            "서울집": ["seoul", "seoul house", "seoul jip", "seoul's", "서울"]
        }
        
        address = None
        for addr_name, aliases in address_aliases.items():
            for alias in aliases:
                if alias in command_lower:
                    address = addr_name
                    break
            if address:
                break
        
        # 기존 방식으로도 검색
        if not address:
            for addr in self.lotteeatz.config.get("addresses", {}).keys():
                if addr.lower() in command_lower:
                    address = addr
                    break
        
        if not address:
            return "Sir, 어느 주소로 배달할까요? 송도집 또는 서울집으로 말씀해주세요."
        
        # 수량 파싱
        quantity = 1
        qty_match = re.search(r'(\d+)\s*개', command)
        if qty_match:
            quantity = int(qty_match.group(1))
        
        # 메뉴 파싱
        menu = None
        patterns = [
            # 한국어 패턴
            r"(.+?)\s*\d*\s*개?\s*시켜",
            r"(.+?)\s*\d*\s*개?\s*주문",
            r"(.+?)\s*\d*\s*개?\s*배달",
            # 영어 패턴
            r"(?:order|send|get|deliver)\s*(?:me\s*)?(?:a\s*)?(.+?)\s*(?:to|from|for)",
            r"(.+?burger)",
            r"(.+?pizza)",
            r"(.+?chicken)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                menu = match.group(1).strip()
                # 불필요한 단어 제거 (한국어 + 영어)
                remove_words = [
                    address, "으로", "로", "에", "좀", "한번",
                    "songdo", "seoul", "house", "to", "from", "a", "the", "please",
                    "songdo's", "seoul's", "me"
                ]
                for word in remove_words:
                    menu = re.sub(rf'\b{word}\b', '', menu, flags=re.IGNORECASE)
                menu = menu.strip()
                if menu:
                    break
        
        if not menu:
            return "Sir, 어떤 메뉴를 주문할까요?"
        
        # 브라우저 시작
        if not self.is_browser_open:
            success = await self.lotteeatz.start_browser()
            if not success:
                return "Sir, 브라우저를 시작할 수 없습니다."
            self.is_browser_open = True
        
        # 매장 이동
        success, msg = await self.lotteeatz.navigate_to_store(address)
        if not success:
            return f"Sir, {msg}"
        
        # 메뉴 추가
        success, msg = await self.lotteeatz.search_and_add_menu(menu, quantity)
        if not success:
            return f"Sir, {msg}"
        
        # 결제 페이지로
        success, msg = await self.lotteeatz.go_to_checkout()
        if not success:
            return f"Sir, {msg}"
        
        order_summary = self.lotteeatz.get_order_summary()
        return f"Sir, {order_summary} 주문을 준비했습니다. 결제 페이지를 열어두었으니 직접 결제를 진행해주세요."
    
    async def cancel(self):
        await self.lotteeatz.close_browser()
        self.is_browser_open = False
        return "Sir, 주문을 취소하고 브라우저를 닫았습니다."


# --- [Main Orion Bot] ---
class OrionPortable:
    def __init__(self):
        self.short_term_memory = []
        self.music_player = MusicPlayer()
        self.calendar = MacCalendar()
        self.delivery_manager = DeliveryManager()
        self.is_running = True
        self.is_speaking = False
        
        self.sample_rate = 16000
        self.channels = 1
        
        self._setup_audio_device()
        self.load_personal_profile()
    
    def _setup_audio_device(self):
        try:
            devices = sd.query_devices()
            input_device = None
            
            for i, dev in enumerate(devices):
                if "Cleer" in dev['name'] and dev['max_input_channels'] > 0:
                    input_device = i
                    print(f"🎧 블루투스 마이크 설정: {dev['name']} (장치 {i})")
                    break
            
            if input_device is not None:
                sd.default.device[0] = input_device
            else:
                print("⚠️ Cleer ARC 없음, 기본 마이크 사용")
        except Exception as e:
            print(f"오디오 장치 설정 에러: {e}")
        
    def load_personal_profile(self):
        extra_info = ""
        if os.path.exists(PROFILE_FILE):
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                extra_info = f.read()
        
        self.system_prompt = (
            f"당신은 건희의 전용 AI 비서 '{AI_NAME}'이야.\n"
            f"[건희 정보]\n{extra_info}\n"
            "핵심 지침:\n"
            "1. 무조건 '존댓말'로 마치 영화 아이언맨에 나오는 자비스처럼 차분하고 똑똑하게 말해줘.\n"
            "2. 답변은 무조건 '한 문장'으로 아주 짧고 핵심만 말해.\n"
            "3. 이전 대화 맥락을 기억해서 자연스럽게 이어가줘.\n"
            "4. 건희를 부를 때 이름 대신 'sir'이라고 해.\n"
            "5. 건희를 항상 2인칭 '당신/you'로 지칭해."
        )

    def notify(self, msg):
        try:
            subprocess.run(["osascript", "-e", 
                f'display notification "{msg.replace(chr(34), chr(39))}" with title "{AI_NAME}"'],
                capture_output=True)
        except:
            pass

    def speak(self, text):
        self.is_speaking = True
        try:
            self.music_player.duck()
            
            english_text = self.translate_to_english(text)
            print(f"🔊 [{AI_NAME}]: {english_text}")
            
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": ELEVENLABS_API_KEY
            }
            
            data = {
                "text": english_text,
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "style": 0.3,
                    "use_speaker_boost": True
                }
            }
            
            response = requests.post(ELEVENLABS_API_URL, json=data, headers=headers)
            
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    f.write(response.content)
                    temp_path = f.name
                
                subprocess.run(["afplay", temp_path], capture_output=True)
                os.remove(temp_path)
                
        except Exception as e:
            print(f"[TTS Error] {e}")
        finally:
            self.music_player.unduck()
            self.is_speaking = False

    def translate_to_english(self, korean_text):
        try:
            response = anthropic_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=200,
                messages=[{
                    "role": "user", 
                    "content": f"Translate to natural English. '건희' = 'sir'. Output translation only:\n\n{korean_text}"
                }]
            )
            return response.content[0].text.strip()
        except:
            return korean_text

    def record_audio(self, duration=4):
        print(f"🎤 녹음 중... ({duration}초)")
        try:
            audio_data = sd.rec(
                int(duration * self.sample_rate),
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype='float32',
                device=sd.default.device[0]
            )
            sd.wait()
            
            volume = np.sqrt(np.mean(audio_data**2))
            print(f"📊 볼륨: {volume:.6f}")
            
            if volume < 0.001:
                return None
            
            return audio_data
        except Exception as e:
            print(f"녹음 에러: {e}")
            return None

    def to_wav_bytes(self, audio_data):
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            audio_int16 = (audio_data * 32767).astype(np.int16)
            wf.writeframes(audio_int16.tobytes())
        buffer.seek(0)
        return buffer.read()

    def transcribe(self, audio_data):
        if not OPENAI_API_KEY:
            return None
        
        try:
            wav_bytes = self.to_wav_bytes(audio_data)
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                temp_path = f.name
            
            with open(temp_path, "rb") as audio_file:
                response = requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    files={"file": audio_file},
                    data={"model": "whisper-1", "language": "en", "prompt": "Hey Orion"}
                )
            os.remove(temp_path)
            
            if response.status_code == 200:
                text = response.json().get("text", "")
                print(f"📥 Whisper: '{text}'")
                return text
            return None
        except Exception as e:
            print(f"Transcribe 에러: {e}")
            return None

    def check_calendar_query(self, text):
        text_lower = text.lower()
        return any(kw in text_lower for kw in CALENDAR_KEYWORDS)

    def check_delivery_query(self, text):
        text_lower = text.lower()
        return any(kw in text_lower for kw in DELIVERY_KEYWORDS)

    def handle_calendar_query(self, text):
        text_lower = text.lower()
        
        if any(w in text_lower for w in ["tomorrow", "내일"]):
            raw_events = self.calendar.get_raw_events(days=1)
            period = "tomorrow"
        elif any(w in text_lower for w in ["week", "이번주", "주"]):
            raw_events = self.calendar.get_raw_events(days=7)
            period = "this week"
        else:
            raw_events = self.calendar.get_raw_events(days=0)
            period = "today"
        
        if not raw_events or raw_events.strip() == "":
            return f"Sir, {period}은 일정이 없습니다."
        
        try:
            response = anthropic_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=150,
                messages=[{
                    "role": "user",
                    "content": f"""다음은 캘린더 일정 데이터입니다:

{raw_events}

질문: {text}

위 일정 데이터를 바탕으로 질문에 한 문장으로 간단히 답해주세요. 
시간은 오전/오후 형식으로 말해주세요.
항상 "Sir,"로 시작하고 존댓말로 답해주세요."""
                }]
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"AI 캘린더 분석 에러: {e}")
            return self.calendar.get_tomorrow_events() if "tomorrow" in text_lower else self.calendar.get_today_events()

    def handle_delivery_command(self, text):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                self.delivery_manager.process_order_command(text)
            )
            return result
        except Exception as e:
            print(f"배달 명령 에러: {e}")
            return f"Sir, 주문 처리 중 오류가 발생했습니다: {str(e)}"
        finally:
            loop.close()

    def handle_delivery_cancel(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(self.delivery_manager.cancel())
            return result
        finally:
            loop.close()

    def get_ai_response(self, user_text):
        try:
            if self.check_calendar_query(user_text):
                return self.handle_calendar_query(user_text)
            
            user_text = unicodedata.normalize('NFC', user_text)
            now = datetime.datetime.now()
            time_info = f"[현재: {now.strftime('%Y-%m-%d %H:%M')}]"
            
            search_keywords = ["날씨", "뉴스", "현재", "지금", "weather", "news"]
            context = ""
            
            if any(kw in user_text.lower() for kw in search_keywords):
                try:
                    search_res = anthropic_client.messages.create(
                        model=CLAUDE_MODEL, max_tokens=50,
                        messages=[{"role": "user", "content": f"'{user_text}' 검색어 영어로 하나만: "}]
                    )
                    query = search_res.content[0].text.strip()
                    res = tavily.search(query=query, search_depth="basic", max_results=2)
                    context = "\n[검색결과]: " + " ".join([r['content'][:200] for r in res['results']])
                except:
                    pass

            messages = list(self.short_term_memory)
            messages.append({"role": "user", "content": f"{time_info} {user_text} {context}"})

            response = anthropic_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=150,
                system=self.system_prompt,
                messages=messages
            )
            answer = response.content[0].text.strip()
            
            self.short_term_memory.append({"role": "user", "content": user_text})
            self.short_term_memory.append({"role": "assistant", "content": answer})
            if len(self.short_term_memory) > 10:
                self.short_term_memory = self.short_term_memory[-10:]
            
            return answer
        except Exception as e:
            return f"잠시 오류가 발생했습니다: {str(e)}"

    def process_command(self, text):
        cmd = text.lower()
        
        # 종료
        if any(w in cmd for w in ["goodbye", "shut down", "turn off", "종료"]):
            self.speak("오리온 C4 작동을 중지하겠습니다. 안녕히 가세요, sir.")
            self.is_running = False
            return
        
        # 배달 취소
        if any(w in cmd for w in ["cancel order", "주문 취소", "배달 취소"]):
            answer = self.handle_delivery_cancel()
            self.notify(answer)
            self.speak(answer)
            return
        
        # 배달 주문
        if self.check_delivery_query(text):
            answer = self.handle_delivery_command(text)
            self.notify(answer)
            self.speak(answer)
            return
        
        # 음악
        if any(w in cmd for w in ["play ", "플레이", "틀어"]):
            for kw in ["play ", "플레이 ", "틀어 ", "틀어줘 "]:
                if kw in cmd:
                    song = text[cmd.find(kw) + len(kw):].strip()
                    if song:
                        if self.music_player.play(song):
                            self.speak(f"{song} 재생하겠습니다, sir.")
                        else:
                            self.speak(f"{song} 파일을 찾을 수 없습니다, sir.")
                        return
        
        if any(w in cmd for w in ["stop music", "stop song", "음악 중지"]):
            self.music_player.stop()
            self.speak("음악을 중지했습니다, sir.")
            return
        
        # 볼륨
        if "volume up" in cmd:
            self.music_player.normal_volume = min(1.0, self.music_player.normal_volume + 0.1)
            pygame.mixer.music.set_volume(self.music_player.normal_volume)
            self.speak("볼륨을 높였습니다.")
            return
        
        if "volume down" in cmd:
            self.music_player.normal_volume = max(0.0, self.music_player.normal_volume - 0.1)
            pygame.mixer.music.set_volume(self.music_player.normal_volume)
            self.speak("볼륨을 낮췄습니다.")
            return
        
        # 일반 대화 / 캘린더
        answer = self.get_ai_response(text)
        self.notify(answer)
        self.speak(answer)

    def extract_command(self, text):
        text_lower = text.lower()
        for wake in WAKE_WORDS:
            if wake in text_lower:
                idx = text_lower.find(wake) + len(wake)
                cmd = text[idx:].strip().lstrip(',').lstrip()
                if len(cmd) > 2:
                    return cmd
        return None

    def run(self):
        print(f"\n{'='*50}")
        print(f"  🎧 {AI_NAME} C4 + Calendar + Delivery")
        print(f"{'='*50}")
        print(f"✅ Whisper: {'OK' if OPENAI_API_KEY else 'NO'}")
        print(f"✅ Calendar: {'OK' if self.calendar.available else 'NO'}")
        print(f"✅ Delivery: {'OK' if PLAYWRIGHT_AVAILABLE else 'NO'}")
        print(f"✅ LotteEatz Login: {'OK' if LOTTEEATZ_ID and LOTTEEATZ_PW else 'NO (.env에 LOTTEEATZ_ID, LOTTEEATZ_PW 설정 필요)'}")
        print(f"✅ 'Hey Orion'이라고 말하세요!")
        print(f"{'='*50}\n")
        
        self.notify("오리온 C4 시작됨!")
        self.speak("오리온 C4 가동되었습니다. 언제든 불러주세요, sir.")
        
        while self.is_running:
            try:
                if self.is_speaking:
                    time.sleep(0.1)
                    continue
                
                audio_data = self.record_audio(duration=4)
                
                if audio_data is None:
                    continue
                
                text = self.transcribe(audio_data)
                
                if not text or len(text.strip()) < 2:
                    continue
                
                print(f"👂 들림: '{text}'")
                
                text_lower = text.lower()
                wake_detected = any(wake in text_lower for wake in WAKE_WORDS)
                
                if wake_detected:
                    print("✨ Wake word!")
                    
                    command = self.extract_command(text)
                    
                    if command:
                        print(f"📝 명령: '{command}'")
                        self.process_command(command)
                    else:
                        self.speak("네, 말씀하세요, sir.")
                        
                        audio_data2 = self.record_audio(duration=8)
                        if audio_data2 is not None:
                            command = self.transcribe(audio_data2)
                            if command:
                                print(f"📝 명령: '{command}'")
                                self.process_command(command)
                
            except KeyboardInterrupt:
                print("\n🛑 Ctrl+C")
                break
            except Exception as e:
                print(f"⚠️ 에러: {e}")
                time.sleep(0.5)
        
        print("\n👋 오리온 C4 종료")
        self.music_player.stop()


if __name__ == "__main__":
    if not os.path.exists(MUSIC_FOLDER):
        os.makedirs(MUSIC_FOLDER)
    
    orion = OrionPortable()
    orion.run()