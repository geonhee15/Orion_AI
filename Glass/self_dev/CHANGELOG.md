# Orion Self-Dev Changelog

자가개발 시스템이 자동 생성한 개발 기록입니다.

---

## [dev_1771418650] Fix music play command extraction bug
- **날짜**: 2026-02-18 21:44
- **타입**: bug_fix
- **요약**: Fixed the music play command extraction bug in process_command(). The original code had two separate keyword lists (one in the `any()` guard check and another in the inner `for` loop) that could mismatch, and the inner loop never broke after finding a match. The fix consolidates detection and extraction into a single helper method `_extract_music_query()` that iterates keywords longest-first, returns the song name on the first match, and eliminates the dual-list inconsistency entirely.
- **변경 파일**:
  - `O1/main.py`
---

## [dev_1771419776] Add automatic schedule summary and reminder system
- **날짜**: 2026-02-18 22:03
- **타입**: new_feature
- **상태**: applied
- **요약**: Implemented automatic schedule summary and reminder system. Created O1/core/scheduler.py with ScheduleReminder class that provides morning daily briefings at 08:00 (configurable) using Claude summarization, and per-event reminders every 5 minutes for events within the next 15 minutes. Added get_events_as_list() method to MacCalendar that returns structured event data with datetime objects for programmatic time comparison. Integrated the scheduler into main.py with proper lifecycle management (daemon threads, start/stop), and added voice command detection for on-demand schedule summaries via keywords like '일정 요약', '오늘 일정', 'schedule summary', and 'daily briefing'.
- **변경 파일**:
  - `O1/core/calendar_manager.py` — Added get_events_as_list() and time parsing helpers
  - `O1/core/scheduler.py` — Created new scheduler module with ScheduleReminder class
  - `O1/main.py` — Integrated ScheduleReminder into OrionO1 lifecycle + voice command support
---

## [dev_1771420016] Fix music play command matching extracting wrong substring
- **날짜**: 2026-02-18 22:07
- **타입**: bug_fix
- **요약**: Fixed a bug in process_command where the music play keyword loop would continue iterating after finding a match, potentially causing the song name to be overwritten or missed. The fix restructures the loop to break on the first matching keyword and moves the play/error handling outside the keyword loop.
- **변경 파일**:
  - `O1/main.py`
---

## [dev_1771424136] Fix unclosed resource and missing exception handling in audio_loop
- **날짜**: 2026-02-18 23:15
- **타입**: bug_fix
- **요약**: Fixed two issues in audio_loop: 1) The KeyboardInterrupt handler now sets self.is_running = False before breaking, ensuring the shutdown path in run() triggers process_command('goodbye') cleanly. 2) The generic Exception handler now calls traceback.print_exc() for full stack trace diagnostics. Added 'import traceback' at the top of main.py to support this.
- **변경 파일**:
  - `O1/main.py` — Added 'import traceback' at top. In audio_loop KeyboardInterrupt handler, set self.is_running = False before break for clean shutdown. In generic Exception handler, added traceback.print_exc() for better diagnostics.
---
