from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialogButtonBox

from shared.domain.user_mode import USER_MODE_CONFIG_PATH, reload_user_mode_config
from shared.services.feedback.settings import FeedbackSettings
from studio.feedback.settings_dialog import FeedbackSettingsDialog


def _write_settings_mode_config(path: Path) -> None:
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
"feedback.settings.window_title" = "Feedback Settings"
"feedback.settings.intro" = "Configure the feedback system."
"feedback.settings.group.capture" = "Feedback Capture"
"feedback.settings.ui_enabled.row_label" = "Feedback UI"
"feedback.settings.ui_enabled.label" = "Show feedback buttons and allow ratings"
"feedback.settings.capture_payload.row_label" = "Store data"
"feedback.settings.capture_payload.label" = "Store reproduction data with ratings"
"feedback.settings.storage.row_label" = "Storage location"
"feedback.settings.storage.button.browse" = "Folder"
"feedback.settings.hint" = "Note: Relative paths are resolved below the app data directory."
"feedback.settings.button.ok" = "OK"
"feedback.settings.button.cancel" = "Cancel"
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
"feedback.settings.window_title" = "Feedback Einstellungen"
"feedback.settings.intro" = "Konfiguration des Feedback-Systems."
"feedback.settings.group.capture" = "Feedback Erfassung"
"feedback.settings.ui_enabled.row_label" = "Feedback UI"
"feedback.settings.ui_enabled.label" = "Feedback-Buttons anzeigen und Bewertungen erlauben"
"feedback.settings.capture_payload.row_label" = "Daten speichern"
"feedback.settings.capture_payload.label" = "Reproduktionsdaten bei Bewertungen speichern"
"feedback.settings.storage.row_label" = "Speicherort"
"feedback.settings.storage.button.browse" = "Ordner"
"feedback.settings.hint" = "Hinweis: Relativer Pfad wird unterhalb des App-Datenordners aufgelöst."
"feedback.settings.button.ok" = "OK"
"feedback.settings.button.cancel" = "Abbrechen"
""".strip(),
        encoding="utf-8",
    )


def test_feedback_settings_dialog_labels_are_profile_driven(tmp_path: Path, qt_app):
    _ = qt_app
    cfg = tmp_path / "user_modes"
    _write_settings_mode_config(cfg)

    try:
        reload_user_mode_config(cfg)
        dialog = FeedbackSettingsDialog(FeedbackSettings(), user_mode="beta")
        ok_btn = dialog._buttons_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = dialog._buttons_box.button(QDialogButtonBox.StandardButton.Cancel)

        assert dialog.windowTitle() == "Feedback Einstellungen"
        assert dialog._intro_lbl.text() == "Konfiguration des Feedback-Systems."
        assert dialog._capture_group.title() == "Feedback Erfassung"
        assert dialog._row_lbl_ui_enabled.text() == "Feedback UI"
        assert dialog.ui_enabled_cb.text() == "Feedback-Buttons anzeigen und Bewertungen erlauben"
        assert dialog._row_lbl_capture_payload.text() == "Daten speichern"
        assert dialog.capture_payload_cb.text() == "Reproduktionsdaten bei Bewertungen speichern"
        assert dialog._row_lbl_storage.text() == "Speicherort"
        assert dialog._browse_btn.text() == "Ordner"
        assert dialog._hint_lbl.text() == "Hinweis: Relativer Pfad wird unterhalb des App-Datenordners aufgelöst."
        assert ok_btn is not None and ok_btn.text() == "OK"
        assert cancel_btn is not None and cancel_btn.text() == "Abbrechen"

        dialog.set_user_mode("alpha")
        assert dialog.windowTitle() == "Feedback Settings"
        assert dialog._intro_lbl.text() == "Configure the feedback system."
        assert dialog._capture_group.title() == "Feedback Capture"
        assert dialog._row_lbl_ui_enabled.text() == "Feedback UI"
        assert dialog.ui_enabled_cb.text() == "Show feedback buttons and allow ratings"
        assert dialog._row_lbl_capture_payload.text() == "Store data"
        assert dialog.capture_payload_cb.text() == "Store reproduction data with ratings"
        assert dialog._row_lbl_storage.text() == "Storage location"
        assert dialog._browse_btn.text() == "Folder"
        assert dialog._hint_lbl.text() == "Note: Relative paths are resolved below the app data directory."
        assert ok_btn.text() == "OK"
        assert cancel_btn.text() == "Cancel"
    finally:
        reload_user_mode_config(USER_MODE_CONFIG_PATH)
