from __future__ import annotations

import unittest

import pytest
from PySide6.QtGui import QTextCursor

from studio.canvas.editor import MarkdownEditor
from studio.canvas.tabbed_editor_widget import TabbedEditorWidget


pytestmark = pytest.mark.usefixtures("qt_app")


class EditorContextReadAloudTests(unittest.TestCase):
    def test_markdown_editor_emits_selected_text_for_read_aloud(self):
        editor = MarkdownEditor(read_only=False)
        try:
            editor.setPlainText("Alpha\nBeta line")
            cursor = editor.textCursor()
            start = editor.toPlainText().find("Beta")
            cursor.setPosition(start)
            cursor.setPosition(start + len("Beta"), QTextCursor.MoveMode.KeepAnchor)
            editor.setTextCursor(cursor)

            captured: list[str] = []
            editor.read_aloud_requested.connect(lambda text: captured.append(str(text)))
            editor._emit_read_aloud_selection()

            self.assertEqual(captured, ["Beta"])
        finally:
            editor.deleteLater()

    def test_tabbed_editor_relays_editor_read_aloud_signal(self):
        tabs = TabbedEditorWidget(default_read_only=False)
        try:
            panel = tabs.current_panel()
            assert panel is not None
            editor = panel.editor
            editor.setPlainText("One\nTwo")
            cursor = editor.textCursor()
            start = editor.toPlainText().find("Two")
            cursor.setPosition(start)
            cursor.setPosition(start + 3, QTextCursor.MoveMode.KeepAnchor)
            editor.setTextCursor(cursor)

            captured: list[str] = []
            tabs.read_aloud_requested.connect(lambda text: captured.append(str(text)))
            editor._emit_read_aloud_selection()

            self.assertEqual(captured, ["Two"])
        finally:
            tabs.deleteLater()


if __name__ == "__main__":
    unittest.main()
