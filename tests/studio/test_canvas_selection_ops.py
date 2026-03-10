from __future__ import annotations

import unittest
from unittest.mock import MagicMock, create_autospec

from PySide6.QtGui import QTextCursor, QTextDocument

from studio.canvas.editor import MarkdownEditor
from studio.canvas.selection import CanvasSelectionActions
from studio.canvas.split_view import MarkdownSplitPanel
from studio.canvas.tabbed_editor_widget import TabbedEditorWidget


def _signal_mock() -> MagicMock:
    signal = MagicMock(spec=["connect", "disconnect"])
    signal.connect.return_value = None
    signal.disconnect.return_value = None
    return signal


def _cursor_mock(
    *,
    has_selection: bool,
    start: int = 0,
    end: int = 0,
    selected_text: str = "",
) -> MagicMock:
    cursor = create_autospec(QTextCursor, instance=True, spec_set=True)
    cursor.hasSelection.return_value = bool(has_selection)
    cursor.selectionStart.return_value = int(start)
    cursor.selectionEnd.return_value = int(end)
    cursor.selectedText.return_value = str(selected_text or "")
    return cursor


def _editor_mock(
    *,
    full_text: str,
    selected_text: str = "",
    cursor_has_selection: bool = False,
    cursor_start: int = 0,
    cursor_end: int = 0,
    has_focus: bool = True,
) -> MagicMock:
    editor = create_autospec(MarkdownEditor, instance=True, spec_set=True)
    editor.get_selected_text.return_value = str(selected_text or "")
    editor.get_full_text.return_value = str(full_text or "")
    editor.hasFocus.return_value = bool(has_focus)
    editor.copyAvailable = _signal_mock()

    cursor = _cursor_mock(
        has_selection=cursor_has_selection,
        start=cursor_start,
        end=cursor_end,
        selected_text=selected_text,
    )
    editor.textCursor.return_value = cursor

    document = create_autospec(QTextDocument, instance=True, spec_set=True)
    document.revision.return_value = 1
    editor.document.return_value = document
    return editor


def _panel_mock(
    *,
    editor: MagicMock,
    preview_selected_text: str = "",
    should_use_preview: bool = False,
    markdown_visible: bool = True,
    preview_visible: bool = True,
    preview_has_focus: bool = True,
) -> MagicMock:
    panel = create_autospec(MarkdownSplitPanel, instance=True)
    panel.editor = editor
    panel.should_use_preview_selection.return_value = bool(should_use_preview)
    panel.get_preview_selected_text.return_value = str(preview_selected_text or "")
    panel.is_markdown_visible.return_value = bool(markdown_visible)
    panel.is_preview_visible.return_value = bool(preview_visible)
    panel.preview_has_focus.return_value = bool(preview_has_focus)
    panel.connect_preview_copy_available.return_value = True
    panel.disconnect_preview_copy_available.return_value = True
    return panel


def _tabs_mock(panel: MagicMock) -> MagicMock:
    tab_widget = MagicMock(spec=["currentChanged"])
    tab_widget.currentChanged = _signal_mock()

    tabs = create_autospec(TabbedEditorWidget, instance=True)
    tabs.tab_widget = tab_widget
    tabs.current_panel.return_value = panel
    return tabs


class CanvasSelectionOpsTests(unittest.TestCase):
    def test_get_selected_text_uses_preview_selection_in_both_mode(self):
        editor = _editor_mock(full_text="Alpha beta gamma", selected_text="")
        panel = _panel_mock(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=False,  # both-mode path
            markdown_visible=True,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_tabs_mock(panel))

        selected = actions.get_selected_text(allow_cached=False)
        self.assertEqual(selected, "Alpha")

    def test_get_selected_text_prefers_editor_when_both_have_selection(self):
        editor = _editor_mock(
            full_text="Alpha beta gamma",
            selected_text="beta",
            cursor_has_selection=True,
            cursor_start=6,
            cursor_end=10,
        )
        panel = _panel_mock(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=False,
            markdown_visible=True,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_tabs_mock(panel))

        selected = actions.get_selected_text(allow_cached=False)
        self.assertEqual(selected, "beta")

    def test_get_selected_span_prefers_editor_selection(self):
        editor = _editor_mock(
            full_text="Alpha beta gamma",
            selected_text="beta",
            cursor_has_selection=True,
            cursor_start=6,
            cursor_end=10,
        )
        panel = _panel_mock(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=False,
            markdown_visible=True,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_tabs_mock(panel))

        self.assertEqual(actions.get_selected_span(allow_cached=False), (6, 10))

    def test_replace_selected_text_uses_preview_path_in_both_mode(self):
        editor = _editor_mock(full_text="Alpha beta gamma", selected_text="")
        panel = _panel_mock(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=False,
            markdown_visible=True,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_tabs_mock(panel))
        captured: dict[str, object] = {}

        def _capture_replace(_editor, start: int, end: int, replacement: str):
            captured["start"] = int(start)
            captured["end"] = int(end)
            captured["replacement"] = replacement

        actions._replace_range = _capture_replace  # type: ignore[method-assign]

        ok, info = actions.replace_selected_text("Z", "Alpha")
        self.assertTrue(ok)
        self.assertIn("Applied", info)
        self.assertEqual(captured, {"start": 0, "end": 5, "replacement": "Z"})

    def test_preview_copy_available_caches_selection_for_later_use(self):
        editor = _editor_mock(full_text="Alpha beta gamma", selected_text="")
        panel = _panel_mock(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=True,
            markdown_visible=False,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_tabs_mock(panel))

        actions._on_preview_copy_available(True)
        panel.get_preview_selected_text.return_value = ""

        self.assertEqual(actions.get_selected_text(allow_cached=False), "")
        self.assertEqual(actions.get_selected_text(allow_cached=True), "Alpha")
        self.assertEqual(actions.get_selected_text(allow_cached=True), "")

    def test_get_selected_text_can_peek_cached_without_consuming(self):
        editor = _editor_mock(full_text="Alpha beta gamma", selected_text="")
        panel = _panel_mock(
            editor=editor,
            preview_selected_text="Alpha",
            should_use_preview=True,
            markdown_visible=False,
            preview_visible=True,
        )
        actions = CanvasSelectionActions(_tabs_mock(panel))

        actions._on_preview_copy_available(True)
        panel.get_preview_selected_text.return_value = ""

        self.assertEqual(
            actions.get_selected_text(
                allow_cached=True,
                consume_cached=False,
            ),
            "Alpha",
        )
        self.assertEqual(
            actions.get_selected_text(
                allow_cached=True,
                consume_cached=False,
            ),
            "Alpha",
        )
        self.assertEqual(actions.get_selected_text(allow_cached=True), "Alpha")
        self.assertEqual(actions.get_selected_text(allow_cached=True), "")


if __name__ == "__main__":
    unittest.main()
