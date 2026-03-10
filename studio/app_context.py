"""Runtime application context shared across Writing Studio controllers."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


class AppContext:
    """Central access point for cross-controller services and runtime state."""

    def __init__(
        self,
        *,
        window,
        app_logger,
        rag_system,
        llm_manager,
        project_manager,
        app_settings,
        file_registry: dict[str, tuple[str, str]],
        user_mode: str,
    ):
        self._window = window
        self.app_logger = app_logger
        self.rag_system = rag_system
        self.llm_manager = llm_manager
        self.project_manager = project_manager
        self.app_settings = app_settings
        self.file_registry = file_registry
        self.user_mode = str(user_mode or "")

        self._theme_controller = None
        self._autosave_controller = None
        self._knowledge_controller = None
        self._chat_controller = None
        self._chat_dock = None
        self._knowledge_dock = None
        self._status_feedback_payload: dict[str, object] = {}

    @property
    def window(self):
        return self._window

    @property
    def autosave_controller(self):
        return self._autosave_controller

    @property
    def status_feedback_payload(self) -> dict[str, object]:
        return dict(self._status_feedback_payload)

    def bind_theme_controller(self, controller) -> None:
        self._theme_controller = controller

    def bind_autosave_controller(self, controller) -> None:
        self._autosave_controller = controller

    def bind_knowledge_controller(self, controller) -> None:
        self._knowledge_controller = controller

    def bind_chat_controller(self, controller) -> None:
        self._chat_controller = controller

    def bind_docks(self, *, knowledge_dock, chat_dock) -> None:
        self._knowledge_dock = knowledge_dock
        self._chat_dock = chat_dock

    def validate(self) -> None:
        """Raise when required runtime bindings are incomplete."""
        missing: list[str] = []
        if self._theme_controller is None:
            missing.append("theme_controller")
        if self._autosave_controller is None:
            missing.append("autosave_controller")
        if self._knowledge_controller is None:
            missing.append("knowledge_controller")
        if self._chat_controller is None:
            missing.append("chat_controller")
        if self._knowledge_dock is None:
            missing.append("knowledge_dock")
        if self._chat_dock is None:
            missing.append("chat_dock")
        if not missing:
            return
        raise RuntimeError(
            "AppContext bindings incomplete: " + ", ".join(missing)
        )

    def show_status(self, message: str, timeout_ms: int = 0) -> None:
        status_bar = self._window.statusBar()
        if status_bar is None:
            return
        status_bar.showMessage(str(message or ""), int(timeout_ms))

    def set_status_feedback_payload(self, payload: Mapping[str, object] | None) -> None:
        self._status_feedback_payload = dict(payload or {})

    def get_user_mode(self) -> str:
        return str(self.user_mode or "")

    def save_project(self, path: Path | str, *, include_st_embeddings: bool = True) -> bool:
        return bool(
            self.project_manager.save_project(
                self._window,
                str(path),
                include_st_embeddings=bool(include_st_embeddings),
            )
        )

    def load_project(self, path: Path | str) -> bool:
        return bool(self.project_manager.load_project(self._window, str(path)))

    def is_rag_busy(self) -> bool:
        worker = getattr(self._knowledge_dock, "rag_worker", None)
        if worker is None:
            return False
        return bool(getattr(worker, "isRunning", lambda: False)())

    def get_autosave_suspended(self) -> bool:
        ctrl = self._autosave_controller
        if ctrl is None:
            return False
        return bool(getattr(ctrl, "suspended", False))

    def set_autosave_suspended(self, value: bool) -> None:
        ctrl = self._autosave_controller
        if ctrl is None:
            return
        setattr(ctrl, "suspended", bool(value))

    def flush_autosave_full(self) -> None:
        ctrl = self._autosave_controller
        if ctrl is None:
            return
        ctrl.flush_full()

    def flush_autosave_pending_preview_edits(self) -> None:
        ctrl = self._autosave_controller
        if ctrl is None:
            return
        ctrl.flush_pending_preview_edits()

    def schedule_autosave(self, delay_ms: int = 900) -> None:
        ctrl = self._autosave_controller
        if ctrl is None:
            return
        ctrl.schedule_full(delay_ms=int(delay_ms))

    def rewire_autosave_editors(self) -> None:
        ctrl = self._autosave_controller
        if ctrl is None:
            return
        ctrl.rewire_editors()

    def refresh_context_bar(self) -> None:
        ctrl = self._chat_controller
        if ctrl is None:
            return
        ctrl.refresh_context_bar()

    def resolve_imported_doc_content(self, name: str) -> str:
        ctrl = self._knowledge_controller
        if ctrl is None:
            return ""
        return str(ctrl.resolve_imported_doc_content(name) or "")

    def chat_tts_mode(self) -> str:
        if self._chat_dock is None:
            return "off"
        try:
            return str(self._chat_dock.chat_tts_mode() or "off")
        except Exception:
            return "off"

    def autosave_state_extras(self) -> dict[str, Any]:
        theme = ""
        preview_margin: dict[str, object] = {}
        preview_theme = ""
        if self._theme_controller is not None:
            try:
                theme = str(self._theme_controller.get_theme_id() or "")
            except Exception:
                theme = ""
            try:
                preview_margin = dict(
                    self._theme_controller.get_preview_page_margin_settings() or {}
                )
            except Exception:
                preview_margin = {}
            try:
                preview_theme = str(self._theme_controller.get_preview_theme_id() or "")
            except Exception:
                preview_theme = ""
        return {
            "user_mode": self.get_user_mode(),
            "theme": theme,
            "imported_docs": sorted(self.file_registry.keys()),
            "preview_page_margin": preview_margin,
            "preview_theme": preview_theme,
        }
