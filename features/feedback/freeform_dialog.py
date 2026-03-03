"""Free-form feedback dialog — independent of any specific AI event."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from services.feedback.settings import FEEDBACK_USE_CASES
from .categories import CATEGORIES, DEFAULT_CATEGORIES

_STYLE = """
QDialog { background: #1E1E2E; color: #CDD6F4; }
QLabel { color: #CDD6F4; font-size: 11px; }
QGroupBox {
    background: #181825; color: #CDD6F4;
    border: 1px solid #45475A; border-radius: 4px;
    margin-top: 8px; padding: 6px 8px; font-size: 11px;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 0 4px; color: #CBA6F7;
}
QComboBox {
    background: #313244; color: #CDD6F4;
    border: 1px solid #45475A; border-radius: 3px;
    padding: 3px 8px; font-size: 11px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background: #313244; color: #CDD6F4;
    border: 1px solid #45475A; selection-background-color: #45475A;
}
QPlainTextEdit {
    background: #313244; color: #CDD6F4;
    border: 1px solid #45475A; border-radius: 4px;
    padding: 4px; font-size: 11px;
}
QPlainTextEdit:focus { border-color: #89B4FA; }
QPushButton {
    background: #313244; color: #CDD6F4;
    border: 1px solid #45475A; border-radius: 4px;
    padding: 4px 12px; font-size: 11px;
}
QPushButton:hover { background: #45475A; }
QPushButton#like  { background: #1E3A2F; border-color: #A6E3A1; color: #A6E3A1; }
QPushButton#like:checked  { background: #2A5040; border-color: #A6E3A1; }
QPushButton#dislike { background: #3A1E2A; border-color: #F38BA8; color: #F38BA8; }
QPushButton#dislike:checked { background: #5A2A3A; border-color: #F38BA8; }
"""

_USE_CASE_LABELS: dict[str, str] = {
    "chat_answer": "Chat-Antwort",
    "fact_check": "Faktencheck",
    "canvas_edit": "Canvas-Rewrite",
    "rag_search": "RAG-Suche",
    "file_import": "Datei-Import",
    "mindmap": "MindMap/Graph",
    "glossary": "Glossar",
    "tts": "Text-zu-Sprache",
    "stt": "Spracherkennung",
    "input": "Eingabe",
    "other": "Sonstiges",
}


class FeedbackFreeformDialog(QDialog):
    """
    Stand-alone feedback dialog — not tied to any specific event.

    The user picks a use-case and sentiment, optionally adds notes,
    and submits.  The caller calls ``get_result()`` to retrieve the values.
    """

    def __init__(self, feedback_service, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Feedback geben")
        self.resize(440, 360)
        self.setStyleSheet(_STYLE)
        self._service = feedback_service
        self._sentiment = ""
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(10)

        # Use-case selector
        uc_group = QGroupBox("Worum geht es?")
        uc_layout = QVBoxLayout(uc_group)
        uc_layout.setContentsMargins(8, 12, 8, 8)
        self._uc_combo = QComboBox()
        for key in FEEDBACK_USE_CASES:
            label = _USE_CASE_LABELS.get(key, key)
            self._uc_combo.addItem(label, key)
        self._uc_combo.currentIndexChanged.connect(self._on_use_case_changed)
        uc_layout.addWidget(self._uc_combo)
        root.addWidget(uc_group)

        # Sentiment
        sent_group = QGroupBox("Bewertung")
        sent_layout = QHBoxLayout(sent_group)
        sent_layout.setContentsMargins(8, 12, 8, 8)
        sent_layout.setSpacing(12)
        self._like_btn = QPushButton("👍  Gut")
        self._like_btn.setObjectName("like")
        self._like_btn.setCheckable(True)
        self._like_btn.clicked.connect(lambda: self._set_sentiment("positive"))
        self._dislike_btn = QPushButton("👎  Schlecht")
        self._dislike_btn.setObjectName("dislike")
        self._dislike_btn.setCheckable(True)
        self._dislike_btn.clicked.connect(lambda: self._set_sentiment("negative"))
        sent_layout.addWidget(self._like_btn)
        sent_layout.addWidget(self._dislike_btn)
        sent_layout.addStretch()
        root.addWidget(sent_group)

        # Note
        note_group = QGroupBox("Anmerkung (optional)")
        note_layout = QVBoxLayout(note_group)
        note_layout.setContentsMargins(8, 12, 8, 8)
        self._note_edit = QPlainTextEdit()
        self._note_edit.setPlaceholderText("Beschreibe deine Erfahrung oder das Problem…")
        self._note_edit.setMaximumHeight(80)
        note_layout.addWidget(self._note_edit)
        root.addWidget(note_group)

        root.addStretch()

        # Buttons
        self._btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._send_btn = self._btn_box.addButton(
            "Feedback senden", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._send_btn.setEnabled(False)
        self._btn_box.accepted.connect(self._submit)
        self._btn_box.rejected.connect(self.reject)
        root.addWidget(self._btn_box)

    def _set_sentiment(self, sentiment: str):
        self._sentiment = sentiment
        self._like_btn.setChecked(sentiment == "positive")
        self._dislike_btn.setChecked(sentiment == "negative")
        self._send_btn.setEnabled(True)

    def _on_use_case_changed(self, _index: int):
        pass  # could update category list in future

    def _current_use_case(self) -> str:
        return str(self._uc_combo.currentData() or "other")

    def _submit(self):
        if not self._sentiment:
            return
        use_case = self._current_use_case()
        note = self._note_edit.toPlainText().strip()
        self._service.submit_feedback(
            use_case=use_case,
            sentiment=self._sentiment,
            note=note,
        )
        self.accept()
