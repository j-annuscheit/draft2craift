"""Runtime application context shared across Writing Studio controllers.

Role: Mediator
--------------
AppContext is a *Mediator* — it gives controllers a stable, named API for
cross-cutting operations (show a status message, schedule an autosave, resolve
a document) without requiring them to know about each other directly.

What belongs here
~~~~~~~~~~~~~~~~~
* Forwarding calls that cross controller boundaries (autosave ↔ knowledge,
  knowledge ↔ chat, any controller ↔ project/settings).
* Runtime state that truly has no single owner (user_mode, feedback payload).
* Validation that all required bindings are present after setup.

What does NOT belong here
~~~~~~~~~~~~~~~~~~~~~~~~~
* Business logic — keep that in the individual controllers.
* New delegation methods that just wrap a single controller method.
  Add those directly to the controller and call it from the consumer.
* Direct dock access — route through the controller that owns the dock.
"""
from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMainWindow

    from shared.services.llm.manager import LLMManager
    from shared.services.project.manager import ProjectManager
    from shared.services.rag.orchestrator import RAGSystem
    from studio.controllers.autosave import AutosaveController
    from studio.controllers.chat_controller import ChatController
    from studio.controllers.knowledge_controller import KnowledgeController
    from studio.controllers.theme_ctrl import ThemeController
    from studio.logger import AppLogger


class AppContext:
    """Mediator for cross-controller operations and shared runtime state.

    Bind all controllers after construction via the ``bind_*`` methods, then
    call :meth:`validate` to assert completeness in debug builds.
    """

    def __init__(
        self,
        *,
        window: QMainWindow,
        app_logger: AppLogger,
        rag_system: RAGSystem,
        llm_manager: LLMManager,
        project_manager: ProjectManager,
        app_settings: QSettings,
        file_registry: dict[str, tuple[str, str]],
        user_mode: str,
    ) -> None:
        # ── Services (long-lived, set at construction) ─────────────────
        self._window = window
        self.app_logger: AppLogger = app_logger
        self.rag_system: RAGSystem = rag_system
        self.llm_manager: LLMManager = llm_manager
        self.project_manager: ProjectManager = project_manager
        self.app_settings: QSettings = app_settings
        self.file_registry: dict[str, tuple[str, str]] = file_registry
        self.user_mode: str = str(user_mode or "")

        # ── Controller bindings (populated during setup) ───────────────
        self._theme_controller: ThemeController | None = None
        self._autosave_controller: AutosaveController | None = None
        self._knowledge_controller: KnowledgeController | None = None
        self._chat_controller: ChatController | None = None

        # ── UI-widget bindings (populated during setup) ────────────────
        self._glossary_feedback_bar = None

        # ── Runtime state ──────────────────────────────────────────────
        self._status_feedback_payload: dict[str, object] = {}

    # ── Bind points ───────────────────────────────────────────────────

    def bind_theme_controller(self, controller: ThemeController) -> None:
        self._theme_controller = controller

    def bind_autosave_controller(self, controller: AutosaveController) -> None:
        self._autosave_controller = controller

    def bind_knowledge_controller(self, controller: KnowledgeController) -> None:
        self._knowledge_controller = controller

    def bind_chat_controller(self, controller: ChatController) -> None:
        self._chat_controller = controller

    def bind_glossary_feedback_bar(self, bar: object) -> None:
        self._glossary_feedback_bar = bar

    # ── Properties ────────────────────────────────────────────────────

    @property
    def window(self) -> QMainWindow:
        return self._window

    @property
    def autosave_controller(self) -> AutosaveController | None:
        return self._autosave_controller

    @property
    def theme_controller(self) -> ThemeController | None:
        return self._theme_controller

    @property
    def glossary_feedback_bar(self) -> object:
        return self._glossary_feedback_bar

    @property
    def status_feedback_payload(self) -> dict[str, object]:
        return dict(self._status_feedback_payload)

    # ── Setup validation ──────────────────────────────────────────────

    @staticmethod
    def _parse_debug_env_flag(value: str | None) -> bool | None:
        raw = str(value or "").strip().casefold()
        if not raw:
            return None
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        return None

    @classmethod
    def _debug_validation_enabled(cls) -> bool:
        env_override = cls._parse_debug_env_flag(os.getenv("APP_DEBUG"))
        if env_override is not None:
            return env_override
        return bool(__debug__)

    def validate(self) -> None:
        """Assert all required controller bindings are present.

        Raises :class:`RuntimeError` in debug mode when any binding is missing.
        Has no effect in optimised (``python -O``) builds unless
        ``APP_DEBUG=1`` is set.
        """
        if not self._debug_validation_enabled():
            return
        missing: list[str] = []
        if self._theme_controller is None:
            missing.append("theme_controller")
        if self._autosave_controller is None:
            missing.append("autosave_controller")
        if self._knowledge_controller is None:
            missing.append("knowledge_controller")
        if self._chat_controller is None:
            missing.append("chat_controller")
        if missing:
            raise RuntimeError(
                "AppContext bindings incomplete: " + ", ".join(missing)
            )

    # ── Window operations ─────────────────────────────────────────────

    def show_status(self, message: str, timeout_ms: int = 0) -> None:
        """Display *message* in the main window status bar."""
        status_bar = self._window.statusBar()
        if status_bar is None:
            return
        status_bar.showMessage(str(message or ""), int(timeout_ms))

    def save_project(self, path: Path | str, *, include_st_embeddings: bool = True) -> bool:
        return bool(
            self.project_manager.save_project(
                self._window,
                str(path),
                include_st_embeddings=bool(include_st_embeddings),
            )
        )

    def export_project_archive(
        self,
        path: Path | str,
        *,
        include_st_embeddings: bool = True,
    ) -> bool:
        return bool(
            self.project_manager.export_project_archive(
                self._window,
                str(path),
                include_st_embeddings=bool(include_st_embeddings),
            )
        )

    def load_project(self, path: Path | str) -> bool:
        return bool(self.project_manager.load_project(self._window, str(path)))

    def import_project_archive(self, path: Path | str) -> bool:
        return bool(self.project_manager.import_project_archive(self._window, str(path)))

    # ── Cross-controller queries ──────────────────────────────────────

    def is_rag_busy(self) -> bool:
        """Return True if the RAG worker is currently indexing or searching."""
        ctrl = self._knowledge_controller
        if ctrl is None:
            return False
        return ctrl.is_rag_busy()

    def chat_tts_mode(self) -> str:
        """Return the current TTS mode from the chat dock ('off', 'auto', …)."""
        ctrl = self._chat_controller
        if ctrl is None:
            return "off"
        return ctrl.get_tts_mode()

    def resolve_imported_doc_content(self, name: str) -> str:
        ctrl = self._knowledge_controller
        if ctrl is None:
            return ""
        return str(ctrl.resolve_imported_doc_content(name) or "")

    def refresh_context_bar(self) -> None:
        ctrl = self._chat_controller
        if ctrl is None:
            return
        ctrl.refresh_context_bar()

    # ── Runtime state helpers ─────────────────────────────────────────

    def get_user_mode(self) -> str:
        return str(self.user_mode or "")

    def set_status_feedback_payload(self, payload: Mapping[str, object] | None) -> None:
        self._status_feedback_payload = dict(payload or {})

    # ── Autosave coordination ─────────────────────────────────────────
    # These methods let controllers (knowledge, project) coordinate with
    # AutosaveController without depending on it directly.  All calls are
    # no-ops if the autosave controller has not been bound yet.

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

    def autosave_state_extras(self) -> dict[str, Any]:
        """Gather cross-controller state required for the autosave snapshot.

        Collects theme, preview settings, user mode, and imported-doc list.
        Each piece is fetched defensively so a failing controller cannot abort
        the autosave cycle.
        """
        theme = ""
        preview_margin: dict[str, object] = {}
        preview_theme = ""
        ctrl = self._theme_controller
        if ctrl is not None:
            try:
                theme = str(ctrl.get_theme_id() or "")
            except Exception as exc:
                self.app_logger.warning("SYS", f"[AUTOSAVE] get_theme_id failed: {exc}")
            try:
                preview_margin = dict(ctrl.get_preview_page_margin_settings() or {})
            except Exception as exc:
                self.app_logger.warning(
                    "SYS", f"[AUTOSAVE] get_preview_page_margin_settings failed: {exc}"
                )
            try:
                preview_theme = str(ctrl.get_preview_theme_id() or "")
            except Exception as exc:
                self.app_logger.warning(
                    "SYS", f"[AUTOSAVE] get_preview_theme_id failed: {exc}"
                )
        return {
            "user_mode": self.get_user_mode(),
            "theme": theme,
            "imported_docs": sorted(self.file_registry.keys()),
            "preview_page_margin": preview_margin,
            "preview_theme": preview_theme,
        }
