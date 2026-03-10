"""Non-blocking text-to-speech manager with simple backend fallbacks."""
from __future__ import annotations

from collections import deque
import subprocess
import threading

from PySide6.QtCore import QObject, QThread, Signal

from shared.config.app_settings import SpeechSettings

from .tts_parts import bind_speech_worker_methods
from .tts_parts.helpers_backend import (
    _espeak_cmd,
    _has_pyttsx3,
    _read_process_stderr,
    _resolve_tts_backend,
    _spd_say_cmd,
    _stop_process,
)
from .tts_parts.helpers_piper_audio import (
    _apply_start_trigger,
    _build_guard_pcm,
    _build_inter_segment_gap_pcm,
    _build_silence_pcm,
    _concat_wav_files,
    _new_temp_wav_path,
    _piper_lead_in_ms,
    _piper_length_scale,
    _prepend_wav_silence,
    _resolve_piper_model_path,
)
from .tts_parts.helpers_text import (
    _build_speech_jobs,
    _merge_units,
    _normalize_text_for_tts,
    _parse_pause_triggers,
    _split_for_trigger_pauses,
    _split_long_unit,
    _split_text_units,
    _split_unit_on_pause_triggers,
    _split_words,
)

class _SpeechWorker(QThread):
    """Speak one text chunk in a background thread."""

    status = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(
        self,
        text: str,
        settings: SpeechSettings,
        pause_after_ms: int = 0,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._text = str(text or "").strip()
        self._settings = SpeechSettings.from_dict(settings.to_dict())
        self._pause_after_ms = max(0, int(pause_after_ms))
        self._stop_requested = threading.Event()
        self._process: subprocess.Popen | None = None
        self._engine = None
        self._lock = threading.Lock()

bind_speech_worker_methods(_SpeechWorker)

class TextToSpeechManager(QObject):
    """Queue-based TTS manager used by GUI interactions."""

    status = Signal(str)
    error = Signal(str)
    speaking_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._settings = SpeechSettings()
        self._queue: deque[tuple[str, int]] = deque()
        self._worker: _SpeechWorker | None = None
        self._speaking = False

    def is_speaking(self) -> bool:
        return bool(self._speaking)

    def update_settings(self, settings: SpeechSettings):
        self._settings = SpeechSettings.from_dict(settings.to_dict())

    def speak(self, text: str, interrupt: bool = False):
        payload = str(text or "").strip()
        if not payload:
            return
        backend = _resolve_tts_backend(self._settings)
        jobs = _build_speech_jobs(
            payload,
            pause_ms=self._settings.tts_pause_ms,
            backend=backend,
            pause_triggers=self._settings.tts_pause_triggers,
        )
        if not jobs:
            return
        if interrupt:
            self.stop()
        self._queue.extend(jobs)
        self._pump()

    def stop(self):
        self._queue.clear()
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.request_stop()
            worker.wait(1500)
        self._worker = None
        self._set_speaking(False)

    def _pump(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._queue:
            return
        text, pause_after_ms = self._queue.popleft()
        worker = _SpeechWorker(
            text=text,
            settings=self._settings,
            pause_after_ms=pause_after_ms,
            parent=self,
        )
        worker.status.connect(self.status.emit)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        if not self._speaking:
            self._set_speaking(True)
            self.status.emit("TTS startet…")
        worker.start()

    def _on_worker_failed(self, message: str):
        self._queue.clear()
        msg = str(message or "").strip() or "Unbekannter TTS-Fehler."
        self.error.emit(msg)

    def _on_worker_finished(self):
        self._worker = None
        if self._queue:
            self._pump()
            return
        if self._speaking:
            self.status.emit("TTS fertig.")
        self._set_speaking(False)

    def _set_speaking(self, speaking: bool):
        next_state = bool(speaking)
        if self._speaking == next_state:
            return
        self._speaking = next_state
        self.speaking_changed.emit(self._speaking)

__all__ = [
    "TextToSpeechManager",
    "_SpeechWorker",
    "_build_speech_jobs",
    "_parse_pause_triggers",
    "_split_for_trigger_pauses",
    "_split_unit_on_pause_triggers",
    "_normalize_text_for_tts",
    "_split_text_units",
    "_merge_units",
    "_split_long_unit",
    "_split_words",
    "_resolve_tts_backend",
    "_resolve_piper_model_path",
    "_piper_length_scale",
    "_piper_lead_in_ms",
    "_apply_start_trigger",
    "_new_temp_wav_path",
    "_concat_wav_files",
    "_build_inter_segment_gap_pcm",
    "_build_silence_pcm",
    "_build_guard_pcm",
    "_prepend_wav_silence",
    "_has_pyttsx3",
    "_spd_say_cmd",
    "_espeak_cmd",
    "_read_process_stderr",
    "_stop_process",
]
