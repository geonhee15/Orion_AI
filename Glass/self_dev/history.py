"""개발 이력 관리 - JSON 기반 영구 로그

쓰레드 안전 (threading.Lock), 최대 100개 이력 유지,
저장 실패 시 조용히 처리합니다.
"""

import os
import json
import time
import threading

MAX_ENTRIES = 100


class DevHistory:
    """자가개발 세션 이력을 history.json에 기록 (쓰레드 안전)"""

    def __init__(self, project_root):
        self.history_file = os.path.join(
            project_root, "O1", "self_dev", "history.json"
        )
        self._lock = threading.Lock()
        self.entries = self._load()

    def _load(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    entries = json.load(f)
                if not isinstance(entries, list):
                    return []
                # 오래된 항목 정리
                if len(entries) > MAX_ENTRIES:
                    entries = entries[-MAX_ENTRIES:]
                return entries
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def _save(self):
        """이력 저장 (항상 _lock 안에서 호출)"""
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"[SelfDev:History] Save failed: {e}")

    def log_session(self, session_id, task_title, task_type, summary, status, files_changed):
        """새 세션 기록 추가"""
        with self._lock:
            entry = {
                "session_id": session_id,
                "timestamp": time.time(),
                "task_title": task_title,
                "task_type": task_type,
                "summary": summary,
                "status": status,
                "files_changed": files_changed,
            }
            self.entries.append(entry)
            if len(self.entries) > MAX_ENTRIES:
                self.entries = self.entries[-MAX_ENTRIES:]
            self._save()

    def update_status(self, session_id, new_status):
        """세션 상태 업데이트"""
        with self._lock:
            for entry in self.entries:
                if entry["session_id"] == session_id:
                    entry["status"] = new_status
                    break
            self._save()

    def get_recent(self, n=5):
        """최근 N개 세션 반환"""
        with self._lock:
            return list(self.entries[-n:])

    def get_context_for_planner(self):
        """Planner에게 제공할 이전 작업 요약 (중복 방지용)"""
        with self._lock:
            if not self.entries:
                return "No previous self-development sessions."
            lines = []
            for e in self.entries[-20:]:
                lines.append(f"- [{e['status']}] {e['task_title']} ({e['task_type']})")
            return "\n".join(lines)
