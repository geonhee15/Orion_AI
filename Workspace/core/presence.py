"""웹캠 기반 인체 감지 — Haar cascade 얼굴 검출 + 상태 머신

ABSENT -> PRESENT 전환 시 on_user_arrived 콜백 호출 (웰컴 인사).
백그라운드 데몬 스레드에서 주기적 검사.
"""

import threading
import time
import cv2

from Workspace import config


class PresenceDetector:
    """웹캠 프레임에서 얼굴 검출 -> 사용자 존재 상태 추적"""

    STATE_ABSENT = "absent"
    STATE_PRESENT = "present"

    def __init__(self, camera, on_user_arrived=None):
        self.camera = camera
        self.on_user_arrived = on_user_arrived

        # Haar cascade 로드 (OpenCV 번들 XML)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(cascade_path)

        # 상태 머신
        self._state = self.STATE_ABSENT
        self._consec_detections = 0
        self._consec_absences = 0
        self._last_greeted_time = 0.0

        self._running = False

    def start(self):
        """백그라운드 감지 루프 시작"""
        if self._running:
            return
        self._running = True
        # 시작 직후 인사 방지 (시작 인사와 중복 방지)
        self._last_greeted_time = time.time()
        threading.Thread(target=self._detection_loop, daemon=True).start()
        print("[Presence] 감지 시작")

    def stop(self):
        """감지 루프 정지"""
        self._running = False
        print("[Presence] 감지 중지")

    @property
    def state(self):
        return self._state

    def _detect_face(self, frame_bgr):
        """BGR 프레임에서 얼굴 검출 -> bool"""
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
        faces = self._cascade.detectMultiScale(
            small,
            scaleFactor=1.3,
            minNeighbors=5,
            minSize=(80, 80),
        )
        return len(faces) > 0

    def _detection_loop(self):
        """메인 감지 루프"""
        while self._running:
            try:
                self._tick()
            except Exception as e:
                print(f"[Presence] 오류: {e}")
            time.sleep(config.PRESENCE_CHECK_INTERVAL)

    def _tick(self):
        """단일 감지 사이클 — 상태 머신 업데이트"""
        frame = self.camera.get_frame_bgr()
        if frame is None:
            return

        face_found = self._detect_face(frame)

        if self._state == self.STATE_ABSENT:
            if face_found:
                self._consec_detections += 1
                self._consec_absences = 0
                if self._consec_detections >= config.PRESENCE_CONFIRM_FRAMES:
                    self._transition_to_present()
            else:
                self._consec_detections = 0

        else:  # STATE_PRESENT
            if not face_found:
                self._consec_absences += 1
                self._consec_detections = 0
                if self._consec_absences >= config.PRESENCE_ABSENCE_FRAMES:
                    self._transition_to_absent()
            else:
                self._consec_absences = 0

    def _transition_to_present(self):
        self._state = self.STATE_PRESENT
        self._consec_detections = 0
        print("[Presence] 사용자 감지됨")

        now = time.time()
        since_last = now - self._last_greeted_time
        if since_last >= config.PRESENCE_COOLDOWN_SEC and self.on_user_arrived:
            self._last_greeted_time = now
            threading.Thread(target=self.on_user_arrived, daemon=True).start()
        else:
            print(f"[Presence] 쿨다운 중 ({config.PRESENCE_COOLDOWN_SEC - since_last:.0f}초 남음)")

    def _transition_to_absent(self):
        self._state = self.STATE_ABSENT
        self._consec_absences = 0
        print("[Presence] 사용자 없음")
