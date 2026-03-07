# ORION O1 - EDITH Smart Glasses AI

EDITH 스타일 AI 비서 스마트 글래스 시스템. 음성 인식, AI 대화, HUD 디스플레이, 자가개발 기능을 갖춘 macOS 네이티브 애플리케이션.

## Features

### Core
- **Voice Assistant** - "Hey Orion"으로 활성화, 자연어 대화
- **240x240 HUD** - EDITH 스타일 시안/초록 디스플레이 (시간, 날씨, 캘린더, AI 응답)
- **Calendar Integration** - macOS Calendar.app 연동, 일정 조회/요약
- **Music Player** - 음성으로 음악 재생/정지/볼륨 조절
- **Delivery Automation** - 음성으로 배달 주문 (LotteEatz)

### Advanced
- **Self-Development Engine** - idle 시 자동 코드 개선, HUD에서 기능 요청 가능
- **Work Assistant** - Chrome 페이지 분석 & 자동 채우기 (`hhheeelllppp` 트리거)
- **Schedule Reminder** - 매일 오전 8시 브리핑 + 이벤트 15분 전 알림
- **Hallucination Filter** - Whisper STT 환청 다단계 필터링

## Quick Start

### 1. Requirements
- macOS (Apple Silicon 권장)
- Python 3.12+
- icalBuddy (`brew install ical-buddy`)

### 2. Setup
```bash
# 의존성 설치
pip install -r O1/requirements.txt

# mlx-whisper 설치 (Apple Silicon, 선택)
pip install mlx-whisper

# .env 파일 생성
cat > .env << 'EOF'
ANTHROPIC_API_KEY=your_key
OPENAI_API_KEY=your_key
ELEVENLABS_API_KEY=your_key
TAVILY_API_KEY=your_key
GOOGLE_API_KEY=your_key
EOF
```

### 3. Run
```bash
python3 -m O1.main
```

HUD가 자동으로 뜨고, "Hey Orion"이라고 말하면 시작.

## Architecture

```
┌─────────────────────────────────────────────┐
│                  OrionO1                     │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌───────────┐  │
│  │ STT  │→│Brain │→│ TTS  │ │    HUD    │  │
│  │Whisper│ │Claude│ │11Labs│ │  240x240  │  │
│  └──────┘ └──────┘ └──────┘ └───────────┘  │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌───────────┐  │
│  │Music │ │ Cal  │ │Deliv.│ │  SelfDev  │  │
│  │Player│ │Sched.│ │Order │ │  Engine   │  │
│  └──────┘ └──────┘ └──────┘ └───────────┘  │
│  ┌────────────────┐ ┌────────────────────┐  │
│  │ Work Assistant │ │ FastAPI WebSocket  │  │
│  │  (hhheeelllppp)│ │   Server :8000    │  │
│  └────────────────┘ └────────────────────┘  │
└─────────────────────────────────────────────┘
         ↕ WebSocket              ↕ Audio
┌─────────────────┐    ┌──────────────────┐
│   HUD Client    │    │   Cleer ARC BT   │
│  (PyQt6 240x240)│    │    Microphone     │
└─────────────────┘    └──────────────────┘
```

## Project Structure

```
O1/
├── main.py              # Main orchestrator
├── config.py            # All configuration
├── core/                # Core modules (9)
│   ├── brain.py         # Claude AI conversation
│   ├── stt.py           # Whisper speech-to-text
│   ├── tts.py           # ElevenLabs text-to-speech
│   ├── calendar_manager.py
│   ├── scheduler.py     # Auto schedule reminders
│   ├── music_player.py
│   ├── wake_word.py
│   ├── delivery.py
│   ├── work_assistant.py
│   └── work_filler.py
├── hud/                 # HUD rendering (Pillow)
├── server/              # FastAPI WebSocket server
├── client/              # Desktop test clients
└── self_dev/            # Self-development system (10 modules)
```

## Voice Commands

| Command | Action |
|---------|--------|
| "Hey Orion" | Wake up |
| "Play [song name]" | Play music |
| "Stop music" | Stop music |
| "Volume up/down" | Adjust volume |
| "What's my schedule?" | Calendar query |
| "일정 요약" / "오늘 일정" | Schedule summary |
| "Order [food]" | Delivery order |
| "Goodbye" / "종료" | Shutdown |

## Work Assistant

Chrome 브라우저에서 `hhheeelllppp` 타이핑 시 페이지 자동 분석 & 작업 수행.

1. 수학 문제 → 풀이 과정 + 답 자동 채우기
2. 에세이 → 학생 수준 맞춰 작성
3. 퀴즈/폼 → 답 자동 입력

macOS 접근성 권한 필요: System Settings → Privacy → Accessibility → Python

## Self-Development

Orion이 idle 상태일 때 자동으로 코드를 개선하는 시스템.

- **자동 모드**: 5분 idle → 버그 수정/최적화 자동 실행
- **수동 모드**: HUD X 버튼 → 원하는 기능 요청
- **안전장치**: 스테이징 → 적용 → 커밋 2중 확인
- **기록**: `O1/self_dev/CHANGELOG.md`에 자동 기록

## Version History

| Version | Date | Feature |
|---------|------|---------|
| V1 | 2026-01-24 | Core: Claude API, Tavily, Notifications |
| V2 | 2026-01-26 | Screen capture analysis |
| V3 | 2026-01-28 | Camera input analysis |
| V4 | 2026-01-28 | ElevenLabs TTS |
| V5 | 2026-01-30 | Gesture control |
| V6 | 2026-01-30 | Music player |
| C1 | 2026-02-01 | Assistant identity |
| C2 | 2026-02-01 | Voice recognition |
| C3 | 2026-02-02 | Calendar integration |
| C4 | 2026-02-03 | Delivery automation |
| **O1** | **2026-02-18** | **Full rewrite: HUD, WebSocket, Self-Dev, Work Assistant** |

## Tech Stack

- **AI**: Claude (Haiku/Sonnet/Opus), Whisper (mlx/API), ElevenLabs TTS
- **Server**: FastAPI, WebSocket, uvicorn
- **HUD**: Pillow rendering → WebSocket → PyQt6 client
- **Audio**: sounddevice, pygame
- **Automation**: pynput (keyboard), AppleScript (macOS)
- **Browser**: Playwright (delivery), osascript (Work Assistant)

---

2026 Geonhee. All rights reserved.
