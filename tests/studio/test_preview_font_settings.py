from __future__ import annotations

import unittest

import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from studio.canvas.editor import MarkdownEditor
from studio.canvas.preview.pane import CanvasPreviewPane
from studio.canvas.preview.style_settings import (
    default_preview_style_settings,
    normalize_preview_style_settings,
)


pytestmark = pytest.mark.usefixtures("qt_app")


def _pick_font_families() -> tuple[str, str]:
    try:
        families = [str(name).strip() for name in QFontDatabase.families() if str(name).strip()]
    except Exception:
        families = []
    if not families:
        return ("DejaVu Sans", "DejaVu Sans Mono")
    primary = families[0]
    secondary = families[-1] if len(families) > 1 else families[0]
    return (primary, secondary)


def _process_events() -> None:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


class PreviewFontSettingsTests(unittest.TestCase):
    def test_normalize_maps_legacy_font_family_to_html_font_family(self):
        style = normalize_preview_style_settings({"font_family": "Arial"})
        self.assertEqual(str(style["html_font_family"]), "Arial")
        self.assertEqual(str(style["font_family"]), "Arial")

    def test_markdown_editor_global_font_family_updates_existing_and_new_instances(self):
        old = MarkdownEditor.global_font_family()
        requested, fallback = _pick_font_families()
        first = MarkdownEditor(read_only=False)
        try:
            MarkdownEditor.apply_global_font_family(requested, force=True)
            _process_events()
            self.assertEqual(str(getattr(first, "_font_family", "")), requested)

            second = MarkdownEditor(read_only=False)
            try:
                self.assertEqual(str(getattr(second, "_font_family", "")), requested)
                MarkdownEditor.apply_global_font_family(fallback, force=True)
                _process_events()
                self.assertEqual(str(getattr(first, "_font_family", "")), fallback)
                self.assertEqual(str(getattr(second, "_font_family", "")), fallback)
            finally:
                second.deleteLater()
        finally:
            MarkdownEditor.apply_global_font_family(old, force=True)
            first.deleteLater()
            _process_events()

    def test_html_font_family_is_applied_to_preview_document(self):
        html_font, markdown_font = _pick_font_families()
        old_editor_font = MarkdownEditor.global_font_family()
        editor = MarkdownEditor(read_only=False)
        pane = CanvasPreviewPane(
            allow_editing=True,
            show_title=False,
            sync_cursor_with_editor=False,
        )
        try:
            style = default_preview_style_settings()
            style["html_font_family"] = html_font
            style["markdown_font_family"] = markdown_font
            pane.bind_editor(editor)
            editor.setPlainText("Hallo\n\nWelt")
            pane._render()
            pane.set_preview_style_settings(style, force=True)
            _process_events()
            body_line = next(
                (
                    line
                    for line in pane._view.toHtml().splitlines()
                    if "<body style=" in line
                ),
                "",
            )
            self.assertIn(html_font, body_line)
        finally:
            MarkdownEditor.apply_global_font_family(old_editor_font, force=True)
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_code_font_size_scales_below_previous_floor_on_small_zoom(self):
        pane = CanvasPreviewPane(
            allow_editing=True,
            show_title=False,
            sync_cursor_with_editor=False,
        )
        try:
            style = default_preview_style_settings()
            style["base_font_percent"] = 70
            pane.set_preview_style_settings(style, force=True)
            pane.set_preview_zoom_percent(60)
            _process_events()

            expected_body_pt = 11.0 * 0.60 * 0.70
            expected_code_pt = expected_body_pt * 0.95
            self.assertLess(expected_code_pt, 8.0)
            self.assertAlmostEqual(pane._code_pt(), expected_code_pt, places=3)
        finally:
            pane.deleteLater()
            _process_events()


if __name__ == "__main__":
    unittest.main()
