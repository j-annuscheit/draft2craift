"""Profile-driven literal text/tooltip overrides for UI widgets."""
from __future__ import annotations

from typing import Iterable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QMessageBox,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QWidget,
)

from shared.domain.user_mode import (
    default_user_mode,
    literal_text_override,
    literal_tooltip_override,
    normalize_user_mode,
    resolve_literal_text,
)

_PROP_BASE_TEXT = "_d2c_base_text"
_PROP_BASE_TOOLTIP = "_d2c_base_tooltip"
_PROP_BASE_WINDOW_TITLE = "_d2c_base_window_title"
_PROP_BASE_PLACEHOLDER = "_d2c_base_placeholder"
_PROP_BASE_TAB_TITLES = "_d2c_base_tab_titles"
_PROP_BASE_COMBO_ITEMS = "_d2c_base_combo_items"
_QMESSAGEBOX_PATCHED = False


def _as_text(value: object) -> str:
    return str(value or "")


def _mode_from_parent(parent: object) -> str:
    current = parent
    while current is not None:
        mode = str(getattr(current, "user_mode", "") or "").strip()
        if mode:
            return mode
        parent_fn = getattr(current, "parent", None)
        current = parent_fn() if callable(parent_fn) else None
    return default_user_mode()


def _base_prop(obj: object, prop: str, current: str) -> str:
    getter = getattr(obj, "property", None)
    setter = getattr(obj, "setProperty", None)
    if not callable(getter) or not callable(setter):
        return _as_text(current)
    stored = getter(prop)
    if stored is None:
        text = _as_text(current)
        setter(prop, text)
        return text
    return _as_text(stored)


def _widget_base_text(widget: QWidget) -> str:
    if isinstance(widget, (QPushButton, QToolButton, QCheckBox, QRadioButton)):
        return _base_prop(widget, _PROP_BASE_TEXT, widget.text())
    if isinstance(widget, QGroupBox):
        return _base_prop(widget, _PROP_BASE_TEXT, widget.title())
    if isinstance(widget, QLabel):
        return _base_prop(widget, _PROP_BASE_TEXT, widget.text())
    return ""


def _apply_widget_text(widget: QWidget, mode: str) -> None:
    if isinstance(widget, (QPushButton, QToolButton, QCheckBox, QRadioButton)):
        base = _base_prop(widget, _PROP_BASE_TEXT, widget.text())
        override = literal_text_override(mode, base)
        if override is not None:
            widget.setText(override)
        return
    if isinstance(widget, QGroupBox):
        base = _base_prop(widget, _PROP_BASE_TEXT, widget.title())
        override = literal_text_override(mode, base)
        if override is not None:
            widget.setTitle(override)
        return
    if isinstance(widget, QLabel):
        base = _base_prop(widget, _PROP_BASE_TEXT, widget.text())
        override = literal_text_override(mode, base)
        if override is not None:
            widget.setText(override)


def _apply_widget_tooltip(widget: QWidget, mode: str) -> None:
    base_tip = _base_prop(widget, _PROP_BASE_TOOLTIP, widget.toolTip())
    if base_tip:
        override = literal_tooltip_override(mode, base_tip)
        if override is not None:
            widget.setToolTip(override)
            return
    seed = _widget_base_text(widget)
    if not seed:
        return
    by_text = literal_tooltip_override(mode, seed)
    if by_text is not None:
        widget.setToolTip(by_text)


def _apply_window_title(widget: QWidget, mode: str) -> None:
    if not widget.isWindow():
        return
    base = _base_prop(widget, _PROP_BASE_WINDOW_TITLE, widget.windowTitle())
    if not base:
        return
    override = literal_text_override(mode, base)
    if override is not None:
        widget.setWindowTitle(override)


def _apply_placeholder(widget: QWidget, mode: str) -> None:
    if isinstance(widget, QLineEdit):
        base = _base_prop(widget, _PROP_BASE_PLACEHOLDER, widget.placeholderText())
        if base:
            override = literal_text_override(mode, base)
            if override is not None:
                widget.setPlaceholderText(override)
        return
    if isinstance(widget, (QPlainTextEdit, QTextEdit)):
        base = _base_prop(widget, _PROP_BASE_PLACEHOLDER, widget.placeholderText())
        if base:
            override = literal_text_override(mode, base)
            if override is not None:
                widget.setPlaceholderText(override)
        return
    if isinstance(widget, QComboBox):
        line = widget.lineEdit()
        if line is None:
            return
        base = _base_prop(line, _PROP_BASE_PLACEHOLDER, line.placeholderText())
        if base:
            override = literal_text_override(mode, base)
            if override is not None:
                line.setPlaceholderText(override)


def _apply_tabs(widget: QWidget, mode: str) -> None:
    if not isinstance(widget, QTabWidget):
        return
    raw = widget.property(_PROP_BASE_TAB_TITLES)
    if not isinstance(raw, list):
        raw = [widget.tabText(i) for i in range(widget.count())]
    else:
        raw = [str(item or "") for item in raw]
    while len(raw) < widget.count():
        raw.append(widget.tabText(len(raw)))
    widget.setProperty(_PROP_BASE_TAB_TITLES, list(raw))
    for idx in range(widget.count()):
        override = literal_text_override(mode, raw[idx])
        if override is not None:
            widget.setTabText(idx, override)


def _apply_combo_items(widget: QWidget, mode: str) -> None:
    if not isinstance(widget, QComboBox):
        return
    raw = widget.property(_PROP_BASE_COMBO_ITEMS)
    if not isinstance(raw, list):
        raw = [widget.itemText(i) for i in range(widget.count())]
    else:
        raw = [str(item or "") for item in raw]
    while len(raw) < widget.count():
        raw.append(widget.itemText(len(raw)))
    widget.setProperty(_PROP_BASE_COMBO_ITEMS, list(raw))
    for idx in range(widget.count()):
        override = literal_text_override(mode, raw[idx])
        if override is not None:
            widget.setItemText(idx, override)


def _apply_action(action: QAction, mode: str) -> None:
    base = _base_prop(action, _PROP_BASE_TEXT, action.text())
    if base:
        override = literal_text_override(mode, base)
        if override is not None:
            action.setText(override)

    base_tip = _base_prop(action, _PROP_BASE_TOOLTIP, action.toolTip())
    if base_tip:
        override = literal_tooltip_override(mode, base_tip)
        if override is not None:
            action.setToolTip(override)
            return

    by_text = literal_tooltip_override(mode, base)
    if by_text is not None:
        action.setToolTip(by_text)


def _iter_widgets(root: QWidget) -> Iterable[QWidget]:
    yield root
    for widget in root.findChildren(QWidget):
        yield widget


def apply_profile_text_overrides(root: QWidget | None, mode: str) -> None:
    """Apply literal text and tooltip overrides to a widget tree."""
    if root is None:
        return
    normalized = normalize_user_mode(mode)
    for widget in _iter_widgets(root):
        _apply_window_title(widget, normalized)
        _apply_widget_text(widget, normalized)
        _apply_widget_tooltip(widget, normalized)
        _apply_placeholder(widget, normalized)
        _apply_tabs(widget, normalized)
        _apply_combo_items(widget, normalized)
    for action in root.findChildren(QAction):
        _apply_action(action, normalized)


def install_qmessagebox_literal_overrides() -> None:
    """Patch QMessageBox static APIs so literals become profile-overridable."""
    global _QMESSAGEBOX_PATCHED
    if _QMESSAGEBOX_PATCHED:
        return
    _QMESSAGEBOX_PATCHED = True

    original_information = QMessageBox.information
    original_warning = QMessageBox.warning
    original_critical = QMessageBox.critical
    original_question = QMessageBox.question
    original_about = QMessageBox.about

    def _wrap(fn):
        def _inner(parent, title, text, *args, **kwargs):
            mode = _mode_from_parent(parent)
            return fn(
                parent,
                resolve_literal_text(mode, _as_text(title)),
                resolve_literal_text(mode, _as_text(text)),
                *args,
                **kwargs,
            )
        return _inner

    QMessageBox.information = staticmethod(_wrap(original_information))
    QMessageBox.warning = staticmethod(_wrap(original_warning))
    QMessageBox.critical = staticmethod(_wrap(original_critical))
    QMessageBox.question = staticmethod(_wrap(original_question))
    QMessageBox.about = staticmethod(_wrap(original_about))
