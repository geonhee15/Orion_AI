"""자가개발 유틸리티 - 견고한 JSON 추출

Claude 응답에서 JSON을 안전하게 추출하는 다중 전략 파서.
코드블록, 트레일링 콤마, 텍스트 혼합 등 모든 형식을 처리합니다.
"""

import re
import json


def extract_json(text, expect_type="auto"):
    """Claude 응답에서 JSON을 견고하게 추출.

    처리 가능한 형식:
    - 순수 JSON
    - ```json ... ```, ```JSON ... ```, ``` ... ``` 코드블록
    - 설명 텍스트 + JSON 혼합
    - 트레일링 콤마 (,] 또는 ,})
    - 중첩 브래킷이 있는 복잡한 JSON

    Args:
        text: Claude 응답 텍스트
        expect_type: "array" | "object" | "auto"

    Returns:
        파싱된 JSON 객체/배열, 또는 None
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # Strategy 1: 코드블록 내부 추출
    code_block = re.search(
        r'```(?:json|JSON|python|py)?\s*\n?(.*?)```', text, re.DOTALL
    )
    if code_block:
        result = _try_parse_lenient(code_block.group(1).strip(), expect_type)
        if result is not None:
            return result

    # Strategy 2: 순수 JSON 직접 파싱
    result = _try_parse_lenient(text, expect_type)
    if result is not None:
        return result

    # Strategy 3: JSON 경계 자동 감지 (브래킷 매칭)
    if expect_type in ("array", "auto"):
        result = _extract_balanced(text, '[', ']', expect_type)
        if result is not None:
            return result

    if expect_type in ("object", "auto"):
        result = _extract_balanced(text, '{', '}', expect_type)
        if result is not None:
            return result

    # Strategy 4: 비-JSON 줄 제거 후 재시도
    lines = text.split('\n')
    json_lines = [
        line for line in lines
        if line.strip() and not line.strip().startswith(
            ('Here', 'I ', 'The ', 'This ', 'Note', 'Let', '#', '//')
        )
    ]
    if json_lines and len(json_lines) != len(lines):
        result = _try_parse_lenient('\n'.join(json_lines), expect_type)
        if result is not None:
            return result

    return None


def _try_parse_lenient(text, expect_type):
    """트레일링 콤마를 허용하는 관대한 JSON 파싱"""
    # 먼저 그대로 시도
    result = _try_parse_strict(text, expect_type)
    if result is not None:
        return result

    # 트레일링 콤마 제거 후 재시도
    cleaned = re.sub(r',\s*([}\]])', r'\1', text)
    if cleaned != text:
        result = _try_parse_strict(cleaned, expect_type)
        if result is not None:
            return result

    return None


def _try_parse_strict(text, expect_type):
    """엄격한 JSON 파싱"""
    try:
        data = json.loads(text)
        if expect_type == "array" and not isinstance(data, list):
            return None
        if expect_type == "object" and not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_balanced(text, open_ch, close_ch, expect_type):
    """중첩 브래킷을 추적하여 완전한 JSON 블록 추출"""
    start = text.find(open_ch)
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        c = text[i]

        if escape:
            escape = False
            continue

        if c == '\\' and in_string:
            escape = True
            continue

        if c == '"' and not escape:
            in_string = not in_string
            continue

        if in_string:
            continue

        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                return _try_parse_lenient(candidate, expect_type)

    return None
