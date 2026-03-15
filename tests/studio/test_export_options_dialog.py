from __future__ import annotations

import unittest

import pytest

from studio.canvas.exporting.options_dialog import ExportOptionsDialog


pytestmark = pytest.mark.usefixtures("qt_app")


class ExportOptionsDialogTests(unittest.TestCase):
    def test_multi_column_is_disabled_for_pdf_and_enabled_for_docx(self):
        dialog = ExportOptionsDialog(default_format="pdf", user_mode="easy_eng")
        try:
            self.assertFalse(dialog.multi_column_cb.isEnabled())
            self.assertFalse(dialog.multi_column_cb.isChecked())
            self.assertTrue(dialog.multi_column_cb.styleSheet())
            self.assertIn("DOCX", dialog.multi_column_cb.toolTip())
            self.assertIn("DOCX", dialog.multi_column_cb.text())
            self.assertFalse(dialog._multi_column_hint.isHidden())
            self.assertIn("PDF", dialog._multi_column_hint.text())

            idx_word = dialog.format_combo.findData("word")
            self.assertGreaterEqual(idx_word, 0)
            dialog.format_combo.setCurrentIndex(idx_word)

            self.assertTrue(dialog.multi_column_cb.isEnabled())
            self.assertFalse(dialog.multi_column_cb.styleSheet())
            self.assertIn("DOCX", dialog.multi_column_cb.toolTip())
            self.assertTrue(dialog._multi_column_hint.isHidden())
        finally:
            dialog.deleteLater()

    def test_options_never_enable_multi_column_for_pdf(self):
        dialog = ExportOptionsDialog(default_format="pdf", user_mode="easy_eng")
        try:
            dialog.multi_column_cb.setChecked(True)
            options_pdf = dialog.options()
            self.assertEqual(options_pdf.output_format, "pdf")
            self.assertFalse(options_pdf.multi_column)

            idx_word = dialog.format_combo.findData("word")
            dialog.format_combo.setCurrentIndex(idx_word)
            dialog.multi_column_cb.setChecked(True)
            options_word = dialog.options()
            self.assertEqual(options_word.output_format, "word")
            self.assertTrue(options_word.multi_column)
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
