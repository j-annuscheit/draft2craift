from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QObject

from studio.controllers.speech_ctrl import SpeechController


pytestmark = pytest.mark.usefixtures("qt_app")


class _SignalStub:
    def __init__(self):
        self._slots: list = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class _FakeTTSManager:
    def __init__(self, _parent=None):
        self.status = _SignalStub()
        self.error = _SignalStub()
        self.speaking_changed = _SignalStub()
        self._speaking = False
        self.speak_calls: list[tuple[str, bool]] = []
        self.stop_calls = 0
        self.update_calls = 0

    def is_speaking(self) -> bool:
        return self._speaking

    def update_settings(self, _settings):
        self.update_calls += 1

    def speak(self, text: str, interrupt: bool = False):
        self.speak_calls.append((str(text), bool(interrupt)))
        self._speaking = True

    def stop(self):
        self.stop_calls += 1
        self._speaking = False


class _FakeWhisperWorker:
    def __init__(self, **_kwargs):
        self.started_ok = _SignalStub()
        self.stopped_ok = _SignalStub()
        self.status = _SignalStub()
        self.text_chunk = _SignalStub()
        self.failed = _SignalStub()
        self.finished = _SignalStub()
        self._running = False
        self.start_calls = 0
        self.stop_calls = 0

    def isRunning(self) -> bool:
        return self._running

    def start(self):
        self.start_calls += 1
        self._running = True

    def request_stop(self):
        self.stop_calls += 1
        self._running = False

    def wait(self, _timeout: int):
        return True


class SpeechControllerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tts_patcher = patch(
            "studio.controllers.speech_ctrl.TextToSpeechManager",
            _FakeTTSManager,
        )
        self._worker_patcher = patch(
            "studio.controllers.speech_ctrl.WhisperDictationWorker",
            _FakeWhisperWorker,
        )
        self._tts_patcher.start()
        self._worker_patcher.start()
        self.addCleanup(self._worker_patcher.stop)
        self.addCleanup(self._tts_patcher.stop)

    def _build_controller(self) -> tuple[SpeechController, Mock, Mock]:
        canvas = Mock()
        canvas.tabs = Mock()
        canvas.tabs.tab_widget = Mock()
        canvas.tabs.tab_widget.currentIndex.return_value = 0
        chat_dock = Mock()
        show_status = Mock()
        autosave_schedule = Mock()
        parent = QObject()

        controller = SpeechController(
            parent=parent,
            canvas=canvas,
            chat_dock=chat_dock,
            app_logger=Mock(),
            app_settings=Mock(),
            show_status=show_status,
            autosave_schedule_fn=autosave_schedule,
            on_tts_speaking_changed=Mock(),
        )
        controller._test_parent = parent
        return controller, show_status, autosave_schedule

    def test_start_whisper_dictation_starts_worker_and_marks_running(self):
        controller, show_status, _autosave = self._build_controller()
        controller._open_new_dictation_target_tab = Mock(return_value=Mock(editor=Mock()))

        controller.start_whisper_dictation()

        worker = controller._dictation_worker
        self.assertIsInstance(worker, _FakeWhisperWorker)
        assert worker is not None
        self.assertEqual(worker.start_calls, 1)
        self.assertTrue(controller.dictation_running)
        show_status.assert_any_call("Starte Whisper-Diktat…", 2500)

    def test_stop_whisper_dictation_when_inactive_reports_status(self):
        controller, show_status, _autosave = self._build_controller()
        controller._dictation_worker = None

        controller.stop_whisper_dictation()

        show_status.assert_called_once_with("Whisper-Diktat ist nicht aktiv.", 2000)

    def test_speak_draft_text_handles_empty_and_non_empty_payload(self):
        controller, show_status, _autosave = self._build_controller()

        controller.speak_draft_text(" ")
        show_status.assert_called_with("Draft ist leer.", 2000)

        controller.speak_draft_text("Hallo Welt")
        tts = controller.tts_manager
        self.assertIsInstance(tts, _FakeTTSManager)
        self.assertEqual(tts.speak_calls[-1], ("Hallo Welt", True))

    def test_chat_tts_mode_change_updates_settings_and_schedules_autosave(self):
        controller, _show_status, autosave = self._build_controller()

        controller.on_chat_tts_mode_changed("selection")

        self.assertEqual(controller.speech_settings.chat_tts_mode, "selection")
        autosave.assert_called_once_with(350)


if __name__ == "__main__":
    unittest.main()
