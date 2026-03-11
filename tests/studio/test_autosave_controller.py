from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject
from pathlib import Path

from studio.controllers.autosave import AutosaveController

class _TimerStub:
    def __init__(self, *_args, **_kwargs):
        self.timeout = Mock()
        self.timeout.connect = Mock()
        self.setSingleShot = Mock()
        self.isActive = Mock(return_value=False)
        self.start = Mock()
        self.stop = Mock()

class _SettingsStub:
    def __init__(self):
        self._values = {}

    def value(self, key, defaultValue):
        return self._values.get(key, defaultValue)

    def setValue(self, key, value):
        self._values[key] = value

    def sync(self):
        pass

class _EditorStub:
    def __init__(self, text=""):
        self._text = text
        self.textChanged = Mock()

    def toPlainText(self):
        return self._text

class _PanelStub:
    def __init__(self, text=""):
        self.editor = _EditorStub(text)

class AutosaveControllerTests(unittest.TestCase):
    def setUp(self):
        self.canvas = Mock()
        self.app_context = Mock()
        self.app_logger = Mock()
        self.app_settings = _SettingsStub()

        # We need to mock QTimer before the controller is instantiated
        with patch("studio.controllers.autosave.QTimer", new=_TimerStub) as mock_timer:
            self.controller = AutosaveController(
                parent=QObject(),
                canvas=self.canvas,
                app_context=self.app_context,
                app_logger=self.app_logger,
                app_settings=self.app_settings,
            )

    def test_enabled_property(self):
        """Test the enabled property updates settings."""
        self.assertTrue(self.controller.enabled) # Default is True

        self.controller.enabled = False
        self.assertFalse(self.controller.enabled)
        self.assertEqual(self.app_settings.value(self.controller._AUTOSAVE_SETTING_KEY, None), False)

        self.controller.enabled = True
        self.assertTrue(self.controller.enabled)
        self.assertEqual(self.app_settings.value(self.controller._AUTOSAVE_SETTING_KEY, None), True)

    def test_schedule_full_skipped_when_disabled(self):
        """Test that schedule_full is skipped when disabled."""
        self.controller.enabled = False
        self.controller.schedule_full()
        self.controller._full_timer.start.assert_not_called()

    def test_schedule_full_skipped_when_suspended(self):
        """Test that schedule_full is skipped when suspended."""
        self.controller.suspended = True
        self.controller.schedule_full()
        self.controller._full_timer.start.assert_not_called()

    def test_schedule_full_skipped_when_not_connected(self):
        """Test that schedule_full is skipped when runtime is not connected."""
        self.controller._runtime_connected = False
        self.controller.schedule_full()
        self.controller._full_timer.start.assert_not_called()

    def test_schedule_full_starts_timer(self):
        """Test that schedule_full starts the timer in the correct state."""
        self.controller.enabled = True
        self.controller.suspended = False
        self.controller._runtime_connected = True
        self.controller.schedule_full(delay_ms=500)
        self.controller._full_timer.start.assert_called_with(500)

    def test_flush_draft_writes_to_file(self):
        """Test that _flush_draft writes the editor content to the correct file."""
        with tempfile.TemporaryDirectory() as tmp:
            autosave_dir = Path(tmp)
            (autosave_dir / "project.json").write_text("{}", encoding="utf-8")

            self.controller._autosave_dir = autosave_dir
            self.controller._write_text_atomic = Mock()
            self.controller._show_saved_hint = Mock()

            panel_stub = _PanelStub(text="draft content")
            self.controller._find_panel_for_editor = Mock(return_value=(panel_stub, 0))
            self.controller._pending_editor = panel_stub.editor

            # Execute
            self.controller._flush_draft()

            # Assert
            self.controller._write_text_atomic.assert_called_once_with(
                autosave_dir / "canvas" / "doc_0000.md",
                "draft content",
            )
            self.controller._show_saved_hint.assert_called_once_with(full_snapshot=False)

    @patch("studio.controllers.autosave.Path")
    def test_flush_full_saves_project(self, mock_path):
        """Test that flush_full calls save_project."""
        self.controller.enabled = True
        self.controller.suspended = False
        self.controller._runtime_connected = True
        self.app_context.is_rag_busy.return_value = False
        self.controller._prepare_workspace = Mock()
        self.controller.flush_pending_preview_edits = Mock()
        self.controller.rewire_editors = Mock()
        self.controller._context.save_project.return_value = True
        self.controller._signature = Mock(return_value="sig")
        
        self.controller.flush_full()
        
        self.controller._prepare_workspace.assert_called_once()
        self.controller.flush_pending_preview_edits.assert_called_once()
        self.controller._context.save_project.assert_called_with(
            self.controller._autosave_dir,
            include_st_embeddings=False,
        )
        self.app_context.show_status.assert_called()

    def test_flush_full_delayed_if_rag_busy(self):
        """Test that flush_full is delayed if RAG is busy."""
        self.controller.enabled = True
        self.controller.suspended = False
        self.controller._runtime_connected = True
        self.app_context.is_rag_busy.return_value = True
        
        self.controller.flush_full()
        
        self.controller._full_timer.start.assert_called_with(900)
        self.controller._context.save_project.assert_not_called()

    def test_resolve_autosave_dir_prefers_app_data_location(self):
        with patch(
            "studio.controllers.autosave.QStandardPaths.writableLocation",
            return_value="/home/tester/.local/share/draft2craift",
        ):
            resolved = AutosaveController._resolve_autosave_dir()

        self.assertEqual(
            resolved,
            Path("/home/tester/.local/share/draft2craift/autosave_project").resolve(),
        )

    def test_resolve_autosave_dir_falls_back_to_home_when_app_data_empty(self):
        with (
            patch(
                "studio.controllers.autosave.QStandardPaths.writableLocation",
                return_value="",
            ),
            patch("studio.controllers.autosave.Path.home", return_value=Path("/home/fallback")),
        ):
            resolved = AutosaveController._resolve_autosave_dir()

        self.assertEqual(
            resolved,
            Path("/home/fallback/.draft2craift/autosave_project").resolve(),
        )

    def test_signature_includes_highlight_store_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            highlight_file = (Path(tmp) / "highlights.json").resolve()
            highlight_file.write_text("{}", encoding="utf-8")

            class _StoreStub:
                path = highlight_file

                @staticmethod
                def is_glossary_enabled():
                    return False

            self.controller._collect_canvas_tabs_data = Mock(return_value=[])
            self.controller._context.autosave_state_extras.return_value = {}
            self.controller._context.chat_tts_mode.return_value = "off"

            with patch(
                "studio.controllers.autosave.get_highlight_store",
                return_value=_StoreStub(),
            ):
                payload = json.loads(self.controller._signature())

            highlights = payload.get("highlights", {})
            self.assertEqual(highlights.get("path"), str(highlight_file))
            self.assertEqual(highlights.get("size"), highlight_file.stat().st_size)
            self.assertIs(highlights.get("glossary_enabled"), False)

if __name__ == "__main__":
    unittest.main()
