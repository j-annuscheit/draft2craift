"""Controller for persistent agentic workflow runtime settings."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog, QWidget

from shared.config.setting_keys import AgenticSettingsKeys
from shared.services.agentic.settings import (
    AgenticRuntimeSettings,
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
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_FACTCHECK,
            bool(payload.get("mindmap_factcheck", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_MAX_NODES,
            int(payload.get("mindmap_max_nodes", 32) or 32),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_MAX_REFINEMENT_ROUNDS,
            int(payload.get("mindmap_max_refinement_rounds", 1) or 1),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_RETRIEVAL_STRATEGY,
            str(payload.get("mindmap_retrieval_strategy", "rag") or "rag"),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_AGENT_MAX_ITERATIONS,
            int(payload.get("mindmap_agent_max_iterations", 6) or 6),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_USE_FULL_CONTEXT,
            bool(payload.get("mindmap_use_full_context", False)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_CONTEXT_MAX_CHARS,
            int(payload.get("mindmap_context_max_chars", 50_000) or 50_000),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_AGENT_ALLOW_RAG,
            bool(payload.get("mindmap_agent_allow_rag", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_AGENT_ALLOW_REGEX,
            bool(payload.get("mindmap_agent_allow_regex", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_AGENT_ALLOW_HEADING,
            bool(payload.get("mindmap_agent_allow_heading", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_AGENT_ALLOW_FULL_TEXT,
            bool(payload.get("mindmap_agent_allow_full_text", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_AGENT_ALLOW_QUERY_NARROWING,
            bool(payload.get("mindmap_agent_allow_query_narrowing", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_AGENT_ALLOW_HEADING_SUMMARIES,
            bool(payload.get("mindmap_agent_allow_heading_summaries", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.MINDMAP_AGENT_MAX_REGEX_CALLS,
            int(payload.get("mindmap_agent_max_regex_calls", 4) or 4),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_FACTCHECK,
            bool(payload.get("graph_factcheck", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_MAX_NODES,
            int(payload.get("graph_max_nodes", 32) or 32),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_RETRIEVAL_STRATEGY,
            str(payload.get("graph_retrieval_strategy", "rag") or "rag"),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_AGENT_MAX_ITERATIONS,
            int(payload.get("graph_agent_max_iterations", 6) or 6),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_USE_FULL_CONTEXT,
            bool(payload.get("graph_use_full_context", False)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_CONTEXT_MAX_CHARS,
            int(payload.get("graph_context_max_chars", 50_000) or 50_000),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_AGENT_ALLOW_RAG,
            bool(payload.get("graph_agent_allow_rag", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_AGENT_ALLOW_REGEX,
            bool(payload.get("graph_agent_allow_regex", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_AGENT_ALLOW_HEADING,
            bool(payload.get("graph_agent_allow_heading", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_AGENT_ALLOW_FULL_TEXT,
            bool(payload.get("graph_agent_allow_full_text", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_AGENT_ALLOW_QUERY_NARROWING,
            bool(payload.get("graph_agent_allow_query_narrowing", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_AGENT_ALLOW_HEADING_SUMMARIES,
            bool(payload.get("graph_agent_allow_heading_summaries", True)),
        )
        self._app_settings.setValue(
            AgenticSettingsKeys.GRAPH_AGENT_MAX_REGEX_CALLS,
            int(payload.get("graph_agent_max_regex_calls", 4) or 4),
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
            "mindmap_factcheck": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_FACTCHECK,
                None,
            ),
            "mindmap_max_nodes": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_MAX_NODES,
                None,
            ),
            "mindmap_max_refinement_rounds": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_MAX_REFINEMENT_ROUNDS,
                None,
            ),
            "mindmap_retrieval_strategy": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_RETRIEVAL_STRATEGY,
                "",
            ),
            "mindmap_agent_max_iterations": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_AGENT_MAX_ITERATIONS,
                None,
            ),
            "mindmap_use_full_context": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_USE_FULL_CONTEXT,
                None,
            ),
            "mindmap_context_max_chars": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_CONTEXT_MAX_CHARS,
                None,
            ),
            "mindmap_agent_allow_rag": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_AGENT_ALLOW_RAG,
                None,
            ),
            "mindmap_agent_allow_regex": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_AGENT_ALLOW_REGEX,
                None,
            ),
            "mindmap_agent_allow_heading": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_AGENT_ALLOW_HEADING,
                None,
            ),
            "mindmap_agent_allow_full_text": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_AGENT_ALLOW_FULL_TEXT,
                None,
            ),
            "mindmap_agent_allow_query_narrowing": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_AGENT_ALLOW_QUERY_NARROWING,
                None,
            ),
            "mindmap_agent_allow_heading_summaries": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_AGENT_ALLOW_HEADING_SUMMARIES,
                None,
            ),
            "mindmap_agent_max_regex_calls": self._app_settings.value(
                AgenticSettingsKeys.MINDMAP_AGENT_MAX_REGEX_CALLS,
                None,
            ),
            "graph_factcheck": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_FACTCHECK,
                None,
            ),
            "graph_max_nodes": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_MAX_NODES,
                None,
            ),
            "graph_retrieval_strategy": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_RETRIEVAL_STRATEGY,
                "",
            ),
            "graph_agent_max_iterations": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_AGENT_MAX_ITERATIONS,
                None,
            ),
            "graph_use_full_context": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_USE_FULL_CONTEXT,
                None,
            ),
            "graph_context_max_chars": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_CONTEXT_MAX_CHARS,
                None,
            ),
            "graph_agent_allow_rag": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_AGENT_ALLOW_RAG,
                None,
            ),
            "graph_agent_allow_regex": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_AGENT_ALLOW_REGEX,
                None,
            ),
            "graph_agent_allow_heading": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_AGENT_ALLOW_HEADING,
                None,
            ),
            "graph_agent_allow_full_text": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_AGENT_ALLOW_FULL_TEXT,
                None,
            ),
            "graph_agent_allow_query_narrowing": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_AGENT_ALLOW_QUERY_NARROWING,
                None,
            ),
            "graph_agent_allow_heading_summaries": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_AGENT_ALLOW_HEADING_SUMMARIES,
                None,
            ),
            "graph_agent_max_regex_calls": self._app_settings.value(
                AgenticSettingsKeys.GRAPH_AGENT_MAX_REGEX_CALLS,
                None,
            ),
        }
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
