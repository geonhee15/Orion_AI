"""변경사항 검증기 - 안전성/문법 체크

경로 정규화, 컴포넌트 기반 디렉토리 매칭, 위험 코드 감지,
일관된 줄 수 제한 (500줄) 을 적용합니다.
"""

import os
from Glass.self_dev.analyzer import PROTECTED_FILES, PROTECTED_DIRS

MAX_FILE_LINES = 500


class ValidationError:
    """검증 실패 항목"""

    def __init__(self, file_path, error_type, message):
        self.file_path = file_path
        self.error_type = error_type
        self.message = message

    def __str__(self):
        return f"[{self.error_type}] {self.file_path}: {self.message}"


class ChangeValidator:
    """코드 변경사항을 다단계 검증"""

    def __init__(self, analyzer):
        self.analyzer = analyzer

    def validate(self, result):
        """전체 검증. (all_passed, errors) 반환."""
        errors = []
        for change in result.changes:
            errors.extend(self._validate_change(change))
        return len(errors) == 0, errors

    def _validate_change(self, change):
        errors = []
        fp = change.file_path

        # 1. 경로 정규화 & 기본 안전성
        normalized = os.path.normpath(fp).replace("\\", "/")

        # 절대 경로 차단
        if os.path.isabs(fp):
            errors.append(ValidationError(fp, "ABSOLUTE_PATH", "Absolute paths not allowed"))
            return errors

        # Path traversal 체크 (컴포넌트 기반)
        if ".." in normalized.split("/"):
            errors.append(ValidationError(fp, "PATH_TRAVERSAL", "Path contains '..'"))
            return errors

        # 2. Scope 체크 (O1/ 내부만)
        if not normalized.startswith("O1/"):
            errors.append(ValidationError(fp, "OUTSIDE_SCOPE", "Only O1/ directory allowed"))
            return errors

        # 3. Protected file 체크
        basename = os.path.basename(normalized)
        if basename in PROTECTED_FILES:
            errors.append(ValidationError(fp, "PROTECTED_FILE", f"Cannot modify {basename}"))
            return errors

        # 4. Protected directory 체크 (컴포넌트 기반 매칭)
        parts = normalized.split("/")
        for protected_dir in PROTECTED_DIRS:
            protected_parts = protected_dir.split("/")
            for i in range(len(parts) - len(protected_parts) + 1):
                if parts[i:i + len(protected_parts)] == protected_parts:
                    errors.append(ValidationError(
                        fp, "PROTECTED_DIR", f"Cannot modify files in {protected_dir}/"
                    ))
                    return errors

        # 5. Python 문법 체크
        if fp.endswith(".py") and change.action != "delete":
            ok, msg = self.analyzer.validate_syntax(change.new_content)
            if not ok:
                errors.append(ValidationError(fp, "SYNTAX_ERROR", msg))

        # 6. 민감 데이터 체크
        if change.action != "delete":
            # API 키 리터럴은 항상 차단
            key_patterns = [
                ("sk-ant-", "Anthropic API key literal"),
                ("sk-proj-", "OpenAI API key literal"),
            ]
            for pattern, desc in key_patterns:
                if pattern in change.new_content:
                    errors.append(ValidationError(fp, "SENSITIVE_DATA", desc))

            # config.py 외에서 직접 env 접근 차단
            if "config.py" not in basename:
                env_patterns = [
                    ("os.getenv(", "Direct env access (use config module)"),
                    ("load_dotenv", "Direct dotenv load (use config module)"),
                ]
                for pattern, desc in env_patterns:
                    if pattern in change.new_content:
                        errors.append(ValidationError(fp, "SENSITIVE_DATA", desc))

        # 7. 위험한 코드 실행 체크
        if fp.endswith(".py") and change.action != "delete":
            for pattern in ["eval(", "exec(", "__import__("]:
                if pattern in change.new_content:
                    errors.append(ValidationError(
                        fp, "DANGEROUS_CODE", f"Contains {pattern} - code execution risk"
                    ))

        # 8. 파일 크기 체크
        if change.action != "delete" and change.new_content:
            line_count = change.new_content.count("\n") + 1
            if line_count > MAX_FILE_LINES:
                errors.append(ValidationError(
                    fp, "TOO_LARGE", f"{line_count} lines (max {MAX_FILE_LINES})"
                ))

        return errors
