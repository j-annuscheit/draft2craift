from __future__ import annotations

import re
import unittest

import pytest
from PySide6.QtWidgets import QApplication

from studio.canvas.editor import MarkdownEditor
from studio.canvas.preview.pane import CanvasPreviewPane


pytestmark = pytest.mark.usefixtures("qt_app")


def _process_events() -> None:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


class PreviewListLayoutSettingsTests(unittest.TestCase):
    def _build_pane(self) -> tuple[CanvasPreviewPane, MarkdownEditor]:
        editor = MarkdownEditor(read_only=False)
        pane = CanvasPreviewPane(
            allow_editing=True,
            show_title=False,
            sync_cursor_with_editor=False,
        )
        pane.bind_editor(editor)
        pane.show()
        _process_events()
        return pane, editor

    @staticmethod
    def _list_blocks(pane: CanvasPreviewPane):
        doc = pane._view.document()
        block = doc.begin()
        out = []
        while block.isValid():
            if block.textList() is not None:
                out.append(block)
            block = block.next()
        return out

    def test_list_indent_and_marker_gap_apply_to_block_format(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("Intro\n\n- Alpha\n- Beta\n\nOutro")
            pane._render()
            style = pane.preview_style_settings()
            style["list_indent_em"] = 2.10
            style["list_marker_gap_em"] = 0.80
            pane.set_preview_style_settings(style, force=True)
            _process_events()

            expected_indent = pane._spacing_px(2.10)
            expected_marker_spaces = " " * (1 + int(0.80 * 4.0))
            list_blocks = self._list_blocks(pane)
            self.assertGreaterEqual(len(list_blocks), 2)
            for block in list_blocks:
                fmt = block.blockFormat()
                self.assertAlmostEqual(fmt.leftMargin(), expected_indent, delta=0.6)
                self.assertEqual(
                    str(block.textList().format().numberSuffix() or ""),
                    expected_marker_spaces,
                )
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_unordered_marker_gap_is_visible_but_not_committed(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("Intro\n\n- Alpha\n- Beta\n\nOutro")
            pane._render()
            style = pane.preview_style_settings()
            style["list_indent_em"] = 3.20
            style["list_marker_gap_em"] = 1.25
            pane.set_preview_style_settings(style, force=True)
            _process_events()

            raw = pane._view.toMarkdown().replace("\r\n", "\n")
            self.assertIsNotNone(
                re.search(r"^-\s[\u00A0 ]{2,}Alpha$", raw, re.MULTILINE),
                msg=raw,
            )

            normalized = pane._view_to_markdown_for_commit().replace("\r\n", "\n")
            self.assertIsNotNone(re.search(r"^-\sAlpha$", normalized, re.MULTILINE))
            self.assertIsNotNone(re.search(r"^-\sBeta$", normalized, re.MULTILINE))
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_unordered_marker_gap_updates_rendered_list_text(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("- Alpha\n- Beta")
            pane._render()

            style = pane.preview_style_settings()
            style["list_marker_gap_em"] = 1.45
            pane.set_preview_style_settings(style, force=True)
            _process_events()

            blocks = self._list_blocks(pane)
            self.assertGreaterEqual(len(blocks), 1)
            first_text = str(blocks[0].text() or "")
            self.assertTrue(first_text.startswith("\u00A0"), msg=repr(first_text))
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_marker_gap_does_not_leak_into_ordered_markdown_commit(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("1. Alpha\n2. Beta")
            pane._render()
            style = pane.preview_style_settings()
            style["list_marker_gap_em"] = 1.45
            pane.set_preview_style_settings(style, force=True)
            _process_events()

            raw = pane._view.toMarkdown().replace("\r\n", "\n")
            self.assertIsNotNone(
                re.search(r"^1\.\s{3,}Alpha$", raw, re.MULTILINE),
                msg=raw,
            )

            normalized = pane._view_to_markdown_for_commit().replace("\r\n", "\n")
            self.assertIsNotNone(re.search(r"^1\.\s{1,2}Alpha$", normalized, re.MULTILINE))
            self.assertIsNotNone(re.search(r"^2\.\s{1,2}Beta$", normalized, re.MULTILINE))
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_marker_gap_does_not_convert_thematic_breaks(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("- - -\n\nText")
            pane._render()
            style = pane.preview_style_settings()
            style["list_marker_gap_em"] = 1.45
            pane.set_preview_style_settings(style, force=True)
            _process_events()

            normalized = pane._view_to_markdown_for_commit().replace("\r\n", "\n")
            self.assertIsNotNone(
                re.search(r"(?m)^(?:- - -|---)$", normalized),
                msg=normalized,
            )
            self.assertNotIn("\\-", normalized)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_horizontal_rule_button_commits_real_hr_marker_free_markdown(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("Start")
            pane._render()
            style = pane.preview_style_settings()
            style["list_marker_gap_em"] = 1.45
            pane.set_preview_style_settings(style, force=True)
            _process_events()

            pane._insert_horizontal_rule()
            _process_events()

            committed = editor.get_full_text().replace("\r\n", "\n")
            self.assertIsNotNone(
                re.search(r"(?m)^(?:- - -|---)$", committed),
                msg=committed,
            )
            self.assertNotIn("{{__D2C_HR__}}", committed)
            self.assertNotIn("\\-", committed)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()


if __name__ == "__main__":
    unittest.main()
