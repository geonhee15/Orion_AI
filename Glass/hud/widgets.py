"""EDITH 스타일 HUD 위젯"""

import math
import time
import datetime
import platform
from PIL import Image, ImageDraw, ImageFont
from Glass import config
from Glass.hud import layout

C = config.COLORS


def _get_font(size):
    """시스템 폰트 로드 (크로스 플랫폼)"""
    system = platform.system()

    font_paths = []

    if system == "Darwin":  # macOS
        font_paths = [
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",  # 한글 지원
            "/System/Library/Fonts/Menlo.ttc",
        ]
    elif system == "Linux":
        font_paths = [
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",  # 한글 지원
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        ]
    elif system == "Windows":
        font_paths = [
            "C:\\Windows\\Fonts\\malgun.ttf",  # 맑은 고딕 (한글 지원)
            "C:\\Windows\\Fonts\\consola.ttf",
        ]

    # 폰트 경로 시도
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue

    # 기본 폰트 사용
    print("⚠️  Using default font - install system fonts for better appearance")
    return ImageFont.load_default()


FONT_S = _get_font(layout.FONT_SMALL)
FONT_M = _get_font(layout.FONT_MEDIUM)
FONT_L = _get_font(layout.FONT_LARGE)
FONT_T = _get_font(layout.FONT_TITLE)


def draw_status_bar(draw, state):
    """상단 상태바: 시간 | 날짜 | WiFi | 배터리"""
    now = datetime.datetime.now()
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%a %b %d")

    # 시간 (왼쪽)
    draw.text((8, 4), time_str, font=FONT_M, fill=C["primary"])

    # 날짜 (중앙)
    draw.text((90, 4), date_str, font=FONT_S, fill=C["dim"])

    # WiFi 아이콘 (오른쪽)
    wifi_x = 205
    for i in range(3):
        r = 3 + i * 3
        arc_y = 8 - i * 2
        draw.arc(
            [wifi_x - r, arc_y, wifi_x + r, arc_y + r * 2],
            200, 340, fill=C["secondary"], width=1,
        )
    draw.ellipse([wifi_x - 1, 12, wifi_x + 1, 14], fill=C["secondary"])

    # 배터리 아이콘
    bx = 222
    draw.rectangle([bx, 6, bx + 12, 14], outline=C["dim"], width=1)
    draw.rectangle([bx + 12, 8, bx + 14, 12], fill=C["dim"])
    draw.rectangle([bx + 2, 8, bx + 9, 12], fill=C["secondary"])


def draw_separator(draw, y):
    """수평 구분선 (EDITH 스타일 - 그라디언트)"""
    for x in range(20, 220):
        alpha = 1.0 - abs(x - 120) / 100
        alpha = max(0, min(1, alpha))
        r = int(C["primary"][0] * alpha * 0.4)
        g = int(C["primary"][1] * alpha * 0.4)
        b = int(C["primary"][2] * alpha * 0.4)
        draw.point((x, y), fill=(r, g, b))


def draw_weather(draw, state):
    """날씨 위젯"""
    area = layout.WEATHER
    weather = state.get("weather", "-- °C")

    # 날씨 아이콘 (간단한 원 = 태양)
    cx, cy = area["x"] + 12, area["y"] + 11
    draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=C["warning"], width=1)
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        x1 = cx + int(7 * math.cos(rad))
        y1 = cy + int(7 * math.sin(rad))
        x2 = cx + int(9 * math.cos(rad))
        y2 = cy + int(9 * math.sin(rad))
        draw.line([(x1, y1), (x2, y2)], fill=C["warning"], width=1)

    draw.text((area["x"] + 24, area["y"] + 3), weather, font=FONT_M, fill=C["primary"])


def draw_calendar(draw, state):
    """캘린더 위젯 - 다음 일정"""
    area = layout.CALENDAR
    next_event = state.get("next_event", "No events")

    # 캘린더 아이콘 (작은 사각형)
    ix, iy = area["x"] + 4, area["y"] + 3
    draw.rectangle([ix, iy, ix + 10, iy + 12], outline=C["secondary"], width=1)
    draw.line([(ix + 2, iy), (ix + 2, iy - 2)], fill=C["secondary"], width=1)
    draw.line([(ix + 8, iy), (ix + 8, iy - 2)], fill=C["secondary"], width=1)
    draw.line([(ix, iy + 4), (ix + 10, iy + 4)], fill=C["secondary"], width=1)

    # 일정 텍스트
    text = f"Next: {next_event}"
    if len(text) > 32:
        text = text[:32] + "..."
    draw.text((area["x"] + 20, area["y"] + 3), text, font=FONT_S, fill=C["secondary"])


def draw_ai_response(draw, state):
    """중앙 AI 응답 영역"""
    area = layout.AI_RESPONSE
    text = state.get("ai_response", "")

    if not text:
        # 대기 상태 - ORION 로고 (중앙정렬)
        cx = area["x"] + area["w"] // 2
        bbox = draw.textbbox((0, 0), "ORION", font=FONT_T)
        draw.text((cx - (bbox[2] - bbox[0]) // 2, area["y"] + 40), "ORION", font=FONT_T, fill=C["dim"])
        bbox = draw.textbbox((0, 0), "O1", font=FONT_S)
        draw.text((cx - (bbox[2] - bbox[0]) // 2, area["y"] + 65), "O1", font=FONT_S, fill=C["dim"])
        return

    # 타이핑 애니메이션 효과 (시간 기반으로 글자 수 제한)
    if state.get("thinking", False):
        # "생각 중" 애니메이션 - 점 3개가 깜빡임 (중앙정렬)
        dots = "." * (int(time.time() * 2) % 4)
        txt = f"Thinking{dots}"
        cx = area["x"] + area["w"] // 2
        bbox = draw.textbbox((0, 0), txt, font=FONT_M)
        draw.text((cx - (bbox[2] - bbox[0]) // 2, area["y"] + 45), txt, font=FONT_M, fill=C["primary"])
        return

    # AI 응답 텍스트 줄바꿈
    words = text.split()
    lines = []
    current_line = ""
    max_chars_per_line = 26

    for word in words:
        test_line = f"{current_line} {word}".strip() if current_line else word
        if len(test_line) <= max_chars_per_line:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    # 최대 7줄까지 표시
    lines = lines[:7]

    # 응답 영역 배경 (살짝 밝은 검정)
    draw.rectangle(
        [area["x"], area["y"], area["x"] + area["w"], area["y"] + area["h"]],
        fill=(5, 8, 15),
    )

    # 왼쪽 강조선
    draw.rectangle(
        [area["x"], area["y"] + 5, area["x"] + 2, area["y"] + area["h"] - 5],
        fill=C["primary"],
    )

    # 텍스트 출력
    for i, line in enumerate(lines):
        y = area["y"] + 8 + i * 16
        draw.text((area["x"] + 10, y), line, font=FONT_M, fill=C["primary"])


def draw_notification(draw, state):
    """하단 알림바 - 인식 텍스트 표시"""
    area = layout.NOTIFICATION
    notif = state.get("notification", "")
    last_heard = state.get("last_heard", "")

    cx = area["x"] + area["w"] // 2

    if state.get("listening", False):
        # 듣는 중 - 마이크 애니메이션 (중앙정렬)
        pulse = abs(math.sin(time.time() * 3))
        r = int(C["secondary"][0] * pulse)
        g = int(C["secondary"][1] * pulse)
        b = int(C["secondary"][2] * pulse)
        txt = "Listening..."
        bbox = draw.textbbox((0, 0), txt, font=FONT_M)
        draw.text((cx - (bbox[2] - bbox[0]) // 2, area["y"] + 5), txt, font=FONT_M, fill=(r, g, b))
        return

    if last_heard:
        # 인식된 텍스트 표시 (최대 30자)
        heard_text = last_heard if len(last_heard) <= 30 else last_heard[:30] + "..."
        bbox = draw.textbbox((0, 0), heard_text, font=FONT_S)
        draw.text((cx - (bbox[2] - bbox[0]) // 2, area["y"] + 5), heard_text, font=FONT_S, fill=C["highlight"])
    elif notif:
        bbox = draw.textbbox((0, 0), notif, font=FONT_S)
        draw.text((cx - (bbox[2] - bbox[0]) // 2, area["y"] + 5), notif, font=FONT_S, fill=C["warning"])
    else:
        txt = '"Hey Orion" to activate'
        bbox = draw.textbbox((0, 0), txt, font=FONT_S)
        draw.text((cx - (bbox[2] - bbox[0]) // 2, area["y"] + 8), txt, font=FONT_S, fill=C["dim"])


def draw_dev_progress(draw, state):
    """하단 개발 진행률 바 - 기능 이름 + 프로그레스 바 + 예상 시간"""
    area = layout.NOTIFICATION
    progress = state.get("dev_progress", {})
    if not progress.get("active"):
        return

    task_name = progress.get("task_name", "Developing")
    percent = min(100, max(0, progress.get("percent", 0)))
    remaining = progress.get("estimated_remaining_sec", 0)

    # 기능 이름 (왼쪽, 최대 12자)
    name_text = task_name if len(task_name) <= 12 else task_name[:11] + ".."
    draw.text((area["x"] + 2, area["y"] + 2), name_text, font=FONT_S, fill=C["primary"])

    # 프로그레스 바 (가운데)
    bar_x = area["x"] + 80
    bar_y = area["y"] + 5
    bar_w = 110
    bar_h = 8

    # 바 배경 (어두운 시안)
    draw.rectangle(
        [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
        fill=(10, 30, 40),
        outline=C["dim"],
    )

    # 바 채움 (초록)
    fill_w = int(bar_w * percent / 100)
    if fill_w > 0:
        draw.rectangle(
            [bar_x + 1, bar_y + 1, bar_x + fill_w, bar_y + bar_h - 1],
            fill=C["secondary"],
        )

    # 퍼센트 텍스트 (바 위)
    pct_text = f"{percent}%"
    bbox = draw.textbbox((0, 0), pct_text, font=FONT_S)
    pct_x = bar_x + (bar_w - (bbox[2] - bbox[0])) // 2
    draw.text((pct_x, bar_y - 1), pct_text, font=FONT_S, fill=C["highlight"])

    # 예상 시간 (오른쪽)
    if remaining > 60:
        time_text = f"~{int(remaining/60)}m"
    elif remaining > 0:
        time_text = f"~{int(remaining)}s"
    else:
        time_text = ""
    if time_text:
        draw.text((area["x"] + area["w"] - 25, area["y"] + 18), time_text, font=FONT_S, fill=C["dim"])


def draw_boot_animation(draw, frame_num):
    """부팅 애니메이션 (EDITH 스타일)"""
    cx, cy = 120, 120

    # 회전하는 원
    for i in range(3):
        r = 30 + i * 25
        angle = frame_num * 5 + i * 120
        alpha = min(1.0, frame_num / 20)
        color = (
            int(C["primary"][0] * alpha),
            int(C["primary"][1] * alpha),
            int(C["primary"][2] * alpha),
        )
        start = angle % 360
        end = (angle + 60) % 360
        if start < end:
            draw.arc([cx - r, cy - r, cx + r, cy + r], start, end, fill=color, width=1)
        else:
            draw.arc([cx - r, cy - r, cx + r, cy + r], start, 360, fill=color, width=1)
            draw.arc([cx - r, cy - r, cx + r, cy + r], 0, end, fill=color, width=1)

    # 텍스트 (페이드 인, 중앙정렬)
    if frame_num > 15:
        text_alpha = min(1.0, (frame_num - 15) / 10)
        color = (
            int(C["primary"][0] * text_alpha),
            int(C["primary"][1] * text_alpha),
            int(C["primary"][2] * text_alpha),
        )
        bbox = draw.textbbox((0, 0), "ORION", font=FONT_T)
        draw.text((cx - (bbox[2] - bbox[0]) // 2, 105), "ORION", font=FONT_T, fill=color)
        bbox = draw.textbbox((0, 0), "O1", font=FONT_L)
        draw.text((cx - (bbox[2] - bbox[0]) // 2, 130), "O1", font=FONT_L, fill=color)

    if frame_num > 30:
        txt = "SYSTEM ONLINE"
        bbox = draw.textbbox((0, 0), txt, font=FONT_S)
        draw.text((cx - (bbox[2] - bbox[0]) // 2, 155), txt, font=FONT_S, fill=C["secondary"])

    # 스캔 라인
    scan_y = (frame_num * 4) % 240
    draw.line([(0, scan_y), (240, scan_y)], fill=(*C["primary"][:2], 30), width=1)
