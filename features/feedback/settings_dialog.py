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

from services.feedback import FeedbackSettings


class FeedbackSettingsDialog(QDialog):
    """GUI dialog for feedback settings."""

    def __init__(self, settings: FeedbackSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Feedback Settings")
        self.resize(620, 320)
        self._base = FeedbackSettings.from_dict(settings.to_dict())
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        intro = QLabel(
            "Konfiguriert das Feedback-System.\n"
            "Bei aktivierter Datenspeicherung werden reproduzierbare "
            "Use-Case-Daten neben den Bewertungen abgelegt."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #CDD6F4;")
        root.addWidget(intro)

        group = QGroupBox("Feedback Erfassung")
        form = QFormLayout(group)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.ui_enabled_cb = QCheckBox(
            "Feedback-Buttons anzeigen und Bewertungen erlauben"
        )
        self.ui_enabled_cb.stateChanged.connect(self._refresh_enabled_state)
        form.addRow("Feedback UI:", self.ui_enabled_cb)

        self.capture_payload_cb = QCheckBox(
            "Reproduktionsdaten bei Bewertungen speichern"
        )
        self.capture_payload_cb.stateChanged.connect(self._refresh_enabled_state)
        form.addRow("Daten speichern:", self.capture_payload_cb)

        self.storage_dir_edit = QLineEdit()
        self.storage_dir_edit.setPlaceholderText("runs/feedback")
        browse_btn = QPushButton("Ordner…")
        browse_btn.clicked.connect(self._pick_storage_dir)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(self.storage_dir_edit, 1)
        row_layout.addWidget(browse_btn)
        form.addRow("Speicherort:", row)

        hint = QLabel(
            "Hinweis: Relativer Pfad wird zum aktuellen Arbeitsverzeichnis "
            "aufgelöst."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #A6ADC8; font-size: 11px;")
        form.addRow("", hint)

        root.addWidget(group, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

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
        start = current
        if current:
            p = Path(current).expanduser()
            if not p.is_absolute():
                p = (Path.cwd() / p).resolve()
            start = str(p)
        folder = QFileDialog.getExistingDirectory(
            self,
            "Feedback-Speicherordner wählen",
            start,
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self.storage_dir_edit.setText(str(folder))

    def get_settings(self) -> FeedbackSettings:
        storage_dir = str(self.storage_dir_edit.text() or "").strip()
        if not storage_dir:
            storage_dir = FeedbackSettings().storage_dir
        return FeedbackSettings(
            ui_enabled=bool(self.ui_enabled_cb.isChecked()),
            capture_payload_enabled=bool(self.capture_payload_cb.isChecked()),
            storage_dir=storage_dir,
        )
