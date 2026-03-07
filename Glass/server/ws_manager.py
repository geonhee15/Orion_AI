import asyncio
import threading
from fastapi import WebSocket
from Glass import config


class ConnectionManager:
    """WebSocket 연결 관리 (글래스 + 테스트 클라이언트)"""

    def __init__(self):
        self.glasses_ws: WebSocket | None = None
        self.test_clients: list[WebSocket] = []
        self._latest_camera_frame: bytes | None = None
        self._frame_lock = threading.Lock()  # 프레임 캐시 동시성 제어

    async def connect_glasses(self, ws: WebSocket):
        await ws.accept()
        if self.glasses_ws:
            try:
                await self.glasses_ws.close()
            except Exception:
                pass
        self.glasses_ws = ws
        print("🕶️ 글래스 연결됨")

    async def connect_test(self, ws: WebSocket):
        await ws.accept()
        self.test_clients.append(ws)
        print(f"🖥️ 테스트 클라이언트 연결됨 (총 {len(self.test_clients)}개)")

    def disconnect_glasses(self):
        self.glasses_ws = None
        print("🕶️ 글래스 연결 해제됨")

    def disconnect_test(self, ws: WebSocket):
        if ws in self.test_clients:
            self.test_clients.remove(ws)
        print(f"🖥️ 테스트 클라이언트 해제됨 (총 {len(self.test_clients)}개)")

    async def send_hud_frame(self, frame_data: bytes):
        """HUD 프레임을 글래스 + 모든 테스트 클라이언트에 전송"""
        # 글래스에 전송 (바이너리: HUD_FRAME + JPEG)
        if self.glasses_ws:
            try:
                # WebSocket 상태 확인
                if self.glasses_ws.client_state.name != "CONNECTED":
                    self.disconnect_glasses()
                else:
                    await self.glasses_ws.send_bytes(bytes([config.WSMessageType.HUD_FRAME]) + frame_data)
            except Exception as e:
                print(f"⚠️ 글래스 전송 실패: {e}")
                self.disconnect_glasses()

        # 테스트 클라이언트에 전송 (PNG)
        disconnected = []
        for client in self.test_clients:
            try:
                # WebSocket 상태 확인
                if client.client_state.name != "CONNECTED":
                    disconnected.append(client)
                else:
                    await client.send_bytes(frame_data)
            except Exception as e:
                print(f"⚠️ 클라이언트 전송 실패: {e}")
                disconnected.append(client)

        for client in disconnected:
            if client in self.test_clients:
                self.test_clients.remove(client)

    async def send_notification(self, text: str):
        """알림 메시지를 JSON으로 전송"""
        import json
        msg = json.dumps({"type": "notification", "text": text})

        if self.glasses_ws:
            try:
                # WebSocket 상태 확인
                if self.glasses_ws.client_state.name != "CONNECTED":
                    self.disconnect_glasses()
                else:
                    await self.glasses_ws.send_text(msg)
            except Exception as e:
                print(f"⚠️ 글래스 알림 실패: {e}")
                self.disconnect_glasses()

        disconnected = []
        for client in self.test_clients:
            try:
                # WebSocket 상태 확인
                if client.client_state.name != "CONNECTED":
                    disconnected.append(client)
                else:
                    await client.send_text(msg)
            except Exception as e:
                print(f"⚠️ 클라이언트 알림 실패: {e}")
                disconnected.append(client)

        for client in disconnected:
            if client in self.test_clients:
                self.test_clients.remove(client)

    def store_camera_frame(self, frame: bytes):
        """최신 카메라 프레임 저장 (스레드 안전)"""
        with self._frame_lock:
            self._latest_camera_frame = frame

    def get_latest_frame(self) -> bytes | None:
        """최신 카메라 프레임 가져오기 (스레드 안전)"""
        with self._frame_lock:
            return self._latest_camera_frame

    @property
    def glasses_connected(self) -> bool:
        return self.glasses_ws is not None

    @property
    def client_count(self) -> int:
        return len(self.test_clients) + (1 if self.glasses_ws else 0)
