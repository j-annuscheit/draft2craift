"""Controller for persistent agentic workflow runtime settings."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog, QWidget

from pathlib import Path

from shared.config.setting_keys import AgenticSettingsKeys
from shared.services.agentic.settings import (
    AgenticRuntimeSettings,
    _DEFAULT_PROFILES,  # noqa: PLC2701
    discover_profile_ids_by_workflow,
)
from studio.dialogs.window_manager import find_dialog_manager


class AgenticSettingsController:
    """Owns user-persisted agentic runtime settings and settings dialog wiring."""

    def __init__(
        self,
        *,
        app_settings: QSettings,
        show_status: Callable[[str, int], None],
        parent_window: QWidget,
    ) -> None:
        self._app_settings = app_settings
        self._show_status = show_status
        self._parent = parent_window
        self._settings = self._load()

    def get_settings(self) -> AgenticRuntimeSettings:
        return self._settings.clone()

    def save(self, settings: AgenticRuntimeSettings) -> None:
        self._settings = settings.clone()
        payload = self._settings.to_dict()
        self._app_settings.setValue(
            AgenticSettingsKeys.FACTCHECK_ENABLED,
            bool(payload.get("factcheck_enabled", False)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.CHAT_ENABLED,
            bool(payload.get("chat_enabled", False)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.CANVAS_ENABLED,
            bool(payload.get("canvas_enabled", False)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_ENABLED,
            bool(payload.get("mindmap_enabled", False)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_ENABLED,
            bool(payload.get("graph_enabled", False)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.FACTCHECK_PROFILE_ID,
            str(payload.get("factcheck_profile_id", "") or ""),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.CHAT_PROFILE_ID,
            str(payload.get("chat_profile_id", "") or ""),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.CANVAS_PROFILE_ID,
            str(payload.get("canvas_profile_id", "") or ""),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_PROFILE_ID,
            str(payload.get("mindmap_profile_id", "") or ""),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_PROFILE_ID,
            str(payload.get("graph_profile_id", "") or ""),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.STRICT_POLICY,
            bool(payload.get("strict_policy", False)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.TRACE_ENABLED,
            bool(payload.get("trace_enabled", False)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.CACHE_ENABLED,
            bool(payload.get("cache_enabled", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MAP_RESULT_DETAIL_LEVEL,
            str(payload.get("map_result_detail_level", "auto") or "auto"),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.ENV_NAME,
            str(payload.get("env_name", "") or ""),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.OVERLAY_PROFILE_IDS,
            str(payload.get("overlay_profile_ids_raw", "") or ""),
        )
        self._app_settings.sync()

    def open_settings_dialog(self) -> None:
        from studio.agentic.settings_dialog import AgenticSettingsDialog

        user_mode = str(getattr(self._parent, "user_mode", "") or "")
        profiles = discover_profile_ids_by_workflow()
        manager = find_dialog_manager(self._parent)
        if manager is not None:
            manager.show_dialog(
                "agentic-workflow-settings",
                lambda: AgenticSettingsDialog(
                    self.get_settings(),
                    profile_ids_by_workflow=profiles,
                    user_mode=user_mode,
                    parent=self._parent,
                ),
                on_reopen=lambda dlg, mode=user_mode: getattr(
                    dlg,
                    "set_user_mode",
                    lambda _m: None,
                )(mode),
                on_accept=lambda dlg: self._apply_dialog(dlg),
            )
            return

        dialog = AgenticSettingsDialog(
            self.get_settings(),
            profile_ids_by_workflow=profiles,
            user_mode=user_mode,
            parent=self._parent,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_dialog(dialog)

    def _load(self) -> AgenticRuntimeSettings:
        raw = {
            "factcheck_enabled": self._app_settings.value(
                AgenticSettingsKeys.FACTCHECK_ENABLED,
                None,
            ),
            "chat_enabled": self._app_settings.value(
                AgenticSettingsKeys.CHAT_ENABLED,
                None,
            ),
            "canvas_enabled": self._app_settings.value(
                AgenticSettingsKeys.CANVAS_ENABLED,
                None,
            ),
            "mindmap_enabled": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_ENABLED,
                None,
            ),
            "graph_enabled": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_ENABLED,
                None,
            ),
            "factcheck_profile_id": self._app_settings.value(
                AgenticSettingsKeys.FACTCHECK_PROFILE_ID,
                "",
            ),
            "chat_profile_id": self._app_settings.value(
                AgenticSettingsKeys.CHAT_PROFILE_ID,
                "",
            ),
            "canvas_profile_id": self._app_settings.value(
                AgenticSettingsKeys.CANVAS_PROFILE_ID,
                "",
            ),
            "mindmap_profile_id": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_PROFILE_ID,
                "",
            ),
            "graph_profile_id": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_PROFILE_ID,
                "",
            ),
            "strict_policy": self._app_settings.value(
                AgenticSettingsKeys.STRICT_POLICY,
                None,
            ),
            "trace_enabled": self._app_settings.value(
                AgenticSettingsKeys.TRACE_ENABLED,
                None,
            ),
            "cache_enabled": self._app_settings.value(
                AgenticSettingsKeys.CACHE_ENABLED,
                None,
            ),
            "map_result_detail_level": self._app_settings.value(
                AgenticSettingsKeys.MAP_RESULT_DETAIL_LEVEL,
                "auto",
            ),
            "env_name": self._app_settings.value(
                AgenticSettingsKeys.ENV_NAME,
                "",
            ),
            "overlay_profile_ids_raw": self._app_settings.value(
                AgenticSettingsKeys.OVERLAY_PROFILE_IDS,
                "",
            ),
        }
        profiles_dir = (
            Path(__file__).resolve().parents[3] / "data" / "workflows" / "profiles"
        )
        for key in ("factcheck", "chat", "canvas", "mindmap", "graph"):
            pid_field = f"{key}_profile_id"
            pid = str(raw.get(pid_field, "") or "").strip()
            if pid and not (profiles_dir / f"{pid}.toml").is_file():
                raw[pid_field] = _DEFAULT_PROFILES.get(key, "")
        return AgenticRuntimeSettings.from_dict(raw)

    def _apply_dialog(self, dialog: QDialog) -> None:
        getter = getattr(dialog, "get_settings", None)
        if not callable(getter):
            return
        try:
            settings = getter()
        except Exception:
            return
        if not isinstance(settings, AgenticRuntimeSettings):
            settings = AgenticRuntimeSettings.from_dict(
                getattr(settings, "to_dict", lambda: {})()
            )
        self.save(settings)
        self._show_status("Agentic-Workflow-Einstellungen gespeichert.", 3000)
