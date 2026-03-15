"""Dialog for selecting export settings."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import (
    default_user_mode,
    is_feature_visible,
    normalize_user_mode,
    resolve_feature_label,
)

from .models import ExportOptions


class ExportOptionsDialog(QDialog):
    """Simple options menu for PDF/Word export settings."""

    def __init__(
        self,
        parent: QWidget | None = None,
        default_format: str = "pdf",
        user_mode: str | None = None,
    ):
        super().__init__(parent)
        self._user_mode = normalize_user_mode(
            default_user_mode() if user_mode is None else user_mode
        )
        self._format_label = None
        self._font_label = None
        self._font_size_label = None
        self._line_spacing_label = None
        self._multi_column_base_text = ""
        self.setModal(True)
        self.resize(460, 260)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.format_combo = QComboBox()
        self.format_combo.addItem("PDF", "pdf")
        self.format_combo.addItem("Word (DOCX)", "word")
        fmt = str(default_format or "pdf").strip().lower()
        self.format_combo.setCurrentIndex(1 if fmt == "word" else 0)
        form.addRow("Format:", self.format_combo)
        self._format_label = form.labelForField(self.format_combo)

        self.font_combo = QComboBox()
        self.font_combo.setEditable(True)
        for name in (
            "Calibri",
            "Arial",
            "Times New Roman",
            "Cambria",
            "Verdana",
            "Tahoma",
            "Georgia",
            "Liberation Sans",
            "Liberation Serif",
            "DejaVu Sans",
            "DejaVu Serif",
        ):
            self.font_combo.addItem(name)
        self.font_combo.setCurrentText("Calibri")
        form.addRow("Schriftart:", self.font_combo)
        self._font_label = form.labelForField(self.font_combo)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 72)
        self.font_size_spin.setValue(11)
        self.font_size_spin.setSuffix(" pt")
        form.addRow("Schriftgroesse:", self.font_size_spin)
        self._font_size_label = form.labelForField(self.font_size_spin)

        self.line_spacing_spin = QDoubleSpinBox()
        self.line_spacing_spin.setRange(1.0, 3.0)
        self.line_spacing_spin.setSingleStep(0.05)
        self.line_spacing_spin.setDecimals(2)
        self.line_spacing_spin.setValue(1.15)
        form.addRow("Zeilenabstand:", self.line_spacing_spin)
        self._line_spacing_label = form.labelForField(self.line_spacing_spin)

        root.addLayout(form)

        self.multi_column_cb = QCheckBox("Multi-Column Export (2 Spalten)")
        self._multi_column_hint = QLabel("")
        self._multi_column_hint.setWordWrap(True)
        self._multi_column_hint.setVisible(False)
        self.highlights_cb = QCheckBox("Markierungen uebernehmen")
        self.comments_cb = QCheckBox("Kommentare uebernehmen")

        root.addWidget(self.multi_column_cb)
        root.addWidget(self._multi_column_hint)
        root.addWidget(self.highlights_cb)
        root.addWidget(self.comments_cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._buttons = buttons
        root.addWidget(buttons)
        self.format_combo.currentIndexChanged.connect(
            self._sync_multi_column_availability
        )
        self.set_user_mode(self._user_mode)

    def _label(self, key: str, default: str) -> str:
        return resolve_feature_label(self._user_mode, key, default)

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self.setWindowTitle(self._label("export.options.window_title", "Export Optionen"))
        if self._format_label is not None:
            self._format_label.setText(self._label("export.options.field.format", "Format:"))
        if self._font_label is not None:
            self._font_label.setText(self._label("export.options.field.font", "Schriftart:"))
        if self._font_size_label is not None:
            self._font_size_label.setText(
                self._label("export.options.field.font_size", "Schriftgroesse:")
            )
        if self._line_spacing_label is not None:
            self._line_spacing_label.setText(
                self._label("export.options.field.line_spacing", "Zeilenabstand:")
            )
        idx_pdf = self.format_combo.findData("pdf")
        if idx_pdf >= 0:
            self.format_combo.setItemText(
                idx_pdf,
                self._label("export.options.option.format.pdf", "PDF"),
            )
        idx_word = self.format_combo.findData("word")
        if idx_word >= 0:
            self.format_combo.setItemText(
                idx_word,
                self._label("export.options.option.format.word", "Word (DOCX)"),
            )
        self._multi_column_base_text = self._label(
            "export.options.checkbox.multi_column",
            "Multi-Column Export (2 Spalten)",
        )
        self.multi_column_cb.setText(self._multi_column_base_text)
        self.multi_column_cb.setVisible(
            bool(
                is_feature_visible(
                    self._user_mode,
                    "export.options.checkbox.multi_column",
                    default=True,
                )
            )
        )
        self._multi_column_hint.setText(
            self._label(
                "export.options.checkbox.multi_column.disabled_note",
                "Hinweis: 2-spaltig ist für PDF derzeit nicht verfügbar.",
            )
        )
        self._multi_column_hint.setStyleSheet(
            "color: #B35A5A; font-size: 11px; font-style: italic;"
        )
        self.highlights_cb.setText(
            self._label(
                "export.options.checkbox.highlights",
                "Markierungen uebernehmen",
            )
        )
        self.comments_cb.setText(
            self._label(
                "export.options.checkbox.comments",
                "Kommentare uebernehmen",
            )
        )
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText(self._label("export.options.button.ok", "OK"))
        cancel_btn = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText(self._label("export.options.button.cancel", "Cancel"))
        self._sync_multi_column_availability()

    def _sync_multi_column_availability(self) -> None:
        fmt = str(self.format_combo.currentData() or "pdf").strip().lower()
        if fmt == "word":
            self.multi_column_cb.setText(self._multi_column_base_text)
            self.multi_column_cb.setEnabled(True)
            self.multi_column_cb.setStyleSheet("")
            self.multi_column_cb.setToolTip(
                self._label(
                    "export.options.checkbox.multi_column.tooltip.word",
                    "Enable 2-column layout for DOCX export.",
                )
            )
            self._multi_column_hint.setVisible(False)
            return
        self.multi_column_cb.setChecked(False)
        self.multi_column_cb.setText(
            self._label(
                "export.options.checkbox.multi_column.disabled_label",
                f"{self._multi_column_base_text} - nur DOCX",
            )
        )
        self.multi_column_cb.setEnabled(False)
        self.multi_column_cb.setStyleSheet(
            "QCheckBox { color: #7F7F7F; font-style: italic; text-decoration: line-through; }"
            "QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #666; "
            "background-color: #2C2C2C; }"
        )
        self.multi_column_cb.setToolTip(
            self._label(
                "export.options.checkbox.multi_column.tooltip.pdf_disabled",
                "2-column layout is only available for Word (DOCX) export.",
            )
        )
        self._multi_column_hint.setHidden(self.multi_column_cb.isHidden())

    def options(self) -> ExportOptions:
        fmt = str(self.format_combo.currentData() or "pdf").strip().lower()
        return ExportOptions(
            output_format="word" if fmt == "word" else "pdf",
            multi_column=bool(fmt == "word" and self.multi_column_cb.isChecked()),
            include_highlights=self.highlights_cb.isChecked(),
            include_comments=self.comments_cb.isChecked(),
            font_name=self.font_combo.currentText().strip() or "Calibri",
            font_size_pt=self.font_size_spin.value(),
            line_spacing=float(self.line_spacing_spin.value()),
        )
