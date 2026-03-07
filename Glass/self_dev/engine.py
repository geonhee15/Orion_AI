"""자가개발 엔진 - 메인 오케스트레이터

핵심 개선:
- 통합 파이프라인 (_execute_development)으로 코드 중복 제거
- threading.Lock으로 진행률 dict 동시 접근 보호
- 검증 실패 시 에러 피드백과 함께 코드 재생성
- 실패 콜백 (_on_dev_failed)으로 사용자 피드백
- _is_user_task 플래그로 idle 복귀 시 사용자 태스크 보호
"""

import os
import json
import time
import threading
from datetime import datetime

from Glass import config
from Glass.self_dev.analyzer import CodeAnalyzer
from Glass.self_dev.planner import TaskPlanner
from Glass.self_dev.coder import CodeGenerator
from Glass.self_dev.validator import ChangeValidator
from Glass.self_dev.staging import StagingManager
from Glass.self_dev.history import DevHistory
from Glass.self_dev.idle_monitor import IdleMonitor


class SelfDevEngine:
    """Orion 자가개발 시스템 메인 오케스트레이터"""

    def __init__(self, project_root):
        self.project_root = project_root

        # 서브 컴포넌트
        self.analyzer = CodeAnalyzer(project_root)
        self.history = DevHistory(project_root)
        self.planner = TaskPlanner(self.analyzer, self.history)
        self.coder = CodeGenerator(self.analyzer)
        self.validator = ChangeValidator(self.analyzer)
        self.staging = StagingManager(project_root)
        self.idle_monitor = IdleMonitor(
            idle_threshold_sec=config.SELF_DEV_IDLE_THRESHOLD_SEC,
            check_interval_sec=config.SELF_DEV_IDLE_CHECK_SEC,
        )

        # 상태
        self.is_developing = False
        self._dev_thread = None
        self._stop_event = threading.Event()
        self._last_api_call_time = 0
        self._is_user_task = False

        # 진행률 (쓰레드 안전)
        self._progress_lock = threading.Lock()
        self._progress = {
            "active": False,
            "task_name": "",
            "step": "",
            "percent": 0,
            "estimated_remaining_sec": 0,
            "start_time": 0,
        }

        # 콜백
        self._on_dev_complete = None
        self._on_dev_failed = None

    def on_dev_complete(self, callback):
        """개발 완료 시 콜백 등록 (OrionO1이 설정)"""
        self._on_dev_complete = callback

    def on_dev_failed(self, callback):
        """개발 실패 시 콜백: callback(error_msg, is_user_task)"""
        self._on_dev_failed = callback

    def start_monitoring(self):
        """idle 모니터링 시작. OrionO1.run()에서 호출."""
        self.idle_monitor.on_idle(self._on_idle)
        self.idle_monitor.on_active(self._on_user_return)
        self.idle_monitor.start()
        self.staging.cleanup_old_sessions(config.SELF_DEV_MAX_AGE_DAYS)
        print("[SelfDev] Idle monitoring started")

    def stop(self):
        """전체 중단"""
        self.idle_monitor.stop()
        self._stop_event.set()

    def record_user_activity(self):
        """사용자 활동 기록 (OrionO1이 호출)"""
        self.idle_monitor.record_activity()

    def has_pending_updates(self):
        """대기 중인 스테이징 세션 목록 반환"""
        return self.staging.get_pending_sessions()

    def has_applied_sessions(self):
        """적용됐지만 커밋 안 된 세션 (크래시 복구용)"""
        return self.staging.get_applied_sessions()

    def apply_update(self, session_id):
        """1차 확인: 변경사항 임시 적용"""
        try:
            return self.staging.apply(session_id)
        except Exception as e:
            print(f"[SelfDev] Apply failed: {e}")
            return False

    def commit_update(self, session_id):
        """2차 확인: 변경사항 영구 커밋"""
        try:
            success = self.staging.commit(session_id)
            if success:
                self.history.update_status(session_id, "committed")
            return success
        except Exception as e:
            print(f"[SelfDev] Commit failed: {e}")
            return False

    def rollback_update(self, session_id):
        """거부: 변경사항 롤백"""
        try:
            success = self.staging.rollback(session_id)
            if success:
                self.history.update_status(session_id, "rolled_back")
            return success
        except Exception as e:
            print(f"[SelfDev] Rollback failed: {e}")
            return False

    def get_session_info(self, session_id):
        """세션 메타데이터 조회"""
        for s in self.staging.get_pending_sessions():
            if s["session_id"] == session_id:
                return s
        for s in self.staging.get_applied_sessions():
            if s["session_id"] == session_id:
                return s
        return None

    # --- 사용자 요청 태스크 ---

    def check_task_request(self):
        """task_request.json 확인. 있으면 dict 반환, 없으면 None."""
        if not os.path.exists(config.TASK_REQUEST_FILE):
            return None
        try:
            with open(config.TASK_REQUEST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("status") == "pending":
                return data
        except (json.JSONDecodeError, IOError):
            pass
        return None

    def start_user_task(self, request):
        """사용자 요청 태스크 즉시 시작 (백그라운드). idle 대기 없이."""
        if self.is_developing:
            print("[SelfDev] Already developing, skipping user task.")
            return
        self._stop_event.clear()
        self._is_user_task = True
        self._dev_thread = threading.Thread(
            target=self._dev_loop_user_task, args=(request,), daemon=True
        )
        self._dev_thread.start()

    def get_progress(self):
        """현재 진행 상태 반환"""
        with self._progress_lock:
            return self._progress.copy()

    def _update_progress(self, step, percent, task_name=None):
        """진행률 업데이트 (쓰레드 안전)"""
        with self._progress_lock:
            if task_name is not None:
                self._progress["task_name"] = task_name
            self._progress["step"] = step
            self._progress["percent"] = percent
            elapsed = time.time() - self._progress["start_time"]
            if percent > 5:
                total_est = elapsed / (percent / 100.0)
                self._progress["estimated_remaining_sec"] = max(0, total_est - elapsed)
            else:
                self._progress["estimated_remaining_sec"] = 120

    # --- 내부 로직 ---

    def _on_idle(self):
        """idle 감지 → 자동 개발 시작"""
        if self.is_developing:
            return
        print("[SelfDev] User idle detected. Starting self-development...")
        self._stop_event.clear()
        self._is_user_task = False
        self._dev_thread = threading.Thread(target=self._dev_loop, daemon=True)
        self._dev_thread.start()

    def _on_user_return(self):
        """사용자 복귀 → 자동 개발만 중단 (사용자 요청 태스크는 유지)"""
        if self.is_developing and not self._is_user_task:
            print("[SelfDev] User returned. Pausing self-development.")
            self._stop_event.set()

    def _notify_failure(self, error_msg):
        """개발 실패 알림"""
        print(f"[SelfDev] FAILED: {error_msg}")
        if self._on_dev_failed:
            try:
                self._on_dev_failed(error_msg, self._is_user_task)
            except Exception:
                pass

    def _dev_loop(self):
        """백그라운드 자동 개발 루프"""
        self.is_developing = True
        with self._progress_lock:
            self._progress["active"] = True
            self._progress["start_time"] = time.time()
        try:
            self._execute_development(focus="auto")
        except Exception as e:
            self._notify_failure(f"Unexpected error: {e}")
        finally:
            with self._progress_lock:
                self._progress["active"] = False
            self.is_developing = False

    def _dev_loop_user_task(self, request):
        """사용자 요청 전용 개발 루프"""
        req_type = request.get("type", "user_feature")
        req_text = request.get("request", "")

        if req_type == "self_improve":
            print("[SelfDev] Self_Improve mode: starting auto development...")
            self._dev_loop()
            return

        self.is_developing = True
        with self._progress_lock:
            self._progress["active"] = True
            self._progress["start_time"] = time.time()
        try:
            self._execute_development(user_request=req_text)
        except Exception as e:
            self._notify_failure(f"Unexpected error: {e}")
        finally:
            with self._progress_lock:
                self._progress["active"] = False
            self.is_developing = False

    def _execute_development(self, focus="auto", user_request=None):
        """통합 개발 파이프라인: 분석 → 계획 → 코딩 → 검증 → 스테이징

        자동 모드와 사용자 요청 모드가 공통 파이프라인을 사용합니다.
        검증 실패 시 에러 피드백과 함께 코드를 재생성합니다.
        """
        task_label = user_request[:30] if user_request else "Auto Improve"

        # === Step 1: 분석 & 태스크 생성 ===
        self._update_progress("analyzing", 5, task_label)
        self._rate_limit_wait()
        if self._stop_event.is_set():
            return

        print("[SelfDev] Analyzing codebase...")
        self._update_progress("planning", 15)

        tasks = self.planner.generate_tasks(
            focus=focus if not user_request else "user",
            user_request=user_request,
        )
        if not tasks:
            self._notify_failure("No tasks could be generated from the request.")
            return

        if self._stop_event.is_set():
            return

        # === Step 2: 태스크 선택 ===
        task = self.planner.get_next_task()
        if not task:
            self._notify_failure("No pending tasks available.")
            return

        self._update_progress("planning", 30, task.title)
        print(f"[SelfDev] Task: {task.title}")
        task.status = "in_progress"

        # === Step 3: 코드 생성 ===
        self._update_progress("coding", 40)
        self._rate_limit_wait()
        if self._stop_event.is_set():
            return

        print("[SelfDev] Generating code...")
        self._update_progress("coding", 55)
        result = self.coder.execute_task(task)

        if result is None:
            task.status = "failed"
            self._notify_failure(f"Code generation failed for: {task.title}")
            return

        if self._stop_event.is_set():
            return

        # === Step 4: 검증 (실패 시 에러 피드백으로 1회 재시도) ===
        self._update_progress("validating", 75)
        print("[SelfDev] Validating changes...")
        ok, errors = self.validator.validate(result)

        if not ok:
            error_msgs = [str(e) for e in errors]
            print(f"[SelfDev] Validation failed: {error_msgs}")

            # 재시도: 에러 피드백과 함께 코드 재생성
            print("[SelfDev] Retrying with error feedback...")
            self._update_progress("coding (retry)", 60)
            self._rate_limit_wait()

            if self._stop_event.is_set():
                return

            result = self.coder.execute_task(task, validation_errors=error_msgs)
            if result is None:
                task.status = "failed"
                self._notify_failure(f"Code retry failed for: {task.title}")
                return

            # 재검증
            self._update_progress("validating (retry)", 80)
            ok, errors = self.validator.validate(result)
            if not ok:
                error_msgs = [str(e) for e in errors]
                task.status = "failed"
                self._notify_failure(
                    f"Validation still failed: {'; '.join(error_msgs[:3])}"
                )
                return

        # === Step 5: 스테이징 ===
        self._update_progress("staging", 90)
        session_id = self.staging.stage(result)
        task.status = "completed"
        self._update_progress("complete", 100)
        print(f"[SelfDev] Complete! Session: {session_id}")
        print(f"[SelfDev] Summary: {result.summary}")

        # === Step 6: 이력 기록 & 알림 ===
        self.history.log_session(
            session_id=session_id,
            task_title=task.title,
            task_type=task.task_type,
            summary=result.summary,
            status="staged",
            files_changed=[c.file_path for c in result.changes],
        )

        # === Step 7: 개발 문서 자동 생성 ===
        self._write_changelog(
            session_id=session_id,
            task=task,
            result=result,
        )

        if self._on_dev_complete:
            self._on_dev_complete(session_id)

    def _write_changelog(self, session_id, task, result):
        """세션 완료 시 CHANGELOG.md에 자동 기록"""
        changelog_path = os.path.join(
            self.project_root, "O1", "self_dev", "CHANGELOG.md"
        )
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            files_list = "\n".join(
                f"  - `{c.file_path}` — {c.change_description}"
                for c in result.changes
            )

            entry = (
                f"\n## [{session_id}] {task.title}\n"
                f"- **날짜**: {now}\n"
                f"- **타입**: {task.task_type}\n"
                f"- **요약**: {result.summary}\n"
                f"- **변경 파일**:\n{files_list}\n"
                f"---\n"
            )

            # 헤더가 없으면 생성
            if not os.path.exists(changelog_path):
                with open(changelog_path, "w", encoding="utf-8") as f:
                    f.write("# Orion Self-Dev Changelog\n\n자가개발 시스템이 자동 생성한 개발 기록입니다.\n\n---\n")

            with open(changelog_path, "a", encoding="utf-8") as f:
                f.write(entry)

            print(f"[SelfDev] Changelog updated: {session_id}")
        except Exception as e:
            print(f"[SelfDev] Changelog write failed: {e}")

    def _rate_limit_wait(self):
        """API 호출 간 최소 간격 보장"""
        elapsed = time.time() - self._last_api_call_time
        if elapsed < config.SELF_DEV_API_MIN_INTERVAL_SEC:
            time.sleep(config.SELF_DEV_API_MIN_INTERVAL_SEC - elapsed)
        self._last_api_call_time = time.time()
