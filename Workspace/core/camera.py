"""웹캠 캡처 모듈 — 실시간 프레임 제공 + 스냅샷

백그라운드 스레드에서 웹캠 프레임을 연속 캡처.
UI에서 실시간 미리보기 + 비전 분석용 스냅샷 제공.
"""

import threading
import time
import cv2
import numpy as np


class WebcamCapture:
    """웹캠 연속 캡처 — 최신 프레임 항상 보유"""

    def __init__(self, camera_index=0, fps=15):
        self.camera_index = camera_index
        self.fps = fps
        self._cap = None
        self._running = False
        self._frame = None          # 최신 프레임 (numpy BGR)
        self._jpeg_bytes = None     # 최신 JPEG 바이트
        self._lock = threading.Lock()

    def start(self):
        """캡처 시작"""
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            print("⚠️ 웹캠 열기 실패")
            self._cap = None
            return False

        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"📷 웹캠 시작: index={self.camera_index}, {w}x{h} @ {self.fps}fps")

        self._running = True
        threading.Thread(target=self._capture_loop, daemon=True).start()
        return True

    def stop(self):
        """캡처 중지"""
        self._running = False
        if self._cap:
            self._cap.release()
            self._cap = None
        print("📷 웹캠 중지")

    @property
    def available(self):
        return self._cap is not None and self._running

    def get_frame_rgb(self):
        """최신 프레임 (RGB numpy array) — UI 표시용"""
        with self._lock:
            if self._frame is None:
                return None
            return cv2.cvtColor(self._frame, cv2.COLOR_BGR2RGB)

    def get_frame_bgr(self):
        """최신 프레임 (BGR numpy array) — CV 처리용"""
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def get_snapshot_jpeg(self):
        """최신 프레임 JPEG 바이트 — 비전 분석용"""
        with self._lock:
            return self._jpeg_bytes

    def _capture_loop(self):
        """백그라운드 캡처 루프"""
        interval = 1.0 / self.fps
        while self._running and self._cap and self._cap.isOpened():
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])

            with self._lock:
                self._frame = frame
                self._jpeg_bytes = jpeg.tobytes()

            time.sleep(interval)
