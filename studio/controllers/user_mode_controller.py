"""Controller for user-mode state and side-task feedback payload."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from shared.domain.user_mode import (
    is_feature_visible,
    normalize_user_mode,
    user_mode_label,
)
from studio.profile_text_overrides import apply_profile_text_overrides


class UserModeController:
    """Owns the canonical user-mode state for the running session."""

    def __init__(self, initial_mode: str) -> None:
        self._user_mode = normalize_user_mode(initial_mode)
        self._status_feedback_payload: dict[str, object] = {}

    def get_user_mode(self) -> str:
        return str(self._user_mode or "")

    def set_user_mode(self, mode: str) -> str:
        normalized = normalize_user_mode(mode)
        self._user_mode = normalized
        return normalized

    def is_prompt_editor_allowed(self, mode: str | None = None) -> bool:
        effective_mode = normalize_user_mode(
            self._user_mode if mode is None else mode
        )
        return bool(
            is_feature_visible(
                effective_mode,
                "window.prompt_editor",
                default=True,
            )
        )

    def propagate_user_mode_to_dialogs(
        self,
        *,
        mode: str,
        dialogs: tuple[object, ...],
        log_warning: Callable[[str, str], None] | None = None,
    ) -> None:
        for dialog in dialogs:
            setter = getattr(dialog, "set_user_mode", None)
            if not callable(setter):
                continue
            try:
                setter(mode)
            except Exception as exc:
                if callable(log_warning):
                    log_warning(
                        "SYS",
                        f"Failed to apply user mode '{mode}' to dialog: {exc}",
                    )
            apply_profile_text_overrides(dialog, mode)

    @staticmethod
    def _apply_mode_to_target(target: object, mode: str) -> None:
        setter = getattr(target, "set_user_mode", None)
        if callable(setter):
            setter(mode)

    def apply_mode_to_window(
        self,
        *,
        mode: str,
        root_widget: object,
        set_user_mode_state: Callable[[str], None],
        mode_targets: tuple[object, ...],
        dialogs: tuple[object, ...],
        action_edit_prompts: object | None,
        log_toggle_action: object | None,
        log_dock: object | None,
        mode_actions: Mapping[str, object],
        mode_label_widget: object | None,
        show_status_message: Callable[[str, int], None] | None,
        schedule_full_autosave: Callable[[int], None] | None,
        log_warning: Callable[[str, str], None] | None,
        notify: bool = True,
        apply_feature_visibility_bindings: Callable[[str], None] | None = None,
        apply_feature_label_bindings: Callable[[str], None] | None = None,
    ) -> str:
        normalized = self.set_user_mode(mode)
        set_user_mode_state(normalized)

        for target in mode_targets:
            self._apply_mode_to_target(target, normalized)

        if callable(apply_feature_visibility_bindings):
            apply_feature_visibility_bindings(normalized)
        if callable(apply_feature_label_bindings):
            apply_feature_label_bindings(normalized)

        self.propagate_user_mode_to_dialogs(
            mode=normalized,
            dialogs=dialogs,
            log_warning=log_warning,
        )
        apply_profile_text_overrides(root_widget, normalized)

        if action_edit_prompts is not None:
            action_edit_prompts.setVisible(
                bool(
                    self.is_prompt_editor_allowed(normalized)
                    and is_feature_visible(
                        normalized,
                        "menu.ai.edit_prompts",
                        default=True,
                    )
                )
            )

        if log_toggle_action is not None:
            show_log = bool(
                is_feature_visible(
                    normalized,
                    "window.log_dock_visible",
                    default=True,
                )
                and is_feature_visible(
                    normalized,
                    "menu.view.debug_log",
                    default=True,
                )
            )
            log_toggle_action.setVisible(show_log)
            if not show_log:
                if log_dock is not None:
                    log_dock.hide()

        for mode_key, action in dict(mode_actions or {}).items():
            blocked = action.blockSignals(True)
            action.setChecked(mode_key == normalized)
            action.blockSignals(blocked)

        if mode_label_widget is not None:
            mode_label_widget.setText(f"mode: {user_mode_label(normalized)}")

        if notify and callable(show_status_message):
            show_status_message(f"Nutzermodus: {user_mode_label(normalized)}", 2500)
            if callable(schedule_full_autosave):
                schedule_full_autosave(500)
        return normalized

    @property
    def status_feedback_payload(self) -> dict[str, object]:
        return dict(self._status_feedback_payload)

    def set_status_feedback_payload(self, payload: Mapping[str, object] | None) -> None:
        self._status_feedback_payload = dict(payload or {})
