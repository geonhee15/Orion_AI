"""코드 생성기 - Claude Opus로 실제 코드 변경 생성

견고한 JSON 파싱, 16K 토큰 출력, 검증 에러 피드백 재시도,
응답 절삭 감지를 포함합니다.
"""

import json
from dataclasses import dataclass
from anthropic import Anthropic, RateLimitError
from Glass import config
from Glass.self_dev import prompts
from Glass.self_dev.utils import extract_json


@dataclass
class FileChange:
    """단일 파일 변경"""
    file_path: str
    action: str             # modify, create, delete
    original_content: str
    new_content: str
    change_description: str


@dataclass
class DevResult:
    """개발 태스크 결과"""
    task: object            # DevTask
    changes: list           # list[FileChange]
    summary: str
    demo_script: str


VALID_ACTIONS = {"modify", "create", "delete"}


class CodeGenerator:
    """Claude Opus를 사용해 코드 변경사항을 생성"""

    def __init__(self, analyzer):
        self.anthropic = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.analyzer = analyzer

    def execute_task(self, task, validation_errors=None):
        """태스크에 대한 코드 변경 생성. DevResult 또는 None 반환.

        Args:
            task: DevTask 객체
            validation_errors: 이전 시도의 검증 에러 문자열 리스트 (재시도용)
        """
        # 대상 파일 내용 수집
        file_contents = {}
        for path in task.target_files:
            content = self.analyzer.read_file(path)
            if content is not None:
                file_contents[path] = content

        codebase_context = self.analyzer.get_full_codebase_summary()
        target_files_str = json.dumps(file_contents, indent=2, ensure_ascii=False)

        # 재시도 시 에러 피드백 포함
        if validation_errors:
            user_content = prompts.CODER_RETRY_PROMPT.format(
                error_details="\n".join(f"- {e}" for e in validation_errors),
                task_title=task.title,
                task_description=task.description,
                target_files=target_files_str,
            )
        else:
            user_content = prompts.CODER_USER_PROMPT.format(
                task_title=task.title,
                task_type=task.task_type,
                task_description=task.description,
                target_files=target_files_str,
                full_codebase=codebase_context,
            )

        # 최대 2회 시도 (JSON 파싱 실패 시)
        last_error = None
        for attempt in range(2):
            try:
                response = self.anthropic.messages.create(
                    model=config.CLAUDE_MODEL_DEV,
                    max_tokens=16384,
                    messages=[{"role": "user", "content": user_content}],
                    system=prompts.CODER_SYSTEM_PROMPT,
                )

                if response.stop_reason == "max_tokens":
                    print("[SelfDev:Coder] Warning: response truncated (max_tokens)")

                raw_text = response.content[0].text.strip()
                result_data = extract_json(raw_text, expect_type="object")

                if result_data is None:
                    last_error = f"JSON parsing failed (attempt {attempt + 1})"
                    print(f"[SelfDev:Coder] {last_error}")
                    print(f"[SelfDev:Coder] Raw preview: {raw_text[:300]}")
                    continue

                # 구조 검증
                if "changes" not in result_data:
                    last_error = "Missing 'changes' key in response"
                    print(f"[SelfDev:Coder] {last_error}")
                    continue

                changes_data = result_data["changes"]
                if not isinstance(changes_data, list) or len(changes_data) == 0:
                    last_error = "Empty changes list"
                    print(f"[SelfDev:Coder] {last_error}")
                    continue

                # 변경사항 파싱
                changes = []
                valid = True
                for ch in changes_data:
                    if not ch.get("file_path"):
                        print("[SelfDev:Coder] Skipping change: no file_path")
                        continue

                    action = ch.get("action", "modify")
                    if action not in VALID_ACTIONS:
                        action = "modify"

                    new_content = ch.get("new_content", "")
                    if action != "delete" and not new_content:
                        print(f"[SelfDev:Coder] Warning: empty content for {ch['file_path']}")
                        valid = False
                        break

                    changes.append(FileChange(
                        file_path=ch["file_path"],
                        action=action,
                        original_content=file_contents.get(ch["file_path"], ""),
                        new_content=new_content,
                        change_description=ch.get("description", ""),
                    ))

                if not valid or not changes:
                    last_error = "Invalid or empty changes after parsing"
                    print(f"[SelfDev:Coder] {last_error}")
                    continue

                return DevResult(
                    task=task,
                    changes=changes,
                    summary=result_data.get("summary", "Changes applied."),
                    demo_script=result_data.get(
                        "demo_script",
                        f"Sir, I've completed the task: {task.title}."
                    ),
                )

            except RateLimitError:
                print("[SelfDev:Coder] Rate limited, aborting")
                return None
            except Exception as e:
                last_error = str(e)
                print(f"[SelfDev:Coder] Error (attempt {attempt + 1}): {e}")

        print(f"[SelfDev:Coder] All attempts failed. Last: {last_error}")
        return None
