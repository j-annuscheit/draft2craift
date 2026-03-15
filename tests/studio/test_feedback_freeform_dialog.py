from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialogButtonBox

from shared.domain.user_mode import USER_MODE_CONFIG_PATH, reload_user_mode_config
from studio.feedback.freeform_dialog import FeedbackFreeformDialog


class _FeedbackServiceStub:
    def submit_feedback(
        self,
        *,
        use_case: str,
        sentiment: str,
        note: str,
    ) -> None:
        _ = use_case, sentiment, note


def _write_feedback_mode_config(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "alpha.toml").write_text(
        """
version = 1
id = "alpha"
label = "Alpha"
order = 0
default_profile = true

[visibility]

[labels]
"feedback.freeform.window_title" = "Give Feedback"
"feedback.freeform.group.use_case" = "What is this about?"
"feedback.freeform.group.sentiment" = "Rating"
"feedback.freeform.group.note" = "Comment (optional)"
"feedback.freeform.note.placeholder" = "Describe your experience or the problem..."
"feedback.freeform.button.like" = "Good"
"feedback.freeform.button.dislike" = "Bad"
"feedback.freeform.button.send" = "Send Feedback"
"feedback.freeform.button.cancel" = "Cancel"
"feedback.freeform.use_case.input" = "Input"
""".strip(),
        encoding="utf-8",
    )

    (path / "beta.toml").write_text(
        """
version = 1
id = "beta"
label = "Beta"
order = 1
default_profile = false

[visibility]

[labels]
"feedback.freeform.window_title" = "Feedback geben"
"feedback.freeform.group.use_case" = "Worum geht es"
"feedback.freeform.group.sentiment" = "Bewertung"
"feedback.freeform.group.note" = "Anmerkung (optional)"
"feedback.freeform.note.placeholder" = "Beschreibe deine Erfahrung oder das Problem..."
"feedback.freeform.button.like" = "Gut"
"feedback.freeform.button.dislike" = "Schlecht"
"feedback.freeform.button.send" = "Feedback senden"
"feedback.freeform.button.cancel" = "Abbrechen"
"feedback.freeform.use_case.input" = "Eingabe"
""".strip(),
        encoding="utf-8",
    )


def _combo_text_for_data(dialog: FeedbackFreeformDialog, key: str) -> str:
    combo = dialog._uc_combo
    for idx in range(combo.count()):
        if str(combo.itemData(idx) or "").strip() == key:
            return combo.itemText(idx)
    return ""


def test_feedback_freeform_dialog_labels_are_profile_driven(tmp_path: Path, qt_app):
    _ = qt_app
    cfg = tmp_path / "user_modes"
    _write_feedback_mode_config(cfg)

    try:
        reload_user_mode_config(cfg)
        dialog = FeedbackFreeformDialog(_FeedbackServiceStub(), user_mode="beta")

        assert dialog.windowTitle() == "Feedback geben"
        assert dialog._uc_group.title() == "Worum geht es"
        assert dialog._sent_group.title() == "Bewertung"
        assert dialog._note_group.title() == "Anmerkung (optional)"
        assert dialog._like_btn.text() == "Gut"
        assert dialog._dislike_btn.text() == "Schlecht"
        assert dialog._note_edit.placeholderText() == "Beschreibe deine Erfahrung oder das Problem..."
        assert dialog._send_btn.text() == "Feedback senden"
        cancel_btn = dialog._btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        assert cancel_btn is not None
        assert cancel_btn.text() == "Abbrechen"
        assert _combo_text_for_data(dialog, "input") == "Eingabe"

        dialog.set_user_mode("alpha")
        assert dialog.windowTitle() == "Give Feedback"
        assert dialog._uc_group.title() == "What is this about?"
        assert dialog._like_btn.text() == "Good"
        assert dialog._dislike_btn.text() == "Bad"
        assert dialog._send_btn.text() == "Send Feedback"
        assert cancel_btn.text() == "Cancel"
        assert _combo_text_for_data(dialog, "input") == "Input"
    finally:
        reload_user_mode_config(USER_MODE_CONFIG_PATH)
