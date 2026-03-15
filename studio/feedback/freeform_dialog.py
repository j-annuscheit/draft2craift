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

from shared.domain.user_mode import normalize_user_mode, resolve_feature_label
from shared.services.feedback.settings import FEEDBACK_USE_CASES
from studio.theme import theme_tokens

def _dialog_style() -> str:
    tokens = theme_tokens()
    return f"""
QDialog {{ background: palette(window); color: palette(window-text); }}
QLabel {{ color: palette(text); font-size: 11px; }}
QGroupBox {{
    background: palette(base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 4px;
    margin-top: 8px; padding: 6px 8px; font-size: 11px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 0 4px; color: palette(highlight);
}}
QComboBox {{
    background: palette(base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 3px;
    padding: 3px 8px; font-size: 11px;
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: palette(alternate-base); color: palette(text);
    border: 1px solid palette(mid);
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
}}
QPlainTextEdit {{
    background: palette(base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 4px;
    padding: 4px; font-size: 11px;
}}
QPlainTextEdit:focus {{ border-color: palette(highlight); }}
QPushButton {{
    background: palette(alternate-base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 4px;
    padding: 4px 12px; font-size: 11px;
}}
QPushButton:hover {{ border-color: palette(highlight); }}
QPushButton#like {{
    background: palette(base);
    border-color: {tokens["success"]};
    color: {tokens["success"]};
}}
QPushButton#like:checked {{
    background: {tokens["success"]};
    border-color: {tokens["success"]};
    color: palette(highlighted-text);
}}
QPushButton#dislike {{
    background: palette(base);
    border-color: {tokens["danger"]};
    color: {tokens["danger"]};
}}
QPushButton#dislike:checked {{
    background: {tokens["danger"]};
    border-color: {tokens["danger"]};
    color: palette(highlighted-text);
}}
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

    def __init__(self, feedback_service, user_mode: str | None = None, parent=None):
        super().__init__(parent)
        self._user_mode = normalize_user_mode("" if user_mode is None else user_mode)
        self._uc_group: QGroupBox | None = None
        self._sent_group: QGroupBox | None = None
        self._note_group: QGroupBox | None = None
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "feedback.freeform.window_title",
                "Feedback geben",
            )
        )
        self.resize(440, 360)
        self.setStyleSheet(_dialog_style())
        self._service = feedback_service
        self._sentiment = ""
        self._setup_ui()

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self._apply_user_mode_labels()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(10)

        # Use-case selector
        uc_group = QGroupBox(
            resolve_feature_label(
                self._user_mode,
                "feedback.freeform.group.use_case",
                "Worum geht es?",
            )
        )
        self._uc_group = uc_group
        uc_layout = QVBoxLayout(uc_group)
        uc_layout.setContentsMargins(8, 12, 8, 8)
        self._uc_combo = QComboBox()
        for key in FEEDBACK_USE_CASES:
            label = self._use_case_label(key)
            self._uc_combo.addItem(label, key)
        self._uc_combo.currentIndexChanged.connect(self._on_use_case_changed)
        uc_layout.addWidget(self._uc_combo)
        root.addWidget(uc_group)

        # Sentiment
        sent_group = QGroupBox(
            resolve_feature_label(
                self._user_mode,
                "feedback.freeform.group.sentiment",
                "Bewertung",
            )
        )
        self._sent_group = sent_group
        sent_layout = QHBoxLayout(sent_group)
        sent_layout.setContentsMargins(8, 12, 8, 8)
        sent_layout.setSpacing(12)
        self._like_btn = QPushButton(
            resolve_feature_label(
                self._user_mode,
                "feedback.freeform.button.like",
                "👍  Gut",
            )
        )
        self._like_btn.setObjectName("like")
        self._like_btn.setCheckable(True)
        self._like_btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "feedback.freeform.button.like.tooltip",
                "Positive Rückmeldung senden",
            )
        )
        self._like_btn.clicked.connect(lambda: self._set_sentiment("positive"))
        self._dislike_btn = QPushButton(
            resolve_feature_label(
                self._user_mode,
                "feedback.freeform.button.dislike",
                "👎  Schlecht",
            )
        )
        self._dislike_btn.setObjectName("dislike")
        self._dislike_btn.setCheckable(True)
        self._dislike_btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "feedback.freeform.button.dislike.tooltip",
                "Negative Rückmeldung senden",
            )
        )
        self._dislike_btn.clicked.connect(lambda: self._set_sentiment("negative"))
        sent_layout.addWidget(self._like_btn)
        sent_layout.addWidget(self._dislike_btn)
        sent_layout.addStretch()
        root.addWidget(sent_group)

        # Note
        note_group = QGroupBox(
            resolve_feature_label(
                self._user_mode,
                "feedback.freeform.group.note",
                "Anmerkung (optional)",
            )
        )
        self._note_group = note_group
        note_layout = QVBoxLayout(note_group)
        note_layout.setContentsMargins(8, 12, 8, 8)
        self._note_edit = QPlainTextEdit()
        self._note_edit.setPlaceholderText(
            resolve_feature_label(
                self._user_mode,
                "feedback.freeform.note.placeholder",
                "Beschreibe deine Erfahrung oder das Problem…",
            )
        )
        self._note_edit.setMaximumHeight(80)
        note_layout.addWidget(self._note_edit)
        root.addWidget(note_group)

        root.addStretch()

        # Buttons
        self._btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._send_btn = self._btn_box.addButton(
            resolve_feature_label(
                self._user_mode,
                "feedback.freeform.button.send",
                "Feedback senden",
            ),
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._send_btn.setEnabled(False)
        cancel_btn = self._btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.freeform.button.cancel",
                    "Abbrechen",
                )
            )
        self._btn_box.accepted.connect(self._submit)
        self._btn_box.rejected.connect(self.reject)
        root.addWidget(self._btn_box)
        self._apply_user_mode_labels()

    def _use_case_label(self, key: str) -> str:
        default = _USE_CASE_LABELS.get(key, key)
        return resolve_feature_label(
            self._user_mode,
            f"feedback.freeform.use_case.{key}",
            default,
        )

    def _apply_user_mode_labels(self) -> None:
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "feedback.freeform.window_title",
                "Feedback geben",
            )
        )
        if self._uc_group is not None:
            self._uc_group.setTitle(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.freeform.group.use_case",
                    "Worum geht es?",
                )
            )
        if self._sent_group is not None:
            self._sent_group.setTitle(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.freeform.group.sentiment",
                    "Bewertung",
                )
            )
        if self._note_group is not None:
            self._note_group.setTitle(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.freeform.group.note",
                    "Anmerkung (optional)",
                )
            )
        combo = getattr(self, "_uc_combo", None)
        if combo is not None:
            for idx in range(combo.count()):
                key = str(combo.itemData(idx) or "").strip()
                combo.setItemText(idx, self._use_case_label(key))
        if hasattr(self, "_like_btn"):
            self._like_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.freeform.button.like",
                    "👍  Gut",
                )
            )
            self._like_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.freeform.button.like.tooltip",
                    "Positive Rückmeldung senden",
                )
            )
        if hasattr(self, "_dislike_btn"):
            self._dislike_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.freeform.button.dislike",
                    "👎  Schlecht",
                )
            )
            self._dislike_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.freeform.button.dislike.tooltip",
                    "Negative Rückmeldung senden",
                )
            )
        if hasattr(self, "_note_edit"):
            self._note_edit.setPlaceholderText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.freeform.note.placeholder",
                    "Beschreibe deine Erfahrung oder das Problem…",
                )
            )
        if hasattr(self, "_send_btn"):
            self._send_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.freeform.button.send",
                    "Feedback senden",
                )
            )
        if hasattr(self, "_btn_box"):
            cancel_btn = self._btn_box.button(QDialogButtonBox.StandardButton.Cancel)
            if cancel_btn is not None:
                cancel_btn.setText(
                    resolve_feature_label(
                        self._user_mode,
                        "feedback.freeform.button.cancel",
                        "Abbrechen",
                    )
                )

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
