from __future__ import annotations

import unittest

import pytest

from studio.dialogs.annotation_export_dialog import AnnotationExportDialog


pytestmark = pytest.mark.usefixtures("qt_app")


class AnnotationExportDialogTests(unittest.TestCase):
    def test_defaults_keep_markers_unchecked_and_sort_by_color(self):
        dialog = AnnotationExportDialog(
            color_counts=[("#F9E2AF", 2), ("#A6E3A1", 1)],
            glossary_count=1,
            user_mode="plus",
        )
        try:
            self.assertFalse(dialog._keep_markers_cb.isChecked())
            self.assertEqual(dialog._sort_combo.currentData(), "grouped_by_color")

            options = dialog.options()
            self.assertFalse(options.keep_markers)
            self.assertEqual(options.sort_mode, "grouped_by_color")
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
