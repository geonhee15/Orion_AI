import os
import io
import wave
import tempfile
import numpy as np
import sounddevice as sd
from anthropic import Anthropic
from O1 import config


# Whisper 환청 필터
HALLUCINATIONS = {
    # YouTube 자막 환청
    "thanks for watching", "thank you for watching", "see you next week",
    "subscribe", "like and subscribe", "don't forget to subscribe",
    "hit the bell", "turn on notifications", "bye", "goodbye",

    # Whisper 특정 환청
    "thank you", "thanks", "you", "the end", "bye bye",
    "hi everyone this is", "what's your name", "good morning",
    "this is a", "okay", "so", "yeah",

    # 한국어 환청
    "감사합니다", "구독", "좋아요", "감사",
    "시청해 주셔서 감사합니다", "구독과 좋아요",

    # 다국어 환청 (Whisper 자동 감지 모드)
    "¡suscríbete!", "suscríbete", "gracias por ver",
    "merci", "danke", "arigato", "arigatou",
    "谢谢", "请订阅", "ありがとう",

    # 짧은 무의미 단어/음성
    "uh", "um", "hmm", "ah", "oh", "eh", "mhm",
    "huh", "uh huh", "mm", "mmm",

    # 기타 일반적 환청
    "rip headphone", "music", "applause", "laughter",
    "!", "...", "♪", "~",
}


def _strip_word(w):
    """개별 단어에서 구두점 제거"""
    return w.strip("!.,?;:\"'()[]{}~♪…·")


def _is_hallucination(text, audio_duration=None):
    """반복 패턴 + 알려진 환청 + 단어속도 감지"""
    from collections import Counter

    cleaned = text.lower().strip().rstrip("!.,?")

    # 1. 알려진 환청 완전 매칭
    if cleaned in HALLUCINATIONS:
        return True

    # 2. 부분 매칭 (긴 구문)
    for halluc in HALLUCINATIONS:
        if len(halluc) > 10 and halluc in cleaned:
            return True

    # 3. 구두점 제거 후 단어 분리
    words = [_strip_word(w) for w in cleaned.split() if _strip_word(w)]
    if len(words) == 0:
        return True

    # 4. 짧은 단어만 있는 경우 (한국어 제외 - 한국어는 2글자 단어가 정상)
    has_korean = any('\uac00' <= c <= '\ud7a3' for w in words for c in w)
    if not has_korean and all(len(w) <= 2 for w in words):
        return True

    # 5. 반복 단어 감지: 가장 많은 단어가 전체의 50% 이상이면 환청
    if len(words) >= 3:
        counts = Counter(words)
        most_common_word, most_common_count = counts.most_common(1)[0]
        if most_common_count >= len(words) * 0.5:
            print(f"  🚫 환청(반복): '{most_common_word}' x{most_common_count}/{len(words)}")
            return True

    # 6. 연속 반복 감지: 같은 단어가 3번 이상 연속
    if len(words) >= 3:
        for i in range(len(words) - 2):
            if words[i] == words[i + 1] == words[i + 2]:
                print(f"  🚫 환청(연속): '{words[i]}' x3+")
                return True

    # 7. 단어 속도 체크: 초당 5단어 초과 = 환청 (정상은 2~3단어/초)
    if audio_duration and audio_duration > 0:
        word_rate = len(words) / audio_duration
        if word_rate > 5.0:
            print(f"  🚫 환청(속도): {word_rate:.1f} words/sec ({len(words)}w / {audio_duration:.1f}s)")
            return True

    # 8. 너무 긴 텍스트: 200자 이상이면 환청 가능성 높음
    if len(cleaned) > 200:
        print(f"  🚫 환청(길이): {len(cleaned)}자")
        return True

    return False

# 로컬 mlx-whisper 로드 (Apple Silicon 최적화)
try:
    import mlx_whisper
    LOCAL_WHISPER = True
    print("✅ 로컬 Whisper (mlx) 로드됨")
except ImportError:
    LOCAL_WHISPER = False
    import requests
    print("⚠️ mlx-whisper 없음, API 사용")


class SpeechToText:
    """음성→텍스트 변환 (VAD + 로컬 Whisper)"""

    def __init__(self):
        self.sample_rate = 16000
        self.channels = 1
        self.chunk_size = 1600  # 100ms 청크
        self._anthropic = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self._last_audio_duration = 0  # 마지막 녹음 길이 (할루시네이션 감지용)
        self._setup_audio_device()

    def _setup_audio_device(self):
        """블루투스 이어폰(Cleer ARC) 마이크 자동 설정"""
        try:
            devices = sd.query_devices()
            input_device = None

            for i, dev in enumerate(devices):
                if "Cleer" in dev["name"] and dev["max_input_channels"] > 0:
                    input_device = i
                    print(f"🎧 블루투스 마이크: {dev['name']} (#{i})")
                    break

            if input_device is not None:
                sd.default.device[0] = input_device
            else:
                print("⚠️ Cleer ARC 없음, 기본 마이크 사용")
        except Exception as e:
            print(f"오디오 장치 설정 에러: {e}")

    def record(self, duration=4, silence_timeout=0.7, min_volume=0.015):
        """VAD 녹음: 소리 감지 → 말 끝나면 즉시 중단.

        개선: 말하기 전 무음 구간 제거, 최소 발화 시간 체크.
        """
        try:
            pre_speech_buffer = []  # 말하기 전 최근 2청크 보관 (맥락용)
            speech_chunks = []
            speech_started = False
            silence_chunks = 0
            speech_chunk_count = 0  # 실제 말한 청크 수
            max_chunks = int(duration * self.sample_rate / self.chunk_size)
            silence_limit = int(silence_timeout * self.sample_rate / self.chunk_size)
            speech_threshold = 0.012  # 상향 (0.008 → 0.012)
            min_speech_chunks = 3  # 최소 0.3초 발화

            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                blocksize=self.chunk_size,
                device=sd.default.device[0],
            )

            with stream:
                for _ in range(max_chunks):
                    chunk, _ = stream.read(self.chunk_size)
                    energy = np.sqrt(np.mean(chunk**2))

                    if energy > speech_threshold:
                        if not speech_started:
                            speech_started = True
                            # 직전 2청크를 포함 (말 시작 직전 컨텍스트)
                            speech_chunks.extend(pre_speech_buffer[-2:])
                        silence_chunks = 0
                        speech_chunk_count += 1
                        speech_chunks.append(chunk.copy())
                    elif speech_started:
                        silence_chunks += 1
                        speech_chunks.append(chunk.copy())
                        if silence_chunks >= silence_limit:
                            break
                    else:
                        # 말하기 전: 최근 2청크만 버퍼에 유지
                        pre_speech_buffer.append(chunk.copy())
                        if len(pre_speech_buffer) > 2:
                            pre_speech_buffer.pop(0)

            if not speech_chunks or not speech_started:
                return None

            # 최소 발화 시간 체크 (0.3초 미만이면 무시)
            if speech_chunk_count < min_speech_chunks:
                return None

            audio_data = np.concatenate(speech_chunks)
            volume = np.sqrt(np.mean(audio_data**2))

            if volume < min_volume:
                return None

            self._last_audio_duration = len(audio_data) / self.sample_rate
            print(f"🎤 {self._last_audio_duration:.1f}초 녹음 (볼륨: {volume:.4f})")
            return audio_data

        except Exception as e:
            print(f"녹음 에러: {e}")
            return None

    def transcribe(self, audio_data):
        """음성 → 텍스트. 로컬 mlx-whisper 우선, 없으면 API 폴백."""
        if LOCAL_WHISPER:
            return self._transcribe_local(audio_data)
        else:
            return self._transcribe_api(audio_data)

    def _transcribe_local(self, audio_data):
        """로컬 mlx-whisper로 변환 (~0.3초)"""
        try:
            audio_flat = audio_data.flatten()

            result = mlx_whisper.transcribe(
                audio_flat,
                path_or_hf_repo=config.WHISPER_MODEL,
                language="ko",
                initial_prompt="헤이 오리온. 오늘 일정 알려줘. 날씨 어때? Hey Orion.",
            )
            text = result.get("text", "").strip()
            print(f"📥 Whisper(local): '{text}'")

            # 1차 환청 필터 (원본)
            if len(text) < 2 or _is_hallucination(text, self._last_audio_duration):
                return None

            # Claude 보정
            corrected = self._correct_transcription(text)

            # 2차 환청 필터 (보정 후) - Claude가 환청을 "살리는" 것 방지
            if corrected and _is_hallucination(corrected, self._last_audio_duration):
                print(f"  🚫 보정 후 환청 감지: '{corrected}'")
                return None

            return corrected
        except Exception as e:
            print(f"로컬 Whisper 에러: {e}")
            return self._transcribe_api(audio_data)

    def _transcribe_api(self, audio_data):
        """OpenAI Whisper API 폴백"""
        if not config.OPENAI_API_KEY:
            return None

        temp_path = None  # 임시 파일 경로 초기화
        try:
            wav_bytes = self._to_wav_bytes(audio_data)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                temp_path = f.name

            with open(temp_path, "rb") as audio_file:
                response = requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                    files={"file": audio_file},
                    data={"model": "whisper-1", "language": "ko", "prompt": "헤이 오리온. 오늘 일정 알려줘. Hey Orion."},
                )

            if response.status_code == 200:
                text = response.json().get("text", "")
                print(f"📥 Whisper(API): '{text}'")
                if len(text) < 2 or _is_hallucination(text, self._last_audio_duration):
                    return None
                corrected = self._correct_transcription(text)
                if corrected and _is_hallucination(corrected, self._last_audio_duration):
                    print(f"  🚫 보정 후 환청 감지: '{corrected}'")
                    return None
                return corrected
            return None
        except Exception as e:
            print(f"Whisper API 에러: {e}")
            return None
        finally:
            # 임시 파일 안전하게 삭제
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass  # 삭제 실패 시 무시

    def _correct_transcription(self, raw_text):
        """Claude Haiku로 STT 오류 보정 (Gemini Live 방식)"""
        try:
            response = self._anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{
                    "role": "user",
                    "content": (
                        f"다음은 음성 인식 결과입니다. 오타나 오인식이 있으면 바로잡아주세요. "
                        f"원문의 의미를 유지하되, 명백한 STT 오류만 수정하세요. "
                        f"수정할 게 없으면 원문 그대로 출력하세요.\n\n"
                        f"원문: {raw_text}\n보정:"
                    ),
                }],
            )
            corrected = response.content[0].text.strip()
            if corrected and len(corrected) > 1:
                if corrected != raw_text:
                    print(f"  ✏️ 보정: '{raw_text}' → '{corrected}'")
                return corrected
            return raw_text
        except Exception as e:
            print(f"  ⚠️ 보정 실패: {e}")
            return raw_text

    def _to_wav_bytes(self, audio_data):
        """numpy float32 배열 → WAV 바이트"""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            audio_int16 = (audio_data * 32767).astype(np.int16)
            wf.writeframes(audio_int16.tobytes())
        buffer.seek(0)
        return buffer.read()
