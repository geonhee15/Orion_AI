import os
import io
import wave
import queue
import tempfile
import threading
import numpy as np
import sounddevice as sd
from anthropic import Anthropic
from Workspace import config


# Whisper 환청 필터
HALLUCINATIONS = {
    "thanks for watching", "thank you for watching", "see you next week",
    "subscribe", "like and subscribe", "don't forget to subscribe",
    "hit the bell", "turn on notifications", "bye", "goodbye",
    "thank you", "thanks", "you", "the end", "bye bye",
    "hi everyone this is", "what's your name", "good morning",
    "this is a", "okay", "so", "yeah",
    "감사합니다", "구독", "좋아요", "감사",
    "시청해 주셔서 감사합니다", "구독과 좋아요",
    "¡suscríbete!", "suscríbete", "gracias por ver",
    "merci", "danke", "arigato", "arigatou",
    "谢谢", "请订阅", "ありがとう",
    "uh", "um", "hmm", "ah", "oh", "eh", "mhm",
    "huh", "uh huh", "mm", "mmm",
    "rip headphone", "music", "applause", "laughter",
    "!", "...", "♪", "~",
}


def _strip_word(w):
    return w.strip("!.,?;:\"'()[]{}~♪…·")


def _is_hallucination(text, audio_duration=None):
    from collections import Counter

    cleaned = text.lower().strip().rstrip("!.,?")

    if cleaned in HALLUCINATIONS:
        return True

    for halluc in HALLUCINATIONS:
        if len(halluc) > 10 and halluc in cleaned:
            return True

    words = [_strip_word(w) for w in cleaned.split() if _strip_word(w)]
    if len(words) == 0:
        return True

    has_korean = any('\uac00' <= c <= '\ud7a3' for w in words for c in w)
    if not has_korean and all(len(w) <= 2 for w in words):
        return True

    if len(words) >= 3:
        counts = Counter(words)
        most_common_word, most_common_count = counts.most_common(1)[0]
        if most_common_count >= len(words) * 0.5:
            print(f"  🚫 환청(반복): '{most_common_word}' x{most_common_count}/{len(words)}")
            return True

    if len(words) >= 3:
        for i in range(len(words) - 2):
            if words[i] == words[i + 1] == words[i + 2]:
                print(f"  🚫 환청(연속): '{words[i]}' x3+")
                return True

    if audio_duration and audio_duration > 0:
        word_rate = len(words) / audio_duration
        if word_rate > 5.0:
            print(f"  🚫 환청(속도): {word_rate:.1f} words/sec ({len(words)}w / {audio_duration:.1f}s)")
            return True

    if len(cleaned) > 200:
        print(f"  🚫 환청(길이): {len(cleaned)}자")
        return True

    return False

# 로컬 mlx-whisper 로드
try:
    import mlx_whisper
    LOCAL_WHISPER = True
    print("✅ 로컬 Whisper (mlx) 로드됨")
except ImportError:
    LOCAL_WHISPER = False
    import requests
    print("⚠️ mlx-whisper 없음, API 사용")


class SpeechToText:
    """음성→텍스트 변환 — 연속 듣기 모드 (상시 오픈 스트림 + VAD + 큐)"""

    def __init__(self):
        self.sample_rate = 16000
        self.channels = 1
        self.chunk_size = 1600  # 100ms 청크
        self._anthropic = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self._last_audio_duration = 0
        self._setup_audio_device()

        # 연속 듣기 상태
        self._listening = False
        self._speech_queue = queue.Queue()

        # 동적 파라미터 (메인 스레드에서 실시간 변경 가능)
        self.min_volume = config.AUDIO_NORMAL_THRESHOLD
        self.max_duration = config.AUDIO_VAD_DURATION
        self.paused = False  # True면 VAD가 모든 오디오 무시

    def _setup_audio_device(self):
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

    # ─── 연속 듣기 API ───

    def start_continuous(self):
        """연속 듣기 시작 — 스트림 상시 오픈, VAD 상시 실행"""
        if self._listening:
            return
        self._listening = True
        thread = threading.Thread(target=self._continuous_vad_loop, daemon=True)
        thread.start()
        print("🎙️ 연속 듣기 모드 시작")

    def stop_continuous(self):
        """연속 듣기 중지"""
        self._listening = False

    def get_speech(self, timeout=0.5):
        """큐에서 다음 음성 세그먼트 가져오기. 없으면 None."""
        try:
            return self._speech_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush_queue(self):
        """큐에 쌓인 오래된 음성 세그먼트 비우기"""
        while not self._speech_queue.empty():
            try:
                self._speech_queue.get_nowait()
            except queue.Empty:
                break

    # ─── 연속 VAD 루프 ───

    def _continuous_vad_loop(self):
        """상시 오픈 스트림으로 연속 VAD — 음성 감지 시 큐에 전달"""
        speech_threshold = 0.012
        min_speech_chunks = 3
        silence_timeout = config.AUDIO_VAD_SILENCE_TIMEOUT

        try:
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                blocksize=self.chunk_size,
                device=sd.default.device[0],
            )
        except Exception as e:
            print(f"🚨 오디오 스트림 열기 실패: {e}")
            self._listening = False
            return

        # VAD 상태
        pre_buffer = []
        speech_chunks = []
        speech_started = False
        speech_count = 0
        silence_chunks = 0
        silence_limit = int(silence_timeout * self.sample_rate / self.chunk_size)

        with stream:
            while self._listening:
                try:
                    chunk, _ = stream.read(self.chunk_size)
                except Exception:
                    continue

                # paused 상태면 VAD 리셋하고 스킵
                if self.paused:
                    if speech_started:
                        speech_started = False
                        speech_chunks = []
                        speech_count = 0
                        silence_chunks = 0
                    pre_buffer.clear()
                    continue

                energy = float(np.sqrt(np.mean(chunk ** 2)))

                if energy > speech_threshold:
                    # 음성 감지
                    if not speech_started:
                        speech_started = True
                        speech_chunks = list(pre_buffer[-2:])  # 직전 200ms 포함
                    speech_chunks.append(chunk.copy())
                    speech_count += 1
                    silence_chunks = 0

                    # 최대 녹음 길이 초과 → 강제 전달
                    duration = len(speech_chunks) * self.chunk_size / self.sample_rate
                    if duration >= self.max_duration:
                        self._deliver_speech(speech_chunks, speech_count, min_speech_chunks)
                        speech_started = False
                        speech_chunks = []
                        speech_count = 0
                        silence_chunks = 0
                        pre_buffer.clear()

                elif speech_started:
                    # 음성 중 침묵
                    silence_chunks += 1
                    speech_chunks.append(chunk.copy())
                    if silence_chunks >= silence_limit:
                        # 말 끝남 → 큐에 전달
                        self._deliver_speech(speech_chunks, speech_count, min_speech_chunks)
                        speech_started = False
                        speech_chunks = []
                        speech_count = 0
                        silence_chunks = 0
                        pre_buffer.clear()
                else:
                    # 대기 중 — pre-speech 버퍼 유지
                    pre_buffer.append(chunk.copy())
                    if len(pre_buffer) > 3:
                        pre_buffer.pop(0)

        print("🎙️ 연속 듣기 모드 종료")

    def _deliver_speech(self, speech_chunks, speech_count, min_speech_chunks):
        """음성 세그먼트 검증 후 큐에 전달"""
        if speech_count < min_speech_chunks:
            return

        audio_data = np.concatenate(speech_chunks)
        volume = float(np.sqrt(np.mean(audio_data ** 2)))

        if volume < self.min_volume:
            return

        self._last_audio_duration = len(audio_data) / self.sample_rate
        print(f"🎤 {self._last_audio_duration:.1f}초 녹음 (볼륨: {volume:.4f})")
        self._speech_queue.put(audio_data)

    # ─── 기존 record() (폴백/특수 용도) ───

    def record(self, duration=4, silence_timeout=0.7, min_volume=0.015):
        """단발 녹음 (연속 듣기 중이면 큐에서 가져옴)"""
        if self._listening:
            old_max = self.max_duration
            self.max_duration = duration
            result = self.get_speech(timeout=duration + 2)
            self.max_duration = old_max
            return result

        # 연속 듣기 비활성화 시 레거시 방식
        try:
            pre_speech_buffer = []
            speech_chunks = []
            speech_started = False
            silence_chunks = 0
            speech_chunk_count = 0
            max_chunks = int(duration * self.sample_rate / self.chunk_size)
            silence_limit = int(silence_timeout * self.sample_rate / self.chunk_size)
            speech_threshold = 0.012
            min_speech_chunks = 3

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
                        pre_speech_buffer.append(chunk.copy())
                        if len(pre_speech_buffer) > 2:
                            pre_speech_buffer.pop(0)

            if not speech_chunks or not speech_started:
                return None
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

    # ─── Transcription ───

    def transcribe(self, audio_data):
        if LOCAL_WHISPER:
            return self._transcribe_local(audio_data)
        else:
            return self._transcribe_api(audio_data)

    def _transcribe_local(self, audio_data):
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

            if len(text) < 2 or _is_hallucination(text, self._last_audio_duration):
                return None

            corrected = self._correct_transcription(text)

            if corrected and _is_hallucination(corrected, self._last_audio_duration):
                print(f"  🚫 보정 후 환청 감지: '{corrected}'")
                return None

            return corrected
        except Exception as e:
            print(f"로컬 Whisper 에러: {e}")
            return self._transcribe_api(audio_data)

    def _transcribe_api(self, audio_data):
        if not config.OPENAI_API_KEY:
            return None

        temp_path = None
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
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def _correct_transcription(self, raw_text):
        try:
            response = self._anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{
                    "role": "user",
                    "content": (
                        f"STT 보정 작업. 규칙:\n"
                        f"1. 명백한 STT 오류만 수정\n"
                        f"2. 보정된 문장만 출력. 설명, 괄호, 주석, 부연 절대 금지\n"
                        f"3. 수정할 게 없으면 원문을 그대로 출력\n\n"
                        f"{raw_text}"
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
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            audio_int16 = (audio_data * 32767).astype(np.int16)
            wf.writeframes(audio_int16.tobytes())
        buffer.seek(0)
        return buffer.read()
