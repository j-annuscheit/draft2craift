"""Reusable helpers for profile-driven UI bindings."""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import QComboBox, QFormLayout, QWidget

from shared.domain.user_mode import is_feature_visible, resolve_feature_label


def feature_visible(mode: str, feature_key: str, *, default: bool = True) -> bool:
    return bool(is_feature_visible(mode, feature_key, default=bool(default)))


def set_form_row_visible(form: QFormLayout, field: QWidget, visible: bool) -> None:
    label = form.labelForField(field)
    if label is not None:
        label.setVisible(bool(visible))
    field.setVisible(bool(visible))


def set_form_row_label(form: QFormLayout, field: QWidget, label_text: str) -> None:
    label = form.labelForField(field)
    if label is not None:
        label.setText(str(label_text or ""))


def apply_widget_visibility(
    mode: str,
    bindings: Iterable[tuple[object, str, bool]],
) -> dict[str, bool]:
    states: dict[str, bool] = {}
    for target, feature_key, default in bindings:
        visible = feature_visible(mode, feature_key, default=default)
        setter = getattr(target, "setVisible", None)
        if callable(setter):
            setter(visible)
        states[feature_key] = visible
    return states


def _apply_text_to_setter(
    mode: str,
    bindings: Iterable[tuple[object, str, str]],
    setter_name: str,
) -> None:
    for target, feature_key, default_text in bindings:
        setter = getattr(target, setter_name, None)
        if not callable(setter):
            continue
        setter(resolve_feature_label(mode, feature_key, str(default_text or "")))


def apply_widget_texts(mode: str, bindings: Iterable[tuple[object, str, str]]) -> None:
    _apply_text_to_setter(mode, bindings, "setText")


def apply_widget_tooltips(mode: str, bindings: Iterable[tuple[object, str, str]]) -> None:
    _apply_text_to_setter(mode, bindings, "setToolTip")


def apply_widget_placeholders(
    mode: str,
    bindings: Iterable[tuple[object, str, str]],
) -> None:
    _apply_text_to_setter(mode, bindings, "setPlaceholderText")


def apply_form_row_labels(
    mode: str,
    form: QFormLayout,
    bindings: Iterable[tuple[QWidget, str, str]],
) -> None:
    for field, feature_key, default_text in bindings:
        set_form_row_label(
            form,
            field,
            resolve_feature_label(mode, feature_key, str(default_text or "")),
        )


def apply_form_row_visibility(
    mode: str,
    form: QFormLayout,
    bindings: Iterable[tuple[QWidget, str, bool]],
) -> dict[str, bool]:
    states: dict[str, bool] = {}
    for field, feature_key, default in bindings:
        visible = feature_visible(mode, feature_key, default=default)
        set_form_row_visible(form, field, visible)
        states[feature_key] = visible
    return states


def apply_combo_item_labels(
    mode: str,
    combo: QComboBox,
    bindings: Iterable[tuple[int, str, str]],
) -> None:
    for index, feature_key, default_text in bindings:
        if int(index) < 0 or int(index) >= combo.count():
            continue
        combo.setItemText(
            int(index),
            resolve_feature_label(mode, feature_key, str(default_text or "")),
        )
