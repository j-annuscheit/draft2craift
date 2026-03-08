from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from features.canvas.widget import CanvasTabWidget
from widgets.markdown.editor import TabbedEditorWidget


class DraftTabTitleLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_tabbed_editor_stored_title_limit_keeps_10_and_truncates_11(self):
        tabs = TabbedEditorWidget(
            default_read_only=False,
            tab_title_prefix="Draft",
            stored_title_max_chars=10,
        )
        try:
            idx = tabs.tab_widget.currentIndex()
            self.assertGreaterEqual(idx, 0)

            tabs.set_tab_full_title(idx, "1234567890")
            self.assertEqual(tabs.get_tab_full_title(idx), "1234567890")
            self.assertEqual(tabs.tab_widget.tabText(idx), "1234567890")

            tabs.set_tab_full_title(idx, "12345678901")
            self.assertEqual(tabs.get_tab_full_title(idx), "1234567...")
            self.assertEqual(tabs.tab_widget.tabText(idx), "1234567...")
        finally:
            tabs.deleteLater()
            self.__class__._app.processEvents()

    def test_canvas_tabs_apply_10_char_limit(self):
        canvas = CanvasTabWidget()
        try:
            idx = canvas.tabs.tab_widget.currentIndex()
            self.assertGreaterEqual(idx, 0)
            canvas.tabs.set_tab_full_title(idx, "ABCDEFGHIJK")
            self.assertEqual(canvas.tabs.get_tab_full_title(idx), "ABCDEFG...")
        finally:
            canvas.deleteLater()
            self.__class__._app.processEvents()


if __name__ == "__main__":
    unittest.main()

