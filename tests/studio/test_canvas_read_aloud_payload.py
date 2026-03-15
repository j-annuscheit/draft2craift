from __future__ import annotations

import unittest

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from studio.canvas.tabs import CanvasTabWidget


pytestmark = pytest.mark.usefixtures("qt_app")


def _process_events() -> None:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


class CanvasReadAloudPayloadTests(unittest.TestCase):
    def test_read_aloud_prefers_selected_text(self):
        canvas = CanvasTabWidget()
        try:
            panel = canvas.tabs.current_panel()
            assert panel is not None
            editor = panel.editor
            editor.setPlainText("Alpha\nBeta line")
            cursor = editor.textCursor()
            start = editor.toPlainText().find("Beta")
            cursor.setPosition(start)
            cursor.setPosition(start + len("Beta"), QTextCursor.MoveMode.KeepAnchor)
            editor.setTextCursor(cursor)

            payloads: list[str] = []
            canvas.read_aloud_requested.connect(lambda text: payloads.append(str(text)))
            canvas._request_read_aloud()

            self.assertEqual(payloads[-1], "Beta")
        finally:
            canvas.deleteLater()
            _process_events()

    def test_read_aloud_falls_back_to_full_document(self):
        canvas = CanvasTabWidget()
        try:
            panel = canvas.tabs.current_panel()
            assert panel is not None
            editor = panel.editor
            editor.setPlainText("Alpha\nBeta line")
            cursor = editor.textCursor()
            pos = editor.toPlainText().find("line")
            cursor.setPosition(pos)
            editor.setTextCursor(cursor)

            payloads: list[str] = []
            canvas.read_aloud_requested.connect(lambda text: payloads.append(str(text)))
            canvas._request_read_aloud()

            self.assertEqual(payloads[-1], "Alpha\nBeta line")
        finally:
            canvas.deleteLater()
            _process_events()


if __name__ == "__main__":
    unittest.main()
