"""
EDITH HUD 데스크톱 테스트 클라이언트
====================================
실행: python -m O1.client.test_hud

240x240 투명 오버레이로 글래스 HUD를 맥북 화면에서 시뮬레이션.
서버(O1.main)가 실행 중이어야 합니다.
"""

import sys
import os
import json
import time
import asyncio
import threading
import random
from io import BytesIO

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QFrame, QPushButton,
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QGroupBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QImage, QPixmap

from O1 import config

try:
    import websockets
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False


def _save_task_request(text):
    """입력된 기능 요청을 task_request.json에 저장"""
    req_type = "self_improve" if text.strip().lower() == "self_improve" else "user_feature"
    data = {
        "request": text.strip(),
        "type": req_type,
        "timestamp": time.time(),
        "status": "pending",
    }
    os.makedirs(os.path.dirname(config.TASK_REQUEST_FILE), exist_ok=True)
    with open(config.TASK_REQUEST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# 추천 기능 풀 (매번 랜덤 3개 표시)
_FEATURE_POOL = [
    # 생산성
    "화면 캡처 → AI 요약 (스크린샷 분석)",
    "실시간 번역 모드 (한↔영 동시통역)",
    "음성 메모 → 자동 정리 & 노션 저장",
    "포모도로 타이머 + 집중도 추적",
    "이메일 요약 & 자동 답장 초안",
    "코드 리뷰 음성 요청 (파일 지정해서 리뷰)",

    # 스마트 라이프
    "음성으로 스마트홈 기기 제어 (HomeKit)",
    "날씨 기반 옷차림 추천",
    "근처 맛집 추천 (현재 위치 기반)",
    "운동 루틴 생성 & 타이머",
    "수면 패턴 분석 & 알람 최적화",
    "실시간 환율/주식 알림",

    # AI 비서
    "대화 내용 자동 요약 & 저장",
    "YouTube 영상 요약 (링크만 주면)",
    "PDF/논문 읽어주기 & 요약",
    "뉴스 브리핑 (관심 분야 맞춤)",
    "일기 자동 생성 (오늘 한 일 기반)",
    "학습 플래시카드 자동 생성",

    # 재미/유틸
    "AI 음성 변조 (다른 목소리로 말하기)",
    "랜덤 퀴즈/퀴즈쇼 모드",
    "음악 분위기 자동 감지 & 추천",
    "사진 찍으면 물체 인식 & 설명",
    "손글씨 인식 → 텍스트 변환",
    "실시간 자막 생성 (회의/강의용)",
]


def _pick_suggestions():
    """매번 랜덤 3개 추천 기능 선택"""
    return random.sample(_FEATURE_POOL, 3)


class FeatureRequestDialog(QDialog):
    """추천기능 3개 + 직접 입력창이 있는 커스텀 다이얼로그"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Orion Feature Request")
        self.setFixedWidth(380)
        self.selected_text = ""

        self.setStyleSheet(
            "QDialog { background-color: #1a1a2e; }"
            "QLabel { color: #e0e0e0; }"
            "QGroupBox { color: #00c8ff; border: 1px solid #00c8ff40; border-radius: 6px; "
            "  margin-top: 8px; padding-top: 14px; font-weight: bold; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
            "QPushButton { background-color: #0d1b2a; color: #00c8ff; border: 1px solid #00c8ff60; "
            "  border-radius: 6px; padding: 10px; text-align: left; font-size: 13px; }"
            "QPushButton:hover { background-color: #1b2838; border-color: #00c8ff; }"
            "QLineEdit { background-color: #0d1b2a; color: #e0e0e0; border: 1px solid #00c8ff60; "
            "  border-radius: 6px; padding: 10px; font-size: 13px; }"
            "QLineEdit:focus { border-color: #00c8ff; }"
        )

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        # 추천 기능 그룹
        suggest_group = QGroupBox("추천 기능")
        suggest_layout = QVBoxLayout(suggest_group)
        suggest_layout.setSpacing(6)

        self._suggest_buttons = []
        for feat in _pick_suggestions():
            btn = QPushButton(f"  {feat}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, t=feat: self._select_suggestion(t))
            suggest_layout.addWidget(btn)
            self._suggest_buttons.append(btn)

        main_layout.addWidget(suggest_group)

        # 직접 입력 그룹
        custom_group = QGroupBox("직접 입력")
        custom_layout = QVBoxLayout(custom_group)

        self._input = QLineEdit()
        self._input.setPlaceholderText("원하는 기능을 입력하세요 (Self_Improve = 자동 모드)")
        self._input.returnPressed.connect(self._submit_custom)
        custom_layout.addWidget(self._input)

        submit_btn = QPushButton("요청하기")
        submit_btn.setStyleSheet(
            "QPushButton { background-color: #00c8ff30; color: #00c8ff; font-weight: bold; text-align: center; }"
            "QPushButton:hover { background-color: #00c8ff50; }"
        )
        submit_btn.clicked.connect(self._submit_custom)
        custom_layout.addWidget(submit_btn)

        main_layout.addWidget(custom_group)

        # 종료만 (기능 요청 없이)
        skip_btn = QPushButton("요청 없이 종료")
        skip_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #666; border: 1px solid #333; text-align: center; }"
            "QPushButton:hover { color: #999; border-color: #666; }"
        )
        skip_btn.clicked.connect(self.reject)
        main_layout.addWidget(skip_btn)

    def _select_suggestion(self, text):
        self.selected_text = text
        self.accept()

    def _submit_custom(self):
        text = self._input.text().strip()
        if text:
            self.selected_text = text
            self.accept()

    def get_request_text(self):
        return self.selected_text


class Signals(QObject):
    frame_received = pyqtSignal(bytes)
    notification_received = pyqtSignal(str)


class HUDTestClient(QMainWindow):
    """240x240 투명 HUD 오버레이 (글래스 시뮬레이션)"""

    def __init__(self):
        super().__init__()

        # 프레임리스, 투명, 항상 최상단
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(260, 260)

        # 화면 우상단에 배치
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 280, 20)

        # 컨테이너 (약간 투명한 검정 배경)
        self.container = QFrame(self)
        self.container.setStyleSheet(
            "background-color: rgba(0, 0, 0, 200); border: 1px solid rgba(0, 200, 255, 80); border-radius: 10px;"
        )
        self.container.setFixedSize(260, 260)

        # HUD 이미지 라벨
        self.image_label = QLabel(self.container)
        self.image_label.setFixedSize(240, 240)
        self.image_label.move(10, 10)
        self.image_label.setStyleSheet("background: black; border-radius: 5px;")

        # X 버튼 (왼쪽 상단)
        self.close_btn = QPushButton("X", self.container)
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.move(12, 12)
        self.close_btn.setStyleSheet(
            "QPushButton { background-color: rgba(255, 60, 60, 150); color: white; "
            "border: none; border-radius: 5px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background-color: rgba(255, 60, 60, 220); }"
        )
        self.close_btn.clicked.connect(self._on_close_clicked)
        self.close_btn.raise_()

        self.setCentralWidget(self.container)

        # 시그널
        self.signals = Signals()
        self.signals.frame_received.connect(self._update_frame)
        self.signals.notification_received.connect(self._show_notification)

        # WebSocket 연결
        self.ws = None
        self._ws_ref = None  # WebSocket 참조 (shutdown 전송용)
        if WS_AVAILABLE:
            self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
            self._ws_thread.start()
        else:
            print("⚠️ websockets 패키지 없음. pip install websockets")

        # 드래그 지원
        self._drag_pos = None

    def _on_close_clicked(self):
        """X 버튼 클릭 → 추천기능 다이얼로그 → 종료"""
        dlg = FeatureRequestDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            text = dlg.get_request_text()
            if text:
                _save_task_request(text)
                print(f"📝 Task request 저장: {text}")
                # WebSocket으로 shutdown 전송
                if self._ws_ref:
                    try:
                        asyncio.run_coroutine_threadsafe(
                            self._ws_ref.send(json.dumps({"type": "shutdown"})),
                            self._ws_loop_ref,
                        )
                    except Exception:
                        pass
        QApplication.quit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def _ws_loop(self):
        """WebSocket 연결 루프"""
        self._ws_loop_ref = asyncio.new_event_loop()
        asyncio.set_event_loop(self._ws_loop_ref)
        self._ws_loop_ref.run_until_complete(self._ws_connect())

    async def _ws_connect(self):
        uri = "ws://localhost:8000/ws/test"
        print(f"🔌 서버 연결 중... ({uri})")

        while True:
            try:
                async with websockets.connect(uri) as ws:
                    self._ws_ref = ws
                    print("✅ 서버 연결됨!")
                    while True:
                        data = await ws.recv()
                        if isinstance(data, bytes):
                            self.signals.frame_received.emit(data)
                        elif isinstance(data, str):
                            try:
                                msg = json.loads(data)
                                if msg.get("type") == "notification":
                                    self.signals.notification_received.emit(msg["text"])
                            except json.JSONDecodeError:
                                pass
            except Exception as e:
                self._ws_ref = None
                print(f"⚠️ 연결 실패: {e}, 3초 후 재시도...")
                await asyncio.sleep(3)

    def _update_frame(self, png_data: bytes):
        """수신된 PNG 프레임을 표시"""
        img = QImage.fromData(png_data)
        if not img.isNull():
            self.image_label.setPixmap(
                QPixmap.fromImage(img).scaled(
                    240, 240,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _show_notification(self, text: str):
        print(f"📢 알림: {text}")


class StandaloneHUD(QMainWindow):
    """서버 없이 로컬에서 HUD를 직접 렌더링하는 모드"""

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(260, 260)

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 280, 20)

        self.container = QFrame(self)
        self.container.setStyleSheet(
            "background-color: rgba(0, 0, 0, 200); border: 1px solid rgba(0, 200, 255, 80); border-radius: 10px;"
        )
        self.container.setFixedSize(260, 260)

        self.image_label = QLabel(self.container)
        self.image_label.setFixedSize(240, 240)
        self.image_label.move(10, 10)
        self.image_label.setStyleSheet("background: black; border-radius: 5px;")

        # X 버튼 (왼쪽 상단)
        self.close_btn = QPushButton("X", self.container)
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.move(12, 12)
        self.close_btn.setStyleSheet(
            "QPushButton { background-color: rgba(255, 60, 60, 150); color: white; "
            "border: none; border-radius: 5px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background-color: rgba(255, 60, 60, 220); }"
        )
        self.close_btn.clicked.connect(self._on_close_clicked)
        self.close_btn.raise_()

        self.setCentralWidget(self.container)

        # HUD 렌더러
        from O1.hud.renderer import HUDRenderer
        self.hud = HUDRenderer()
        self.state = {
            "ai_response": "",
            "notification": "",
            "listening": False,
            "thinking": False,
            "weather": "3°C Cloudy",
            "next_event": "Math Class 2:30 PM",
        }

        # 업데이트 타이머
        self.timer = QTimer()
        self.timer.timeout.connect(self._render)
        self.timer.start(100)  # 10 FPS

        # 드래그 지원
        self._drag_pos = None

    def _on_close_clicked(self):
        """X 버튼 클릭 → 추천기능 다이얼로그 → 종료"""
        dlg = FeatureRequestDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            text = dlg.get_request_text()
            if text:
                _save_task_request(text)
                print(f"📝 Task request 저장: {text}")
        QApplication.quit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def _render(self):
        png_data = self.hud.render_png(self.state)
        img = QImage.fromData(png_data)
        if not img.isNull():
            self.image_label.setPixmap(QPixmap.fromImage(img))


def main():
    app = QApplication(sys.argv)

    # 서버 모드 or 스탠드얼론 모드
    if "--standalone" in sys.argv:
        print("🕶️ EDITH HUD 테스트 (스탠드얼론 모드)")
        print("   서버 없이 로컬 렌더링")
        window = StandaloneHUD()
    else:
        print("🕶️ EDITH HUD 테스트 클라이언트")
        print("   서버에 연결해서 HUD 수신")
        window = HUDTestClient()

    window.show()
    print("✅ HUD 오버레이 표시됨 (드래그로 이동 가능, X로 종료)")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
