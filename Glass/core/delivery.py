import os
import re
import json
import asyncio
import concurrent.futures
from Glass import config

# Playwright (배달 주문용)
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

LOTTEEATZ_LOGIN_URL = "https://www.lotteeatz.com/member/login"


class LotteEatzOrder:
    """롯데잇츠 주문 자동화 (Playwright)"""

    def __init__(self):
        self.config = self._load_config()
        self.playwright = None
        self.context = None
        self.page = None
        self.user_data_dir = os.path.expanduser("~/.lotteeatz_session")
        self.current_order = {
            "address": None, "store": None, "items": [], "status": "idle"
        }

    def _load_config(self):
        if os.path.exists(config.DELIVERY_CONFIG_FILE):
            with open(config.DELIVERY_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"addresses": {}, "menu_aliases": {}}

    def _resolve_address(self, address_query):
        address_query = address_query.lower()
        address_aliases = {
            "송도집": ["songdo", "songdo house", "songdo jip", "songdo's", "송도"],
            "서울집": ["seoul", "seoul house", "seoul jip", "seoul's", "서울"],
        }

        for addr_name, aliases in address_aliases.items():
            for alias in aliases:
                if alias in address_query:
                    addr_data = self.config.get("addresses", {}).get(addr_name)
                    if addr_data:
                        return addr_name, addr_data

        for addr_name, addr_data in self.config.get("addresses", {}).items():
            if addr_name.lower() in address_query or address_query in addr_name.lower():
                return addr_name, addr_data
        return None, None

    def _find_menu_match(self, query):
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
            self.user_data_dir, headless=False,
            viewport={"width": 1280, "height": 900}, locale="ko-KR",
        )
        self.page = await self.context.new_page()
        return True

    async def ensure_logged_in(self):
        await self.page.goto("https://www.lotteeatz.com/eatzMain")
        await self.page.wait_for_load_state("networkidle")
        await self.page.wait_for_timeout(1500)
        if "login" in self.page.url.lower():
            return await self.login()
        login_link = await self.page.query_selector("a[href*='/member/login']")
        if login_link:
            text = await login_link.inner_text() if login_link else ""
            if "로그인" in text:
                return await self.login()
        return True, "이미 로그인됨"

    async def login(self):
        if not config.LOTTEEATZ_ID or not config.LOTTEEATZ_PW:
            return False, "로그인 정보가 .env에 없습니다."
        try:
            await self.page.goto(LOTTEEATZ_LOGIN_URL)
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(1500)

            id_input = await self.page.query_selector("#onlId")
            if id_input:
                await id_input.fill(config.LOTTEEATZ_ID)
            pw_input = await self.page.query_selector("#password")
            if pw_input:
                await pw_input.fill(config.LOTTEEATZ_PW)

            auto_login = await self.page.query_selector("#chkAutoLogin")
            if auto_login:
                await auto_login.check()

            login_btn = await self.page.query_selector("button.btn-md.btn-primary")
            if login_btn:
                await login_btn.click()

            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(2000)

            if "login" not in self.page.url.lower():
                return True, "로그인 성공"
            return False, "로그인 실패"
        except Exception as e:
            return False, f"로그인 실패: {str(e)}"

    async def navigate_to_store(self, address_name, store_type="롯데리아"):
        success, msg = await self.ensure_logged_in()
        if isinstance(success, tuple):
            success, msg = success
        if not success:
            return False, msg

        addr_name, addr_data = self._resolve_address(address_name)
        if not addr_data:
            return False, f"'{address_name}' 주소를 찾을 수 없습니다."

        stores = addr_data.get("stores", {})
        if store_type not in stores:
            return False, f"'{addr_name}'에 등록된 {store_type} 매장이 없습니다."

        store_info = stores[store_type]
        self.current_order["address"] = addr_name
        self.current_order["store"] = store_info["store_name"]

        await self.page.goto(store_info["url"])
        await self.page.wait_for_load_state("networkidle")
        await self.page.wait_for_timeout(3000)

        if "login" in self.page.url.lower():
            success, msg = await self.login()
            if not success:
                return False, msg
            await self.page.goto(store_info["url"])
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(3000)

        self.current_order["status"] = "browsing"
        return True, store_info["store_name"]

    async def search_and_add_menu(self, menu_query, quantity=1):
        if self.current_order["status"] != "browsing":
            return False, "먼저 매장 페이지로 이동해주세요."
        try:
            menu_name = self._find_menu_match(menu_query)
            await self.page.wait_for_timeout(2000)

            delivery_tab = await self.page.query_selector(
                "a[href='#tabContentDelivery'], button:has-text('배달')"
            )
            if delivery_tab:
                await delivery_tab.click()
                await self.page.wait_for_timeout(1000)

            for scroll_y in [300, 600, 900]:
                await self.page.evaluate(f"window.scrollTo(0, {scroll_y})")
                await self.page.wait_for_timeout(500)

            menu_links = await self.page.query_selector_all(
                "a.btn-link[onclick*='selectMenu']"
            )
            found_menu = None
            for link in menu_links:
                onclick = await link.get_attribute("onclick")
                if onclick:
                    onclick_clean = onclick.lower().replace(" ", "")
                    if menu_name.lower().replace(" ", "") in onclick_clean:
                        found_menu = link
                        break

            if not found_menu:
                return False, f"'{menu_query}' 메뉴를 찾을 수 없습니다."

            await found_menu.scroll_into_view_if_needed()
            await found_menu.evaluate("el => el.click()")
            await self.page.wait_for_timeout(2000)

            if quantity > 1:
                plus_btn = await self.page.query_selector("a.ui-spinner-up")
                if plus_btn:
                    for _ in range(quantity - 1):
                        await plus_btn.click()
                        await self.page.wait_for_timeout(300)

            add_cart_btn = await self.page.query_selector("#addCart")
            if add_cart_btn:
                await add_cart_btn.scroll_into_view_if_needed()
                await add_cart_btn.click()
                await self.page.wait_for_timeout(1500)

            self.current_order["items"].append({"name": menu_name, "quantity": quantity})
            return True, f"{menu_name} {quantity}개 담았습니다."
        except Exception as e:
            return False, f"메뉴 추가 실패: {str(e)}"

    async def go_to_checkout(self):
        try:
            cart_btn = await self.page.query_selector("a.btn-md.btn-line-primary")
            if cart_btn:
                await cart_btn.click()
                await self.page.wait_for_load_state("networkidle")
                await self.page.wait_for_timeout(1500)

            order_btn = await self.page.query_selector("#btnOrdAmt")
            if order_btn:
                await order_btn.click()
                await self.page.wait_for_load_state("networkidle")
                await self.page.wait_for_timeout(2000)
                self.current_order["status"] = "checkout"
                return True, "결제 페이지를 열었습니다."
            return False, "주문하기 버튼을 찾을 수 없습니다."
        except Exception as e:
            return False, f"주문 페이지 이동 실패: {str(e)}"

    async def close_browser(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        self.playwright = None
        self.context = None
        self.page = None
        self.current_order = {"address": None, "store": None, "items": [], "status": "idle"}

    def get_order_summary(self):
        if not self.current_order["items"]:
            return "장바구니가 비어있습니다."
        items_str = ", ".join(
            f"{item['name']} {item['quantity']}개"
            for item in self.current_order["items"]
        )
        return f"{self.current_order['store']}에서 {items_str}"


class DeliveryManager:
    """Orion 통합용 배달 관리자"""

    def __init__(self):
        self.lotteeatz = LotteEatzOrder()
        self.is_browser_open = False
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    async def process_order_command(self, command):
        if not PLAYWRIGHT_AVAILABLE:
            return "Sir, 배달 기능을 사용하려면 Playwright를 설치해주세요."

        command_lower = command.lower()

        # 주소 파싱
        address_aliases = {
            "송도집": ["songdo", "songdo house", "songdo jip", "songdo's", "송도"],
            "서울집": ["seoul", "seoul house", "seoul jip", "seoul's", "서울"],
        }
        address = None
        for addr_name, aliases in address_aliases.items():
            for alias in aliases:
                if alias in command_lower:
                    address = addr_name
                    break
            if address:
                break

        if not address:
            for addr in self.lotteeatz.config.get("addresses", {}).keys():
                if addr.lower() in command_lower:
                    address = addr
                    break

        if not address:
            return "Sir, 어느 주소로 배달할까요? 송도집 또는 서울집으로 말씀해주세요."

        # 수량 파싱
        quantity = 1
        qty_match = re.search(r"(\d+)\s*개", command)
        if qty_match:
            quantity = int(qty_match.group(1))

        # 메뉴 파싱
        menu = None
        patterns = [
            r"(.+?)\s*\d*\s*개?\s*시켜", r"(.+?)\s*\d*\s*개?\s*주문",
            r"(.+?)\s*\d*\s*개?\s*배달",
            r"(?:order|send|get|deliver)\s*(?:me\s*)?(?:a\s*)?(.+?)\s*(?:to|from|for)",
            r"(.+?burger)", r"(.+?pizza)", r"(.+?chicken)",
        ]
        for pattern in patterns:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                menu = match.group(1).strip()
                remove_words = [
                    address, "으로", "로", "에", "좀", "한번",
                    "songdo", "seoul", "house", "to", "from", "a", "the", "please",
                ]
                for word in remove_words:
                    if word:
                        menu = re.sub(rf"\b{re.escape(word)}\b", "", menu, flags=re.IGNORECASE)
                menu = menu.strip()
                if menu:
                    break

        if not menu:
            return "Sir, 어떤 메뉴를 주문할까요?"

        # 주문 실행
        if not self.is_browser_open:
            success = await self.lotteeatz.start_browser()
            if not success:
                return "Sir, 브라우저를 시작할 수 없습니다."
            self.is_browser_open = True

        success, msg = await self.lotteeatz.navigate_to_store(address)
        if not success:
            return f"Sir, {msg}"

        success, msg = await self.lotteeatz.search_and_add_menu(menu, quantity)
        if not success:
            return f"Sir, {msg}"

        success, msg = await self.lotteeatz.go_to_checkout()
        if not success:
            return f"Sir, {msg}"

        order_summary = self.lotteeatz.get_order_summary()
        return f"Sir, {order_summary} 주문을 준비했습니다. 결제를 진행해주세요."

    async def cancel(self):
        await self.lotteeatz.close_browser()
        self.is_browser_open = False
        return "Sir, 주문을 취소하고 브라우저를 닫았습니다."

    def handle_order(self, text):
        """동기식 래퍼 - 별도 스레드에서 비동기 실행"""
        try:
            # 스레드풀에서 실행하여 메인 이벤트 루프와 충돌 방지
            future = self._executor.submit(self._run_async_order, text)
            return future.result(timeout=60)  # 최대 60초 대기
        except concurrent.futures.TimeoutError:
            return "Sir, 주문 처리 시간이 초과되었습니다."
        except Exception as e:
            return f"Sir, 주문 처리 중 오류가 발생했습니다: {str(e)}"

    def handle_cancel(self):
        """동기식 래퍼 - 별도 스레드에서 비동기 실행"""
        try:
            future = self._executor.submit(self._run_async_cancel)
            return future.result(timeout=10)  # 최대 10초 대기
        except concurrent.futures.TimeoutError:
            return "Sir, 취소 처리 시간이 초과되었습니다."
        except Exception as e:
            return f"Sir, 취소 처리 중 오류가 발생했습니다: {str(e)}"

    def _run_async_order(self, text):
        """별도 스레드에서 실행될 비동기 래퍼"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.process_order_command(text))
        finally:
            loop.close()

    def _run_async_cancel(self):
        """별도 스레드에서 실행될 비동기 래퍼"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.cancel())
        finally:
            loop.close()
