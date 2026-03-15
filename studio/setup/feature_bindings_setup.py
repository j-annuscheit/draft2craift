"""Feature-visibility and label binding helpers for MainWindow menus/actions."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtGui import QAction, QKeySequence

from shared.domain.user_mode import is_feature_visible, resolve_feature_label


class FeatureBindingRegistry:
    """Stores profile-driven visibility/label bindings for UI targets."""

    def __init__(self) -> None:
        self._feature_visibility_bindings: list[tuple[object, str, bool]] = []
        self._feature_label_bindings: list[tuple[object, str, str]] = []

    def bind_feature_visibility(
        self,
        target: object,
        feature_key: str,
        default: bool = True,
        *,
        mode: str,
    ) -> None:
        key = str(feature_key or "").strip()
        if not key:
            return
        self._feature_visibility_bindings.append((target, key, bool(default)))
        self.apply_feature_visibility_for_target(target, key, bool(default), mode)

    @staticmethod
    def apply_feature_visibility_for_target(
        target: object,
        feature_key: str,
        default: bool,
        mode: str,
    ) -> None:
        setter = getattr(target, "setVisible", None)
        if not callable(setter):
            return
        setter(bool(is_feature_visible(mode, feature_key, default=default)))

    def apply_feature_visibility_bindings(self, mode: str) -> None:
        for target, feature_key, default in list(self._feature_visibility_bindings):
            self.apply_feature_visibility_for_target(
                target,
                feature_key,
                bool(default),
                mode,
            )

    def bind_feature_label(
        self,
        target: object,
        feature_key: str,
        default_text: str,
        *,
        mode: str,
    ) -> None:
        key = str(feature_key or "").strip()
        if not key:
            return
        fallback = str(default_text or "")
        self._feature_label_bindings.append((target, key, fallback))
        self.apply_feature_label_for_target(target, key, fallback, mode)

    @staticmethod
    def apply_feature_label_for_target(
        target: object,
        feature_key: str,
        default_text: str,
        mode: str,
    ) -> None:
        setter = getattr(target, "setText", None)
        if not callable(setter):
            return
        setter(resolve_feature_label(mode, feature_key, default_text))

    def apply_feature_label_bindings(self, mode: str) -> None:
        for target, feature_key, default_text in list(self._feature_label_bindings):
            self.apply_feature_label_for_target(
                target,
                feature_key,
                default_text,
                mode,
            )

    def add_action(
        self,
        menu: Any,
        parent: object,
        label: str,
        shortcut: str,
        slot: Callable[..., Any],
        *,
        mode: str,
        visibility_key: str | None = None,
        visible_default: bool = True,
        label_key: str | None = None,
        label_default: str | None = None,
    ) -> QAction:
        action = QAction(label, parent)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        if visibility_key:
            self.bind_feature_visibility(
                action,
                visibility_key,
                default=bool(visible_default),
                mode=mode,
            )
        key_for_label = str(label_key or visibility_key or "").strip()
        if key_for_label:
            self.bind_feature_label(
                action,
                key_for_label,
                str(label if label_default is None else label_default),
                mode=mode,
            )
        return action
