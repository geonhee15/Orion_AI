# Orion AI - Project Guide for Claude

## Overview

Orion은 EDITH 스타일 스마트 글래스 AI 비서 프로젝트. macOS에서 음성 인식 → Claude AI → TTS 응답 + HUD 디스플레이 파이프라인으로 동작한다.

## Project Structure

```
Orion_AI/
├── O1/                        # 현재 메인 버전
│   ├── main.py                # 메인 오케스트레이터 (OrionO1 클래스)
│   ├── config.py              # 전체 설정 (API 키, 모델, 오디오, HUD, 자가개발 등)
│   ├── requirements.txt       # Python 의존성
│   │
│   ├── core/                  # 핵심 모듈
│   │   ├── brain.py           # Claude AI 대화 엔진 (Tavily 검색 통합)
│   │   ├── stt.py             # Whisper STT (mlx-whisper 로컬 + API 폴백)
│   │   ├── tts.py             # ElevenLabs TTS (스트리밍, 음악 ducking)
│   │   ├── calendar_manager.py # macOS Calendar.app 연동 (icalBuddy)
│   │   ├── music_player.py    # 음악 재생 + 볼륨 제어
│   │   ├── wake_word.py       # 웨이크워드 감지 + 쿼리 분류
│   │   ├── delivery.py        # 배달 주문 자동화 (Playwright)
│   │   ├── scheduler.py       # 일정 자동 브리핑 + 리마인더
│   │   ├── work_assistant.py  # Work Assistant (hhheeelllppp 트리거)
│   │   └── work_filler.py     # 페이지 타입별 자동 채우기
│   │
│   ├── hud/                   # HUD 렌더링 (240x240 EDITH 스타일)
│   │   ├── renderer.py        # HUD 프레임 생성 (Pillow)
│   │   ├── widgets.py         # 위젯 드로잉 (상태바, 날씨, 캘린더, 알림, 진행률)
│   │   └── layout.py          # 레이아웃 상수
│   │
│   ├── server/                # FastAPI WebSocket 서버
│   │   ├── app.py             # WebSocket 엔드포인트 (/ws/glass, /ws/test)
│   │   ├── ws_manager.py      # WebSocket 연결 관리
│   │   └── vision.py          # 카메라 프레임 분석
│   │
│   ├── client/                # 테스트 클라이언트
│   │   ├── test_hud.py        # PyQt6 데스크탑 HUD 시뮬레이터
│   │   └── esp32_simulator.py # ESP32 글래스 시뮬레이터
│   │
│   └── self_dev/              # 자가개발 시스템 (10 모듈)
│       ├── engine.py          # 메인 오케스트레이터 (분석→계획→코딩→검증→스테이징)
│       ├── analyzer.py        # 코드베이스 분석기
│       ├── planner.py         # 태스크 생성 (Claude Opus)
│       ├── coder.py           # 코드 생성기 (Claude Opus)
│       ├── validator.py       # 코드 검증 (경로 보안, 구문 체크)
│       ├── staging.py         # 변경사항 스테이징/적용/롤백/커밋
│       ├── history.py         # 개발 이력 관리 (JSON)
│       ├── idle_monitor.py    # 사용자 idle 감지
│       ├── prompts.py         # AI 프롬프트 모음
│       └── utils.py           # JSON 추출 유틸리티
│
├── .env                       # API 키 (git 제외)
├── user_profile.txt           # 사용자 프로필
├── Music/                     # 음악 파일
└── UpdateLog.txt              # 버전 히스토리
```

## Key Architecture

### 메인 루프 (main.py)
- `OrionO1.run()` → 서버 시작 → HUD 클라이언트 시작 → `audio_loop()` (메인 블로킹)
- `audio_loop()`: VAD 녹음 → Whisper STT → 웨이크워드 감지 → `process_command()` → TTS 응답
- 에코 방지: TTS 후 쿨다운 + 고감도 볼륨 필터

### AI 모델 사용
- `claude-haiku-4-5-20251001`: 빠른 응답, STT 보정
- `claude-sonnet-4-5-20250929`: 복잡한 분석, Work Assistant
- `claude-opus-4-6`: 자가개발 코드 생성

### 자가개발 시스템
- 사용자 idle 5분 → 자동 코드 개선 시작
- HUD X 버튼으로 기능 요청 가능
- 2중 확인 (apply → commit) 안전장치
- CHANGELOG.md 자동 생성

### Work Assistant
- 트리거: 키보드로 `hhheeelllppp` 입력
- 플로우: Chrome 내용 추출 → Claude 분석 → 알림 → 자동 채우기
- 수학/에세이/퀴즈/폼 타입별 전략

## Commands

```bash
# 실행
python3 -m O1.main

# HUD 클라이언트만 (별도 터미널)
python3 -m O1.client.test_hud

# 의존성 설치
pip install -r O1/requirements.txt
```

## Conventions

- 언어: 코드는 영어, 주석/로그는 한국어+영어 혼용
- 설정: 모든 상수는 `config.py`에 집중
- 에러 처리: 조용히 실패 (print 로그만, 크래시 방지)
- 스레딩: 데몬 스레드 + Lock 패턴 (self_dev, work_assistant)
- macOS 전용: osascript, icalBuddy, afplay 등 macOS API 사용
- HUD: 240x240, EDITH 스타일 시안/초록 색상 팔레트

## Important Notes

- `.env` 파일에 ANTHROPIC_API_KEY, OPENAI_API_KEY, ELEVENLABS_API_KEY 필수
- mlx-whisper가 있으면 로컬 STT, 없으면 OpenAI API 폴백
- Work Assistant는 macOS 접근성 권한 필요 (pynput)
- 자가개발 결과는 `O1/self_dev/staging/`에 저장, 수동 확인 후 적용
