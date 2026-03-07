import os
from dotenv import load_dotenv

# .env 파일 로드 (프로젝트 루트)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

# --- API Keys ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# --- AI 설정 ---
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MODEL_HEAVY = "claude-sonnet-4-5-20250929"
AI_NAME = "Orion"

# --- Whisper STT 모델 ---
WHISPER_MODEL = "mlx-community/whisper-medium-mlx"

# --- 파일 경로 ---
PROFILE_FILE = os.path.join(_PROJECT_ROOT, "user_profile.txt")
MUSIC_FOLDER = os.path.join(_PROJECT_ROOT, "Music")

# --- ElevenLabs TTS ---
ELEVENLABS_VOICE_ID = "QYrOVogqhHWUzdZFXf0E"
ELEVENLABS_API_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

# --- Wake Words ---
WAKE_WORDS = [
    "hey orion", "hey orian", "hey oreon", "hey orianne",
    "a orion", "a orian", "hey oryan", "hey aurion",
    "orion", "orian", "hey orient", "hey o'brien",
    "헤이 오리온", "오리온", "헤이오리온", "hey 오리온",
]

# --- 캘린더 키워드 ---
CALENDAR_KEYWORDS = [
    "schedule", "calendar", "일정", "스케줄", "약속", "미팅", "meeting",
    "what do i have", "what's on", "events", "plan", "class",
    "오늘", "내일", "이번주", "today", "tomorrow", "this week", "next week"
]

# --- 오디오 설정 ---
AUDIO_ECHO_COOLDOWN_SEC = 1.5
AUDIO_ECHO_FILTER_SEC = 4.0
AUDIO_ECHO_THRESHOLD = 0.06
AUDIO_NORMAL_THRESHOLD = 0.018
AUDIO_VAD_DURATION = 7
AUDIO_VAD_SILENCE_TIMEOUT = 0.7

# --- 음악 플레이어 설정 ---
MUSIC_DEFAULT_VOLUME = 0.2
MUSIC_DUCKED_VOLUME = 0.05
MUSIC_VOLUME_STEP = 0.1

# --- 웹캠 ---
CAMERA_INDEX = 0                        # 0=외장 웹캠 (OBSBot), 1=내장 카메라
CAMERA_FPS = 15

# --- 웰컴백 감지 ---
PRESENCE_CHECK_INTERVAL = 1.5       # 검사 주기 (초)
PRESENCE_CONFIRM_FRAMES = 3         # 존재 확정 연속 횟수
PRESENCE_ABSENCE_FRAMES = 5         # 부재 확정 연속 횟수
PRESENCE_COOLDOWN_SEC = 60.0        # 재인사 쿨다운 (초)

# --- GIF 비주얼라이저 ---
VISUALIZER_GIF = os.path.join(_PROJECT_ROOT, "Orion_Visualizer.gif")
VISUALIZER_BASE_SIZE = 300          # 기본 GIF 크기 (px)
VISUALIZER_ACTIVE_SCALE = 1.4      # 응답 시 확대 비율
VISUALIZER_ANIMATION_MS = 600      # 확대/축소 애니메이션 시간 (ms)

# --- API 키 검증 함수 ---
def validate_api_keys():
    """필수 API 키 검증"""
    required = {
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "ELEVENLABS_API_KEY": ELEVENLABS_API_KEY,
    }

    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"Missing required API keys in .env: {', '.join(missing)}")

    optional = {
        "TAVILY_API_KEY": TAVILY_API_KEY,
        "GOOGLE_API_KEY": GOOGLE_API_KEY,
    }
    for name, value in optional.items():
        if not value:
            print(f"⚠️  Optional API key not set: {name}")
