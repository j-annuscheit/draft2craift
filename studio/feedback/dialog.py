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

from shared.domain.user_mode import normalize_user_mode, resolve_feature_label

_DIALOG_STYLE = """
QDialog {
    background: palette(window);
    color: palette(window-text);
}
QGroupBox {
    background: palette(base);
    color: palette(text);
    border: 1px solid palette(mid);
    border-radius: 4px;
    margin-top: 8px;
    padding: 6px 8px;
    font-size: 11px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    color: palette(highlight);
}
QCheckBox {
    color: palette(text);
    font-size: 11px;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid palette(mid);
    border-radius: 2px;
    background: palette(alternate-base);
}
QCheckBox::indicator:checked {
    background: palette(highlight);
    border-color: palette(highlight);
}
QPlainTextEdit {
    background: palette(base);
    color: palette(text);
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 4px;
    font-size: 11px;
}
QPlainTextEdit:focus { border-color: palette(highlight); }
QPushButton {
    background: palette(alternate-base);
    color: palette(text);
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 11px;
}
QPushButton:hover { border-color: palette(highlight); }
QPushButton:pressed { background: palette(mid); }
"""

_CATEGORIES: dict[str, list[str]] = {
    "chat_answer": [
        "Fehlende Wörter im Satz",
        "Sätze beginnen immer gleich",
        "Falsche Informationen",
        "Zu lange Antwort",
        "Zu kurze Antwort",
        "Schlechter Schreibstil",
        "Antwort thematisch falsch",
        "Sonstiges",
    ],
    "fact_check": [
        "Fakten falsch bewertet",
        "Quellen falsch zugeordnet",
        "Ergebnis unvollständig",
        "Zu viele Falsch-Positive",
        "Sonstiges",
    ],
    "canvas_edit": [
        "Rewrite inhaltlich falsch",
        "Wichtige Aussagen fehlen",
        "Zu stark verändert",
        "Schlechter Schreibstil",
        "Sonstiges",
    ],
    "mindmap": [
        "Knotenstruktur unklar",
        "Wichtige Knoten fehlen",
        "Verbindungen fehlerhaft",
        "Interaktion/Navigation problematisch",
        "Sonstiges",
    ],
    "rag_search": [
        "Falsche Dokumente gefunden",
        "Relevante Dokumente fehlen",
        "Ergebnisse doppelt",
        "Schlechte Relevanz",
        "Sonstiges",
    ],
    "file_import": [
        "Text unlesbar/fehlerhaft",
        "Formatierung verloren",
        "Seiten/Abschnitte fehlen",
        "Tabellen fehlerhaft",
        "Zu viel Rauschen",
        "Sonstiges",
    ],
}

_DEFAULT_CATEGORIES: list[str] = [
    "Fehlerhafte Ausgabe",
    "Unerwartetes Verhalten",
    "Sonstiges",
]


class FeedbackNegativeDialog(QDialog):
    """Dialog for negative feedback with category checkboxes and free text."""

    def __init__(self, use_case: str, user_mode: str | None = None, parent=None):
        super().__init__(parent)
        self._user_mode = normalize_user_mode("" if user_mode is None else user_mode)
        self._group_problem: QGroupBox | None = None
        self._send_btn = None
        self._cancel_btn = None
        self._note_edit: QPlainTextEdit | None = None
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "feedback.negative.window_title",
                "Feedback: Was war das Problem?",
            )
        )
        self.resize(400, 320)
        self.setStyleSheet(_DIALOG_STYLE)
        self._use_case = str(use_case or "").strip()
        self._checkboxes: list[QCheckBox] = []
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(8)

        categories = _CATEGORIES.get(self._use_case, _DEFAULT_CATEGORIES)

        group = QGroupBox(
            resolve_feature_label(
                self._user_mode,
                "feedback.negative.group.problem",
                "Was war das Problem?",
            )
        )
        self._group_problem = group
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(4)
        group_layout.setContentsMargins(8, 12, 8, 8)

        for cat in categories:
            cb = QCheckBox(cat)
            group_layout.addWidget(cb)
            self._checkboxes.append(cb)

        root.addWidget(group)

        self._note_edit = QPlainTextEdit()
        self._note_edit.setPlaceholderText(
            resolve_feature_label(
                self._user_mode,
                "feedback.negative.note.placeholder",
                "Weitere Anmerkungen (optional)…",
            )
        )
        self._note_edit.setMaximumHeight(64)
        root.addWidget(self._note_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
        )
        send_btn = buttons.addButton(
            resolve_feature_label(
                self._user_mode,
                "feedback.negative.button.send",
                "Feedback senden",
            ),
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._send_btn = send_btn
        send_btn.setDefault(True)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self._cancel_btn = cancel_btn
        if cancel_btn is not None:
            cancel_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.negative.button.cancel",
                    "Abbrechen",
                )
            )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "feedback.negative.window_title",
                "Feedback: Was war das Problem?",
            )
        )
        if self._group_problem is not None:
            self._group_problem.setTitle(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.negative.group.problem",
                    "Was war das Problem?",
                )
            )
        if self._note_edit is not None:
            self._note_edit.setPlaceholderText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.negative.note.placeholder",
                    "Weitere Anmerkungen (optional)…",
                )
            )
        if self._send_btn is not None:
            self._send_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.negative.button.send",
                    "Feedback senden",
                )
            )
        if self._cancel_btn is not None:
            self._cancel_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.negative.button.cancel",
                    "Abbrechen",
                )
            )

    def get_error_tags(self) -> list[str]:
        return [cb.text() for cb in self._checkboxes if cb.isChecked()]

    def get_note(self) -> str:
        return self._note_edit.toPlainText().strip()
