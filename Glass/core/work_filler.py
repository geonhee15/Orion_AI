"""Work Assistant 자동 채우기 — 타입별 전략 디스패치

수학: 풀이 과정 + 답 채우기
에세이: 학생 수준 맞춰 작성
퀴즈/폼: Tab 이동하며 답 채우기
Google Docs: 클립보드 붙여넣기 (Cmd+V)
"""

import time
import json

from Glass import config


class ContentFiller:
    """페이지 타입에 따라 적절한 자동 채우기 전략 실행"""

    def __init__(self, chrome, anthropic_client):
        self.chrome = chrome
        self._anthropic = anthropic_client

    def execute(self, page_type, analysis, page_content):
        """타입별 디스패치"""
        strategy = analysis.get("fill_strategy", "paste_all")
        tasks = analysis.get("tasks", [])

        if not tasks:
            print("[WorkFiller] No tasks to fill")
            return

        print(f"[WorkFiller] {len(tasks)} tasks, strategy: {strategy}, type: {page_type}")

        if page_type == "math":
            self._fill_math(analysis, tasks, strategy)
        elif page_type == "essay":
            self._fill_essay(analysis, tasks)
        elif page_type in ("quiz", "form"):
            self._fill_sequential(analysis, tasks, strategy)
        else:
            self._fill_generic(analysis, tasks, strategy)

    # ─── 수학 채우기 ───

    def _fill_math(self, analysis, tasks, strategy):
        """수학 문제: 풀이 과정 + 답 채우기"""
        # 빈 문제만 필터 (이미 답이 있으면 건너뛸지 결정)
        empty_tasks = [t for t in tasks if not t.get("existing_answer")]
        fill_tasks = empty_tasks if empty_tasks else tasks

        if strategy == "paste_all":
            # 전체를 한번에 붙여넣기 (Google Docs 등)
            full_text = self._format_math_answers(fill_tasks)
            self.chrome.paste_text(full_text)

        elif strategy == "sequential_fields":
            # 필드 하나씩 채우기 (웹 폼)
            for task in fill_tasks:
                work = task.get("work_shown", "")
                answer = task.get("answer", "")

                if work:
                    self.chrome.paste_text(work)
                    self.chrome.press_tab()
                    time.sleep(0.2)

                if answer:
                    self.chrome.paste_text(str(answer))
                    self.chrome.press_tab()
                    time.sleep(0.2)

        else:
            # tab_navigate 폴백
            self._fill_with_tabs(fill_tasks)

    def _format_math_answers(self, tasks):
        """수학 풀이를 텍스트로 포맷"""
        lines = []
        for t in tasks:
            q_id = t.get("id", "?")
            work = t.get("work_shown", "")
            answer = t.get("answer", "")

            lines.append(f"\n{q_id}.")
            if work:
                lines.append(f"Work:\n{work}")
            if answer:
                lines.append(f"Answer: {answer}")

        return "\n".join(lines)

    # ─── 에세이 채우기 ───

    def _fill_essay(self, analysis, tasks):
        """에세이: 학생 수준에 맞춰 작성 후 붙여넣기"""
        writing = analysis.get("writing_analysis", {})

        for task in tasks:
            prompt_text = task.get("question_text", "")
            existing = task.get("answer", "")

            if existing:
                # 분석에서 이미 생성한 답이 있으면 사용
                self.chrome.paste_text(existing)
            else:
                # Claude로 에세이 생성
                essay = self._generate_essay(prompt_text, writing)
                if essay:
                    self.chrome.paste_text(essay)

            time.sleep(0.3)

    def _generate_essay(self, prompt_text, writing_analysis):
        """Claude로 학생 수준 에세이 생성"""
        style = writing_analysis.get("detected_style", "academic")
        level = writing_analysis.get("vocabulary_level", "grade 6-8")
        tone = writing_analysis.get("tone", "formal")

        try:
            response = self._anthropic.messages.create(
                model=config.CLAUDE_MODEL_HEAVY,
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Write an essay for this prompt:\n{prompt_text}\n\n"
                        f"Requirements:\n"
                        f"- Writing style: {style}\n"
                        f"- Vocabulary level: {level}\n"
                        f"- Tone: {tone}\n"
                        f"- Write at a middle school student's level (NOT college level)\n"
                        f"- Use simple, natural language\n"
                        f"- Appropriate length for a classroom assignment\n\n"
                        f"Output ONLY the essay text. No title, no explanation."
                    ),
                }],
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"[WorkFiller] Essay generation error: {e}")
            return None

    # ─── 퀴즈/폼 채우기 ───

    def _fill_sequential(self, analysis, tasks, strategy):
        """퀴즈/폼: 순서대로 답 채우기"""
        for task in tasks:
            answer = task.get("answer", "")
            if not answer:
                continue

            answer_str = str(answer)

            if len(answer_str) > 100:
                # 긴 답변은 클립보드로
                self.chrome.paste_text(answer_str)
            else:
                # 짧은 답변은 타이핑
                self.chrome.type_text(answer_str)

            self.chrome.press_tab()
            time.sleep(0.2)

    # ─── 제네릭 채우기 ───

    def _fill_generic(self, analysis, tasks, strategy):
        """범용 폴백: 전체 답변을 텍스트로 붙여넣기"""
        all_text = []
        for task in tasks:
            q_id = task.get("id", "?")
            answer = task.get("answer", "")
            work = task.get("work_shown", "")

            if work:
                all_text.append(f"{q_id}.\nWork: {work}\nAnswer: {answer}")
            elif answer:
                all_text.append(f"{q_id}. {answer}")

        if all_text:
            self.chrome.paste_text("\n\n".join(all_text))

    # ─── 유틸 ───

    def _fill_with_tabs(self, tasks):
        """Tab으로 필드 이동하며 채우기"""
        for task in tasks:
            work = task.get("work_shown", "")
            answer = task.get("answer", "")

            if work:
                self.chrome.paste_text(work)
                self.chrome.press_tab()
                time.sleep(0.15)

            if answer:
                self.chrome.paste_text(str(answer))
                self.chrome.press_tab()
                time.sleep(0.15)
