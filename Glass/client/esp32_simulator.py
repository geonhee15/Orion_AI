"""
ESP32 글래스 시뮬레이터
======================
실행: python -m O1.client.esp32_simulator

맥북 웹캠을 ESP32 카메라로 시뮬레이션해서 서버에 전송.
서버(O1.main)가 실행 중이어야 합니다.
"""

import asyncio
import json
import time
import cv2

try:
    import websockets
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    print("⚠️ websockets 패키지 필요: pip install websockets")


async def simulate_esp32():
    """맥북 웹캠 → JPEG → WebSocket → 서버"""
    if not WS_AVAILABLE:
        return

    uri = "ws://localhost:8000/ws/glasses"
    print(f"🕶️ ESP32 시뮬레이터 시작")
    print(f"🔌 서버 연결 중... ({uri})")

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ 웹캠 열기 실패!")
        return

    print("✅ 웹캠 연결됨")

    while True:
        try:
            async with websockets.connect(uri) as ws:
                print("✅ 서버 연결됨!")

                # 디바이스 정보 전송
                await ws.send(json.dumps({
                    "device": "esp32_simulator",
                    "version": "1.0",
                    "battery": 100,
                }).encode())

                frame_count = 0
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        continue

                    # JPEG 인코딩 (ESP32-CAM과 동일)
                    _, jpeg = cv2.imencode(
                        ".jpg", frame,
                        [cv2.IMWRITE_JPEG_QUALITY, 70]
                    )
                    jpeg_bytes = jpeg.tobytes()

                    # 0x01 헤더 + JPEG 전송
                    await ws.send(b"\x01" + jpeg_bytes)

                    frame_count += 1
                    if frame_count % 25 == 0:
                        # 주기적으로 상태 전송
                        status = json.dumps({
                            "battery": 85,
                            "wifi_rssi": -42,
                            "fps": 5,
                        })
                        await ws.send(b"\x04" + status.encode())

                    # 서버에서 HUD 프레임 수신 (있으면)
                    try:
                        data = await asyncio.wait_for(ws.recv(), timeout=0.01)
                        if isinstance(data, bytes) and len(data) > 0:
                            msg_type = data[0]
                            if msg_type == 0x02:
                                # HUD 프레임 수신 (실제 ESP32에서는 LCD에 표시)
                                print(f"📺 HUD 프레임 수신: {len(data)-1} bytes")
                    except asyncio.TimeoutError:
                        pass

                    # 5 FPS (ESP32와 동일)
                    await asyncio.sleep(0.2)

        except Exception as e:
            print(f"⚠️ 연결 실패: {e}, 3초 후 재시도...")
            await asyncio.sleep(3)

    cap.release()


def main():
    print("🕶️ ESP32 Smart Glasses 시뮬레이터")
    print("   맥북 웹캠 → 서버 → HUD")
    print("   종료: Ctrl+C")
    print()

    try:
        asyncio.run(simulate_esp32())
    except KeyboardInterrupt:
        print("\n👋 시뮬레이터 종료")


if __name__ == "__main__":
    main()
