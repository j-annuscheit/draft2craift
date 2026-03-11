"""Dialog for selecting export settings."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .models import ExportOptions


class ExportOptionsDialog(QDialog):
    """Simple options menu for PDF/Word export settings."""

    def __init__(self, parent: QWidget | None = None, default_format: str = "pdf"):
        super().__init__(parent)
        self.setWindowTitle("Export Optionen")
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

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 72)
        self.font_size_spin.setValue(11)
        self.font_size_spin.setSuffix(" pt")
        form.addRow("Schriftgroesse:", self.font_size_spin)

        self.line_spacing_spin = QDoubleSpinBox()
        self.line_spacing_spin.setRange(1.0, 3.0)
        self.line_spacing_spin.setSingleStep(0.05)
        self.line_spacing_spin.setDecimals(2)
        self.line_spacing_spin.setValue(1.15)
        form.addRow("Zeilenabstand:", self.line_spacing_spin)

        root.addLayout(form)

        self.multi_column_cb = QCheckBox("Multi-Column Export (2 Spalten)")
        self.highlights_cb = QCheckBox("Markierungen uebernehmen")
        self.comments_cb = QCheckBox("Kommentare uebernehmen")

        root.addWidget(self.multi_column_cb)
        root.addWidget(self.highlights_cb)
        root.addWidget(self.comments_cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def options(self) -> ExportOptions:
        fmt = str(self.format_combo.currentData() or "pdf").strip().lower()
        return ExportOptions(
            output_format="word" if fmt == "word" else "pdf",
            multi_column=self.multi_column_cb.isChecked(),
            include_highlights=self.highlights_cb.isChecked(),
            include_comments=self.comments_cb.isChecked(),
            font_name=self.font_combo.currentText().strip() or "Calibri",
            font_size_pt=self.font_size_spin.value(),
            line_spacing=float(self.line_spacing_spin.value()),
        )
