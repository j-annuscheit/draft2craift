from __future__ import annotations

import unittest

import pytest
from PySide6.QtGui import QTextCursor, QTextFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from studio.canvas.preview.pane import CanvasPreviewPane
from studio.canvas.editor import MarkdownEditor


pytestmark = pytest.mark.usefixtures("qt_app")


def _process_events() -> None:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


class PreviewBlankLineTests(unittest.TestCase):
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
        _process_events()
        return pane, editor

    def _select_preview_text(self, pane: CanvasPreviewPane, snippet: str):
        plain = pane._view.toPlainText()
        pos = plain.find(str(snippet or ""))
        self.assertGreaterEqual(pos, 0, f"Snippet not found: {snippet!r}")
        cursor = pane._view.textCursor()
        cursor.setPosition(pos)
        cursor.setPosition(
            pos + len(str(snippet or "")),
            QTextCursor.MoveMode.KeepAnchor,
        )
        pane._view.setTextCursor(cursor)

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
            pane._preview_user_edit_dirty = True
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
            _process_events()

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
            _process_events()

    def test_timer_commit_is_deferred_while_preview_has_focus(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("Alpha")
            pane._render()

            pane._view.setFocus()
            _process_events()
            cursor = pane._view.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            pane._view.setTextCursor(cursor)
            QTest.keyClicks(pane._view, " X")
            _process_events()

            before_cursor = pane._view.textCursor().position()
            self.assertTrue(pane._preview_edit_active)
            pane._commit_preview_edit_to_markdown()

            self.assertEqual(editor.toPlainText(), "Alpha")
            self.assertEqual(pane._view.textCursor().position(), before_cursor)

            pane._view.clearFocus()
            _process_events()
            pane._commit_preview_edit_to_markdown(force=True)
            self.assertEqual(editor.toPlainText(), "Alpha X")
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_programmatic_rerender_does_not_arm_preview_commit(self):
        pane, editor = self._build_pane()
        try:
            source = (
                "Dies ist eine lange Fliesstext-Zeile ohne manuelle Umbrueche "
                "und sie darf durch reines Anzeigen in der Vorschau nie "
                "zurueck in mehrere harte Zeilen umgewandelt werden."
            )
            editor.setPlainText(source)
            pane._render()
            _process_events()

            pane._view.setFocus()
            _process_events()
            pane.invalidate_render_cache()
            pane._render()
            _process_events()

            self.assertFalse(pane._preview_edit_active)
            self.assertFalse(pane._preview_user_edit_dirty)

            pane._view.clearFocus()
            _process_events()
            pane._finish_preview_edit_session()
            self.assertEqual(editor.toPlainText(), source)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_preview_commit_unwraps_long_flow_text_soft_wraps(self):
        pane, editor = self._build_pane()
        try:
            source = (
                "Im Rahmen dieser Arbeit konnte, mithilfe der durchgefuehrten "
                "Studie, aufgezeigt werden, dass frei verfuegbare KI-basierte "
                "Textgeneratoren derzeit keine qualitativ hochwertigen Berichte "
                "generieren koennen. Die durchgefuehrte Studie bestand aus einer "
                "Online-Befragung und einem Experiment. Als Grundlage des "
                "Experiments wurde ein Basistext zum Thema Die Folgen der "
                "Corona-Pandemie fuer die Kunst- und Kulturbranche verfasst."
            )
            editor.setPlainText("")
            pane._render()
            _process_events()

            pane._view.setFocus()
            _process_events()
            cursor = pane._view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            pane._view.setTextCursor(cursor)
            cursor = pane._view.textCursor()
            cursor.insertText(source)
            pane._view.setTextCursor(cursor)
            _process_events()

            pane._preview_edit_active = True
            pane._preview_user_edit_dirty = True
            pane._commit_preview_edit_to_markdown(force=True)
            _process_events()

            out = editor.toPlainText()
            self.assertEqual(out, source)
            self.assertEqual(len(out.splitlines()), 1)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_typing_in_preview_marks_dirty_and_commits(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("Alpha")
            pane._render()
            _process_events()

            pane._view.setFocus()
            _process_events()
            cursor = pane._view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            pane._view.setTextCursor(cursor)
            QTest.keyClicks(pane._view, " X")
            _process_events()

            self.assertTrue(pane._preview_edit_active)
            self.assertTrue(pane._preview_user_edit_dirty)

            pane._view.clearFocus()
            _process_events()
            pane._finish_preview_edit_session()
            _process_events()
            self.assertEqual(editor.toPlainText(), "Alpha X")
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_render_spacer_injection_is_idempotent_for_existing_sentinels(self):
        source = f"A\n\n{CanvasPreviewPane._BLANK_LINE_SENTINEL}\n\nB"
        injected = CanvasPreviewPane._inject_render_spacers_for_extra_blank_lines(
            source
        )
        self.assertEqual(injected, source)

    def test_repeated_preview_format_toggle_keeps_blank_gaps_stable(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("A\n\n\nB\n\n\nC")
            pane._render()
            _process_events()

            initial_gap = self._gap_between_first_two_nonempty_lines(
                pane._view.toPlainText()
            )
            self.assertEqual(initial_gap, 1)

            def select_b():
                plain = pane._view.toPlainText()
                pos = plain.find("B")
                self.assertGreaterEqual(pos, 0)
                cursor = pane._view.textCursor()
                cursor.setPosition(pos)
                cursor.movePosition(
                    QTextCursor.MoveOperation.NextCharacter,
                    QTextCursor.MoveMode.KeepAnchor,
                    1,
                )
                pane._view.setTextCursor(cursor)

            select_b()
            pane._toggle_bold()
            _process_events()

            after_first_gap = self._gap_between_first_two_nonempty_lines(
                pane._view.toPlainText()
            )
            sentinels_after_first = editor.toPlainText().count("\u200B")

            select_b()
            pane._toggle_bold()
            _process_events()

            after_second_gap = self._gap_between_first_two_nonempty_lines(
                pane._view.toPlainText()
            )
            sentinels_after_second = editor.toPlainText().count("\u200B")

            self.assertEqual(after_first_gap, initial_gap)
            self.assertEqual(after_second_gap, initial_gap)
            self.assertEqual(sentinels_after_second, sentinels_after_first)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_toggle_block_quote_roundtrip(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("A\n\nB")
            pane._render()
            _process_events()

            def select_b():
                plain = pane._view.toPlainText()
                pos = plain.find("B")
                self.assertGreaterEqual(pos, 0)
                cursor = pane._view.textCursor()
                cursor.setPosition(pos)
                pane._view.setTextCursor(cursor)

            select_b()
            pane._toggle_block_quote()
            _process_events()
            self.assertEqual(editor.toPlainText(), "A\n\n> B")

            select_b()
            pane._toggle_block_quote()
            _process_events()
            self.assertEqual(editor.toPlainText(), "A\n\nB")
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_markdown_stylesheet_contains_blockquote_bar(self):
        pane, editor = self._build_pane()
        try:
            stylesheet = pane._markdown_stylesheet()
            self.assertIn("blockquote", stylesheet)
            self.assertIn("border-left", stylesheet)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_markdown_stylesheet_contains_code_block_box_rules(self):
        pane, editor = self._build_pane()
        try:
            stylesheet = pane._markdown_stylesheet()
            self.assertIn("pre {", stylesheet)
            self.assertIn("border-radius: 6px;", stylesheet)
            self.assertIn("padding: 0.55em 0.75em;", stylesheet)
            self.assertIn("pre code {", stylesheet)
            self.assertIn("background: transparent;", stylesheet)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_fenced_code_block_receives_single_box_spacing_and_background(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText(
                "Vorher\n\n"
                "```python\nx = 1\ny = 2\n```\n\n"
                "Mitte\n\n"
                "```\nabc\n```\n"
            )
            pane._render()
            _process_events()

            doc = pane._view.document()
            runs: list[list] = []
            current: list = []
            block = doc.begin()
            while block.isValid():
                fmt = block.blockFormat()
                has_fence = bool(
                    str(
                        fmt.stringProperty(int(QTextFormat.Property.BlockCodeFence))
                        or ""
                    ).strip()
                )
                if has_fence:
                    current.append(block)
                elif current:
                    runs.append(current)
                    current = []
                block = block.next()
            if current:
                runs.append(current)

            self.assertGreaterEqual(len(runs), 2)
            first_run = runs[0]
            self.assertGreaterEqual(len(first_run), 2)
            first_fmt = first_run[0].blockFormat()
            second_fmt = first_run[1].blockFormat()

            self.assertGreater(first_fmt.leftMargin(), 0.5)
            self.assertGreater(first_fmt.rightMargin(), 0.5)
            self.assertGreater(first_fmt.topMargin(), second_fmt.topMargin() + 0.25)
            self.assertGreater(first_run[-1].blockFormat().bottomMargin(), 0.5)

            first_bg = first_fmt.background().color()
            self.assertTrue(first_bg.isValid())
            self.assertGreater(first_bg.alpha(), 0)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_view_colors_apply_to_widget_and_custom_paint_properties(self):
        pane, editor = self._build_pane()
        try:
            style = pane.preview_style_settings()
            style["body_background_color"] = "#123456"
            style["body_text_color"] = "#F0E0D0"
            style["quote_border_color"] = "#13579B"
            style["hr_color"] = "#B97531"
            pane.set_preview_style_settings(style, force=True)
            _process_events()

            sheet = str(pane._view.styleSheet() or "").upper()
            self.assertIn("#123456", sheet)
            self.assertIn("#F0E0D0", sheet)
            self.assertEqual(
                str(pane._view.property("_quote_border_color") or "").upper(),
                "#13579B",
            )
            self.assertEqual(
                str(pane._view.property("_hr_color") or "").upper(),
                "#B97531",
            )
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_heading_size_factors_are_applied_to_stylesheet(self):
        pane, editor = self._build_pane()
        try:
            style = pane.preview_style_settings()
            style["heading_h1_size_em"] = 2.35
            style["heading_h2_size_em"] = 1.95
            style["heading_h3_size_em"] = 1.55
            style["heading_h4_size_em"] = 1.30
            style["heading_h5_size_em"] = 1.05
            style["heading_h6_size_em"] = 0.85
            pane.set_preview_style_settings(style, force=True)
            _process_events()

            stylesheet = pane._markdown_stylesheet()
            self.assertIn("h1 { font-size: 2.35em;", stylesheet)
            self.assertIn("h2 { font-size: 1.95em;", stylesheet)
            self.assertIn("h3 { font-size: 1.55em;", stylesheet)
            self.assertIn("h4 { font-size: 1.30em;", stylesheet)
            self.assertIn("h5 { font-size: 1.05em;", stylesheet)
            self.assertIn("h6 { font-size: 0.85em;", stylesheet)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_soft_line_breaks_are_preserved_after_preview_bold_toggle(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("A\nB\nC")
            pane._render()
            _process_events()

            plain = pane._view.toPlainText()
            pos = plain.find("B")
            self.assertGreaterEqual(pos, 0)
            cursor = pane._view.textCursor()
            cursor.setPosition(pos)
            cursor.movePosition(
                QTextCursor.MoveOperation.NextCharacter,
                QTextCursor.MoveMode.KeepAnchor,
                1,
            )
            pane._view.setTextCursor(cursor)

            pane._toggle_bold()
            _process_events()
            self.assertEqual(editor.toPlainText(), "A\n**B**\nC")
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_soft_break_injection_keeps_markdown_blocks_unchanged(self):
        source = "# T\nText\n\n- A\n- B\n\n> Q\n> W\n\n```\nx\ny\n```"
        rendered = CanvasPreviewPane._inject_render_soft_break_tags(source)
        self.assertIn("Text", rendered)
        self.assertNotIn("- A\\", rendered)
        self.assertNotIn("> Q\\", rendered)
        self.assertNotIn("x\\", rendered)

    def test_soft_break_injection_adds_markers_for_plain_lines(self):
        source = "A\nB\nC"
        rendered = CanvasPreviewPane._inject_render_soft_break_tags(source)
        self.assertEqual(rendered, "A\\\nB\\\nC")

    def test_restore_blank_like_runs_from_reference(self):
        restored = CanvasPreviewPane._restore_blank_like_runs_from_reference(
            "A\n\n**B**\n\nC",
            "A\nB\nC",
        )
        self.assertEqual(restored, "A\n**B**\nC")

    def test_restore_soft_wrapped_plain_lines_from_reference(self):
        wrapped = "Alpha\nBeta\nGamma"
        reference = "Alpha Beta Gamma"
        restored = CanvasPreviewPane._restore_soft_wrapped_plain_lines_from_reference(
            wrapped,
            reference,
        )
        self.assertEqual(restored, reference)

    def test_restore_soft_wrapped_plain_lines_keeps_structured_blocks(self):
        wrapped = "- Alpha\n- Beta\n- Gamma"
        reference = "- Alpha\n- Beta\n- Gamma"
        restored = CanvasPreviewPane._restore_soft_wrapped_plain_lines_from_reference(
            wrapped,
            reference,
        )
        self.assertEqual(restored, wrapped)

    def test_preview_commit_does_not_split_single_long_plain_line(self):
        pane, editor = self._build_pane()
        try:
            original = ("Diesisteinelangezeileohneumbruecheundmitvielenworten " * 12).strip()
            editor.setPlainText(original)
            pane._render()
            _process_events()

            pane._preview_edit_active = True
            pane._preview_user_edit_dirty = True
            pane._commit_preview_edit_to_markdown(force=True)
            _process_events()

            self.assertEqual(editor.toPlainText(), original)
            self.assertEqual(editor.toPlainText().count("\n"), 0)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_bold_toggle_trims_selection_edge_spaces(self):
        pane, editor = self._build_pane()
        try:
            for snippet in ("Sonne", "Sonne ", " Sonne "):
                with self.subTest(selection=snippet):
                    editor.setPlainText("Die Sonne ist blau.")
                    pane._render()
                    _process_events()

                    self._select_preview_text(pane, snippet)
                    pane._toggle_bold()
                    _process_events()
                    self.assertEqual(
                        editor.toPlainText(),
                        "Die **Sonne** ist blau.",
                    )

                    self._select_preview_text(pane, snippet)
                    pane._toggle_bold()
                    _process_events()
                    self.assertEqual(editor.toPlainText(), "Die Sonne ist blau.")
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_bold_toggle_inside_bold_span_with_spaced_selection(self):
        pane, editor = self._build_pane()
        try:
            for snippet in ("ist", " ist", " ist ", "ist "):
                with self.subTest(selection=snippet):
                    editor.setPlainText("Die **Sonne ist blau**.")
                    pane._render()
                    _process_events()

                    self._select_preview_text(pane, snippet)
                    pane._toggle_bold()
                    _process_events()
                    self.assertEqual(
                        editor.toPlainText(),
                        "Die **Sonne** ist **blau**.",
                    )

                    self._select_preview_text(pane, snippet)
                    pane._toggle_bold()
                    _process_events()
                    self.assertEqual(
                        editor.toPlainText(),
                        "Die **Sonne ist blau**.",
                    )
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_italic_toggle_trims_selection_edge_spaces(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("Die Sonne ist blau.")
            pane._render()
            _process_events()

            self._select_preview_text(pane, " Sonne ")
            pane._toggle_italic()
            _process_events()
            self.assertEqual(editor.toPlainText(), "Die *Sonne* ist blau.")

            self._select_preview_text(pane, " Sonne ")
            pane._toggle_italic()
            _process_events()
            self.assertEqual(editor.toPlainText(), "Die Sonne ist blau.")
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_build_markdown_table_dimensions(self):
        table = CanvasPreviewPane._build_markdown_table(3, 2)
        self.assertEqual(
            table,
            "|   |   |\n| --- | --- |\n|   |   |\n|   |   |",
        )

    def test_normalize_table_row_spacing_removes_blank_lines_between_rows(self):
        source = (
            "| A | B |\n\n"
            "| --- | --- |\n\n"
            "| C | D |"
        )
        normalized = CanvasPreviewPane._normalize_table_row_spacing(source)
        self.assertEqual(
            normalized,
            "| A | B |\n| --- | --- |\n| C | D |",
        )

    def test_normalize_pure_pipe_table_blocks_restores_separator(self):
        source = "||||||\n||||||\n||||||\n||||||\n||||||\n||||||"
        normalized = CanvasPreviewPane._normalize_pure_pipe_table_blocks(source)
        self.assertEqual(
            normalized,
            (
                "|   |   |   |   |   |\n"
                "| --- | --- | --- | --- | --- |\n"
                "|   |   |   |   |   |\n"
                "|   |   |   |   |   |\n"
                "|   |   |   |   |   |\n"
                "|   |   |   |   |   |"
            ),
        )

    def test_insert_markdown_table_via_preview_button_logic(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("Start")
            pane._render()
            _process_events()

            cursor = pane._view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            pane._view.setTextCursor(cursor)

            pane._insert_markdown_table(2, 3)
            _process_events()
            self.assertEqual(
                editor.toPlainText(),
                "Start\n\n|  |  |  |\n| --- | --- | --- |\n|  |  |  |",
            )
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_inserted_blank_table_survives_rerender_cycles(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("A\nB\n\nD\nE")
            pane._render()
            _process_events()

            plain = pane._view.toPlainText()
            pos_d = plain.find("D")
            self.assertGreaterEqual(pos_d, 0)
            cursor = pane._view.textCursor()
            cursor.setPosition(pos_d)
            pane._view.setTextCursor(cursor)

            pane._insert_markdown_table(5, 5)
            _process_events()
            inserted = editor.toPlainText()
            self.assertIn("| --- | --- | --- | --- | --- |", inserted)

            for _ in range(2):
                pane._render()
                _process_events()
                pane._preview_edit_active = True
                pane._preview_user_edit_dirty = True
                pane._commit_preview_edit_to_markdown(force=True)
                _process_events()

            stable = editor.toPlainText()
            self.assertIn("| --- | --- | --- | --- | --- |", stable)
            self.assertNotIn("||||||", stable)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_normalize_table_column_mismatch_collapses_overflow(self):
        source = "| A | B |\n| --- | --- |\n| C |  |  | D |"
        normalized = CanvasPreviewPane._normalize_table_column_mismatch(source)
        self.assertEqual(
            normalized,
            "| A | B |\n| --- | --- |\n| C | D |",
        )

    def test_normalize_table_column_mismatch_repairs_weak_separator_row(self):
        source = "|HELLO|||||\n|-----|||||\n|     |||||"
        normalized = CanvasPreviewPane._normalize_table_column_mismatch(source)
        self.assertEqual(
            normalized,
            (
                "| HELLO |  |  |  |  |\n"
                "| --- | --- | --- | --- | --- |\n"
                "|  |  |  |  |  |"
            ),
        )

    def test_normalize_table_column_mismatch_multiline_overflow_uses_br(self):
        source = "| A | B |\n| --- | --- |\n| C | y | z | D |"
        normalized = CanvasPreviewPane._normalize_table_column_mismatch(source)
        self.assertEqual(
            normalized,
            "| A | B |\n| --- | --- |\n| C<br>y<br>z | D |",
        )

    def test_typing_in_empty_table_cell_stays_valid_table(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("|   |   |\n| --- | --- |\n|   |   |")
            pane._render()
            _process_events()

            doc = pane._view.document()
            table_pos = None
            for pos in range(doc.characterCount()):
                probe = QTextCursor(doc)
                probe.setPosition(pos)
                if probe.currentTable() is not None:
                    table_pos = pos
                    break
            self.assertIsNotNone(table_pos)

            cursor = pane._view.textCursor()
            cursor.setPosition(int(table_pos))
            pane._view.setTextCursor(cursor)
            cursor = pane._view.textCursor()
            cursor.insertText("ABC")
            pane._view.setTextCursor(cursor)

            pane._preview_edit_active = True
            pane._preview_user_edit_dirty = True
            pane._commit_preview_edit_to_markdown(force=True)
            _process_events()

            nonempty = [line for line in editor.toPlainText().splitlines() if line.strip()]
            self.assertGreaterEqual(len(nonempty), 3)
            self.assertEqual(
                nonempty[:3],
                ["| ABC |  |", "| --- | --- |", "|  |  |"],
            )
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_typed_table_cell_survives_rerender_cycles(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("A\nB\n\nD\nE")
            pane._render()
            _process_events()

            plain = pane._view.toPlainText()
            pos_d = plain.find("D")
            self.assertGreaterEqual(pos_d, 0)
            cursor = pane._view.textCursor()
            cursor.setPosition(pos_d)
            pane._view.setTextCursor(cursor)

            pane._insert_markdown_table(5, 5)
            _process_events()

            doc = pane._view.document()
            table_pos = None
            for pos in range(doc.characterCount()):
                probe = QTextCursor(doc)
                probe.setPosition(pos)
                if probe.currentTable() is not None:
                    table_pos = pos
                    break
            self.assertIsNotNone(table_pos)

            cursor = pane._view.textCursor()
            cursor.setPosition(int(table_pos))
            pane._view.setTextCursor(cursor)
            cursor = pane._view.textCursor()
            cursor.insertText("HELLO")
            pane._view.setTextCursor(cursor)

            pane._preview_edit_active = True
            pane._preview_user_edit_dirty = True
            pane._commit_preview_edit_to_markdown(force=True)
            _process_events()

            for _ in range(2):
                pane._render()
                _process_events()
                pane._preview_edit_active = True
                pane._preview_user_edit_dirty = True
                pane._commit_preview_edit_to_markdown(force=True)
                _process_events()

            out = editor.toPlainText()
            self.assertIn("| HELLO |", out)
            self.assertIn("| --- | --- | --- | --- | --- |", out)
            self.assertNotIn("|HELLO|||||", out)
            self.assertNotIn("||||||", out)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_multiline_in_table_cell_keeps_table_structure(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("| A | B |\n| --- | --- |\n| C | D |")
            pane._render()
            _process_events()

            plain = pane._view.toPlainText()
            pos_c = plain.find("C")
            self.assertGreaterEqual(pos_c, 0)
            cursor = pane._view.textCursor()
            cursor.setPosition(pos_c + 1)
            pane._view.setTextCursor(cursor)
            cursor = pane._view.textCursor()
            cursor.insertBlock()
            cursor.insertBlock()
            pane._view.setTextCursor(cursor)

            pane._preview_edit_active = True
            pane._preview_user_edit_dirty = True
            pane._commit_preview_edit_to_markdown(force=True)
            _process_events()

            out = editor.toPlainText()
            self.assertIn("| --- | --- |", out)
            self.assertIn("| C | D |", out)
            self.assertNotIn("| C |  |  | D |", out)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_accent_preview_theme_adds_visual_color_overlays(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("# Titel\n\nDas ist **fett** und *kursiv*.")
            pane._render()
            _process_events()

            pane.set_preview_theme_id("accent")
            _process_events()
            selections = pane._view.extraSelections()
            self.assertGreater(len(selections), 0)
            colors_by_text: dict[str, str] = {}
            for sel in selections:
                fg = sel.format.foreground().color()
                if not fg.isValid():
                    continue
                token = sel.cursor.selectedText().replace("\u2029", "\n").strip()
                if token in {"Titel", "fett"}:
                    colors_by_text[token] = fg.name()
            self.assertIn("Titel", colors_by_text)
            self.assertIn("fett", colors_by_text)
            self.assertNotEqual(colors_by_text["Titel"], colors_by_text["fett"])

            pane.set_preview_theme_id("classic")
            pane._render()
            _process_events()
            self.assertEqual(len(pane._view.extraSelections()), 0)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_vivid_preview_theme_has_strong_color_contrast(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("# Titel\n\nDas ist **fett** und *kursiv*.")
            pane._render()
            _process_events()

            pane.set_preview_theme_id("vivid")
            _process_events()
            selections = pane._view.extraSelections()
            self.assertGreater(len(selections), 0)
            colors_by_text: dict[str, str] = {}
            for sel in selections:
                fg = sel.format.foreground().color()
                if not fg.isValid():
                    continue
                token = sel.cursor.selectedText().replace("\u2029", "\n").strip()
                if token in {"Titel", "fett", "kursiv"}:
                    colors_by_text[token] = fg.name()
            self.assertIn("Titel", colors_by_text)
            self.assertIn("fett", colors_by_text)
            self.assertIn("kursiv", colors_by_text)
            unique = {colors_by_text["Titel"], colors_by_text["fett"], colors_by_text["kursiv"]}
            self.assertGreaterEqual(len(unique), 3)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_heading_levels_have_distinct_non_classic_theme_colors(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText(
                "# Überschrift 1\n\n"
                "## Überschrift 2\n\n"
                "### Überschrift 3\n\n"
                "#### Überschrift 4\n\n"
                "##### Überschrift 5\n\n"
                "###### Überschrift 6"
            )
            pane._render()
            _process_events()

            expected = {
                "Überschrift 1",
                "Überschrift 2",
                "Überschrift 3",
                "Überschrift 4",
                "Überschrift 5",
                "Überschrift 6",
            }

            for theme_id in ("accent", "vivid"):
                pane.set_preview_theme_id(theme_id)
                _process_events()
                selections = pane._view.extraSelections()
                self.assertGreater(len(selections), 0)

                colors_by_text: dict[str, str] = {}
                for sel in selections:
                    fg = sel.format.foreground().color()
                    if not fg.isValid():
                        continue
                    token = sel.cursor.selectedText().replace("\u2029", "\n").strip()
                    if token in expected:
                        colors_by_text[token] = fg.name()

                self.assertEqual(set(colors_by_text.keys()), expected)
                self.assertEqual(len(set(colors_by_text.values())), 6)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()


if __name__ == "__main__":
    unittest.main()
