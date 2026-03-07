"""Workspace 전체화면 윈도우 — GIF 비주얼라이저 + 실시간 오디오 반응

중앙에 Orion Visualizer GIF 표시.
TTS 오디오의 실제 amplitude 레벨에 따라 GIF가 실시간으로 커졌다 작아졌다 함.

스레드 안전: TTS 백그라운드 스레드가 공유 변수에 쓰고,
메인 스레드의 QTimer가 그 값을 폴링해서 UI 업데이트.
"""

import sys
import os
from datetime import datetime, timezone, timedelta
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QMovie, QKeyEvent, QImage, QPixmap

from Workspace import config


class GifVisualizer(QLabel):
    """중앙 GIF 비주얼라이저 — 실시간 오디오 레벨 반응"""

    def __init__(self, gif_path, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 공유 amplitude 값 (TTS 스레드가 쓰고, UI 타이머가 읽음)
        self.amplitude = 0.0

        # GIF 로드
        self._movie = QMovie(gif_path)
        if not self._movie.isValid():
            self.setText("GIF 로드 실패")
            self.setStyleSheet("color: red; font-size: 20px;")
            self._base_w = 0
            self._base_h = 0
            return

        # 원본 비율 계산
        self._movie.jumpToFrame(0)
        orig = self._movie.currentImage().size()
        orig_w = orig.width()
        orig_h = orig.height()
        aspect = orig_w / orig_h  # 800/600 = 1.333

        # 기본 크기: 높이 기준으로 비율 유지
        self._base_h = config.VISUALIZER_BASE_SIZE
        self._base_w = int(self._base_h * aspect)

        # 스케일
        self._current_scale = 1.0
        self._max_extra_scale = config.VISUALIZER_ACTIVE_SCALE - 1.0  # 0.4

        # 초기 크기 적용
        self._movie.setScaledSize(QSize(self._base_w, self._base_h))
        self.setMovie(self._movie)
        self._movie.start()

        # 애니메이션 타이머 (~60fps, 메인 스레드에서 실행)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._animate_step)
        self._anim_timer.start()

        # lerp 속도 — 올라갈 때 빠르게, 내려갈 때 부드럽게
        self._lerp_up = 0.25
        self._lerp_down = 0.08

    def _animate_step(self):
        """프레임별: 공유 amplitude → 목표 스케일 → lerp → 적용"""
        # 공유 변수에서 amplitude 읽기 (Python float read는 atomic)
        target_scale = 1.0 + self.amplitude * self._max_extra_scale

        diff = target_scale - self._current_scale
        if abs(diff) < 0.002:
            self._current_scale = target_scale
        elif diff > 0:
            self._current_scale += diff * self._lerp_up
        else:
            self._current_scale += diff * self._lerp_down

        self._apply_scale()

    def _apply_scale(self):
        """현재 스케일에 맞게 GIF 크기 업데이트 (비율 유지)"""
        if not self._movie or not self._movie.isValid():
            return
        new_w = int(self._base_w * self._current_scale)
        new_h = int(self._base_h * self._current_scale)
        self._movie.setScaledSize(QSize(new_w, new_h))


class WorkspaceWindow(QMainWindow):
    """전체화면 Workspace 윈도우"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Orion Workspace")

        # 완전 검정 배경
        self.setStyleSheet("background-color: #000000;")

        # 중앙 위젯
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(0, 40, 0, 0)

        # 시계 (상단 가운데, 한국 시간 KST)
        self.clock_label = QLabel("")
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock_label.setStyleSheet(
            "color: #00C8FF; font-size: 36px; font-weight: 300; "
            "font-family: 'SF Mono', 'Menlo', monospace; "
            "background: transparent; padding-bottom: 10px;"
        )
        layout.addWidget(self.clock_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._kst = timezone(timedelta(hours=9))
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)  # 1초
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

        # GIF 비주얼라이저 — stretch로 남은 공간 전부 차지 (텍스트에 밀리지 않음)
        gif_path = config.VISUALIZER_GIF
        self.visualizer = GifVisualizer(gif_path)
        self.visualizer.setMinimumHeight(config.VISUALIZER_BASE_SIZE)
        layout.addWidget(self.visualizer, stretch=1, alignment=Qt.AlignmentFlag.AlignCenter)

        # 상태 텍스트 (하단) — 고정 높이, 자동 줄바꿈, 최대 너비 제한
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setMaximumWidth(900)
        self.status_label.setMinimumHeight(60)
        self.status_label.setStyleSheet(
            "color: #00C8FF; font-size: 14px; font-family: 'SF Mono', 'Menlo', monospace; "
            "padding: 6px 20px; background: transparent;"
        )
        layout.addWidget(self.status_label, stretch=0, alignment=Qt.AlignmentFlag.AlignCenter)

        # ─── 하단 영역: Update Input (왼쪽) + 웹캠 미리보기 (오른쪽) ───
        bottom_bar = QWidget()
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)

        # — 왼쪽: Update Input —
        input_container = QWidget()
        input_vlayout = QVBoxLayout(input_container)
        input_vlayout.setContentsMargins(30, 0, 0, 30)
        input_vlayout.setSpacing(4)
        input_vlayout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

        input_label = QLabel("Update Input")
        input_label.setStyleSheet(
            "color: #00C8FF; font-size: 12px; font-family: 'SF Mono', 'Menlo', monospace; "
            "background: transparent;"
        )
        input_vlayout.addWidget(input_label)

        self.update_input = QLineEdit()
        self.update_input.setPlaceholderText("Type info to remember...")
        self.update_input.setFixedWidth(400)
        self.update_input.setFixedHeight(36)
        self.update_input.setStyleSheet(
            "QLineEdit {"
            "  color: #FFFFFF; background-color: #1A1A2E; border: 1px solid #00C8FF;"
            "  border-radius: 6px; padding: 4px 10px;"
            "  font-size: 14px; font-family: 'SF Mono', 'Menlo', monospace;"
            "}"
            "QLineEdit:focus { border: 1px solid #00FF96; }"
            "QLineEdit::placeholder { color: #555555; }"
        )
        self.update_input.returnPressed.connect(self._on_update_submit)
        input_vlayout.addWidget(self.update_input)

        bottom_layout.addWidget(input_container, stretch=1, alignment=Qt.AlignmentFlag.AlignLeft)

        # — 오른쪽: 웹캠 미리보기 —
        cam_container = QWidget()
        cam_vlayout = QVBoxLayout(cam_container)
        cam_vlayout.setContentsMargins(0, 0, 30, 30)
        cam_vlayout.setSpacing(4)
        cam_vlayout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        cam_label = QLabel("Webcam")
        cam_label.setStyleSheet(
            "color: #00C8FF; font-size: 12px; font-family: 'SF Mono', 'Menlo', monospace; "
            "background: transparent;"
        )
        cam_vlayout.addWidget(cam_label, alignment=Qt.AlignmentFlag.AlignRight)

        self.cam_preview = QLabel()
        self.cam_preview.setFixedSize(240, 180)
        self.cam_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cam_preview.setStyleSheet(
            "background-color: #0A0A14; border: 1px solid #00C8FF; border-radius: 6px;"
        )
        self.cam_preview.setText("No Camera")
        self.cam_preview.setStyleSheet(
            self.cam_preview.styleSheet() +
            " color: #555555; font-size: 12px; font-family: 'SF Mono', 'Menlo', monospace;"
        )
        cam_vlayout.addWidget(self.cam_preview, alignment=Qt.AlignmentFlag.AlignRight)

        bottom_layout.addWidget(cam_container, stretch=0, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addWidget(bottom_bar, stretch=0)

        # 콜백 (main.py에서 설정)
        self.on_profile_update = None

        # 웹캠 프레임 콜백 (main.py에서 설정)
        self._webcam_capture = None  # WebcamCapture 인스턴스

        # 웹캠 미리보기 타이머 (~15fps)
        self._cam_timer = QTimer(self)
        self._cam_timer.setInterval(66)
        self._cam_timer.timeout.connect(self._poll_cam)
        self._cam_timer.start()

        # 상태 텍스트 폴링 (스레드 안전)
        self._pending_status = None
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(100)  # 10fps
        self._status_timer.timeout.connect(self._poll_status)
        self._status_timer.start()

    def _poll_status(self):
        """메인 스레드에서 대기 중인 상태 텍스트 적용"""
        if self._pending_status is not None:
            self.status_label.setText(self._pending_status)
            self._pending_status = None

    def _poll_cam(self):
        """웹캠 프레임 폴링 → 미리보기 업데이트 (메인 스레드)"""
        if self._webcam_capture is None:
            return
        frame_rgb = self._webcam_capture.get_frame_rgb()
        if frame_rgb is None:
            return
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self.cam_preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.cam_preview.setPixmap(pixmap)

    def set_webcam(self, webcam_capture):
        """웹캠 캡처 인스턴스 연결"""
        self._webcam_capture = webcam_capture

    def _update_clock(self):
        """한국 시간(KST) 시계 업데이트"""
        now = datetime.now(self._kst)
        self.clock_label.setText(now.strftime("%I:%M:%S %p"))

    def showEvent(self, event):
        """윈도우 표시 시 전체화면"""
        super().showEvent(event)
        self.showFullScreen()

    def keyPressEvent(self, event: QKeyEvent):
        """ESC로 종료"""
        if event.key() == Qt.Key.Key_Escape:
            QApplication.quit()
        super().keyPressEvent(event)

    def _on_update_submit(self):
        """Enter 키 → 프로필 업데이트 요청"""
        text = self.update_input.text().strip()
        if not text:
            return
        self.update_input.clear()
        if self.on_profile_update:
            import threading
            threading.Thread(target=self.on_profile_update, args=(text,), daemon=True).start()

    def set_status(self, text):
        """상태 텍스트 변경 (스레드 안전 — 폴링으로 적용)"""
        self._pending_status = text

    def set_amplitude(self, value):
        """오디오 amplitude 설정 (스레드 안전 — float write는 atomic)"""
        self.visualizer.amplitude = value
