from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from PySide6.QtGui import QTextDocument

from studio.controllers.find_replace_ctrl import FindReplaceController
from studio.canvas.editor import MarkdownEditor

# Stub classes to mimic Qt objects
class _Signal:
    def __init__(self):
        self._slots = []
    def connect(self, slot):
        self._slots.append(slot)
    def disconnect(self, slot):
        if slot in self._slots:
            self._slots.remove(slot)
    def emit(self, *args):
        for slot in self._slots:
            slot(*args)

class _Cursor(Mock):
    def __init__(self, selected_text="", is_null=False, start=0, end=0):
        super().__init__()
        self._selected_text = selected_text
        self._is_null = is_null
        self._start = start
        self._end = end
        self.insertText = Mock()
        self.beginEditBlock = Mock()
        self.endEditBlock = Mock()
        self.movePosition = Mock()
        self.clearSelection = Mock()

    def selectedText(self):
        return self._selected_text

    def isNull(self):
        return self._is_null

    def selectionStart(self):
        return self._start

    def selectionEnd(self):
        return self._end

    def position(self):
        return self._end

class _DocumentStub(Mock):
    def __init__(self, text=""):
        super().__init__(spec=QTextDocument)
        self._text = text
        self.find = Mock(side_effect=self._find)

    def toPlainText(self):
        return self._text

    def characterCount(self):
        return len(self._text)

    def _find(self, needle, start=0, *_args):
        query = str(needle or "")
        if not query:
            return _Cursor(is_null=True)
        text = self._text
        index = text.find(query, max(0, int(start)))
        if index < 0:
            return _Cursor(is_null=True)
        return _Cursor(
            selected_text=query,
            is_null=False,
            start=index,
            end=index + len(query),
        )

class _EditorStub(Mock):
    def __init__(self, text="", selected_text="", **kwargs):
        super().__init__(spec=MarkdownEditor, **kwargs)
        self._document = _DocumentStub(text)
        self._cursor = _Cursor(selected_text=selected_text)
        self.textChanged = _Signal()
        self.read_only_changed = _Signal()
        self.setTextCursor = Mock()
        self.ensureCursorVisible = Mock()

    def toPlainText(self):
        return self._document.toPlainText()

    def document(self):
        return self._document

    def textCursor(self):
        return self._cursor

    def isReadOnly(self):
        return False

class FindReplaceControllerTests(unittest.TestCase):

    def setUp(self):
        self.parent_window = Mock()
        self.canvas = Mock()
        self.knowledge_dock = Mock()
        self.show_status = Mock()

    def test_initialization(self):
        """Test that the controller initializes correctly."""
        with patch("studio.controllers.autosave.QTimer", Mock()):
            controller = FindReplaceController(
                parent_window=self.parent_window,
                canvas=self.canvas,
                knowledge_dock=self.knowledge_dock,
                show_status=self.show_status,
            )
        self.assertIsNotNone(controller)
        self.assertIsNone(controller._dialog)

    def test_open_dialog_no_target(self):
        """Test open_dialog when no active editor is found."""
        with patch("studio.controllers.autosave.QTimer", Mock()):
            controller = FindReplaceController(
                parent_window=self.parent_window,
                canvas=self.canvas,
                knowledge_dock=self.knowledge_dock,
                show_status=self.show_status,
            )
        controller._resolve_find_target = Mock(return_value=None)
        controller.open_dialog()
        self.show_status.assert_called_with("Kein aktiver Editor für Suche.", 2000)

    @patch('studio.controllers.find_replace_ctrl.QDialog')
    @patch('studio.controllers.find_replace_ctrl.QLineEdit')
    @patch('studio.controllers.find_replace_ctrl.QCheckBox')
    @patch('studio.controllers.find_replace_ctrl.QLabel')
    @patch('studio.controllers.find_replace_ctrl.QPushButton')
    @patch('studio.controllers.find_replace_ctrl.QHBoxLayout')
    @patch('studio.controllers.find_replace_ctrl.QVBoxLayout')
    @patch("studio.controllers.find_replace_ctrl.QApplication.focusWidget")
    def test_open_dialog_with_editor_target(self, mock_focus_widget, *mocks):
        """Test open_dialog when an editor target is found."""
        with patch("studio.controllers.autosave.QTimer", Mock()):
            controller = FindReplaceController(
                parent_window=self.parent_window,
                canvas=self.canvas,
                knowledge_dock=self.knowledge_dock,
                show_status=self.show_status,
            )
        editor_stub = _EditorStub(text="some text", selected_text="find me")
        mock_focus_widget.return_value = editor_stub
        
        controller._resolve_find_target = Mock(return_value={"kind": "editor", "editor": editor_stub})

        controller.open_dialog()
        
        self.assertIsNotNone(controller._dialog)
        controller._find_query_edit.setText.assert_called_with("find me")
        controller._dialog.show.assert_called_once()

if __name__ == "__main__":
    unittest.main()
