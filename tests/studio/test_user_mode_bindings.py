from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from studio.user_mode_bindings import (
    apply_combo_item_labels,
    apply_form_row_labels,
    apply_form_row_visibility,
    apply_widget_placeholders,
    apply_widget_texts,
    apply_widget_tooltips,
    apply_widget_visibility,
    feature_visible,
)


def test_widget_text_tooltip_placeholder_bindings_use_defaults_for_unknown_keys(qt_app):
    _ = qt_app
    button = QPushButton()
    edit = QLineEdit()

    apply_widget_texts("unknown-mode", ((button, "missing.key.text", "Run"),))
    apply_widget_tooltips("unknown-mode", ((button, "missing.key.tip", "Run tip"),))
    apply_widget_placeholders(
        "unknown-mode",
        ((edit, "missing.key.placeholder", "Type here"),),
    )

    assert button.text() == "Run"
    assert button.toolTip() == "Run tip"
    assert edit.placeholderText() == "Type here"


def test_widget_visibility_and_feature_visible_default_behavior(qt_app):
    _ = qt_app
    widget = QWidget()
    widget.show()

    states = apply_widget_visibility(
        "unknown-mode",
        (
            (widget, "missing.key.visible", False),
            (widget, "missing.key.visible.default_true", True),
        ),
    )

    assert feature_visible("unknown-mode", "missing.key.visible", default=False) is False
    assert feature_visible("unknown-mode", "missing.key.visible.default_true", default=True) is True
    assert states["missing.key.visible"] is False
    assert states["missing.key.visible.default_true"] is True
    assert widget.isVisible() is True


def test_form_row_and_combo_bindings_apply_defaults_for_unknown_keys(qt_app):
    _ = qt_app
    host = QWidget()
    form = QFormLayout(host)
    spin = QSpinBox()
    form.addRow("Old:", spin)

    apply_form_row_labels("unknown-mode", form, ((spin, "missing.key.row", "New:"),))
    states = apply_form_row_visibility(
        "unknown-mode",
        form,
        ((spin, "missing.key.row.visible", False),),
    )
    label = form.labelForField(spin)

    combo = QComboBox()
    combo.addItem("Old 1")
    combo.addItem("Old 2")
    apply_combo_item_labels(
        "unknown-mode",
        combo,
        (
            (0, "missing.key.combo0", "New 1"),
            (1, "missing.key.combo1", "New 2"),
            (3, "missing.key.combo_out_of_range", "Ignored"),
        ),
    )

    assert label is not None and label.text() == "New:"
    assert states["missing.key.row.visible"] is False
    assert spin.isVisible() is False
    assert label.isVisible() is False
    assert combo.itemText(0) == "New 1"
    assert combo.itemText(1) == "New 2"
