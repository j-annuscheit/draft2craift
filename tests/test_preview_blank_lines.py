from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCursor
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
            self.__class__._app.processEvents()

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
            self.__class__._app.processEvents()

            after_first_gap = self._gap_between_first_two_nonempty_lines(
                pane._view.toPlainText()
            )
            sentinels_after_first = editor.toPlainText().count("\u200B")

            select_b()
            pane._toggle_bold()
            self.__class__._app.processEvents()

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
            self.__class__._app.processEvents()

    def test_toggle_block_quote_roundtrip(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("A\n\nB")
            pane._render()
            self.__class__._app.processEvents()

            def select_b():
                plain = pane._view.toPlainText()
                pos = plain.find("B")
                self.assertGreaterEqual(pos, 0)
                cursor = pane._view.textCursor()
                cursor.setPosition(pos)
                pane._view.setTextCursor(cursor)

            select_b()
            pane._toggle_block_quote()
            self.__class__._app.processEvents()
            self.assertEqual(editor.toPlainText(), "A\n\n> B")

            select_b()
            pane._toggle_block_quote()
            self.__class__._app.processEvents()
            self.assertEqual(editor.toPlainText(), "A\n\nB")
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_markdown_stylesheet_contains_blockquote_bar(self):
        pane, editor = self._build_pane()
        try:
            stylesheet = pane._markdown_stylesheet()
            self.assertIn("blockquote", stylesheet)
            self.assertIn("border-left", stylesheet)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_soft_line_breaks_are_preserved_after_preview_bold_toggle(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("A\nB\nC")
            pane._render()
            self.__class__._app.processEvents()

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
            self.__class__._app.processEvents()
            self.assertEqual(editor.toPlainText(), "A\n**B**\nC")
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

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
            self.__class__._app.processEvents()

            pane._preview_edit_active = True
            pane._commit_preview_edit_to_markdown(force=True)
            self.__class__._app.processEvents()

            self.assertEqual(editor.toPlainText(), original)
            self.assertEqual(editor.toPlainText().count("\n"), 0)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_bold_toggle_trims_selection_edge_spaces(self):
        pane, editor = self._build_pane()
        try:
            for snippet in ("Sonne", "Sonne ", " Sonne "):
                with self.subTest(selection=snippet):
                    editor.setPlainText("Die Sonne ist blau.")
                    pane._render()
                    self.__class__._app.processEvents()

                    self._select_preview_text(pane, snippet)
                    pane._toggle_bold()
                    self.__class__._app.processEvents()
                    self.assertEqual(
                        editor.toPlainText(),
                        "Die **Sonne** ist blau.",
                    )

                    self._select_preview_text(pane, snippet)
                    pane._toggle_bold()
                    self.__class__._app.processEvents()
                    self.assertEqual(editor.toPlainText(), "Die Sonne ist blau.")
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_bold_toggle_inside_bold_span_with_spaced_selection(self):
        pane, editor = self._build_pane()
        try:
            for snippet in ("ist", " ist", " ist ", "ist "):
                with self.subTest(selection=snippet):
                    editor.setPlainText("Die **Sonne ist blau**.")
                    pane._render()
                    self.__class__._app.processEvents()

                    self._select_preview_text(pane, snippet)
                    pane._toggle_bold()
                    self.__class__._app.processEvents()
                    self.assertEqual(
                        editor.toPlainText(),
                        "Die **Sonne** ist **blau**.",
                    )

                    self._select_preview_text(pane, snippet)
                    pane._toggle_bold()
                    self.__class__._app.processEvents()
                    self.assertEqual(
                        editor.toPlainText(),
                        "Die **Sonne ist blau**.",
                    )
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_italic_toggle_trims_selection_edge_spaces(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("Die Sonne ist blau.")
            pane._render()
            self.__class__._app.processEvents()

            self._select_preview_text(pane, " Sonne ")
            pane._toggle_italic()
            self.__class__._app.processEvents()
            self.assertEqual(editor.toPlainText(), "Die *Sonne* ist blau.")

            self._select_preview_text(pane, " Sonne ")
            pane._toggle_italic()
            self.__class__._app.processEvents()
            self.assertEqual(editor.toPlainText(), "Die Sonne ist blau.")
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

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
            self.__class__._app.processEvents()

            cursor = pane._view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            pane._view.setTextCursor(cursor)

            pane._insert_markdown_table(2, 3)
            self.__class__._app.processEvents()
            self.assertEqual(
                editor.toPlainText(),
                "Start\n\n|  |  |  |\n| --- | --- | --- |\n|  |  |  |",
            )
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_inserted_blank_table_survives_rerender_cycles(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("A\nB\n\nD\nE")
            pane._render()
            self.__class__._app.processEvents()

            plain = pane._view.toPlainText()
            pos_d = plain.find("D")
            self.assertGreaterEqual(pos_d, 0)
            cursor = pane._view.textCursor()
            cursor.setPosition(pos_d)
            pane._view.setTextCursor(cursor)

            pane._insert_markdown_table(5, 5)
            self.__class__._app.processEvents()
            inserted = editor.toPlainText()
            self.assertIn("| --- | --- | --- | --- | --- |", inserted)

            for _ in range(2):
                pane._render()
                self.__class__._app.processEvents()
                pane._preview_edit_active = True
                pane._commit_preview_edit_to_markdown(force=True)
                self.__class__._app.processEvents()

            stable = editor.toPlainText()
            self.assertIn("| --- | --- | --- | --- | --- |", stable)
            self.assertNotIn("||||||", stable)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

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
            self.__class__._app.processEvents()

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
            pane._commit_preview_edit_to_markdown(force=True)
            self.__class__._app.processEvents()

            nonempty = [line for line in editor.toPlainText().splitlines() if line.strip()]
            self.assertGreaterEqual(len(nonempty), 3)
            self.assertEqual(
                nonempty[:3],
                ["| ABC |  |", "| --- | --- |", "|  |  |"],
            )
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_typed_table_cell_survives_rerender_cycles(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("A\nB\n\nD\nE")
            pane._render()
            self.__class__._app.processEvents()

            plain = pane._view.toPlainText()
            pos_d = plain.find("D")
            self.assertGreaterEqual(pos_d, 0)
            cursor = pane._view.textCursor()
            cursor.setPosition(pos_d)
            pane._view.setTextCursor(cursor)

            pane._insert_markdown_table(5, 5)
            self.__class__._app.processEvents()

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
            pane._commit_preview_edit_to_markdown(force=True)
            self.__class__._app.processEvents()

            for _ in range(2):
                pane._render()
                self.__class__._app.processEvents()
                pane._preview_edit_active = True
                pane._commit_preview_edit_to_markdown(force=True)
                self.__class__._app.processEvents()

            out = editor.toPlainText()
            self.assertIn("| HELLO |", out)
            self.assertIn("| --- | --- | --- | --- | --- |", out)
            self.assertNotIn("|HELLO|||||", out)
            self.assertNotIn("||||||", out)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_multiline_in_table_cell_keeps_table_structure(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("| A | B |\n| --- | --- |\n| C | D |")
            pane._render()
            self.__class__._app.processEvents()

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
            pane._commit_preview_edit_to_markdown(force=True)
            self.__class__._app.processEvents()

            out = editor.toPlainText()
            self.assertIn("| --- | --- |", out)
            self.assertIn("| C | D |", out)
            self.assertNotIn("| C |  |  | D |", out)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_accent_preview_theme_adds_visual_color_overlays(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("# Titel\n\nDas ist **fett** und *kursiv*.")
            pane._render()
            self.__class__._app.processEvents()

            pane.set_preview_theme_id("accent")
            self.__class__._app.processEvents()
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
            self.__class__._app.processEvents()
            self.assertEqual(len(pane._view.extraSelections()), 0)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()

    def test_vivid_preview_theme_has_strong_color_contrast(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText("# Titel\n\nDas ist **fett** und *kursiv*.")
            pane._render()
            self.__class__._app.processEvents()

            pane.set_preview_theme_id("vivid")
            self.__class__._app.processEvents()
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
            self.__class__._app.processEvents()

    def test_heading_levels_have_distinct_accent_colors(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText(
                "# Überschrift 1\n\n## Überschrift 2\n\n### Überschrift 3"
            )
            pane._render()
            self.__class__._app.processEvents()

            pane.set_preview_theme_id("accent")
            self.__class__._app.processEvents()
            selections = pane._view.extraSelections()
            self.assertGreater(len(selections), 0)
            colors_by_text: dict[str, str] = {}
            for sel in selections:
                fg = sel.format.foreground().color()
                if not fg.isValid():
                    continue
                token = sel.cursor.selectedText().replace("\u2029", "\n").strip()
                if token in {"Überschrift 1", "Überschrift 2", "Überschrift 3"}:
                    colors_by_text[token] = fg.name()
            self.assertIn("Überschrift 1", colors_by_text)
            self.assertIn("Überschrift 2", colors_by_text)
            self.assertIn("Überschrift 3", colors_by_text)
            unique = {
                colors_by_text["Überschrift 1"],
                colors_by_text["Überschrift 2"],
                colors_by_text["Überschrift 3"],
            }
            self.assertGreaterEqual(len(unique), 3)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            self.__class__._app.processEvents()


if __name__ == "__main__":
    unittest.main()
