"""스테이징 매니저 - 파일 백업/적용/롤백/커밋

git add/commit 결과 검증, 백업 복사 에러 처리,
정확한 에러 메시지 출력을 포함합니다.
"""

import os
import json
import shutil
import subprocess
import time


class StagingManager:
    """변경사항의 안전한 스테이징, 적용, 롤백, git 커밋 관리"""

    def __init__(self, project_root):
        self.project_root = project_root
        self.staging_dir = os.path.join(project_root, "O1", "self_dev", "staging")
        self.backup_dir = os.path.join(project_root, "O1", "self_dev", "backups")
        os.makedirs(self.staging_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)

    def stage(self, result):
        """변경사항을 스테이징 디렉토리에 저장. session_id 반환."""
        session_id = f"dev_{int(time.time())}"
        session_dir = os.path.join(self.staging_dir, session_id)
        os.makedirs(session_dir)

        metadata = {
            "session_id": session_id,
            "timestamp": time.time(),
            "task_title": result.task.title,
            "task_type": result.task.task_type,
            "summary": result.summary,
            "demo_script": result.demo_script,
            "status": "staged",
            "changes": [],
        }

        for change in result.changes:
            staged_name = change.file_path.replace("/", "__")
            staged_path = os.path.join(session_dir, staged_name)
            with open(staged_path, "w", encoding="utf-8") as f:
                f.write(change.new_content)

            metadata["changes"].append({
                "file_path": change.file_path,
                "action": change.action,
                "staged_filename": staged_name,
                "description": change.change_description,
            })

        with open(os.path.join(session_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return session_id

    def get_pending_sessions(self):
        """status='staged'인 세션 목록 반환"""
        return self._get_sessions_by_status("staged")

    def get_applied_sessions(self):
        """status='applied'인 세션 목록 반환 (크래시 복구용)"""
        return self._get_sessions_by_status("applied")

    def _get_sessions_by_status(self, status):
        """특정 상태의 세션 목록"""
        sessions = []
        if not os.path.exists(self.staging_dir):
            return sessions
        for name in sorted(os.listdir(self.staging_dir)):
            meta_path = os.path.join(self.staging_dir, name, "metadata.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    if meta.get("status") == status:
                        sessions.append(meta)
                except (json.JSONDecodeError, IOError):
                    continue
        return sessions

    def apply(self, session_id):
        """스테이징된 변경사항을 소스에 적용. 원본은 백업."""
        session_dir = os.path.join(self.staging_dir, session_id)
        meta_path = os.path.join(session_dir, "metadata.json")

        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # 백업 디렉토리 생성
        backup_session = os.path.join(self.backup_dir, session_id)
        os.makedirs(backup_session, exist_ok=True)

        for change_info in metadata["changes"]:
            file_path = change_info["file_path"]
            full_path = os.path.join(self.project_root, file_path)

            # 원본 백업
            if os.path.exists(full_path):
                try:
                    backup_name = file_path.replace("/", "__")
                    shutil.copy2(full_path, os.path.join(backup_session, backup_name))
                except OSError as e:
                    print(f"[SelfDev:Staging] Backup failed for {file_path}: {e}")
                    return False

            # 변경사항 적용
            if change_info["action"] == "delete":
                if os.path.exists(full_path):
                    os.remove(full_path)
            else:
                staged_file = os.path.join(session_dir, change_info["staged_filename"])
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                shutil.copy2(staged_file, full_path)

        # 상태 업데이트
        metadata["status"] = "applied"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return True

    def rollback(self, session_id):
        """백업에서 원본 복원"""
        session_dir = os.path.join(self.staging_dir, session_id)
        backup_session = os.path.join(self.backup_dir, session_id)
        meta_path = os.path.join(session_dir, "metadata.json")

        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        for change_info in metadata["changes"]:
            file_path = change_info["file_path"]
            full_path = os.path.join(self.project_root, file_path)
            backup_name = file_path.replace("/", "__")
            backup_path = os.path.join(backup_session, backup_name)

            if change_info["action"] == "create":
                if os.path.exists(full_path):
                    os.remove(full_path)
            elif os.path.exists(backup_path):
                shutil.copy2(backup_path, full_path)

        # 상태 업데이트
        metadata["status"] = "rolled_back"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return True

    def commit(self, session_id):
        """적용된 변경사항을 git commit"""
        session_dir = os.path.join(self.staging_dir, session_id)
        meta_path = os.path.join(session_dir, "metadata.json")

        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # git add (개별 파일, 결과 검증)
        for change_info in metadata["changes"]:
            full_path = os.path.join(self.project_root, change_info["file_path"])
            result = subprocess.run(
                ["git", "add", full_path],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"[SelfDev:Staging] git add failed for {change_info['file_path']}: {result.stderr}")
                return False

        # git commit
        commit_msg = (
            f"[Orion Self-Dev] {metadata['task_title']}\n\n"
            f"{metadata['summary']}\n\n"
            f"Type: {metadata['task_type']}\n"
            f"Session: {session_id}"
        )
        result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=self.project_root,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            metadata["status"] = "committed"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            # 백업 정리
            backup_session = os.path.join(self.backup_dir, session_id)
            if os.path.exists(backup_session):
                shutil.rmtree(backup_session)
            return True
        else:
            print(f"[SelfDev:Staging] Git commit failed: {result.stderr}")
            return False

    def cleanup_old_sessions(self, max_age_days=7):
        """오래된 세션 자동 정리"""
        cutoff = time.time() - (max_age_days * 86400)
        for base_dir in [self.staging_dir, self.backup_dir]:
            if not os.path.exists(base_dir):
                continue
            for name in os.listdir(base_dir):
                path = os.path.join(base_dir, name)
                try:
                    if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                        shutil.rmtree(path)
                except OSError:
                    continue
