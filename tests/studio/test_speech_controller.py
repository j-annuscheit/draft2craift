from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

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
        canvas.tabs.current_panel.return_value = None
        canvas.parentWidget.return_value = None
        knowledge_dock = Mock()
        knowledge_dock.tab_widget = Mock()
        knowledge_dock.doc_viewer = Mock()
        knowledge_dock.rag_tab = Mock()
        knowledge_dock.rag_panel = Mock()
        knowledge_dock.doc_viewer.tabs = Mock()
        knowledge_dock.doc_viewer.tabs.current_panel.return_value = None
        knowledge_dock.rag_panel.tabs = Mock()
        knowledge_dock.rag_panel.tabs.current_panel.return_value = None
        knowledge_dock.tab_widget.currentWidget.return_value = None
        knowledge_dock.parentWidget.return_value = None
        chat_dock = Mock()
        chat_dock.parentWidget.return_value = None
        show_status = Mock()
        autosave_schedule = Mock()
        parent = QObject()

        controller = SpeechController(
            parent=parent,
            canvas=canvas,
            knowledge_dock=knowledge_dock,
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

    def test_speak_selection_text_handles_empty_and_non_empty_payload(self):
        controller, show_status, _autosave = self._build_controller()

        controller.speak_selection_text(" ")
        show_status.assert_called_with("Keine Auswahl zum Vorlesen.", 2000)

        controller.speak_selection_text("Markierung")
        tts = controller.tts_manager
        self.assertIsInstance(tts, _FakeTTSManager)
        self.assertEqual(tts.speak_calls[-1], ("Markierung", True))

    def test_chat_tts_mode_change_updates_settings_and_schedules_autosave(self):
        controller, _show_status, autosave = self._build_controller()

        controller.on_chat_tts_mode_changed("selection")

        self.assertEqual(controller.speech_settings.chat_tts_mode, "selection")
        autosave.assert_called_once_with(350)

    def test_speak_active_workspace_text_prefers_selection(self):
        controller, show_status, _autosave = self._build_controller()

        panel = QWidget()
        panel.editor = _EditorStub("Alpha\nBeta line")
        panel.get_preview_selected_text = lambda: ""
        panel.editor.select_span("Beta")
        controller._last_workspace_panel = panel

        with patch("studio.controllers.speech_ctrl.QApplication.focusWidget", return_value=None):
            controller.speak_active_workspace_text()

        tts = controller.tts_manager
        self.assertIsInstance(tts, _FakeTTSManager)
        self.assertEqual(tts.speak_calls[-1], ("Beta", True))
        show_status.assert_not_called()

    def test_speak_active_workspace_text_falls_back_to_full_panel_text(self):
        controller, show_status, _autosave = self._build_controller()

        panel = QWidget()
        panel.editor = _EditorStub("Alpha\nBeta line")
        panel.get_preview_selected_text = lambda: ""
        panel.editor.move_cursor_to("line")
        controller._last_workspace_panel = panel

        with patch("studio.controllers.speech_ctrl.QApplication.focusWidget", return_value=None):
            controller.speak_active_workspace_text()

        tts = controller.tts_manager
        self.assertIsInstance(tts, _FakeTTSManager)
        self.assertEqual(tts.speak_calls[-1], ("Alpha\nBeta line", True))
        show_status.assert_not_called()

    def test_speak_active_workspace_text_reports_missing_payload(self):
        controller, show_status, _autosave = self._build_controller()

        panel = QWidget()
        panel.editor = _EditorStub("")
        panel.get_preview_selected_text = lambda: ""
        controller._last_workspace_panel = panel

        with patch("studio.controllers.speech_ctrl.QApplication.focusWidget", return_value=None):
            controller.speak_active_workspace_text()

        tts = controller.tts_manager
        self.assertIsInstance(tts, _FakeTTSManager)
        self.assertEqual(tts.speak_calls, [])
        show_status.assert_called_once_with(
            "Keine Markierung oder Text im aktiven Draft/Viewer/RAG gefunden.",
            2500,
        )

    def test_speak_active_workspace_text_uses_cached_selection_on_focus_loss(self):
        controller, show_status, _autosave = self._build_controller()

        panel = QWidget()
        panel.editor = _EditorStub("Alpha\nBeta line")
        panel.get_preview_selected_text = lambda: ""
        panel.editor.select_span("Beta")
        controller._canvas.tabs.current_panel.return_value = panel

        old_focus = _FocusWidget(parent=controller._canvas)
        controller._on_focus_changed(old_focus, None)
        panel.editor.move_cursor_to("line")

        with patch("studio.controllers.speech_ctrl.QApplication.focusWidget", return_value=None):
            controller.speak_active_workspace_text()

        tts = controller.tts_manager
        self.assertIsInstance(tts, _FakeTTSManager)
        self.assertEqual(tts.speak_calls[-1], ("Beta", True))
        show_status.assert_not_called()

    def test_workspace_cached_selection_is_cleared_when_refocusing_without_selection(self):
        controller, show_status, _autosave = self._build_controller()

        panel = QWidget()
        panel.editor = _EditorStub("Alpha\nGamma line")
        panel.get_preview_selected_text = lambda: ""
        panel.editor.select_span("Alpha")
        controller._canvas.tabs.current_panel.return_value = panel

        old_focus = _FocusWidget(parent=controller._canvas)
        controller._on_focus_changed(old_focus, None)
        panel.editor.move_cursor_to("Gamma")
        new_focus = _FocusWidget(parent=controller._canvas)
        controller._on_focus_changed(None, new_focus)

        with patch("studio.controllers.speech_ctrl.QApplication.focusWidget", return_value=new_focus):
            controller.speak_active_workspace_text()

        tts = controller.tts_manager
        self.assertIsInstance(tts, _FakeTTSManager)
        self.assertEqual(tts.speak_calls[-1], ("Alpha\nGamma line", True))
        show_status.assert_not_called()

    def test_knowledge_selection_is_preferred_over_canvas_when_menu_steals_focus(self):
        controller, show_status, _autosave = self._build_controller()

        canvas_panel = QWidget()
        canvas_panel.editor = _EditorStub("Canvas only")
        canvas_panel.get_preview_selected_text = lambda: ""
        canvas_panel.editor.select_span("Canvas")
        controller._canvas.tabs.current_panel.return_value = canvas_panel

        knowledge_panel = QWidget()
        knowledge_panel.editor = _EditorStub("Knowledge hit")
        knowledge_panel.get_preview_selected_text = lambda: ""
        knowledge_panel.editor.select_span("Knowledge")

        controller._knowledge_dock.rag_panel.tabs.current_panel.return_value = knowledge_panel
        controller._knowledge_dock.tab_widget.currentWidget.return_value = controller._knowledge_dock.rag_tab
        controller._last_workspace_panel = canvas_panel

        with patch("studio.controllers.speech_ctrl.QApplication.focusWidget", return_value=None):
            controller.speak_active_workspace_text()

        tts = controller.tts_manager
        self.assertIsInstance(tts, _FakeTTSManager)
        self.assertEqual(tts.speak_calls[-1], ("Knowledge", True))
        show_status.assert_not_called()


class _CursorBlock:
    def __init__(self, text: str):
        self._text = str(text or "")

    def text(self) -> str:
        return self._text


class _CursorStub:
    def __init__(
        self,
        *,
        selected_text: str,
        block_text: str,
    ):
        self._selected_text = str(selected_text or "")
        self._block_text = str(block_text or "")

    def selectedText(self) -> str:
        return self._selected_text

    def block(self):
        return _CursorBlock(self._block_text)


class _EditorStub:
    def __init__(self, text: str):
        self._text = str(text or "")
        self._selected_text = ""
        self._cursor_line = ""
        self._cursor_index = 0

    def select_span(self, token: str) -> None:
        text = str(token or "")
        self._selected_text = text
        idx = self._text.find(text)
        if idx >= 0:
            self._cursor_index = idx
            self._cursor_line = self._line_at_index(idx)

    def move_cursor_to(self, token: str) -> None:
        idx = self._text.find(str(token or ""))
        self._selected_text = ""
        if idx >= 0:
            self._cursor_index = idx
            self._cursor_line = self._line_at_index(idx)
        else:
            self._cursor_line = ""

    def _line_at_index(self, index: int) -> str:
        start = self._text.rfind("\n", 0, max(0, int(index))) + 1
        end = self._text.find("\n", max(0, int(index)))
        if end < 0:
            end = len(self._text)
        return self._text[start:end]

    def textCursor(self):
        return _CursorStub(
            selected_text=self._selected_text,
            block_text=self._cursor_line,
        )

    def toPlainText(self) -> str:
        return self._text


class _FocusWidget:
    def __init__(self, parent=None):
        self._parent = parent

    def parentWidget(self):
        return self._parent


if __name__ == "__main__":
    unittest.main()
