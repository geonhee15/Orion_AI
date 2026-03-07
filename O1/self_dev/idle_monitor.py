"""Idle 감지기 - 사용자 비활성 시 자가개발 트리거"""

import time
import threading


class IdleMonitor:
    """사용자 활동을 추적하고 idle 상태에서 콜백 실행"""

    def __init__(self, idle_threshold_sec=300, check_interval_sec=30):
        self.idle_threshold_sec = idle_threshold_sec
        self.check_interval_sec = check_interval_sec
        self.last_activity_time = time.time()
        self._on_idle_callback = None
        self._on_active_callback = None
        self._is_idle = False
        self._running = False
        self._thread = None

    def record_activity(self):
        """사용자 활동 기록 (wake word 감지/명령 처리 시 호출)"""
        self.last_activity_time = time.time()
        if self._is_idle:
            self._is_idle = False
            if self._on_active_callback:
                self._on_active_callback()

    def on_idle(self, callback):
        """idle 상태 진입 시 콜백 등록"""
        self._on_idle_callback = callback

    def on_active(self, callback):
        """활성 상태 복귀 시 콜백 등록"""
        self._on_active_callback = callback

    def start(self):
        """백그라운드 스레드로 모니터링 시작"""
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """모니터링 중단"""
        self._running = False

    def _monitor_loop(self):
        """주기적으로 idle 상태 체크"""
        while self._running:
            elapsed = time.time() - self.last_activity_time
            if not self._is_idle and elapsed >= self.idle_threshold_sec:
                self._is_idle = True
                if self._on_idle_callback:
                    try:
                        self._on_idle_callback()
                    except Exception as e:
                        print(f"[IdleMonitor] Callback error: {e}")
            time.sleep(self.check_interval_sec)
