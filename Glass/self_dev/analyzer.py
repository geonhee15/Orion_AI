"""코드베이스 분석기 - 소스 파일 읽기/구조화"""

import os
import ast


PROTECTED_FILES = {".env", "credentials.json", "token.json", "user_profile.txt"}
PROTECTED_DIRS = {"self_dev/staging", "self_dev/backups", "venv", "__pycache__", ".git", "firmware"}
MAX_FILE_SIZE = 100_000  # 100KB


class CodeAnalyzer:
    """Orion 코드베이스를 읽고 Claude에게 전달할 형태로 구조화"""

    def __init__(self, project_root):
        self.project_root = project_root
        self.o1_root = os.path.join(project_root, "O1")

    def get_file_tree(self):
        """O1/ 디렉토리의 파일 트리 + 줄 수 반환"""
        lines = []
        for root, dirs, files in os.walk(self.o1_root):
            dirs[:] = [d for d in dirs if not self._is_protected_dir(
                os.path.relpath(os.path.join(root, d), self.project_root)
            )]
            for f in sorted(files):
                if not f.endswith(".py"):
                    continue
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, self.project_root)
                content = self._safe_read(full_path)
                if content is not None:
                    line_count = content.count("\n") + (
                        1 if content and not content.endswith("\n") else 0
                    )
                    lines.append(f"  {rel_path} ({line_count} lines)")
                else:
                    lines.append(f"  {rel_path} (binary/unreadable)")
        return "\n".join(lines)

    def read_file(self, relative_path):
        """안전하게 파일 읽기. 보호된 파일은 None 반환."""
        if self._is_protected(relative_path):
            return None
        full_path = os.path.join(self.project_root, relative_path)
        if not os.path.exists(full_path):
            return None
        return self._safe_read(full_path)

    def get_full_codebase_summary(self):
        """전체 Python 파일 내용을 헤더와 함께 연결. Claude 컨텍스트용."""
        parts = []
        total_chars = 0
        max_chars = 80000

        for root, dirs, files in os.walk(self.o1_root):
            dirs[:] = [d for d in dirs if not self._is_protected_dir(
                os.path.relpath(os.path.join(root, d), self.project_root)
            )]
            for f in sorted(files):
                if not f.endswith(".py"):
                    continue
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, self.project_root)
                if self._is_protected(rel_path):
                    continue
                content = self._safe_read(full_path)
                if content is None:
                    continue
                if total_chars + len(content) > max_chars:
                    parts.append(f"\n=== {rel_path} === (truncated - context limit)")
                    break
                parts.append(f"\n=== {rel_path} ===\n{content}")
                total_chars += len(content)

        return "\n".join(parts)

    def validate_syntax(self, code):
        """Python 문법 검증. (True, "") 또는 (False, error_msg) 반환."""
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"Line {e.lineno}: {e.msg}"

    def _safe_read(self, full_path):
        """파일 안전 읽기 (크기 제한, 인코딩 폴백, 바이너리 감지)"""
        try:
            size = os.path.getsize(full_path)
            if size > MAX_FILE_SIZE:
                return None
        except OSError:
            return None

        # UTF-8 시도
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            if '\x00' in content:  # 바이너리 감지
                return None
            return content
        except UnicodeDecodeError:
            pass

        # Latin-1 폴백
        try:
            with open(full_path, "r", encoding="latin-1") as f:
                content = f.read()
            if '\x00' in content:
                return None
            return content
        except Exception:
            return None

    def _is_protected(self, relative_path):
        """파일이 보호 대상인지 확인"""
        basename = os.path.basename(relative_path)
        if basename in PROTECTED_FILES:
            return True
        return self._is_protected_dir(relative_path)

    def _is_protected_dir(self, relative_path):
        """디렉토리가 보호 대상인지 확인 (경로 컴포넌트 기반 매칭)"""
        normalized = os.path.normpath(relative_path).replace("\\", "/")
        parts = normalized.split("/")

        for protected in PROTECTED_DIRS:
            protected_parts = protected.split("/")
            # 연속된 경로 컴포넌트가 정확히 일치하는지 확인
            for i in range(len(parts) - len(protected_parts) + 1):
                if parts[i:i + len(protected_parts)] == protected_parts:
                    return True
        return False
