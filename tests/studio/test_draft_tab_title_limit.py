from __future__ import annotations

import unittest

import pytest
from PySide6.QtWidgets import QApplication

from studio.canvas.tabs import CanvasTabWidget
from studio.canvas.tabbed_editor_widget import TabbedEditorWidget


pytestmark = pytest.mark.usefixtures("qt_app")


def _process_events() -> None:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


class DraftTabTitleLimitTests(unittest.TestCase):
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
            _process_events()

    def test_canvas_tabs_apply_10_char_limit(self):
        canvas = CanvasTabWidget()
        try:
            idx = canvas.tabs.tab_widget.currentIndex()
            self.assertGreaterEqual(idx, 0)
            canvas.tabs.set_tab_full_title(idx, "ABCDEFGHIJK")
            self.assertEqual(canvas.tabs.get_tab_full_title(idx), "ABCDEFG...")
        finally:
            canvas.deleteLater()
            _process_events()


if __name__ == "__main__":
    unittest.main()
