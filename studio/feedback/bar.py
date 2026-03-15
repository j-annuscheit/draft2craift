"""Compact feedback bar widget with thumbs up/down buttons."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from shared.domain.user_mode import normalize_user_mode, resolve_feature_label
from .dialog import FeedbackNegativeDialog
from studio.dialogs.window_manager import find_dialog_manager
from studio.theme import theme_tokens

_BTN_BASE = (
    "QPushButton {"
    "    background: palette(alternate-base); color: palette(text);"
    "    border: 1px solid palette(mid); border-radius: 3px;"
    "    padding: 2px 8px; font-size: 12px;"
    "}"
    "QPushButton:hover { border-color: palette(highlight); }"
    "QPushButton:pressed { background: palette(mid); }"
    "QPushButton:disabled { background: palette(window); color: palette(placeholder-text); border-color: palette(alternate-base); }"
)

_BAR_STYLE = (
    "QWidget#FeedbackBar {"
    "    background: palette(base);"
    "    border-top: 1px solid palette(alternate-base);"
    "}"
)

_BAR_STYLE_INLINE = (
    "QWidget#FeedbackBar {"
    "    background: transparent;"
    "}"
)

_HIDE_DELAY_MS = 1500  # ms bis die Bar nach einem Klick verschwindet


class FeedbackBar(QWidget):
    """Compact thumbs-up/down bar shown after AI outputs.

    Pass ``inline=True`` for a transparent, borderless variant that fits
    inside a status bar or toolbar row.
    """

    feedback_submitted = Signal(str, list, str)  # sentiment, error_tags, note

    def __init__(self, parent: QWidget | None = None, *, inline: bool = False):
        super().__init__(parent)
        self.setObjectName("FeedbackBar")
        if inline:
            self.setFixedHeight(22)
            self.setStyleSheet(_BAR_STYLE_INLINE)
        else:
            self.setFixedHeight(28)
            self.setStyleSheet(_BAR_STYLE)
        self._use_case = ""
        self._user_mode = ""
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self._setup_ui()
        self.set_user_mode("")
        self.hide()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        self._like_btn = QPushButton("👍")
        self._like_btn.setToolTip("Gut – Feedback senden")
        self._like_btn.setFixedWidth(36)
        self._like_btn.setStyleSheet(_BTN_BASE)
        self._like_btn.clicked.connect(self._on_like)

        self._dislike_btn = QPushButton("👎")
        self._dislike_btn.setToolTip("Schlecht – Feedback senden")
        self._dislike_btn.setFixedWidth(36)
        self._dislike_btn.setStyleSheet(_BTN_BASE)
        self._dislike_btn.clicked.connect(self._on_dislike)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            "color: palette(placeholder-text); font-size: 10px; background: transparent;"
        )

        layout.addWidget(self._like_btn)
        layout.addWidget(self._dislike_btn)
        layout.addWidget(self._status_lbl)
        layout.addStretch()

    def activate(self, use_case: str):
        """Show bar and enable buttons for the given use-case."""
        self._hide_timer.stop()
        self._use_case = str(use_case or "").strip()
        self._like_btn.setEnabled(True)
        self._dislike_btn.setEnabled(True)
        self._status_lbl.setText("")
        self._status_lbl.setStyleSheet(
            "color: palette(placeholder-text); font-size: 10px; background: transparent;"
        )
        self.show()

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self._like_btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "feedback.bar.like.tooltip",
                "Gut – Feedback senden",
            )
        )
        self._dislike_btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "feedback.bar.dislike.tooltip",
                "Schlecht – Feedback senden",
            )
        )

    def reset(self):
        """Hide bar immediately and reset state."""
        self._hide_timer.stop()
        self._use_case = ""
        self._like_btn.setEnabled(True)
        self._dislike_btn.setEnabled(True)
        self._status_lbl.setText("")
        self.hide()

    def _confirm_and_hide(self, text: str, color: str):
        """Show confirmation text, then fade out after a short delay."""
        self._like_btn.setEnabled(False)
        self._dislike_btn.setEnabled(False)
        self._status_lbl.setStyleSheet(
            f"color: {color}; font-size: 10px; background: transparent;"
        )
        self._status_lbl.setText(text)
        self._hide_timer.start(_HIDE_DELAY_MS)

    def _on_like(self):
        self.feedback_submitted.emit("positive", [], "")
        self._confirm_and_hide(
            resolve_feature_label(
                self._user_mode,
                "feedback.bar.like.saved_text",
                "👍 Gespeichert",
            ),
            theme_tokens()["success"],
        )

    def _on_dislike(self):
        manager = find_dialog_manager(self)
        if manager is not None:
            manager.show_dialog(
                f"feedback-negative:{id(self)}",
                lambda: FeedbackNegativeDialog(
                    self._use_case,
                    user_mode=self._user_mode,
                    parent=self,
                ),
                on_accept=lambda dlg: self._submit_negative_feedback(dlg),
            )
            return
        dlg = FeedbackNegativeDialog(
            self._use_case,
            user_mode=self._user_mode,
            parent=self,
        )
        if dlg.exec() != FeedbackNegativeDialog.DialogCode.Accepted:
            return
        self._submit_negative_feedback(dlg)

    def _submit_negative_feedback(self, dialog: FeedbackNegativeDialog) -> None:
        tags = dialog.get_error_tags()
        note = dialog.get_note()
        self.feedback_submitted.emit("negative", tags, note)
        self._confirm_and_hide(
            resolve_feature_label(
                self._user_mode,
                "feedback.bar.dislike.saved_text",
                "👎 Danke",
            ),
            theme_tokens()["danger"],
        )
