from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from features.canvas.preview import CanvasPreviewPane
from features.canvas.structured_graph import extract_graph_spec
from widgets.markdown.editor import MarkdownEditor


_GRAPH_MARKDOWN = """```mindmap
Root
  Child
```"""


class PreviewStructuredGraphCommitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _build_pane(self) -> tuple[CanvasPreviewPane, MarkdownEditor]:
        editor = MarkdownEditor(read_only=False)
        pane = CanvasPreviewPane(
            allow_editing=True,
            show_title=False,
            sync_cursor_with_editor=False,
        )
        pane.bind_editor(editor)
        pane.show()
        self.__class__._app.processEvents()
        return pane, editor

    def test_commit_does_not_overwrite_editor_when_structured_graph_active(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText(_GRAPH_MARKDOWN)
            pane._render()
            self.assertTrue(pane._structured_view_active)

            original_text = editor.toPlainText()
            pane._view.setMarkdown("plain text")
            pane._preview_edit_active = True
            pane._commit_preview_edit_to_markdown()

            self.assertEqual(editor.toPlainText(), original_text)
            self.assertFalse(pane._preview_edit_active)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_entering_structured_graph_mode_cancels_pending_preview_commit(self):
        pane, editor = self._build_pane()
        try:
            spec = extract_graph_spec(_GRAPH_MARKDOWN)
            self.assertIsNotNone(spec)

            pane._preview_edit_active = True
            pane._preview_to_markdown_timer.start(10_000)
            pane._set_structured_graph_state(spec)

            self.assertTrue(pane._structured_view_active)
            self.assertFalse(pane._preview_to_markdown_timer.isActive())
            self.assertFalse(pane._preview_edit_active)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()


if __name__ == "__main__":
    unittest.main()
