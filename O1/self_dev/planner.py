"""태스크 계획기 - Claude로 개발 태스크 생성

견고한 JSON 파싱 + 2회 재시도 + 필드 검증으로
Claude 응답 형식 변동에도 안정적으로 동작합니다.
"""

import json
from dataclasses import dataclass
from anthropic import Anthropic, RateLimitError
from O1 import config
from O1.self_dev import prompts
from O1.self_dev.utils import extract_json


@dataclass
class DevTask:
    """자가개발 태스크"""
    id: str
    title: str
    description: str
    task_type: str      # bug_fix, optimization, new_feature, refactor
    priority: str       # critical, high, medium, low
    target_files: list
    estimated_complexity: str = "simple"
    status: str = "pending"
    result_summary: str = ""


VALID_TASK_TYPES = {"bug_fix", "optimization", "new_feature", "refactor"}
VALID_PRIORITIES = {"critical", "high", "medium", "low"}


class TaskPlanner:
    """코드베이스를 분석하고 개발 태스크를 생성"""

    def __init__(self, analyzer, history):
        self.anthropic = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.analyzer = analyzer
        self.history = history
        self.task_queue = []

    def generate_tasks(self, focus="auto", user_request=None):
        """코드베이스 분석 → 태스크 리스트 생성. 실패 시 1회 재시도."""
        file_tree = self.analyzer.get_file_tree()
        codebase = self.analyzer.get_full_codebase_summary()
        history_context = self.history.get_context_for_planner()

        if user_request:
            user_prompt = prompts.PLANNER_USER_TASK_PROMPT.format(
                user_request=user_request,
                file_tree=file_tree,
                codebase=codebase,
                history=history_context,
            )
        else:
            user_prompt = prompts.PLANNER_USER_PROMPT.format(
                file_tree=file_tree,
                codebase=codebase,
                history=history_context,
                focus=focus,
            )

        # 최대 2회 시도
        last_error = None
        for attempt in range(2):
            try:
                response = self.anthropic.messages.create(
                    model=config.CLAUDE_MODEL_DEV,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": user_prompt}],
                    system=prompts.PLANNER_SYSTEM_PROMPT,
                )

                if response.stop_reason == "max_tokens":
                    print("[SelfDev:Planner] Warning: response truncated")

                raw_text = response.content[0].text.strip()
                raw_tasks = extract_json(raw_text, expect_type="array")

                if raw_tasks is None:
                    last_error = f"JSON parsing failed (attempt {attempt + 1})"
                    print(f"[SelfDev:Planner] {last_error}")
                    print(f"[SelfDev:Planner] Raw preview: {raw_text[:200]}")
                    continue

                if not isinstance(raw_tasks, list) or len(raw_tasks) == 0:
                    last_error = f"Empty task list (attempt {attempt + 1})"
                    print(f"[SelfDev:Planner] {last_error}")
                    continue

                self.task_queue = []
                for t in raw_tasks:
                    # 필수 필드 검증
                    if not t.get("title") or not t.get("description"):
                        print("[SelfDev:Planner] Skipping task: missing title/description")
                        continue

                    task_type = t.get("task_type", "optimization")
                    if task_type not in VALID_TASK_TYPES:
                        task_type = "optimization"

                    priority = t.get("priority", "medium")
                    if priority not in VALID_PRIORITIES:
                        priority = "medium"

                    target_files = t.get("target_files", [])
                    if not isinstance(target_files, list):
                        target_files = []

                    self.task_queue.append(DevTask(
                        id=t.get("id", f"task_{len(self.task_queue) + 1:03d}"),
                        title=t["title"],
                        description=t["description"],
                        task_type=task_type,
                        priority=priority,
                        target_files=target_files,
                        estimated_complexity=t.get("estimated_complexity", "simple"),
                    ))

                if self.task_queue:
                    print(f"[SelfDev:Planner] {len(self.task_queue)} tasks generated")
                    return self.task_queue
                else:
                    last_error = "All tasks filtered out during validation"
                    print(f"[SelfDev:Planner] {last_error}")
                    continue

            except RateLimitError:
                print("[SelfDev:Planner] Rate limited, aborting")
                return []
            except Exception as e:
                last_error = str(e)
                print(f"[SelfDev:Planner] Error (attempt {attempt + 1}): {e}")

        print(f"[SelfDev:Planner] All attempts failed. Last: {last_error}")
        return []

    def get_next_task(self):
        """가장 높은 우선순위의 pending 태스크 반환"""
        for task in self.task_queue:
            if task.status == "pending":
                return task
        return None
