import base64
import io
from PIL import Image, UnidentifiedImageError
from O1 import config

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


class VisionAnalyzer:
    """카메라 프레임 분석 (Gemini 2.0 Flash)"""

    def __init__(self, system_prompt=""):
        self.system_prompt = system_prompt
        if GEMINI_AVAILABLE and config.GOOGLE_API_KEY:
            self.gemini = genai.Client(api_key=config.GOOGLE_API_KEY)
            print("✅ Vision Analyzer: Gemini 2.0 Flash")
        else:
            self.gemini = None
            print("⚠️ Vision Analyzer: 비활성화 (google-genai 없음)")

    def analyze_frame(self, jpeg_bytes, prompt=None):
        """JPEG 바이트 → AI 분석 결과"""
        if not self.gemini:
            return "Sir, 비전 분석 기능이 비활성화되어 있습니다."

        try:
            img = Image.open(io.BytesIO(jpeg_bytes))

            if not prompt:
                prompt = "이 이미지를 보고 차분하게 한 문장으로 말해줘."

            full_prompt = self.system_prompt + "\n" + prompt

            response = self.gemini.models.generate_content(
                model="gemini-2.0-flash",
                contents=[full_prompt, img],
            )

            return response.text.strip()
        except UnidentifiedImageError as e:
            print(f"[Vision] Invalid image: {e}")
            return "Sir, the image data is corrupted."
        except Exception as e:
            # genai는 표준 에러가 없으므로 일반 예외 처리
            print(f"[Vision] Error: {e}")
            if "API" in str(e) or "quota" in str(e).lower():
                return "Sir, there was an error with the vision API."
            return "Sir, an unexpected error occurred during image analysis."

    def identify_object(self, jpeg_bytes):
        """빠른 물체 식별 (HUD 오버레이용)"""
        return self.analyze_frame(
            jpeg_bytes,
            prompt="Identify the main object in this image. Reply in one short phrase in English only."
        )
