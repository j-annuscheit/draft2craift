"""Feedback orchestration extracted from MainWindow."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog, QWidget

from shared.config.setting_keys import FeedbackSettingsKeys
from shared.services.feedback.service import FeedbackService
from shared.services.feedback.settings import FeedbackSettings
from studio.dialogs.window_manager import find_dialog_manager


class FeedbackController:
    """Owns feedback settings persistence and dialog wiring."""

    def __init__(
        self,
        *,
        app_settings: QSettings,
        show_status: Callable[[str, int], None],
        parent_window: QWidget,
    ):
        self._app_settings = app_settings
        self._show_status = show_status
        self._parent = parent_window
        self._feedback_settings = self._load()
        self._feedback_service = FeedbackService(self._feedback_settings)

    # ── public ────────────────────────────────────────────────────────

    @property
    def settings(self) -> FeedbackSettings:
        return self._feedback_settings

    @property
    def service(self) -> FeedbackService:
        return self._feedback_service

    def save(self, settings: FeedbackSettings):
        self._feedback_settings = settings
        self._feedback_service.update_settings(settings)
        self._app_settings.setValue(
            FeedbackSettingsKeys.UI_ENABLED,
            bool(settings.ui_enabled),
        )
        self._app_settings.setValue(
            FeedbackSettingsKeys.CAPTURE_PAYLOAD_ENABLED,
            bool(settings.capture_payload_enabled),
        )
        self._app_settings.setValue(
            FeedbackSettingsKeys.STORAGE_DIR,
            str(settings.storage_dir or ""),
        )
        self._app_settings.sync()

    def open_settings_dialog(self):
        from studio.feedback.settings_dialog import FeedbackSettingsDialog
        user_mode = str(getattr(self._parent, "user_mode", "") or "")
        manager = find_dialog_manager(self._parent)
        if manager is not None:
            manager.show_dialog(
                "feedback-settings",
                lambda: FeedbackSettingsDialog(
                    self._feedback_settings,
                    user_mode=user_mode,
                    parent=self._parent,
                ),
                on_reopen=lambda dlg, mode=user_mode: getattr(dlg, "set_user_mode", lambda _m: None)(mode),
                on_accept=lambda dlg: self._apply_settings_dialog(dlg),
            )
            return
        dlg = FeedbackSettingsDialog(
            self._feedback_settings,
            user_mode=user_mode,
            parent=self._parent,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_settings_dialog(dlg)

    def open_stats_dialog(self):
        from studio.feedback.stats_dialog import FeedbackStatsDialog
        user_mode = str(getattr(self._parent, "user_mode", "") or "")
        manager = find_dialog_manager(self._parent)
        if manager is not None:
            manager.show_dialog(
                "feedback-stats",
                lambda: FeedbackStatsDialog(
                    self._feedback_service,
                    user_mode=user_mode,
                    parent=self._parent,
                ),
                on_reopen=lambda dlg, mode=user_mode: self._reopen_stats_dialog(dlg, mode),
            )
            return
        FeedbackStatsDialog(
            self._feedback_service,
            user_mode=user_mode,
            parent=self._parent,
        ).exec()

    def open_freeform_dialog(self):
        from studio.feedback.freeform_dialog import FeedbackFreeformDialog
        user_mode = str(getattr(self._parent, "user_mode", "") or "")
        manager = find_dialog_manager(self._parent)
        if manager is not None:
            manager.show_dialog(
                "feedback-freeform",
                lambda: FeedbackFreeformDialog(
                    self._feedback_service,
                    user_mode=user_mode,
                    parent=self._parent,
                ),
                on_reopen=lambda dlg, mode=user_mode: getattr(dlg, "set_user_mode", lambda _m: None)(mode),
                on_accept=lambda _dlg: self._show_status("Feedback gespeichert. Danke!", 3000),
            )
            return
        dlg = FeedbackFreeformDialog(
            self._feedback_service,
            user_mode=user_mode,
            parent=self._parent,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._show_status("Feedback gespeichert. Danke!", 3000)

    def submit_status_feedback(
        self,
        sentiment: str,
        tags: list,
        note: str,
        *,
        glossary_feedback_bar,
        payload: dict,
    ):
        use_case = str(getattr(glossary_feedback_bar, "_use_case", "") or "").strip() or "other"
        self._feedback_service.submit_feedback(
            use_case=use_case,
            sentiment=sentiment,
            payload=payload if isinstance(payload, dict) else None,
            error_tags=tags or None,
            note=note,
        )

    # ── private ───────────────────────────────────────────────────────

    def _load(self) -> FeedbackSettings:
        raw = {
            "ui_enabled": self._app_settings.value(
                FeedbackSettingsKeys.UI_ENABLED,
                True,
            ),
            "capture_payload_enabled": self._app_settings.value(
                FeedbackSettingsKeys.CAPTURE_PAYLOAD_ENABLED,
                True,
            ),
            "storage_dir": self._app_settings.value(
                FeedbackSettingsKeys.STORAGE_DIR,
                "runs/feedback",
            ),
        }
        return FeedbackSettings.from_dict(raw)

    def _apply_settings_dialog(self, dialog: QDialog) -> None:
        get_settings = getattr(dialog, "get_settings", None)
        if not callable(get_settings):
            return
        self.save(get_settings())
        self._show_status("Feedback-Einstellungen gespeichert.", 3000)

    @staticmethod
    def _reopen_stats_dialog(dialog: QDialog, mode: str) -> None:
        setter = getattr(dialog, "set_user_mode", None)
        if callable(setter):
            setter(mode)
        loader = getattr(dialog, "_load_data", None)
        if callable(loader):
            loader()
