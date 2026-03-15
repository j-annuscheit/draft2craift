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

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
)

from shared.domain.user_mode import (
    is_feature_visible,
    normalize_user_mode,
    resolve_feature_label,
    user_mode_label,
)
from shared.services.highlights.store import get_highlight_store
from studio.canvas.preview.pane import CanvasPreviewPane
from studio.canvas.tabs import CanvasTabWidget
from studio.controllers.feedback_ctrl import FeedbackController
from studio.controllers.theme_ctrl import ThemeController
from studio.feedback.bar import FeedbackBar
from studio.glossary.editor import GlossaryEditorDialog
from studio.importer.dialog import FileImportDialog
from studio.dialogs.window_manager import DialogWindowManager
from studio.profile_text_overrides import (
    apply_profile_text_overrides,
    install_qmessagebox_literal_overrides,
)
from studio.setup.controllers_setup import init_controllers as _setup_controllers
from studio.setup.docks_setup import init_docks as _setup_docks
from studio.setup.services_setup import init_services as _setup_services


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

    def __init__(self):
        super().__init__()
        install_qmessagebox_literal_overrides()
        self._dialog_manager = DialogWindowManager(self)
        self._init_services()
        self._init_early_controllers()
        self._init_window()
        self._init_central()
        # Status bar first: binds _glossary_feedback_bar to ctx before controllers run.
        self._init_statusbar()
        self._init_docks()
        self._init_controllers()
        self._context.validate()
        from studio.menubar import build_menubar
        self._knowledge_controller.set_loaded_menu(None)
        build_menubar(self)
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
        services = _setup_services(self)
        self._services = services
        self._context = services.context
        self.app_logger = services.app_logger
        self.rag_system = services.rag_system
        self.llm_manager = services.llm_manager
        self._project_manager = services.project_manager
        self._file_registry = services.file_registry
        self._user_mode = services.user_mode
        self._app_settings = services.app_settings
        self._mode_actions = {}
        self._model_status_success = None
        self._theme_actions = {}
        self._preview_theme_actions = {}
        self._feature_visibility_bindings: list[tuple[object, str, bool]] = []
        self._feature_label_bindings: list[tuple[object, str, str]] = []

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

    # Thin wrappers kept for backward-compat (menubar.py calls these via window ref)
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
        key = str(feature_key or "").strip()
        if not key:
            return
        self._feature_visibility_bindings.append((target, key, bool(default)))
        self._apply_feature_visibility_for_target(target, key, bool(default), self._user_mode)

    @staticmethod
    def _apply_feature_visibility_for_target(
        target: object,
        feature_key: str,
        default: bool,
        mode: str,
    ) -> None:
        setter = getattr(target, "setVisible", None)
        if not callable(setter):
            return
        setter(bool(is_feature_visible(mode, feature_key, default=default)))

    def _apply_feature_visibility_bindings(self, mode: str) -> None:
        for target, feature_key, default in list(self._feature_visibility_bindings):
            self._apply_feature_visibility_for_target(
                target,
                feature_key,
                bool(default),
                mode,
            )

    def _bind_feature_label(
        self,
        target: object,
        feature_key: str,
        default_text: str,
    ) -> None:
        key = str(feature_key or "").strip()
        if not key:
            return
        fallback = str(default_text or "")
        self._feature_label_bindings.append((target, key, fallback))
        self._apply_feature_label_for_target(target, key, fallback, self._user_mode)

    @staticmethod
    def _apply_feature_label_for_target(
        target: object,
        feature_key: str,
        default_text: str,
        mode: str,
    ) -> None:
        setter = getattr(target, "setText", None)
        if not callable(setter):
            return
        setter(resolve_feature_label(mode, feature_key, default_text))

    def _apply_feature_label_bindings(self, mode: str) -> None:
        for target, feature_key, default_text in list(self._feature_label_bindings):
            self._apply_feature_label_for_target(
                target,
                feature_key,
                default_text,
                mode,
            )

    def _propagate_user_mode_to_dialogs(self, mode: str) -> None:
        dialogs = getattr(self._dialog_manager, "dialogs", None)
        if not callable(dialogs):
            return
        for dialog in dialogs():
            setter = getattr(dialog, "set_user_mode", None)
            if not callable(setter):
                continue
            try:
                setter(mode)
            except Exception as exc:
                self.app_logger.warning(
                    "SYS",
                    f"Failed to apply user mode '{mode}' to dialog: {exc}",
                )
            apply_profile_text_overrides(dialog, mode)

    def _add_action(
        self,
        menu,
        label: str,
        shortcut: str,
        slot,
        *,
        visibility_key: str | None = None,
        visible_default: bool = True,
        label_key: str | None = None,
        label_default: str | None = None,
    ) -> QAction:
        act = QAction(label, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        if visibility_key:
            self._bind_feature_visibility(
                act,
                visibility_key,
                default=bool(visible_default),
            )
        key_for_label = str(label_key or visibility_key or "").strip()
        if key_for_label:
            self._bind_feature_label(
                act,
                key_for_label,
                str(label if label_default is None else label_default),
            )
        return act

    def _init_global_shortcuts(self):
        self._global_shortcuts: list[QShortcut] = []

        def _bind(seq: str, slot):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(Qt.ShortcutContext.ApplicationShortcut)
            s.activated.connect(slot)
            self._global_shortcuts.append(s)

        _bind("Ctrl+Tab", self._select_next_draft_tab)
        _bind("Ctrl+Shift+Tab", self._select_previous_draft_tab)
        _bind("Ctrl+F", lambda: self._find_replace_ctrl.open_dialog())
        _bind("Alt+1", lambda: self._set_canvas_view_mode_shortcut("markdown"))
        _bind("Alt+2", lambda: self._set_canvas_view_mode_shortcut("preview"))
        _bind("Alt+3", lambda: self._set_canvas_view_mode_shortcut("both"))
        _bind("Ctrl+Alt+S", self._toggle_autosave_shortcut)

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
        self.llm_manager.model_loaded.connect(self._on_model_loaded)
        self._speech_ctrl.tts_manager.speaking_changed.connect(self._on_tts_speaking_changed)
        self.rag_system.backend_changed.connect(self._on_backend_changed)
        self._backend_lbl.setText(f"backend: {self.rag_system.current_backend()}")
        self.knowledge_dock.rag_settings_requested.connect(self._knowledge_controller.open_rag_settings_dialog)
        self.knowledge_dock.rag_status_changed.connect(self._on_rag_status)
        self.knowledge_dock.document_remove_requested.connect(self._remove_imported_document)
        self.knowledge_dock.document_rename_requested.connect(self._rename_imported_document)
        self.knowledge_dock.rag_worker.index_complete.connect(self._on_rag_index_complete)
        self.chat_dock.tts_mode_changed.connect(self._speech_ctrl.on_chat_tts_mode_changed)
        try:
            self.chat_dock.history.content_changed.connect(self._on_chat_history_content_changed)
        except Exception as exc:
            self.app_logger.warning(
                "SYS",
                f"Failed to connect chat history autosave hook: {exc}",
            )
        self._on_tts_speaking_changed(self._speech_ctrl.tts_manager.is_speaking())
        self._speech_ctrl._apply_runtime_settings()
        self._ctx_timer = QTimer(self)
        self._ctx_timer.timeout.connect(self._refresh_context_bar)
        self._ctx_timer.start(1000)

    # ── Public delegations (theme, speech — called by ProjectManager) ──

    def get_theme_id(self) -> str: return self._theme_ctrl.get_theme_id()
    def apply_theme_id(self, theme_id: object, persist: bool = True): self._theme_ctrl.apply_theme_id(theme_id, persist=persist)
    def get_preview_page_margin_settings(self) -> dict: return self._theme_ctrl.get_preview_page_margin_settings()
    def apply_preview_page_margin_settings(self, raw: object): self._theme_ctrl.apply_preview_page_margin_settings(raw)
    def get_preview_theme_id(self) -> str: return self._theme_ctrl.get_preview_theme_id()
    def apply_preview_theme_id(self, theme_id: object, *, persist: bool = True): self._theme_ctrl.apply_preview_theme_id(theme_id, persist=persist)
    def get_speech_settings(self) -> dict: return self._speech_ctrl.get_speech_settings()
    def apply_speech_settings(self, raw: object): self._speech_ctrl.apply_speech_settings(raw)
    @property
    def dialog_manager(self) -> DialogWindowManager: return self._dialog_manager

    # ── LLM tasks ─────────────────────────────────────────────────────

    def _generate_glossary_from_llm_context(self, ctx: dict, done_cb=None) -> tuple[bool, str]:
        return self._llm_tasks.generate_glossary_from_llm_context(ctx, done_cb=done_cb)
    def _generate_mindmap_from_llm_context(self, ctx, query_raw="", mode_hint="auto", done_cb=None):
        return self._llm_tasks.generate_mindmap_from_llm_context(ctx, query_raw, mode_hint, done_cb=done_cb)
    def _llm_side_task_active(self) -> bool: return self._llm_tasks.is_task_active()

    # ── Speech wrappers ───────────────────────────────────────────────

    def _speak_draft_text(self, text: str): self._speech_ctrl.speak_draft_text(text)
    def _speak_chat_text(self, text: str): self._speech_ctrl.speak_chat_text(text)
    def _stop_tts(self): self._speech_ctrl.stop_tts()
    def _start_whisper_dictation(self): self._speech_ctrl.start_whisper_dictation()
    def _stop_whisper_dictation(self): self._speech_ctrl.stop_whisper_dictation()
    def _open_speech_settings(self): self._speech_ctrl.open_speech_settings_dialog(self)
    def _on_dictation_running_changed(self, running: bool):
        if hasattr(self, "_action_start_dictation"): self._action_start_dictation.setEnabled(not running)
        if hasattr(self, "_action_stop_dictation"): self._action_stop_dictation.setEnabled(running)
    def _on_tts_speaking_changed(self, speaking: bool):
        self.canvas.set_read_aloud_active(bool(speaking))
        self.chat_dock.set_read_aloud_active(bool(speaking))

    # ── Autosave toggle ───────────────────────────────────────────────

    def _toggle_autosave_enabled(self, checked: bool):
        enabled = bool(checked)
        if enabled == self._autosave_ctrl.enabled:
            return
        self._autosave_ctrl.enabled = enabled
        if enabled:
            self._autosave_ctrl.start_runtime()
            self._autosave_ctrl.schedule_full(delay_ms=150)
            self.statusBar().showMessage("Autosave aktiviert (lokales Autosave-Projekt).", 3000)
        else:
            self._autosave_ctrl.stop_runtime()
            self._autosave_ctrl._reset_workspace()
            self.statusBar().showMessage(
                "Autosave deaktiviert. Lokales Autosave-Projekt wurde entfernt.",
                3500,
            )
    def _toggle_autosave_shortcut(self):
        self._toggle_autosave_enabled(not bool(self._autosave_ctrl.enabled))
        action = getattr(self, "_action_autosave_toggle", None)
        if action is not None:
            blocked = action.blockSignals(True)
            action.setChecked(bool(self._autosave_ctrl.enabled))
            action.blockSignals(blocked)

    # ── Core slots ────────────────────────────────────────────────────

    def _build_llm_context(self) -> dict: return self._chat_controller.build_llm_context()
    def _refresh_context_bar(self): self._chat_controller.refresh_context_bar()
    def _update_loaded_menu(self):
        if hasattr(self, "_knowledge_controller"):
            self._knowledge_controller.update_loaded_menu()
    def _resolve_imported_doc_content(self, name: str) -> str:
        return self._knowledge_controller.resolve_imported_doc_content(name)
    def _on_model_loaded(self, success: bool, message: str):
        self._model_lbl.setText(message)
        self._model_status_success = bool(success)
        self._apply_status_label_styles()
        if success:
            self.rag_system.set_tfidf_query_expander(self.llm_manager.expand_query_tfidf_sync)
            self.rag_system.set_st_query_expander(self.llm_manager.expand_query_st_sync)
            self.rag_system.set_literal_query_expander(self.llm_manager.expand_query_literal_terms_sync)
            self.rag_system.set_rag_reranker(self.llm_manager.rerank_rag_results_sync)
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
    def _canvas_selection_text(self) -> str:
        return str(self.canvas.get_selected_text(allow_cached=True) or "")

    # ── Canvas / tabs / zoom ──────────────────────────────────────────

    def _select_next_draft_tab(self):
        tabs = self.canvas.tabs.tab_widget; count = int(tabs.count())
        if count > 1: tabs.setCurrentIndex((int(tabs.currentIndex()) + 1) % count)
    def _select_previous_draft_tab(self):
        tabs = self.canvas.tabs.tab_widget; count = int(tabs.count())
        if count > 1: tabs.setCurrentIndex((int(tabs.currentIndex()) - 1) % count)
    def _set_canvas_view_mode_shortcut(self, mode: str):
        self._zoom_ctrl.set_canvas_view_mode(mode, canvas_controller=self._canvas_controller)
    def _increase_active_text_size(self): self._zoom_ctrl.increase_active()
    def _decrease_active_text_size(self): self._zoom_ctrl.decrease_active()
    def _reset_active_text_size(self): self._zoom_ctrl.reset_active()
    def _increase_preview_text_size(self): self._zoom_ctrl.increase_preview()
    def _decrease_preview_text_size(self): self._zoom_ctrl.decrease_preview()
    def _reset_preview_text_size(self): self._zoom_ctrl.reset_preview()
    def _apply_llm_selection_rewrite(self, replacement, expected_original, preferred_span=None):
        return self.canvas.replace_selected_text(replacement, expected_original, preferred_span)
    def _open_fact_check_canvas(self, title_hint: str, content: str):
        title = f"Fakten: {str(title_hint or '').strip()}" if str(title_hint or "").strip() else "Faktencheck"
        try:
            self.canvas.tabs.add_tab(title=title, content=content, read_only=True)
            self.statusBar().showMessage("Faktencheck im Draft-Workspace geöffnet.", 4000)
            return True, title
        except Exception as exc:
            self.app_logger.error(
                "SYS",
                f"Failed to open fact-check canvas tab '{title}': {exc}",
            )
            return False, str(exc)
    def _export_active_canvas_document(self): self._canvas_controller.export_active_canvas_document()

    # ── Glossary ──────────────────────────────────────────────────────

    def _toggle_glossary_overlays(self, checked: bool):
        get_highlight_store().set_glossary_enabled(bool(checked))
        self._theme_ctrl.refresh_all_preview_overlays()
        self.statusBar().showMessage("Glossar-Overlay: AN" if checked else "Glossar-Overlay: AUS", 2500)
    def _open_glossary_editor(self):
        def _create() -> GlossaryEditorDialog:
            dialog = GlossaryEditorDialog(self, user_mode=self._user_mode)
            dialog.glossary_saved.connect(self._on_glossary_saved_from_editor)
            return dialog

        self._dialog_manager.show_dialog("glossary-editor", _create)
    def _on_glossary_saved_from_editor(self, count: int):
        self._theme_ctrl.refresh_all_preview_overlays()
        overlays_on = get_highlight_store().is_glossary_enabled()
        suffix = "" if overlays_on else " (Overlay aktuell AUS)."
        self.statusBar().showMessage(f"Glossar gespeichert: {int(count)} Begriffe{suffix}", 4500)

    # ── LLM context menu actions ──────────────────────────────────────

    def _generate_glossary_from_context(self):
        _err = lambda ok, info: (not ok) and QMessageBox.information(self, "Glossar", info)
        ok, info = self._generate_glossary_from_llm_context(self._build_llm_context(), done_cb=_err)
        if not ok: QMessageBox.information(self, "Glossar", info)
    def _generate_mindmap_from_context(self):
        title = resolve_feature_label(
            self._user_mode,
            "mindmap.generate.dialog.title",
            "MindMap/Graph/Chunk-MindMap generieren",
        )
        output_label = resolve_feature_label(
            self._user_mode,
            "mindmap.generate.dialog.output_format",
            "Ausgabeformat:",
        )
        ok_text = resolve_feature_label(
            self._user_mode,
            "mindmap.generate.dialog.button.ok",
            "OK",
        )
        cancel_text = resolve_feature_label(
            self._user_mode,
            "mindmap.generate.dialog.button.cancel",
            "Cancel",
        )
        mode_options = [
            (
                "chunkmap",
                resolve_feature_label(
                    self._user_mode,
                    "mindmap.generate.dialog.option.chunkmap",
                    "Chunk-MindMap",
                ),
            ),
            (
                "mindmap",
                resolve_feature_label(
                    self._user_mode,
                    "mindmap.generate.dialog.option.mindmap",
                    "MindMap",
                ),
            ),
            (
                "graph",
                resolve_feature_label(
                    self._user_mode,
                    "mindmap.generate.dialog.option.graph",
                    "Graph",
                ),
            ),
        ]

        mode_dialog = QInputDialog(self)
        mode_dialog.setWindowTitle(title)
        mode_dialog.setLabelText(output_label)
        mode_dialog.setComboBoxItems([label for _, label in mode_options])
        mode_dialog.setTextValue(mode_options[0][1])
        mode_dialog.setOkButtonText(ok_text)
        mode_dialog.setCancelButtonText(cancel_text)
        if mode_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected_mode_label = str(mode_dialog.textValue() or "")
        mode_hint = mode_options[0][0]
        for mode_name, mode_label in mode_options:
            if mode_label == selected_mode_label:
                mode_hint = mode_name
                break

        query_defaults = {
            "graph": resolve_feature_label(
                self._user_mode,
                "mindmap.generate.dialog.query_default.graph",
                "Welche zentralen Entitäten und Beziehungen sind im Kontext belegt?",
            ),
            "chunkmap": resolve_feature_label(
                self._user_mode,
                "mindmap.generate.dialog.query_default.chunkmap",
                "Wie ist der Kontext nach Überschriften und Chunks strukturiert?",
            ),
            "mindmap": resolve_feature_label(
                self._user_mode,
                "mindmap.generate.dialog.query_default.mindmap",
                "Welche zentralen Konzepte beantworten die Fragestellung im Kontext?",
            ),
        }
        query_label = resolve_feature_label(
            self._user_mode,
            "mindmap.generate.dialog.query_label",
            "Fragestellung (optional):",
        )

        query_dialog = QInputDialog(self)
        query_dialog.setWindowTitle(title)
        query_dialog.setInputMode(QInputDialog.InputMode.TextInput)
        query_dialog.setOption(
            QInputDialog.InputDialogOption.UsePlainTextEditForTextInput,
            True,
        )
        query_dialog.setLabelText(query_label)
        query_dialog.setTextValue(query_defaults.get(mode_hint, query_defaults["mindmap"]))
        query_dialog.setOkButtonText(ok_text)
        query_dialog.setCancelButtonText(cancel_text)
        if query_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        query_raw = query_dialog.textValue()

        _err2 = lambda ok2, info: (not ok2) and QMessageBox.information(self, "MindMap/Graph", info)
        ok, info = self._generate_mindmap_from_llm_context(
            self._build_llm_context(), str(query_raw or ""), mode_hint=mode_hint, done_cb=_err2)
        if not ok: QMessageBox.information(self, "MindMap/Graph", info)

    # ── Project, import, user mode ────────────────────────────────────

    def _save_project(self) -> bool: return self._project_controller.save_project()
    def _load_project(self) -> bool: return self._project_controller.load_project()
    def _export_project_archive(self) -> bool: return self._project_controller.export_project_archive()
    def _import_project_archive(self) -> bool: return self._project_controller.import_project_archive()
    def _open_import_dialog(self):
        def _create() -> FileImportDialog:
            dlg = FileImportDialog(
                self,
                user_mode=self._user_mode,
                feedback_service=self._feedback_ctrl.service,
            )
            dlg.files_imported.connect(self._knowledge_controller.on_files_imported)
            return dlg

        existing = self._dialog_manager.get("import-dialog")
        self._dialog_manager.show_dialog("import-dialog", _create)
        if existing is not None:
            self.statusBar().showMessage("Import-Fenster ist bereits geöffnet.", 2500)

    def _import_dialog_busy(self) -> bool:
        dlg = self._dialog_manager.get("import-dialog")
        if dlg is None:
            return False
        busy_check = getattr(dlg, "_has_running_background_worker", None)
        if not callable(busy_check):
            return False
        try:
            return bool(busy_check())
        except Exception:
            return False

    def _rename_imported_document(self, old_name: str, new_name: str):
        self._knowledge_controller.rename_imported_document(old_name, new_name)
    def _remove_imported_document(self, display_name: str):
        self._knowledge_controller.remove_imported_document(display_name)

    @property
    def user_mode(self) -> str: return self._user_mode

    def _is_prompt_editor_allowed(self, mode: str | None = None) -> bool:
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

    def set_user_mode(self, mode: str, notify: bool = True):
        normalized = normalize_user_mode(mode)
        self._user_mode = normalized
        self._context.user_mode = normalized
        if hasattr(self, "canvas"): self.canvas.set_user_mode(normalized)
        if hasattr(self, "chat_dock"): self.chat_dock.set_user_mode(normalized)
        if hasattr(self, "log_dock"): self.log_dock.set_user_mode(normalized)
        if hasattr(self, "knowledge_dock"): self.knowledge_dock.set_user_mode(normalized)
        self._apply_feature_visibility_bindings(normalized)
        self._apply_feature_label_bindings(normalized)
        self._propagate_user_mode_to_dialogs(normalized)
        apply_profile_text_overrides(self, normalized)
        if hasattr(self, "_action_edit_prompts"):
            self._action_edit_prompts.setVisible(bool(
                self._is_prompt_editor_allowed(normalized)
                and is_feature_visible(
                    normalized,
                    "menu.ai.edit_prompts",
                    default=True,
                )
            ))
        if hasattr(self, "_log_toggle_action"):
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
            self._log_toggle_action.setVisible(show_log)
            if not show_log and hasattr(self, "log_dock"): self.log_dock.hide()
        for mode_key, act in self._mode_actions.items():
            blocked = act.blockSignals(True); act.setChecked(mode_key == normalized); act.blockSignals(blocked)
        if hasattr(self, "_mode_lbl"): self._mode_lbl.setText(f"mode: {user_mode_label(normalized)}")
        if notify and self.statusBar():
            self.statusBar().showMessage(f"Nutzermodus: {user_mode_label(normalized)}", 2500)
            self._autosave_ctrl.schedule_full(delay_ms=500)

    # ── RAG, prompts, view actions ────────────────────────────────────

    def _open_rag_settings(self): self._knowledge_controller.open_rag_settings_dialog()
    def _try_sentence_transformers(self): self._knowledge_controller.try_load_sentence_transformers()
    def _edit_system_prompt(self):
        if not self._is_prompt_editor_allowed():
            QMessageBox.information(self, "Prompt Editor",
                "Im Einfach-Modus ist der Prompt-Editor ausgeblendet.\nWechsle zu Plus oder Experte.")
            return
        from studio.dialogs.prompt_editor import PromptEditorDialog
        self._dialog_manager.show_dialog(
            "prompt-editor",
            lambda: PromptEditorDialog(self.llm_manager, self._user_mode, parent=self),
            on_accept=lambda _dlg: self._autosave_ctrl.schedule_full(delay_ms=300),
        )
    def _focus_model_panel(self):
        self.chat_dock.show(); self.chat_dock.raise_()
        self.chat_dock.set_model_panel_visible(True); self._sync_model_controls_toggle_action()
    def _reset_layout(self):
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.knowledge_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.chat_dock)
        self.knowledge_dock.show(); self.chat_dock.show()
        self.chat_dock.set_model_panel_visible(True)
        self.resizeDocks([self.knowledge_dock, self.chat_dock], [340, 380], Qt.Orientation.Horizontal)
        self._sync_model_controls_toggle_action()
    def _set_model_controls_visible(self, visible: bool):
        if bool(visible): self.chat_dock.show(); self.chat_dock.raise_()
        self.chat_dock.set_model_panel_visible(bool(visible)); self._sync_model_controls_toggle_action()
    def _sync_model_controls_toggle_action(self):
        action = getattr(self, "_model_controls_toggle_action", None)
        if action is None or not hasattr(self, "chat_dock"): return
        checked = bool(self.chat_dock.isVisible() and self.chat_dock.is_model_panel_visible())
        blocked = action.blockSignals(True); action.setChecked(checked); action.blockSignals(blocked)

    # ── Feedback, help, welcome, close ───────────────────────────────

    def _open_feedback_settings(self): self._feedback_ctrl.open_settings_dialog()
    def _open_feedback_stats(self): self._feedback_ctrl.open_stats_dialog()
    def _open_freeform_feedback(self): self._feedback_ctrl.open_freeform_dialog()
    def _on_status_feedback(self, sentiment: str, tags: list, note: str):
        self._feedback_ctrl.submit_status_feedback(sentiment, tags, note,
            glossary_feedback_bar=self._glossary_feedback_bar,
            payload=self._context.status_feedback_payload,
        )
    def _show_shortcuts(self): QMessageBox.information(self, "Keyboard Shortcuts", _SHORTCUTS_TEXT)
    def _show_about(self): QMessageBox.about(self, "About draft2craift", _ABOUT_TEXT)
    def _show_welcome(self):
        panel = self.canvas.tabs.current_panel()
        if panel: panel.editor.setPlainText(_WELCOME_TEXT)

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
        llm_worker = self.llm_manager.worker
        if llm_worker.isRunning():
            llm_worker.request_stop()
            if not llm_worker.wait(3000):
                self.app_logger.warning(
                    "SYS",
                    "LLM worker did not stop within 3000ms; terminating thread.",
                )
                llm_worker.terminate()
                if not llm_worker.wait(2000):
                    self.app_logger.error(
                        "SYS",
                        "LLM worker did not terminate within 2000ms; aborting shutdown.",
                    )
                    QMessageBox.warning(
                        self,
                        "Beenden abgebrochen",
                        "LLM-Worker konnte nicht sicher beendet werden.\n"
                        "Bitte laufende Aufgaben stoppen und erneut versuchen.",
                    )
                    event.ignore()
                    return
        rag_worker = self.knowledge_dock.rag_worker
        if not rag_worker.stop_and_wait(5000):
            self.app_logger.warning(
                "SYS",
                "RAG worker did not stop within 5000ms; terminating thread.",
            )
            rag_worker.terminate()
            if not rag_worker.wait(2000):
                self.app_logger.error(
                    "SYS",
                    "RAG worker did not terminate within 2000ms; aborting shutdown.",
                )
                QMessageBox.warning(
                    self,
                    "Beenden abgebrochen",
                    "RAG-Worker konnte nicht sicher beendet werden.\n"
                    "Bitte laufende Aufgaben stoppen und erneut versuchen.",
                )
                event.ignore()
                return
        event.accept()
