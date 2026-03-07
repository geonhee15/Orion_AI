"""Gemini 비전 분석 모듈 — 웹캠 스냅샷 → AI 분석"""

import io
from PIL import Image, UnidentifiedImageError
from Workspace import config

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


class VisionAnalyzer:
    """카메라 프레임 분석 (Gemini 2.0 Flash)"""

    def __init__(self):
        if GEMINI_AVAILABLE and config.GOOGLE_API_KEY:
            self.gemini = genai.Client(api_key=config.GOOGLE_API_KEY)
            print("✅ Vision: Gemini 2.0 Flash")
        else:
            self.gemini = None
            print("⚠️ Vision: 비활성화 (google-genai 또는 API 키 없음)")

    @property
    def available(self):
        return self.gemini is not None

    def analyze(self, jpeg_bytes, prompt=None):
        """JPEG 바이트 → AI 분석 결과 텍스트"""
        if not self.gemini:
            return "Sir, vision analysis is currently unavailable."

        try:
            img = Image.open(io.BytesIO(jpeg_bytes))

            if not prompt:
                prompt = (
                    "You are Orion, a JARVIS-like AI assistant. "
                    "Describe what you see in this image in 1-2 concise English sentences. "
                    "Start with 'Sir,'."
                )

            response = self.gemini.models.generate_content(
                model="gemini-2.0-flash",
                contents=[prompt, img],
            )
            return response.text.strip()
        except UnidentifiedImageError:
            return "Sir, the image data appears to be corrupted."
        except Exception as e:
            print(f"[Vision] Error: {e}")
            return "Sir, an error occurred during image analysis."
