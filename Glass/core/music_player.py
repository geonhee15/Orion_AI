import os
import pygame
from Glass import config


class MusicPlayer:
    """pygame 기반 음악 플레이어 (볼륨 ducking 지원)"""

    def __init__(self):
        pygame.mixer.init()
        self.is_playing = False
        self.current_song = None
        self.normal_volume = config.MUSIC_DEFAULT_VOLUME
        self.ducked_volume = config.MUSIC_DUCKED_VOLUME
        self._music_cache = {}  # {normalized_name: filepath}
        self._refresh_music_cache()

    def _refresh_music_cache(self):
        """Music 폴더 스캔하여 캐시 생성"""
        self._music_cache.clear()
        if not os.path.exists(config.MUSIC_FOLDER):
            return

        try:
            for filename in os.listdir(config.MUSIC_FOLDER):
                if not filename.lower().endswith(".mp3"):
                    continue

                # 정규화된 이름: 확장자 제거, 소문자, 공백→언더스코어
                normalized = filename[:-4].lower().replace(" ", "_")
                filepath = os.path.join(config.MUSIC_FOLDER, filename)
                self._music_cache[normalized] = filepath
        except Exception as e:
            print(f"⚠️ 음악 캐시 생성 실패: {e}")

    def duck(self):
        """TTS 중 볼륨 낮추기"""
        if self.is_playing:
            pygame.mixer.music.set_volume(self.ducked_volume)

    def unduck(self):
        """TTS 후 볼륨 복구"""
        if self.is_playing:
            pygame.mixer.music.set_volume(self.normal_volume)

    def play(self, song_name):
        """노래 재생 (무한 반복) - 캐시 기반 검색"""
        self.stop()

        # 입력 정규화 (확장자 제거, 소문자, 공백→언더스코어)
        normalized = song_name.strip().lower().replace(" ", "_")
        if normalized.endswith(".mp3"):
            normalized = normalized[:-4]

        filepath = None

        # 1. 캐시에서 정확히 일치하는 항목 찾기 (O(1))
        if normalized in self._music_cache:
            filepath = self._music_cache[normalized]
        else:
            # 2. 부분 매칭 시도 (정규화된 이름이 파일명에 포함)
            for cached_name, cached_path in self._music_cache.items():
                if normalized in cached_name or cached_name in normalized:
                    filepath = cached_path
                    break

        # 3. 여전히 없으면 캐시 새로고침 후 재시도
        if not filepath:
            self._refresh_music_cache()
            if normalized in self._music_cache:
                filepath = self._music_cache[normalized]

        # 4. 파일을 찾지 못한 경우
        if not filepath or not os.path.exists(filepath):
            return False

        # 5. 재생 시도
        try:
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.set_volume(self.normal_volume)
            pygame.mixer.music.play(loops=-1)
            self.is_playing = True
            self.current_song = song_name
            return True
        except Exception as e:
            print(f"⚠️ 음악 재생 실패: {e}")
            return False

    def stop(self):
        """재생 중지"""
        if self.is_playing:
            pygame.mixer.music.stop()
        self.is_playing = False
        self.current_song = None

    def volume_up(self):
        self.normal_volume = min(1.0, self.normal_volume + config.MUSIC_VOLUME_STEP)
        pygame.mixer.music.set_volume(self.normal_volume)

    def volume_down(self):
        self.normal_volume = max(0.0, self.normal_volume - config.MUSIC_VOLUME_STEP)
        pygame.mixer.music.set_volume(self.normal_volume)
