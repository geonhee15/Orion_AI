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
LOTTEEATZ_ID = os.getenv("LOTTEEATZ_ID")
LOTTEEATZ_PW = os.getenv("LOTTEEATZ_PW")

# --- AI 설정 ---
CLAUDE_MODEL = "claude-haiku-4-5-20251001"   # 빠른 응답용
CLAUDE_MODEL_HEAVY = "claude-sonnet-4-5-20250929"  # 복잡한 질문용
AI_NAME = "Orion"

# --- Whisper STT 모델 ---
WHISPER_MODEL = "mlx-community/whisper-medium-mlx"

# --- 파일 경로 ---
PROFILE_FILE = os.path.join(_PROJECT_ROOT, "user_profile.txt")
MUSIC_FOLDER = os.path.join(_PROJECT_ROOT, "Music")
DELIVERY_CONFIG_FILE = os.path.join(_PROJECT_ROOT, "delivery_config.json")

# --- ElevenLabs TTS ---
ELEVENLABS_VOICE_ID = "QYrOVogqhHWUzdZFXf0E"
ELEVENLABS_API_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

# --- Wake Words ---
WAKE_WORDS = [
    "hey orion", "hey orian", "hey oreon", "hey orianne",
    "a orion", "a orian", "hey oryan", "hey aurion",
    "orion", "orian", "hey orient", "hey o'brien",
    # 한국어 웨이크워드
    "헤이 오리온", "오리온", "헤이오리온", "hey 오리온",
]

# --- 캘린더 키워드 ---
CALENDAR_KEYWORDS = [
    "schedule", "calendar", "일정", "스케줄", "약속", "미팅", "meeting",
    "what do i have", "what's on", "events", "plan", "class",
    "오늘", "내일", "이번주", "today", "tomorrow", "this week", "next week"
]

# --- 배달 키워드 ---
DELIVERY_KEYWORDS = [
    "시켜", "주문", "배달", "롯데리아", "버거", "피자", "치킨",
    "order", "deliver", "delivery", "lotteria",
    "burger", "pizza", "chicken", "send me", "get me",
    "bulgogi", "korean beef", "shrimp", "cheese stick"
]

# --- 서버 설정 ---
WS_HOST = "0.0.0.0"
HTTP_PORT = 8000

# --- HUD 설정 ---
HUD_WIDTH = 240
HUD_HEIGHT = 240
HUD_FPS = 10

# --- HUD 색상 팔레트 (EDITH 스타일) ---
COLORS = {
    "background": (0, 0, 0),
    "primary": (0, 200, 255),       # 시안 - 메인 텍스트
    "secondary": (0, 255, 150),     # 초록 - 강조
    "warning": (255, 180, 0),       # 주황 - 경고
    "error": (255, 60, 60),         # 빨강 - 에러
    "dim": (60, 80, 100),           # 어두운 텍스트
    "highlight": (255, 255, 255),   # 흰색 - 강조
}

# --- 오디오 설정 ---
# TTS 에코 방지 (스피커 출력 → 마이크 재입력 차단)
AUDIO_ECHO_COOLDOWN_SEC = 1.5       # TTS 종료 후 대기 시간 (에코 방지 강화)
AUDIO_ECHO_FILTER_SEC = 4.0         # TTS 후 고감도 필터링 지속 시간
AUDIO_ECHO_THRESHOLD = 0.06         # TTS 직후 높은 볼륨 임계값 (잔향 차단)
AUDIO_NORMAL_THRESHOLD = 0.018      # 일반 볼륨 임계값

# VAD (Voice Activity Detection) 설정
AUDIO_VAD_DURATION = 7              # 최대 녹음 길이 (초) - 한국어 긴 문장 대응
AUDIO_VAD_SILENCE_TIMEOUT = 0.7     # 침묵 판단 시간 (초)

# --- 음악 플레이어 설정 ---
MUSIC_DEFAULT_VOLUME = 0.2          # 기본 볼륨
MUSIC_DUCKED_VOLUME = 0.05          # TTS 중 낮춘 볼륨 (ducking)
MUSIC_VOLUME_STEP = 0.1             # 볼륨 조절 단위

# --- 자가개발 설정 ---
CLAUDE_MODEL_DEV = "claude-opus-4-6"        # 자가개발용 최고 코딩 모델
SELF_DEV_IDLE_THRESHOLD_SEC = 300            # 5분 idle 후 개발 시작
SELF_DEV_IDLE_CHECK_SEC = 30                 # idle 체크 간격
SELF_DEV_API_MIN_INTERVAL_SEC = 10           # API 호출 최소 간격
SELF_DEV_FOLLOWUP_SEC = 15                   # 후속 응답 대기 시간
SELF_DEV_MAX_AGE_DAYS = 7                    # 오래된 세션 자동 정리
TASK_REQUEST_FILE = os.path.join(_PROJECT_ROOT, "O1", "self_dev", "task_request.json")

# --- Work Assistant 설정 ---
WORK_ASSISTANT_ENABLED = True
WORK_ASSISTANT_TRIGGER = "hhheeelllppp"
WORK_ASSISTANT_BUFFER_TIMEOUT_SEC = 5.0     # 키 입력 버퍼 타임아웃
WORK_ASSISTANT_DIALOG_TIMEOUT_SEC = 30      # 다이얼로그 자동 닫힘
WORK_ASSISTANT_TYPE_DELAY = 0.02            # 타이핑 딜레이
WORK_ASSISTANT_COOLDOWN_SEC = 30            # 연속 트리거 방지
WORK_ASSISTANT_MAX_CONTENT_CHARS = 50000    # 최대 분석 텍스트 길이

# --- WebSocket 메시지 타입 ---
class WSMessageType:
    """WebSocket 바이너리 메시지 타입 정의 (ESP32 프로토콜)"""
    CAMERA_FRAME = 0x01      # 글래스 → 서버: 카메라 프레임
    HUD_FRAME = 0x02         # 서버 → 글래스: HUD 프레임
    DEVICE_STATUS = 0x04     # 글래스 → 서버: 배터리/온도 등
    BUTTON_PRESS = 0x05      # 글래스 → 서버: 버튼 입력


# --- API 키 검증 함수 ---
def validate_api_keys():
    """필수 API 키 검증 - 누락 시 ValueError 발생"""
    required = {
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "ELEVENLABS_API_KEY": ELEVENLABS_API_KEY,
    }

    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"Missing required API keys in .env: {', '.join(missing)}")

    # 선택적 API 키 체크 (경고만)
    optional = {
        "TAVILY_API_KEY": TAVILY_API_KEY,
        "GOOGLE_API_KEY": GOOGLE_API_KEY,
    }
    for name, value in optional.items():
        if not value:
            print(f"⚠️  Optional API key not set: {name}")
