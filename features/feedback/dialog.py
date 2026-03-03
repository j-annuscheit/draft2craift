"""Feedback negative dialog with checkboxes and optional free-text."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from .categories import CATEGORIES, DEFAULT_CATEGORIES

_DIALOG_STYLE = """
QDialog {
    background: #1E1E2E;
    color: #CDD6F4;
}
QGroupBox {
    background: #181825;
    color: #CDD6F4;
    border: 1px solid #45475A;
    border-radius: 4px;
    margin-top: 8px;
    padding: 6px 8px;
    font-size: 11px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    color: #CBA6F7;
}
QCheckBox {
    color: #CDD6F4;
    font-size: 11px;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #45475A;
    border-radius: 2px;
    background: #313244;
}
QCheckBox::indicator:checked {
    background: #CBA6F7;
    border-color: #CBA6F7;
}
QPlainTextEdit {
    background: #313244;
    color: #CDD6F4;
    border: 1px solid #45475A;
    border-radius: 4px;
    padding: 4px;
    font-size: 11px;
}
QPlainTextEdit:focus { border-color: #89B4FA; }
QPushButton {
    background: #313244;
    color: #CDD6F4;
    border: 1px solid #45475A;
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 11px;
}
QPushButton:hover { background: #45475A; }
QPushButton:pressed { background: #585B70; }
"""


class FeedbackNegativeDialog(QDialog):
    """Dialog for negative feedback with category checkboxes and free text."""

    def __init__(self, use_case: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Feedback: Was war das Problem?")
        self.resize(400, 320)
        self.setStyleSheet(_DIALOG_STYLE)
        self._use_case = str(use_case or "").strip()
        self._checkboxes: list[QCheckBox] = []
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(8)

        categories = CATEGORIES.get(self._use_case, DEFAULT_CATEGORIES)

        group = QGroupBox("Was war das Problem?")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(4)
        group_layout.setContentsMargins(8, 12, 8, 8)

        for cat in categories:
            cb = QCheckBox(cat)
            group_layout.addWidget(cb)
            self._checkboxes.append(cb)

        root.addWidget(group)

        self._note_edit = QPlainTextEdit()
        self._note_edit.setPlaceholderText("Weitere Anmerkungen (optional)…")
        self._note_edit.setMaximumHeight(64)
        root.addWidget(self._note_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
        )
        send_btn = buttons.addButton(
            "Feedback senden", QDialogButtonBox.ButtonRole.AcceptRole
        )
        send_btn.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def get_error_tags(self) -> list[str]:
        return [cb.text() for cb in self._checkboxes if cb.isChecked()]

    def get_note(self) -> str:
        return self._note_edit.toPlainText().strip()
