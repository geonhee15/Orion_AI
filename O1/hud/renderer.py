"""EDITH 스타일 HUD 렌더러 (240x240)"""

import io
import time
import numpy as np
from PIL import Image, ImageDraw
from O1 import config
from O1.hud import layout
from O1.hud.widgets import (
    draw_status_bar,
    draw_separator,
    draw_weather,
    draw_calendar,
    draw_ai_response,
    draw_notification,
    draw_dev_progress,
    draw_boot_animation,
)


class HUDRenderer:
    """240x240 EDITH 스타일 HUD 프레임 생성기"""

    def __init__(self):
        self.boot_frame = 0
        self.boot_complete = False
        self.boot_start_time = time.time()
        self._frame_count = 0
        print("✅ HUD Renderer 초기화됨 (240x240)")

    def render(self, state: dict) -> Image.Image:
        """현재 상태로 HUD 프레임 렌더링. PIL Image 반환."""
        img = Image.new("RGB", (layout.WIDTH, layout.HEIGHT), config.COLORS["background"])
        draw = ImageDraw.Draw(img)

        # 부팅 애니메이션 (처음 3초)
        if not self.boot_complete:
            elapsed = time.time() - self.boot_start_time
            if elapsed < 3.0:
                self.boot_frame += 1
                draw_boot_animation(draw, self.boot_frame)
                return img
            else:
                self.boot_complete = True

        # 메인 HUD 렌더링
        draw_status_bar(draw, state)
        draw_separator(draw, layout.SEP_1_Y)
        draw_weather(draw, state)
        draw_calendar(draw, state)
        draw_separator(draw, layout.SEP_2_Y)
        draw_ai_response(draw, state)
        draw_separator(draw, layout.SEP_3_Y)
        # 개발 진행 중이면 진행률 바, 아니면 일반 알림
        if state.get("dev_progress", {}).get("active"):
            draw_dev_progress(draw, state)
        else:
            draw_notification(draw, state)

        # 코너 장식 (EDITH 스타일)
        self._draw_corners(draw)

        # 프레임 카운터 (디버그)
        self._frame_count += 1

        return img

    def render_png(self, state: dict) -> bytes:
        """PNG 바이트로 렌더링 (테스트 클라이언트 / 브라우저용)"""
        img = self.render(state)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()

    def render_jpeg(self, state: dict, quality=85) -> bytes:
        """JPEG 바이트로 렌더링 (ESP32 전송용 - 작은 크기)"""
        img = self.render(state)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()

    def render_rgb565(self, state: dict) -> bytes:
        """RGB565 바이트로 렌더링 (ESP32 ST7789 직접 출력용) - Numpy 벡터화"""
        img = self.render(state)

        # PIL Image → Numpy 배열 (240x240x3)
        rgb_array = np.array(img, dtype=np.uint8)

        # RGB888 → RGB565 벡터화 변환
        r = (rgb_array[:, :, 0] & 0xF8).astype(np.uint16) << 8
        g = (rgb_array[:, :, 1] & 0xFC).astype(np.uint16) << 3
        b = (rgb_array[:, :, 2] & 0xF8).astype(np.uint16) >> 3
        rgb565 = r | g | b

        # Big-endian uint16 → bytes
        return rgb565.astype('>u2').tobytes()

    def _draw_corners(self, draw):
        """코너 장식 (이디스/자비스 스타일 L자 라인)"""
        c = config.COLORS["primary"]
        dim_c = (c[0] // 4, c[1] // 4, c[2] // 4)
        size = 15

        # 좌상단
        draw.line([(0, 0), (size, 0)], fill=dim_c, width=1)
        draw.line([(0, 0), (0, size)], fill=dim_c, width=1)

        # 우상단
        draw.line([(240 - size, 0), (239, 0)], fill=dim_c, width=1)
        draw.line([(239, 0), (239, size)], fill=dim_c, width=1)

        # 좌하단
        draw.line([(0, 239), (size, 239)], fill=dim_c, width=1)
        draw.line([(0, 240 - size), (0, 239)], fill=dim_c, width=1)

        # 우하단
        draw.line([(240 - size, 239), (239, 239)], fill=dim_c, width=1)
        draw.line([(239, 240 - size), (239, 239)], fill=dim_c, width=1)
