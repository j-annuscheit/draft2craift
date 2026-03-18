"""
MainWindow
==========
Layout glue.  Owns:
  • Central widget  – CanvasTabWidget (tab-based Markdown editor)
  • Left dock       – KnowledgeDock   (Viewer / RAG with file selector on top)
  • Right dock      – ChatDock        (LLM chat with streaming)

All docks are floating-capable (QDockWidget) and dock-nesting is enabled.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
)

from shared.domain.user_mode import (
    user_mode_label,
)
from shared.services.project.project_variables import (
    normalize_project_variables,
    resolve_project_variables_text,
)
from studio.canvas.preview.pane import CanvasPreviewPane
from studio.canvas.tabs import CanvasTabWidget
from studio.controllers.feedback_ctrl import FeedbackController
from studio.controllers.theme_ctrl import ThemeController
from studio.feedback.bar import FeedbackBar
from studio.dialogs.window_manager import DialogWindowManager
from studio.profile_text_overrides import (
    install_qmessagebox_literal_overrides,
)
from studio.setup.controllers_setup import init_controllers as _setup_controllers
from studio.setup.docks_setup import init_docks as _setup_docks
from studio.setup.feature_bindings_setup import FeatureBindingRegistry
from studio.setup.shortcuts_setup import init_global_shortcuts as _setup_shortcuts
from studio.setup.signals_setup import connect_global_signals as _setup_global_signals
from studio.setup.services_setup import init_services as _setup_services

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings


def _read_data_file(relative_path: str, fallback: str) -> str:
    base = Path(__file__).resolve().parents[1]
    candidate = base / "data" / relative_path
    try:
        return candidate.read_text(encoding="utf-8")
    except Exception:
        return str(fallback or "")


_WELCOME_TEXT = _read_data_file(
    "welcome.md",
    "",
)

_ABOUT_TEXT = _read_data_file("about.md", "")
_SHORTCUTS_TEXT = _read_data_file("shortcuts.md", "")

# ── Main Window ────────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    """
    Orchestration layer.

    Responsibilities
    ----------------
    • Create and wire all top-level widgets / docks.
    • Build the LLM context dict on demand (context_getter).
    • Menu bar, status bar, keyboard shortcuts.
    • Periodic context-bar refresh (1 s timer).
    """

    def __init__(self, app_settings: QSettings):
        self._init_bootstrap(app_settings=app_settings)

    def _init_bootstrap(self, *, app_settings: QSettings):
        super().__init__()
        install_qmessagebox_literal_overrides()
        self._dialog_manager = DialogWindowManager(self)
        self._project_variables: dict[str, str] = {}
        self._bootstrap_app_settings = app_settings
        self._init_services()
        self._init_early_controllers()
        self._init_window()
        self._init_central()
        # Status bar first: binds _glossary_feedback_bar to ctx before controllers run.
        self._init_statusbar()
        self._init_docks()
        self._init_controllers()
        self._context.validate()
        from studio.menubar import MenuBuildInputs, build_menubar
        self._knowledge_controller.set_loaded_menu(None)
        menu_result = build_menubar(
            MenuBuildInputs(
                host=self,
                canvas=self.canvas,
                knowledge_dock=self.knowledge_dock,
                chat_dock=self.chat_dock,
                log_dock=self.log_dock,
                llm_stop=self.llm_manager.stop,
                user_mode_changed=self.set_user_mode,
                apply_theme_id=self.apply_theme_id,
                apply_preview_theme_id=self.apply_preview_theme_id,
                bind_feature_visibility=self._bind_feature_visibility,
                bind_feature_label=self._bind_feature_label,
                action_handlers={
                    "export_active_canvas_document": self._export_active_canvas_document,
                    "save_project": self._save_project,
                    "load_project": self._load_project,
                    "export_project_archive": self._export_project_archive,
                    "import_project_archive": self._import_project_archive,
                    "open_import_dialog": self._open_import_dialog,
                    "set_model_controls_visible": self._set_model_controls_visible,
                    "increase_active_text_size": self._increase_active_text_size,
                    "decrease_active_text_size": self._decrease_active_text_size,
                    "reset_active_text_size": self._reset_active_text_size,
                    "increase_preview_text_size": self._increase_preview_text_size,
                    "decrease_preview_text_size": self._decrease_preview_text_size,
                    "reset_preview_text_size": self._reset_preview_text_size,
                    "toggle_glossary_overlays": self._toggle_glossary_overlays,
                    "open_glossary_editor": self._open_glossary_editor,
                    "reset_layout": self._reset_layout,
                    "toggle_autosave_enabled": self._toggle_autosave_enabled,
                    "open_freeform_feedback": self._open_freeform_feedback,
                    "open_feedback_stats": self._open_feedback_stats,
                    "open_feedback_settings": self._open_feedback_settings,
                    "open_project_variables": self._open_project_variables,
                    "focus_model_panel": self._focus_model_panel,
                    "edit_system_prompt": self._edit_system_prompt,
                    "generate_glossary_from_context": self._generate_glossary_from_context,
                    "generate_mindmap_from_context": self._generate_mindmap_from_context,
                    "try_sentence_transformers": self._try_sentence_transformers,
                    "open_rag_settings": self._open_rag_settings,
                    "open_speech_settings": self._open_speech_settings,
                    "speak_active_workspace_text": self._speak_active_workspace_text,
                    "stop_tts": self._stop_tts,
                    "start_whisper_dictation": self._start_whisper_dictation,
                    "stop_whisper_dictation": self._stop_whisper_dictation,
                    "on_dictation_running_changed": self._on_dictation_running_changed,
                    "show_shortcuts": self._show_shortcuts,
                    "show_about": self._show_about,
                    "apply_window_chrome_theme": self._apply_window_chrome_theme,
                },
                theme_ctrl=self._theme_ctrl,
                speech_ctrl=self._speech_ctrl,
                autosave_enabled=self._autosave_ctrl.enabled,
            )
        )
        self._loaded_menu = menu_result.loaded_menu
        self._log_toggle_action = menu_result.log_toggle_action
        self._model_controls_toggle_action = menu_result.model_controls_toggle_action
        self._mode_group = menu_result.mode_group
        self._mode_actions = menu_result.mode_actions
        self._theme_group = menu_result.theme_group
        self._theme_actions = menu_result.theme_actions
        self._action_page_margin_enabled = menu_result.action_page_margin_enabled
        self._page_margin_group = menu_result.page_margin_group
        self._page_margin_actions = menu_result.page_margin_actions
        self._preview_theme_group = menu_result.preview_theme_group
        self._preview_theme_actions = menu_result.preview_theme_actions
        self._action_glossary_overlay = menu_result.action_glossary_overlay
        self._action_autosave_toggle = menu_result.action_autosave_toggle
        self._action_edit_prompts = menu_result.action_edit_prompts
        self._action_start_dictation = menu_result.action_start_dictation
        self._action_stop_dictation = menu_result.action_stop_dictation
        self._sync_model_controls_toggle_action()
        self._knowledge_controller.set_loaded_menu(self._loaded_menu)
        self._init_global_shortcuts()
        self._connect_global_signals()
        self.set_user_mode(self._user_mode, notify=False)
        restored_from_tmp = self._autosave_ctrl.maybe_restore_from_tmp(self)
        if not restored_from_tmp:
            self._show_welcome()
        self._autosave_ctrl.start_runtime()
        if self._autosave_ctrl.enabled and not restored_from_tmp:
            self._autosave_ctrl.schedule_full(delay_ms=200)
        self.app_logger.info(
            "SYS", f"draft2craift started  |  RAG backend: {self.rag_system.current_backend()}")
        log_path = str(getattr(self.app_logger, "log_file_path", lambda: "")() or "").strip()
        if log_path:
            self.app_logger.info("SYS", f"Debug log file: {log_path}")

    def _init_services(self):
        services = _setup_services(self, app_settings=self._bootstrap_app_settings)
        self._services = services
        self._context = services.context
        self.app_logger = services.app_logger
        self.rag_system = services.rag_system
        self.llm_manager = services.llm_manager
        llm_setter = getattr(self.llm_manager, "set_project_variables_getter", None)
        if callable(llm_setter):
            llm_setter(self.get_project_variables)
        self._project_manager = services.project_manager
        self._file_registry = services.file_registry
        self._user_mode_ctrl = services.user_mode_ctrl
        self._user_mode = self._user_mode_ctrl.get_user_mode()
        self._app_settings = services.app_settings
        self._mode_actions = {}
        self._model_status_success = None
        self._theme_actions = {}
        self._preview_theme_actions = {}
        self._feature_bindings = FeatureBindingRegistry()

    def _init_early_controllers(self):
        self._theme_ctrl = ThemeController(
            app_settings=self._app_settings, parent_window=self,
            autosave_schedule_fn=self._context.schedule_autosave,
        )
        self._context.bind_theme_controller(self._theme_ctrl)
        self._theme_ctrl.apply_theme_id(self._theme_ctrl.get_theme_id(), persist=False)
        margin_enabled, margin_em = self._theme_ctrl._load_preview_page_margin_settings()
        CanvasPreviewPane.apply_global_page_margin_settings(enabled=margin_enabled, em=margin_em)
        CanvasPreviewPane.apply_global_preview_theme(self._theme_ctrl._load_preview_theme_id())
        self._feedback_ctrl = FeedbackController(
            app_settings=self._app_settings,
            show_status=self._context.show_status,
            parent_window=self,
        )

    def _init_controllers(self):
        controllers = _setup_controllers(self._context)
        self._controllers = controllers
        self._autosave_ctrl = controllers.autosave_ctrl
        self._canvas_controller = controllers.canvas_controller
        self._knowledge_controller = controllers.knowledge_controller
        self._project_controller = controllers.project_controller
        self._chat_controller = controllers.chat_controller
        self._speech_ctrl = controllers.speech_ctrl
        self._zoom_ctrl = controllers.zoom_ctrl
        self._llm_tasks = controllers.llm_tasks_ctrl
        self._find_replace_ctrl = controllers.find_replace_ctrl

    # ── Initialisation helpers ────────────────────────────────────────

    def _init_window(self):
        self.setWindowTitle(
            "draft2craift — Document Retrieval Augmented File Tool 2 Collaboratively Revised AI Formatted Text"
        )
        self.resize(1440, 900)
        self.setDockNestingEnabled(True)
        self._apply_window_chrome_theme()

    def _apply_window_chrome_theme(self): self._theme_ctrl.apply_window_chrome()
    def _apply_status_label_styles(self): self._theme_ctrl.apply_status_label_styles()

    def _init_central(self):
        self.canvas = CanvasTabWidget()
        self.setCentralWidget(self.canvas)
        self.canvas.read_aloud_requested.connect(self._speak_draft_text)
        self.canvas.read_aloud_stop_requested.connect(self._stop_tts)

    def _init_docks(self):
        docks = _setup_docks(self._context, feedback_service=self._feedback_ctrl.service)
        self._docks = docks
        self.knowledge_dock = docks.knowledge_dock
        self.chat_dock = docks.chat_dock
        self.log_dock = docks.log_dock

    def _bind_feature_visibility(
        self,
        target: object,
        feature_key: str,
        default: bool = True,
    ) -> None:
        self._feature_bindings.bind_feature_visibility(
            target,
            feature_key,
            default=default,
            mode=self._user_mode,
        )

    def _apply_feature_visibility_bindings(self, mode: str) -> None:
        self._feature_bindings.apply_feature_visibility_bindings(mode)

    def _bind_feature_label(
        self,
        target: object,
        feature_key: str,
        default_text: str,
    ) -> None:
        self._feature_bindings.bind_feature_label(
            target,
            feature_key,
            default_text,
            mode=self._user_mode,
        )

    def _apply_feature_label_bindings(self, mode: str) -> None:
        self._feature_bindings.apply_feature_label_bindings(mode)

    def _init_global_shortcuts(self):
        _setup_shortcuts(self)

    def _init_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._glossary_feedback_bar = FeedbackBar(inline=True)
        self._glossary_feedback_bar.feedback_submitted.connect(self._on_status_feedback)
        sb.addPermanentWidget(self._glossary_feedback_bar)
        self._model_lbl = QLabel("No model loaded")
        sb.addPermanentWidget(self._model_lbl)
        self._backend_lbl = QLabel(f"backend: {self.rag_system.current_backend()}")
        sb.addPermanentWidget(self._backend_lbl)
        self._mode_lbl = QLabel(f"mode: {user_mode_label(self._user_mode)}")
        sb.addPermanentWidget(self._mode_lbl)
        self._bind_feature_visibility(self._mode_lbl, "window.status.mode_label", default=True)
        self._apply_window_chrome_theme()
        sb.showMessage("Ready")
        # Bind early so controllers_setup can access it when creating LLMSideTaskController.
        self._context.bind_glossary_feedback_bar(self._glossary_feedback_bar)

    def _connect_global_signals(self):
        _setup_global_signals(self)

    # ── Public delegations (theme, speech — called by ProjectManager) ──

    def get_theme_id(self) -> str: return self._theme_ctrl.get_theme_id()
    def apply_theme_id(self, theme_id: object, persist: bool = True): self._theme_ctrl.apply_theme_id(theme_id, persist=persist)
    def get_preview_page_margin_settings(self) -> dict: return self._theme_ctrl.get_preview_page_margin_settings()
    def apply_preview_page_margin_settings(self, raw: object): self._theme_ctrl.apply_preview_page_margin_settings(raw)
    def get_preview_theme_id(self) -> str: return self._theme_ctrl.get_preview_theme_id()
    def apply_preview_theme_id(self, theme_id: object, *, persist: bool = True): self._theme_ctrl.apply_preview_theme_id(theme_id, persist=persist)
    def get_speech_settings(self) -> dict: return self._speech_ctrl.get_speech_settings()
    def apply_speech_settings(self, raw: object): self._speech_ctrl.apply_speech_settings(raw)
    def get_project_variables(self) -> dict[str, str]:
        return dict(self._project_variables)
    def set_project_variables(self, raw: object, *, notify: bool = True) -> None:
        self._project_variables = normalize_project_variables(raw)
        if notify:
            bar = self.statusBar()
            if bar is not None:
                bar.showMessage("Project variables updated.", 3000)
    def resolve_project_variables_text(self, text: object) -> str:
        return resolve_project_variables_text(
            text,
            self._project_variables,
        ).text
    @property
    def dialog_manager(self) -> DialogWindowManager: return self._dialog_manager

    # ── LLM tasks ─────────────────────────────────────────────────────

    def _llm_side_task_active(self) -> bool: return self._llm_tasks.is_task_active()

    # ── Speech wrappers ───────────────────────────────────────────────

    def _speak_draft_text(self, text: str): self._speech_ctrl.speak_draft_text(text)
    def _speak_selection_text(self, text: str): self._speech_ctrl.speak_selection_text(text)
    def _speak_chat_text(self, text: str): self._speech_ctrl.speak_chat_text(text)
    def _speak_active_workspace_text(self): self._speech_ctrl.speak_active_workspace_text()
    def _stop_tts(self): self._speech_ctrl.stop_tts()
    def _start_whisper_dictation(self): self._speech_ctrl.start_whisper_dictation()
    def _stop_whisper_dictation(self): self._speech_ctrl.stop_whisper_dictation()
    def _open_speech_settings(self): self._speech_ctrl.open_speech_settings_dialog(self)
    def _on_dictation_running_changed(self, running: bool):
        self._speech_ctrl.apply_dictation_running_to_actions(
            running,
            start_action=getattr(self, "_action_start_dictation", None),
            stop_action=getattr(self, "_action_stop_dictation", None),
        )
    def _on_tts_speaking_changed(self, speaking: bool):
        self._speech_ctrl.apply_tts_speaking_state(speaking)

    # ── Autosave toggle ───────────────────────────────────────────────

    def _toggle_autosave_enabled(self, checked: bool):
        self._autosave_ctrl.toggle_enabled(checked)
    def _toggle_autosave_shortcut(self):
        self._autosave_ctrl.toggle_enabled_shortcut(
            action=getattr(self, "_action_autosave_toggle", None)
        )

    # ── Core slots ────────────────────────────────────────────────────

    def _refresh_context_bar(self): self._chat_controller.refresh_context_bar()
    def _update_loaded_menu(self): self._knowledge_controller.update_loaded_menu()
    def _resolve_imported_doc_content(self, name: str) -> str:
        return self._knowledge_controller.resolve_imported_doc_content(name)
    def _on_model_loaded(self, success: bool, message: str):
        self._chat_controller.on_model_loaded(
            success,
            message,
            set_model_label_text=self._model_lbl.setText,
            set_model_status_success=lambda value: setattr(self, "_model_status_success", bool(value)),
            apply_status_label_styles=self._apply_status_label_styles,
            rag_system=self.rag_system,
            llm_manager=self.llm_manager,
        )
    def _on_rag_status(self, message: str):
        self.statusBar().showMessage(message if message else "Ready")
    def _on_backend_changed(self, backend: str):
        self._backend_lbl.setText(f"backend: {backend}")
    def _on_rag_index_complete(self, count: int):
        self.statusBar().showMessage(
            f"RAG indexed {int(count)} document{'s' if int(count) != 1 else ''}",
            3000,
        )
    def _on_chat_history_content_changed(self):
        self._context.schedule_autosave(350)
    def _on_chat_dock_visibility_changed(self, _visible: bool):
        self._sync_model_controls_toggle_action()
    # ── Canvas / tabs / zoom ──────────────────────────────────────────

    def _select_next_draft_tab(self): self._canvas_controller.select_next_draft_tab()
    def _select_previous_draft_tab(self): self._canvas_controller.select_previous_draft_tab()
    def _set_canvas_view_mode_shortcut(self, mode: str):
        self._zoom_ctrl.set_canvas_view_mode(mode, canvas_controller=self._canvas_controller)
    def _increase_active_text_size(self): self._zoom_ctrl.increase_active()
    def _decrease_active_text_size(self): self._zoom_ctrl.decrease_active()
    def _reset_active_text_size(self): self._zoom_ctrl.reset_active()
    def _increase_preview_text_size(self): self._zoom_ctrl.increase_preview()
    def _decrease_preview_text_size(self): self._zoom_ctrl.decrease_preview()
    def _reset_preview_text_size(self): self._zoom_ctrl.reset_preview()
    def _export_active_canvas_document(self): self._canvas_controller.export_active_canvas_document()

    # ── Glossary ──────────────────────────────────────────────────────

    def _toggle_glossary_overlays(self, checked: bool): self._llm_tasks.toggle_glossary_overlays(checked)
    def _open_glossary_editor(self): self._llm_tasks.open_glossary_editor()
    def _on_glossary_saved_from_editor(self, count: int): self._llm_tasks.on_glossary_saved_from_editor(count)

    # ── LLM context menu actions ──────────────────────────────────────

    def _generate_glossary_from_context(self): self._llm_tasks.generate_glossary_from_context()
    def _generate_mindmap_from_context(self): self._llm_tasks.generate_mindmap_from_context()

    # ── Project, import, user mode ────────────────────────────────────

    def _save_project(self) -> bool: return self._project_controller.save_project()
    def _load_project(self) -> bool: return self._project_controller.load_project()
    def _export_project_archive(self) -> bool: return self._project_controller.export_project_archive()
    def _import_project_archive(self) -> bool: return self._project_controller.import_project_archive()
    def _open_project_variables(self): self._project_controller.open_project_variables_dialog()
    def _open_import_dialog(self): self._knowledge_controller.open_import_dialog(feedback_service=self._feedback_ctrl.service)

    def _import_dialog_busy(self) -> bool: return self._knowledge_controller.import_dialog_busy()

    def _rename_imported_document(self, old_name: str, new_name: str):
        self._knowledge_controller.rename_imported_document(old_name, new_name)
    def _remove_imported_document(self, display_name: str):
        self._knowledge_controller.remove_imported_document(display_name)

    @property
    def user_mode(self) -> str: return self._user_mode

    def _is_prompt_editor_allowed(self, mode: str | None = None) -> bool:
        return self._user_mode_ctrl.is_prompt_editor_allowed(mode)

    def set_user_mode(self, mode: str, notify: bool = True):
        self._user_mode_ctrl.apply_mode_to_window(
            mode=mode,
            root_widget=self,
            set_user_mode_state=lambda normalized: setattr(self, "_user_mode", normalized),
            mode_targets=(self.canvas, self.chat_dock, self.log_dock, self.knowledge_dock),
            dialogs=self._dialog_manager.dialogs(),
            action_edit_prompts=getattr(self, "_action_edit_prompts", None),
            log_toggle_action=getattr(self, "_log_toggle_action", None),
            log_dock=getattr(self, "log_dock", None),
            mode_actions=self._mode_actions,
            mode_label_widget=getattr(self, "_mode_lbl", None),
            show_status_message=self._context.show_status,
            schedule_full_autosave=lambda delay_ms: self._autosave_ctrl.schedule_full(delay_ms=delay_ms),
            log_warning=self.app_logger.warning,
            notify=notify,
            apply_feature_visibility_bindings=self._feature_bindings.apply_feature_visibility_bindings,
            apply_feature_label_bindings=self._feature_bindings.apply_feature_label_bindings,
        )

    # ── RAG, prompts, view actions ────────────────────────────────────

    def _open_rag_settings(self): self._knowledge_controller.open_rag_settings_dialog()
    def _try_sentence_transformers(self): self._knowledge_controller.try_load_sentence_transformers()
    def _edit_system_prompt(self): self._llm_tasks.edit_system_prompt()
    def _focus_model_panel(self):
        self._chat_controller.focus_model_panel(
            sync_toggle_action=self._sync_model_controls_toggle_action
        )
    def _reset_layout(self):
        self._chat_controller.reset_layout(
            add_dock_widget=self.addDockWidget,
            resize_docks=self.resizeDocks,
            sync_toggle_action=self._sync_model_controls_toggle_action,
        )
    def _set_model_controls_visible(self, visible: bool):
        self._chat_controller.set_model_controls_visible(
            visible,
            sync_toggle_action=self._sync_model_controls_toggle_action,
        )
    def _sync_model_controls_toggle_action(self):
        self._chat_controller.sync_model_controls_toggle_action(
            getattr(self, "_model_controls_toggle_action", None)
        )

    # ── Feedback, help, welcome, close ───────────────────────────────

    def _open_feedback_settings(self): self._feedback_ctrl.open_settings_dialog()
    def _open_feedback_stats(self): self._feedback_ctrl.open_stats_dialog()
    def _open_freeform_feedback(self): self._feedback_ctrl.open_freeform_dialog()
    def _on_status_feedback(self, sentiment: str, tags: list, note: str):
        self._feedback_ctrl.submit_status_feedback(sentiment, tags, note,
            glossary_feedback_bar=self._glossary_feedback_bar,
            payload=self._user_mode_ctrl.status_feedback_payload,
        )
    def _show_shortcuts(self): QMessageBox.information(self, "Keyboard Shortcuts", _SHORTCUTS_TEXT)
    def _show_about(self): QMessageBox.about(self, "About draft2craift", _ABOUT_TEXT)
    def _show_welcome(self): self._canvas_controller.show_welcome_text(_WELCOME_TEXT)

    def closeEvent(self, event):
        choice = QMessageBox.question(
            self, "Projekt speichern?",
            "Möchtest du das aktuelle Projekt vor dem Beenden speichern?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            event.ignore(); return
        if choice == QMessageBox.StandardButton.Save and not self._save_project():
            event.ignore(); return
        if self._llm_side_task_active():
            QMessageBox.information(self, "Bitte warten",
                "Es läuft noch eine Glossar/MindMap/Graph-Generierung.\nBitte warten, bis die Aufgabe abgeschlossen ist.")
            event.ignore(); return
        if self._import_dialog_busy():
            QMessageBox.information(
                self,
                "Bitte warten",
                "Der Import-Dialog verarbeitet noch Dateien.\n"
                "Bitte warten, bis Import, Analyse oder LLM-Optimierung abgeschlossen ist.",
            )
            event.ignore(); return
        self._theme_ctrl._persist_preview_page_margin_settings()
        self._theme_ctrl._persist_theme_id(self.get_theme_id())
        self._autosave_ctrl.flush_before_close()
        self._speech_ctrl.stop_all()
        self._dialog_manager.close_all()
        if not self.llm_manager.shutdown(stop_timeout_ms=3000, terminate_timeout_ms=2000):
            QMessageBox.warning(
                self,
                "Beenden abgebrochen",
                "LLM-Worker konnte nicht sicher beendet werden.\n"
                "Bitte laufende Aufgaben stoppen und erneut versuchen.",
            )
            event.ignore()
            return
        if not self._knowledge_controller.shutdown(stop_timeout_ms=5000, terminate_timeout_ms=2000):
            QMessageBox.warning(
                self,
                "Beenden abgebrochen",
                "RAG-Worker konnte nicht sicher beendet werden.\n"
                "Bitte laufende Aufgaben stoppen und erneut versuchen.",
            )
            event.ignore()
            return
        event.accept()
