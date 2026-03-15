"""Dialog to configure feedback collection and storage."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import (
    is_feature_visible,
    normalize_user_mode,
    resolve_feature_label,
)
from shared.config.paths import app_data_dir
from shared.services.feedback.settings import FeedbackSettings


class FeedbackSettingsDialog(QDialog):
    """GUI dialog for feedback settings."""

    def __init__(self, settings: FeedbackSettings, user_mode: str | None = None, parent=None):
        super().__init__(parent)
        self._user_mode = normalize_user_mode("" if user_mode is None else user_mode)
        self._intro_lbl: QLabel | None = None
        self._capture_group: QGroupBox | None = None
        self._storage_row: QWidget | None = None
        self._hint_lbl: QLabel | None = None
        self._browse_btn: QPushButton | None = None
        self._buttons_box: QDialogButtonBox | None = None
        self._row_lbl_ui_enabled: QLabel | None = None
        self._row_lbl_capture_payload: QLabel | None = None
        self._row_lbl_storage: QLabel | None = None
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.window_title",
                "Feedback Settings",
            )
        )
        self.resize(620, 320)
        self._base = FeedbackSettings.from_dict(settings.to_dict())
        self._build_ui()
        self._load_values()

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self._apply_user_mode_labels()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        intro = QLabel(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.intro",
                "Konfiguriert das Feedback-System.\n"
                "Bei aktivierter Datenspeicherung werden reproduzierbare "
                "Use-Case-Daten neben den Bewertungen abgelegt.",
            )
        )
        self._intro_lbl = intro
        intro.setWordWrap(True)
        intro.setStyleSheet("color: palette(text);")
        root.addWidget(intro)

        group = QGroupBox(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.group.capture",
                "Feedback Erfassung",
            )
        )
        self._capture_group = group
        form = QFormLayout(group)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.ui_enabled_cb = QCheckBox(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.ui_enabled.label",
                "Feedback-Buttons anzeigen und Bewertungen erlauben",
            )
        )
        self.ui_enabled_cb.stateChanged.connect(self._refresh_enabled_state)
        self._row_lbl_ui_enabled = QLabel(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.ui_enabled.row_label",
                "Feedback UI:",
            )
        )
        form.addRow(self._row_lbl_ui_enabled, self.ui_enabled_cb)

        self.capture_payload_cb = QCheckBox(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.capture_payload.label",
                "Reproduktionsdaten bei Bewertungen speichern",
            )
        )
        self.capture_payload_cb.stateChanged.connect(self._refresh_enabled_state)
        self._row_lbl_capture_payload = QLabel(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.capture_payload.row_label",
                "Daten speichern:",
            )
        )
        form.addRow(self._row_lbl_capture_payload, self.capture_payload_cb)

        self.storage_dir_edit = QLineEdit()
        self.storage_dir_edit.setPlaceholderText(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.storage.placeholder",
                "runs/feedback",
            )
        )
        browse_btn = QPushButton(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.storage.button.browse",
                "Ordner…",
            )
        )
        self._browse_btn = browse_btn
        browse_btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.storage.button.browse.tooltip",
                "Speicherordner auswählen",
            )
        )
        browse_btn.clicked.connect(self._pick_storage_dir)
        row = QWidget()
        self._storage_row = row
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(self.storage_dir_edit, 1)
        row_layout.addWidget(browse_btn)
        self._row_lbl_storage = QLabel(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.storage.row_label",
                "Speicherort:",
            )
        )
        form.addRow(self._row_lbl_storage, row)

        hint = QLabel(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.hint",
                "Hinweis: Relativer Pfad wird unterhalb des "
                "App-Datenordners aufgelöst.",
            )
        )
        self._hint_lbl = hint
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        form.addRow("", hint)

        root.addWidget(group, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons_box = buttons
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.settings.button.ok",
                    "OK",
                )
            )
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.settings.button.cancel",
                    "Abbrechen",
                )
            )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._apply_user_mode_labels()

    def _load_values(self):
        self.ui_enabled_cb.setChecked(bool(self._base.ui_enabled))
        self.capture_payload_cb.setChecked(bool(self._base.capture_payload_enabled))
        self.storage_dir_edit.setText(str(self._base.storage_dir or "").strip())
        self._refresh_enabled_state()

    def _refresh_enabled_state(self):
        enabled = self.ui_enabled_cb.isChecked()
        self.capture_payload_cb.setEnabled(enabled)
        self.storage_dir_edit.setEnabled(enabled)

    def _pick_storage_dir(self):
        current = str(self.storage_dir_edit.text() or "").strip()
        start = str(app_data_dir())
        if current:
            p = Path(current).expanduser()
            if not p.is_absolute():
                p = (app_data_dir() / p).resolve(strict=False)
            start = str(p)
        folder = QFileDialog.getExistingDirectory(
            self,
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.storage.dialog_title",
                "Feedback-Speicherordner wählen",
            ),
            start,
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self.storage_dir_edit.setText(str(folder))

    def _apply_user_mode_labels(self) -> None:
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.window_title",
                "Feedback Settings",
            )
        )
        if self._intro_lbl is not None:
            self._intro_lbl.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.settings.intro",
                    "Konfiguriert das Feedback-System.\n"
                    "Bei aktivierter Datenspeicherung werden reproduzierbare "
                    "Use-Case-Daten neben den Bewertungen abgelegt.",
                )
            )
        if self._capture_group is not None:
            self._capture_group.setTitle(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.settings.group.capture",
                    "Feedback Erfassung",
                )
            )
        self.ui_enabled_cb.setText(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.ui_enabled.label",
                "Feedback-Buttons anzeigen und Bewertungen erlauben",
            )
        )
        self.capture_payload_cb.setText(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.capture_payload.label",
                "Reproduktionsdaten bei Bewertungen speichern",
            )
        )
        self.storage_dir_edit.setPlaceholderText(
            resolve_feature_label(
                self._user_mode,
                "feedback.settings.storage.placeholder",
                "runs/feedback",
            )
        )
        if self._browse_btn is not None:
            self._browse_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.settings.storage.button.browse",
                    "Ordner…",
                )
            )
            self._browse_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.settings.storage.button.browse.tooltip",
                    "Speicherordner auswählen",
                )
            )
        if self._hint_lbl is not None:
            self._hint_lbl.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.settings.hint",
                    "Hinweis: Relativer Pfad wird unterhalb des "
                    "App-Datenordners aufgelöst.",
                )
            )
        if self._row_lbl_ui_enabled is not None:
            self._row_lbl_ui_enabled.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.settings.ui_enabled.row_label",
                    "Feedback UI:",
                )
            )
        if self._row_lbl_capture_payload is not None:
            self._row_lbl_capture_payload.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.settings.capture_payload.row_label",
                    "Daten speichern:",
                )
            )
        if self._row_lbl_storage is not None:
            self._row_lbl_storage.setText(
                resolve_feature_label(
                    self._user_mode,
                    "feedback.settings.storage.row_label",
                    "Speicherort:",
                )
            )
        if self._buttons_box is not None:
            ok_btn = self._buttons_box.button(QDialogButtonBox.StandardButton.Ok)
            if ok_btn is not None:
                ok_btn.setText(
                    resolve_feature_label(
                        self._user_mode,
                        "feedback.settings.button.ok",
                        "OK",
                    )
                )
            cancel_btn = self._buttons_box.button(QDialogButtonBox.StandardButton.Cancel)
            if cancel_btn is not None:
                cancel_btn.setText(
                    resolve_feature_label(
                        self._user_mode,
                        "feedback.settings.button.cancel",
                        "Abbrechen",
                    )
                )

        self.ui_enabled_cb.setVisible(
            bool(
                is_feature_visible(
                    self._user_mode,
                    "feedback.settings.ui_enabled",
                    default=True,
                )
            )
        )
        self.capture_payload_cb.setVisible(
            bool(
                is_feature_visible(
                    self._user_mode,
                    "feedback.settings.capture_payload",
                    default=True,
                )
            )
        )
        if self._storage_row is not None:
            self._storage_row.setVisible(
                bool(
                    is_feature_visible(
                        self._user_mode,
                        "feedback.settings.storage_dir",
                        default=True,
                    )
                )
            )

    def get_settings(self) -> FeedbackSettings:
        storage_dir = str(self.storage_dir_edit.text() or "").strip()
        if not storage_dir:
            storage_dir = FeedbackSettings().storage_dir
        return FeedbackSettings(
            ui_enabled=bool(self.ui_enabled_cb.isChecked()),
            capture_payload_enabled=bool(self.capture_payload_cb.isChecked()),
            storage_dir=storage_dir,
        )
