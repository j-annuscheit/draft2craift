from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from features.canvas.preview import CanvasPreviewPane
from widgets.markdown.editor import MarkdownEditor


class PreviewBlankLineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    @staticmethod
    def _is_blank_like(line: str) -> bool:
        token = str(line or "").replace("\u200B", "").replace("\u00A0", " ")
        return not token.strip()

    @staticmethod
    def _gap_between_first_two_nonempty_lines(text: str) -> int:
        lines = str(text or "").replace("\r\n", "\n").split("\n")
        nonempty = [
            idx
            for idx, line in enumerate(lines)
            if not PreviewBlankLineTests._is_blank_like(line)
        ]
        if len(nonempty) < 2:
            return 0
        return max(0, int(nonempty[1] - nonempty[0] - 1))

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

    def test_preview_commit_preserves_extra_blank_paragraphs(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("A\n\nB")
            pane._render()

            pos = pane._view.toPlainText().find("B")
            cursor = pane._view.textCursor()
            cursor.setPosition(max(0, pos))
            pane._view.setTextCursor(cursor)
            cursor = pane._view.textCursor()
            cursor.insertBlock()
            pane._view.setTextCursor(cursor)
            cursor = pane._view.textCursor()
            cursor.insertBlock()
            pane._view.setTextCursor(cursor)

            self.assertEqual(
                self._gap_between_first_two_nonempty_lines(pane._view.toPlainText()),
                2,
            )

            pane._preview_edit_active = True
            pane._commit_preview_edit_to_markdown(force=True)

            stored = editor.toPlainText()
            self.assertIn("\u200B", stored)

            pane.invalidate_render_cache()
            pane._render()
            self.assertEqual(
                self._gap_between_first_two_nonempty_lines(pane._view.toPlainText()),
                2,
            )
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_restore_blank_lines_noop_when_plain_matches_markdown(self):
        text = "Alpha\n\nBeta"
        restored = CanvasPreviewPane._restore_extra_blank_lines_from_plaintext(
            text,
            "Alpha\nBeta",
        )
        self.assertEqual(restored, text)

    def test_markdown_multiple_blank_lines_render_as_wider_gap(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("A\n\n\nB")
            pane.invalidate_render_cache()
            pane._render()
            self.assertEqual(
                self._gap_between_first_two_nonempty_lines(pane._view.toPlainText()),
                1,
            )
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_timer_commit_is_deferred_while_preview_has_focus(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("Alpha")
            pane._render()

            pane._view.setFocus()
            self.__class__._app.processEvents()
            cursor = pane._view.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            pane._view.setTextCursor(cursor)
            cursor = pane._view.textCursor()
            cursor.insertText(" X")
            pane._view.setTextCursor(cursor)

            before_cursor = pane._view.textCursor().position()
            pane._preview_edit_active = True
            pane._commit_preview_edit_to_markdown()

            self.assertEqual(editor.toPlainText(), "Alpha")
            self.assertEqual(pane._view.textCursor().position(), before_cursor)

            pane._view.clearFocus()
            self.__class__._app.processEvents()
            pane._commit_preview_edit_to_markdown(force=True)
            self.assertEqual(editor.toPlainText(), "Alpha X")
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()


if __name__ == "__main__":
    unittest.main()
