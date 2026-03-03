"""Small reusable helpers for importer settings panel widgets."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QWidget


def set_form_row_visible(form: QFormLayout, field: QWidget, visible: bool):
    """Show/hide a form row by field widget."""
    label = form.labelForField(field)
    if label is not None:
        label.setVisible(visible)
    field.setVisible(visible)


def set_combo_value(combo: QComboBox, text: str):
    """Set combo box selection by exact text when available."""
    idx = combo.findText(text)
    if idx >= 0:
        combo.setCurrentIndex(idx)

