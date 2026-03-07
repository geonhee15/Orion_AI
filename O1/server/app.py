import io
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, JSONResponse
from O1 import config
from O1.server.ws_manager import ConnectionManager
from O1.server.vision import VisionAnalyzer


def create_app(orion_instance):
    """FastAPI 앱 생성. orion_instance는 OrionO1 객체."""
    app = FastAPI(title="Orion O1 - EDITH Smart Glasses Server")
    manager = ConnectionManager()
    vision = VisionAnalyzer(system_prompt=orion_instance.brain.system_prompt)

    # OrionO1에 manager 참조 저장 (HUD 전송용)
    orion_instance._ws_manager = manager

    # --- WebSocket: 글래스 연결 ---
    @app.websocket("/ws/glasses")
    async def glasses_endpoint(ws: WebSocket):
        await manager.connect_glasses(ws)
        try:
            while True:
                data = await ws.receive_bytes()
                if len(data) < 1:
                    continue

                msg_type = data[0]
                payload = data[1:]

                if msg_type == config.WSMessageType.CAMERA_FRAME:
                    # 카메라 프레임 수신
                    manager.store_camera_frame(payload)

                elif msg_type == config.WSMessageType.DEVICE_STATUS:
                    # 디바이스 상태 (JSON)
                    try:
                        status = json.loads(payload.decode("utf-8"))
                        print(f"🔋 글래스 상태: {status}")
                    except Exception:
                        pass

                elif msg_type == config.WSMessageType.BUTTON_PRESS:
                    # 버튼 프레스
                    if payload == b"\x01":
                        # 롱프레스 → 비전 분석
                        frame = manager.get_latest_frame()
                        if frame:
                            result = vision.analyze_frame(frame)
                            orion_instance.hud_state["ai_response"] = result
                            orion_instance.tts.speak(result)

        except WebSocketDisconnect:
            manager.disconnect_glasses()

    # --- WebSocket: 테스트 클라이언트 연결 ---
    @app.websocket("/ws/test")
    async def test_endpoint(ws: WebSocket):
        await manager.connect_test(ws)
        try:
            while True:
                msg = await ws.receive()
                if "bytes" in msg and msg["bytes"]:
                    # 시뮬레이션 카메라 프레임 수신
                    if len(msg["bytes"]) > 0:
                        manager.store_camera_frame(msg["bytes"])
                elif "text" in msg and msg["text"]:
                    # JSON 텍스트 메시지 (shutdown 등)
                    try:
                        data = json.loads(msg["text"])
                        if data.get("type") == "shutdown":
                            print("🛑 HUD 클라이언트에서 종료 요청")
                            orion_instance.is_running = False
                    except json.JSONDecodeError:
                        pass
        except WebSocketDisconnect:
            manager.disconnect_test(ws)

    # --- REST: 서버 상태 ---
    @app.get("/status")
    async def get_status():
        return {
            "name": config.AI_NAME,
            "version": "O1",
            "glasses_connected": manager.glasses_connected,
            "clients": manager.client_count,
            "hud_state": orion_instance.hud_state,
        }

    # --- REST: HUD 미리보기 (브라우저에서 확인용) ---
    @app.get("/hud/preview")
    async def hud_preview():
        if orion_instance.hud:
            png_data = orion_instance.hud.render_png(orion_instance.hud_state)
            return Response(content=png_data, media_type="image/png")
        return JSONResponse({"error": "HUD renderer not available"}, status_code=503)

    # --- REST: 수동 명령 ---
    @app.post("/command")
    async def post_command(body: dict):
        text = body.get("text", "")
        if not text:
            return {"error": "text required"}

        # 백그라운드에서 명령 처리
        import threading
        threading.Thread(
            target=orion_instance.process_command,
            args=(text,),
            daemon=True,
        ).start()

        return {"status": "processing", "command": text}

    # --- REST: 캘린더 ---
    @app.get("/calendar")
    async def get_calendar():
        today = orion_instance.calendar.get_raw_events(days=0)
        tomorrow = orion_instance.calendar.get_raw_events(days=1)
        return {"today": today, "tomorrow": tomorrow}

    # --- REST: 비전 분석 ---
    @app.post("/vision/analyze")
    async def analyze_vision(body: dict):
        frame = manager.get_latest_frame()
        if not frame:
            return {"error": "No camera frame available"}
        prompt = body.get("prompt", None)
        result = vision.analyze_frame(frame, prompt)
        return {"result": result}

    # --- HUD 프레임 주기적 전송 태스크 ---
    @app.on_event("startup")
    async def start_hud_broadcast():
        async def broadcast_loop():
            while True:
                if orion_instance.hud and manager.client_count > 0:
                    try:
                        png_data = orion_instance.hud.render_png(orion_instance.hud_state)
                        await manager.send_hud_frame(png_data)
                    except Exception as e:
                        print(f"HUD broadcast 에러: {e}")
                await asyncio.sleep(1.0 / config.HUD_FPS)

        asyncio.create_task(broadcast_loop())

    return app
