import os
import pygame
from Workspace import config


class MusicPlayer:
    """pygame 기반 음악 플레이어 (볼륨 ducking 지원)"""

    def __init__(self):
        pygame.mixer.init()
        self.is_playing = False
        self.current_song = None
        self.normal_volume = config.MUSIC_DEFAULT_VOLUME
        self.ducked_volume = config.MUSIC_DUCKED_VOLUME
        self._music_cache = {}
        self._refresh_music_cache()

    def _refresh_music_cache(self):
        self._music_cache.clear()
        if not os.path.exists(config.MUSIC_FOLDER):
            return

        try:
            for filename in os.listdir(config.MUSIC_FOLDER):
                if not filename.lower().endswith(".mp3"):
                    continue
                normalized = filename[:-4].lower().replace(" ", "_")
                filepath = os.path.join(config.MUSIC_FOLDER, filename)
                self._music_cache[normalized] = filepath
        except Exception as e:
            print(f"⚠️ 음악 캐시 생성 실패: {e}")

    def duck(self):
        if self.is_playing:
            pygame.mixer.music.set_volume(self.ducked_volume)

    def unduck(self):
        if self.is_playing:
            pygame.mixer.music.set_volume(self.normal_volume)

    def play(self, song_name):
        self.stop()

        normalized = song_name.strip().lower().replace(" ", "_")
        if normalized.endswith(".mp3"):
            normalized = normalized[:-4]

        filepath = None

        if normalized in self._music_cache:
            filepath = self._music_cache[normalized]
        else:
            for cached_name, cached_path in self._music_cache.items():
                if normalized in cached_name or cached_name in normalized:
                    filepath = cached_path
                    break

        if not filepath:
            self._refresh_music_cache()
            if normalized in self._music_cache:
                filepath = self._music_cache[normalized]

        if not filepath or not os.path.exists(filepath):
            return False

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
