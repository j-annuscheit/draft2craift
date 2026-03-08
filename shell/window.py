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

import json
import os
from pathlib import Path
import shutil
import time
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QFileDialog,
    QStatusBar, QMessageBox, QDialog, QDialogButtonBox,
    QTextEdit, QApplication, QMenu, QInputDialog, QCheckBox, QLineEdit,
)
from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Qt, Signal
from PySide6.QtGui import (
    QAction, QActionGroup, QKeySequence, QTextCursor, QTextDocument, QShortcut,
)

from widgets.markdown.editor import MarkdownEditor
from services.llm.manager import LLMManager
from services.rag.system import RAGSystem
from features.knowledge.dock import KnowledgeDock
from features.chat.dock import ChatDock
from features.importer.facade import FileImportDialog
from features.knowledge.rag_settings_dialog import RAGSettingsDialog
from features.speech import SpeechSettingsDialog
from shell.logging import AppLogger, LogDock
from services.project.manager import ProjectManager
from services.speech import (
    SpeechSettings,
    TextToSpeechManager,
    WhisperDictationWorker,
)
from services.highlights import get_highlight_store
from core.user_modes import (
    USER_MODE_ORDER,
    USER_MODE_PLUS,
    USER_MODE_SIMPLE,
    USER_MODE_LABELS,
    normalize_user_mode,
)
from features.canvas.widget import CanvasTabWidget
from features.canvas.preview import CanvasPreviewPane
from features.feedback import (
    FeedbackFreeformDialog,
    FeedbackSettingsDialog,
    FeedbackStatsDialog,
)
from features.feedback.bar import FeedbackBar
from features.glossary import GlossaryEditorDialog
from services.feedback.service import FeedbackService
from services.feedback.settings import FeedbackSettings
from widgets.markdown.split_view import MarkdownSplitPanel
from shell.theme import (
    apply_theme,
    available_themes,
    normalize_theme_id,
    theme_tokens,
)

# ── Main Window ────────────────────────────────────────────────────────────────


class _LLMSideTaskWorker(QObject):
    """Runs non-streaming LLM side tasks in a background thread."""

    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, llm_manager: LLMManager, *, task: str, payload: dict):
        super().__init__()
        self._llm_manager = llm_manager
        self._task = str(task or "").strip().lower()
        self._payload = dict(payload or {})

    def run(self):
        try:
            if self._task == "glossary":
                context_text = str(self._payload.get("context_text", "") or "")
                max_terms = int(self._payload.get("max_terms", 32) or 32)
                entries, meta = self._llm_manager.generate_glossary_sync(
                    context_text=context_text,
                    max_terms=max_terms,
                )
                self.finished.emit(
                    {
                        "task": "glossary",
                        "context_text": context_text,
                        "entries": entries,
                        "meta": meta,
                    }
                )
                return

            if self._task == "mindmap":
                context_text = str(self._payload.get("context_text", "") or "")
                query = str(self._payload.get("query", "") or "")
                mode = str(self._payload.get("mode", "mindmap") or "mindmap")
                max_nodes = int(self._payload.get("max_nodes", 32) or 32)
                chunking_strategy = str(
                    self._payload.get("chunking_strategy", "sliding_window")
                    or "sliding_window"
                )
                chunk_size = int(self._payload.get("chunk_size", 900) or 900)
                chunk_overlap = int(self._payload.get("chunk_overlap", 160) or 160)
                markdown, meta = self._llm_manager.generate_mindmap_sync(
                    context_text=context_text,
                    query=query,
                    mode=mode,
                    max_nodes=max_nodes,
                    chunking_strategy=chunking_strategy,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                self.finished.emit(
                    {
                        "task": "mindmap",
                        "context_text": context_text,
                        "query": query,
                        "mode": mode,
                        "markdown": markdown,
                        "meta": meta,
                    }
                )
                return

            self.failed.emit(f"Unbekannte Hintergrundaufgabe: {self._task}")
        except Exception as exc:
            self.failed.emit(str(exc))


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

    _AUTOSAVE_SETTING_KEY = "autosave/enabled"
    _THEME_SETTING_KEY = "ui/theme"
    _PREVIEW_MARGIN_ENABLED_KEY = "preview/page_margin_enabled"
    _PREVIEW_MARGIN_EM_KEY = "preview/page_margin_em"
    _PREVIEW_THEME_KEY = "preview/markdown_theme"

    def __init__(self):
        super().__init__()

        # Core services
        self.app_logger  = AppLogger(enabled=True)
        self.rag_system  = RAGSystem(logger=self.app_logger)
        self.llm_manager = LLMManager(logger=self.app_logger)

        # Runtime state
        # Registry of imported files: display_name → (orig_path, markdown)
        self._file_registry: dict[str, tuple[str, str]] = {}
        self._project_manager = ProjectManager()
        self._user_mode = USER_MODE_PLUS
        self._mode_actions: dict[str, QAction] = {}
        self._dictation_worker: WhisperDictationWorker | None = None
        self._dictation_target_panel: QWidget | None = None
        self._speech_settings = SpeechSettings()
        self._tts_manager = TextToSpeechManager(self)
        self._app_settings = QSettings("draft2craift", "draft2craift")
        self._theme_id = self._load_theme_id()
        self._theme_actions: dict[str, QAction] = {}
        self._preview_theme_actions: dict[str, QAction] = {}
        self._model_status_success: bool | None = None
        self.apply_theme_id(self._theme_id, persist=False)
        preview_margin_enabled, preview_margin_em = (
            self._load_preview_page_margin_settings()
        )
        CanvasPreviewPane.apply_global_page_margin_settings(
            enabled=preview_margin_enabled,
            em=preview_margin_em,
        )
        CanvasPreviewPane.apply_global_preview_theme(
            self._load_preview_theme_id()
        )
        self._feedback_settings = self._load_feedback_settings()
        self._feedback_service = FeedbackService(self._feedback_settings)
        self._status_feedback_payload: dict[str, object] = {}
        self._autosave_enabled = self._load_autosave_enabled()
        self._autosave_dir = self._resolve_autosave_dir()
        self._autosave_suspended = False
        self._autosave_runtime_connected = False
        self._autosave_editor_hooks: set[int] = set()
        self._autosave_pending_editor: MarkdownEditor | None = None
        self._autosave_last_tab_count = 0
        self._autosave_last_signature = ""
        self._autosave_last_hint_ts = 0.0
        self._llm_side_task_thread: QThread | None = None
        self._llm_side_task_worker: _LLMSideTaskWorker | None = None
        self._llm_side_task_kind = ""
        self._llm_side_task_done_cb = None

        self._autosave_draft_timer = QTimer(self)
        self._autosave_draft_timer.setSingleShot(True)
        self._autosave_draft_timer.timeout.connect(self._autosave_flush_draft)

        self._autosave_full_timer = QTimer(self)
        self._autosave_full_timer.setSingleShot(True)
        self._autosave_full_timer.timeout.connect(self._autosave_flush_full)

        self._autosave_watch_timer = QTimer(self)
        self._autosave_watch_timer.setSingleShot(False)
        self._autosave_watch_timer.timeout.connect(self._autosave_watch_structure)

        self._init_window()
        self._init_central()
        self._init_docks()
        self._init_menubar()
        self._init_statusbar()
        self._init_global_shortcuts()
        self._connect_global_signals()
        self._find_replace_dialog: QDialog | None = None
        self._find_editor: MarkdownEditor | None = None
        self._find_target: dict | None = None
        self._find_read_only_editor: MarkdownEditor | None = None
        self.set_user_mode(self._user_mode, notify=False)
        restored_from_tmp = self._maybe_restore_autosave_project()
        if not restored_from_tmp:
            self._show_welcome()
        self._autosave_start_runtime()
        if self._autosave_enabled and not restored_from_tmp:
            self._autosave_schedule_full(delay_ms=200)
        self.app_logger.info(
            "SYS",
            f"draft2craift started  |  RAG backend: {self.rag_system.current_backend()}",
        )

        # Periodic context-bar update
        self._ctx_timer = QTimer(self)
        self._ctx_timer.timeout.connect(self._refresh_context_bar)
        self._ctx_timer.start(1000)

    # ──────────────────────────────────────────────────────────────────
    # Initialisation helpers
    # ──────────────────────────────────────────────────────────────────

    def _init_window(self):
        self.setWindowTitle(
            "draft2craift — Document Retrieval Augmented File Tool 2 Collaboratively Revised AI Formatted Text"
        )
        self.resize(1440, 900)
        self.setDockNestingEnabled(True)
        self._apply_window_chrome_theme()

    def _apply_window_chrome_theme(self):
        tokens = theme_tokens(self.get_theme_id())
        self.setStyleSheet(
            f"""
            QMainWindow {{
                background: {tokens['base_bg']};
            }}
            QMainWindow::separator {{
                background: {tokens['border']};
                width: 3px;
                height: 3px;
            }}
            QMainWindow::separator:hover {{
                background: {tokens['accent']};
            }}
            """
        )

        bar = self.menuBar()
        if bar is not None:
            bar.setStyleSheet(
                f"""
                QMenuBar {{
                    background: {tokens['menu_bg']};
                    color: {tokens['text']};
                    border-bottom: 1px solid {tokens['border_strong']};
                    font-size: 11px;
                }}
                QMenuBar::item:selected {{
                    background: {tokens['menu_item_hover']};
                }}
                QMenu {{
                    background: {tokens['panel_alt_bg']};
                    color: {tokens['text']};
                    border: 1px solid {tokens['border']};
                    font-size: 11px;
                }}
                QMenu::item:selected {{
                    background: {tokens['menu_item_hover']};
                }}
                QMenu::separator {{
                    background: {tokens['border']};
                    height: 1px;
                    margin: 2px 0;
                }}
                """
            )

        sb = self.findChild(QStatusBar)
        if isinstance(sb, QStatusBar):
            sb.setStyleSheet(
                f"""
                QStatusBar {{
                    background: {tokens['menu_bg']};
                    color: {tokens['muted_text']};
                    border-top: 1px solid {tokens['border_strong']};
                    font-size: 10px;
                }}
                """
            )

        self._apply_status_label_styles()

    def _apply_status_label_styles(self):
        tokens = theme_tokens(self.get_theme_id())
        model_color = (
            tokens["success"]
            if self._model_status_success is True
            else tokens["danger"]
        )
        muted_style = f"color: {tokens['muted_text']}; padding: 0 8px;"

        if hasattr(self, "_model_lbl"):
            self._model_lbl.setStyleSheet(f"color: {model_color}; padding: 0 8px;")
        if hasattr(self, "_backend_lbl"):
            self._backend_lbl.setStyleSheet(muted_style)
        if hasattr(self, "_mode_lbl"):
            self._mode_lbl.setStyleSheet(muted_style)

    def _init_central(self):
        self.canvas = CanvasTabWidget()
        self.setCentralWidget(self.canvas)
        self.canvas.read_aloud_requested.connect(self._speak_draft_text)
        self.canvas.read_aloud_stop_requested.connect(self._stop_tts)

    def _init_docks(self):
        # ── Knowledge Dock (left)
        self.knowledge_dock = KnowledgeDock(self.rag_system, self)
        self.knowledge_dock.setObjectName("knowledge_dock")
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.knowledge_dock)

        # ── Chat Dock (right)
        self.chat_dock = ChatDock(self.llm_manager, self)
        self.chat_dock.setObjectName("chat_dock")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.chat_dock)

        # Inject context getter
        self.chat_dock.set_context_getter(self._build_llm_context)
        self.chat_dock.set_canvas_selection_getter(
            self._get_canvas_selected_text_for_context
        )
        self.chat_dock.set_selection_apply_handler(self._apply_llm_selection_rewrite)
        self.chat_dock.set_fact_result_handler(self._open_fact_check_canvas)
        self.chat_dock.set_glossary_request_handler(
            self._generate_glossary_from_llm_context
        )
        self.chat_dock.set_mindmap_request_handler(
            self._generate_mindmap_from_llm_context
        )
        self.chat_dock.set_feedback_service(self._feedback_service)
        self.chat_dock.read_aloud_requested.connect(self._speak_chat_text)
        self.chat_dock.read_aloud_stop_requested.connect(self._stop_tts)
        self.chat_dock.tts_mode_changed.connect(self._on_chat_tts_mode_changed)
        self.chat_dock.visibilityChanged.connect(
            lambda _visible: self._sync_model_controls_toggle_action()
        )
        self.knowledge_dock.set_feedback_service(self._feedback_service)

        # ── Debug Log Dock (bottom, hidden by default)
        self.log_dock = LogDock(self.app_logger, self)
        self.log_dock.setObjectName("log_dock")
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()

        # Initial dock widths
        self.resizeDocks(
            [self.knowledge_dock, self.chat_dock],
            [340, 380],
            Qt.Orientation.Horizontal,
        )

    def _get_canvas_selected_text_for_context(self) -> str:
        return str(self.canvas.get_selected_text(allow_cached=True) or "")

    def _init_menubar(self):
        bar = self.menuBar()

        # File
        file_menu = bar.addMenu("&File")
        self._add_action(file_menu, "New Draft Tab", "Ctrl+N", lambda: self.canvas.tabs.add_tab())
        self._add_action(file_menu, "Open File…",     "Ctrl+O", self.canvas.open_file)
        self._add_action(file_menu, "Save",           "Ctrl+S", self.canvas.save_current)
        self._add_action(file_menu, "Export…", "", self.canvas.export_document)
        file_menu.addSeparator()
        self._add_action(file_menu, "Save Project…", "Ctrl+Shift+S", self._save_project)
        self._add_action(file_menu, "Load Project…", "Ctrl+Shift+O", self._load_project)
        file_menu.addSeparator()
        self._add_action(file_menu, "Import Files…",  "Ctrl+I", self._open_import_dialog)
        file_menu.addSeparator()
        self._loaded_menu = file_menu.addMenu("Loaded Documents")
        self._loaded_menu.setEnabled(False)   # disabled until something is imported
        file_menu.addSeparator()
        self._add_action(file_menu, "Quit", "Ctrl+Q", self.close)

        # View
        view_menu = bar.addMenu("&View")
        tk = self.knowledge_dock.toggleViewAction()
        tk.setText("Knowledge Dock")
        tk.setShortcut(QKeySequence("Ctrl+1"))
        tk.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        tc = self.chat_dock.toggleViewAction()
        tc.setText("AI Chat Dock")
        tc.setShortcut(QKeySequence("Ctrl+2"))
        tc.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        tl = self.log_dock.toggleViewAction()
        tl.setText("Debug Log")
        tl.setShortcut(QKeySequence("Ctrl+3"))
        tl.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self._log_toggle_action = tl
        view_menu.addAction(tk)
        view_menu.addAction(tc)
        view_menu.addAction(tl)
        self._model_controls_toggle_action = QAction(
            "Model Load + Generation",
            self,
        )
        self._model_controls_toggle_action.setCheckable(True)
        self._model_controls_toggle_action.setChecked(True)
        self._model_controls_toggle_action.setShortcut(QKeySequence("Ctrl+4"))
        self._model_controls_toggle_action.setShortcutContext(
            Qt.ShortcutContext.ApplicationShortcut
        )
        self._model_controls_toggle_action.toggled.connect(
            self._set_model_controls_visible
        )
        view_menu.addAction(self._model_controls_toggle_action)
        self._sync_model_controls_toggle_action()
        mode_menu = view_menu.addMenu("Nutzermodus")
        self._mode_group = QActionGroup(self)
        self._mode_group.setExclusive(True)
        for mode in USER_MODE_ORDER:
            act = QAction(USER_MODE_LABELS[mode], self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked=False, m=mode: self.set_user_mode(m))
            self._mode_group.addAction(act)
            mode_menu.addAction(act)
            self._mode_actions[mode] = act
        theme_menu = view_menu.addMenu("Theme")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        for theme_id, label in available_themes():
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(
                lambda _checked=False, t=theme_id: self.apply_theme_id(t, persist=True)
            )
            self._theme_group.addAction(act)
            theme_menu.addAction(act)
            self._theme_actions[theme_id] = act
        self._sync_theme_actions()
        view_menu.addSeparator()
        text_size_menu = view_menu.addMenu("Textgröße")
        self._add_action(text_size_menu, "Aktive Ansicht größer", "Ctrl+=", self._increase_active_text_size)
        self._add_action(text_size_menu, "Aktive Ansicht kleiner", "Ctrl+-", self._decrease_active_text_size)
        self._add_action(text_size_menu, "Aktive Ansicht Standard (100%)", "Ctrl+0", self._reset_active_text_size)
        text_size_menu.addSeparator()
        self._add_action(text_size_menu, "HTML-Vorschau größer", "", self._increase_preview_text_size)
        self._add_action(text_size_menu, "HTML-Vorschau kleiner", "", self._decrease_preview_text_size)
        self._add_action(text_size_menu, "HTML-Vorschau Standard (100%)", "", self._reset_preview_text_size)
        page_margin_menu = view_menu.addMenu("Seitenrand")
        self._action_page_margin_enabled = QAction("Seitenrand aktiv", self)
        self._action_page_margin_enabled.setCheckable(True)
        self._action_page_margin_enabled.triggered.connect(
            self._toggle_preview_page_margin_enabled
        )
        page_margin_menu.addAction(self._action_page_margin_enabled)
        page_margin_menu.addSeparator()
        self._page_margin_group = QActionGroup(self)
        self._page_margin_group.setExclusive(True)
        self._page_margin_actions: list[tuple[float, QAction]] = []
        for label, em_value in CanvasPreviewPane._PAGE_MARGIN_PRESETS:
            action = QAction(str(label), self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, em=float(em_value): self._set_preview_page_margin_preset(em)
            )
            self._page_margin_group.addAction(action)
            page_margin_menu.addAction(action)
            self._page_margin_actions.append((float(em_value), action))
        self._sync_preview_page_margin_actions()
        preview_theme_menu = view_menu.addMenu("HTML-Stil")
        self._preview_theme_group = QActionGroup(self)
        self._preview_theme_group.setExclusive(True)
        for theme_id, label in CanvasPreviewPane.preview_theme_options():
            action = QAction(str(label), self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, t=theme_id: self.apply_preview_theme_id(t)
            )
            self._preview_theme_group.addAction(action)
            preview_theme_menu.addAction(action)
            self._preview_theme_actions[str(theme_id)] = action
        self._sync_preview_theme_actions()
        view_menu.addSeparator()
        self._action_glossary_overlay = QAction("Glossar-Overlay anzeigen", self)
        self._action_glossary_overlay.setCheckable(True)
        self._action_glossary_overlay.setChecked(
            get_highlight_store().is_glossary_enabled()
        )
        self._action_glossary_overlay.triggered.connect(
            self._toggle_glossary_overlays
        )
        view_menu.addAction(self._action_glossary_overlay)
        self._add_action(
            view_menu,
            "Glossar verwalten…",
            "",
            self._open_glossary_editor,
        )
        view_menu.addSeparator()
        self._add_action(view_menu, "Reset Layout", "", self._reset_layout)

        # Einstellungen
        settings_menu = bar.addMenu("&Einstellungen")
        self._action_autosave_toggle = QAction(
            "Autosave im tmp-Projekt aktivieren",
            self,
        )
        self._action_autosave_toggle.setCheckable(True)
        self._action_autosave_toggle.setChecked(self._autosave_enabled)
        self._action_autosave_toggle.triggered.connect(
            self._toggle_autosave_enabled
        )
        settings_menu.addAction(self._action_autosave_toggle)
        settings_menu.addSeparator()
        self._add_action(
            settings_menu,
            "Feedback geben…",
            "",
            self._open_freeform_feedback,
        )
        self._add_action(
            settings_menu,
            "Feedback Statistik…",
            "",
            self._open_feedback_stats,
        )
        settings_menu.addSeparator()
        self._add_action(
            settings_menu,
            "Feedback Einstellungen…",
            "",
            self._open_feedback_settings,
        )

        # AI
        ai_menu = bar.addMenu("&AI")
        self._add_action(ai_menu, "Load GGUF Model…",       "",          self._focus_model_panel)
        self._add_action(ai_menu, "Stop Generation",         "Ctrl+.",    self.llm_manager.stop)
        ai_menu.addSeparator()
        self._action_edit_prompts = self._add_action(ai_menu, "Edit Prompts…", "", self._edit_system_prompt)
        self._add_action(
            ai_menu,
            "Generate Glossary From Context",
            "",
            self._generate_glossary_from_context,
        )
        self._add_action(
            ai_menu,
            "Generate MindMap/Graph From Context",
            "",
            self._generate_mindmap_from_context,
        )
        ai_menu.addSeparator()
        self._add_action(ai_menu, "Enable sentence-transformers RAG", "", self._try_sentence_transformers)
        self._add_action(ai_menu, "RAG Settings…",           "",          self._open_rag_settings)
        self._add_action(ai_menu, "Speech Settings…", "", self._open_speech_settings)
        ai_menu.addSeparator()
        self._action_start_dictation = self._add_action(
            ai_menu,
            "Start Whisper Dictation",
            "",
            self._start_whisper_dictation,
        )
        self._action_stop_dictation = self._add_action(
            ai_menu,
            "Stop Whisper Dictation",
            "",
            self._stop_whisper_dictation,
        )
        self._action_stop_dictation.setEnabled(False)

        # Help
        help_menu = bar.addMenu("&Help")
        self._add_action(help_menu, "Keyboard Shortcuts",   "",           self._show_shortcuts)
        self._add_action(help_menu, "About draft2craift",  "",           self._show_about)
        self._apply_window_chrome_theme()

    def _add_action(self, menu, label: str, shortcut: str, slot) -> QAction:
        act = QAction(label, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _init_global_shortcuts(self):
        self._global_shortcuts: list[QShortcut] = []

        def _bind(sequence: str, slot):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(slot)
            self._global_shortcuts.append(shortcut)

        _bind("Ctrl+Tab", self._select_next_draft_tab)
        _bind("Ctrl+Shift+Tab", self._select_previous_draft_tab)
        _bind("Ctrl+F", self._open_find_replace_dialog)
        _bind("Alt+1", lambda: self._set_canvas_view_mode_shortcut("markdown"))
        _bind("Alt+2", lambda: self._set_canvas_view_mode_shortcut("preview"))
        _bind("Alt+3", lambda: self._set_canvas_view_mode_shortcut("both"))
        _bind("Ctrl+Alt+S", self._toggle_autosave_shortcut)

    def _init_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)

        # Inline FeedbackBar für Glossar (rechts, versteckt bis nach Generierung)
        self._glossary_feedback_bar = FeedbackBar(inline=True)
        self._glossary_feedback_bar.feedback_submitted.connect(
            self._on_status_feedback
        )
        sb.addPermanentWidget(self._glossary_feedback_bar)

        self._model_lbl = QLabel("No model loaded")
        sb.addPermanentWidget(self._model_lbl)

        self._backend_lbl = QLabel(f"backend: {self.rag_system.current_backend()}")
        sb.addPermanentWidget(self._backend_lbl)

        self._mode_lbl = QLabel(f"mode: {USER_MODE_LABELS[self._user_mode]}")
        sb.addPermanentWidget(self._mode_lbl)

        self._apply_window_chrome_theme()
        sb.showMessage("Ready")

    def _connect_global_signals(self):
        self.llm_manager.model_loaded.connect(self._on_model_loaded)
        self._tts_manager.status.connect(self._on_tts_status)
        self._tts_manager.error.connect(self._on_tts_error)
        self._tts_manager.speaking_changed.connect(self._on_tts_speaking_changed)
        self.rag_system.backend_changed.connect(
            lambda b: self._backend_lbl.setText(f"backend: {b}")
        )
        # Keep the status bar backend label in sync with current_backend() too
        self._backend_lbl.setText(f"backend: {self.rag_system.current_backend()}")
        self.knowledge_dock.rag_settings_requested.connect(self._open_rag_settings)
        self.knowledge_dock.rag_status_changed.connect(self._on_rag_status)
        self.knowledge_dock.document_remove_requested.connect(self._remove_imported_document)
        self.knowledge_dock.document_rename_requested.connect(self._rename_imported_document)
        self.knowledge_dock.rag_worker.index_complete.connect(
            lambda n: self.statusBar().showMessage(
                f"RAG indexed {n} document{'s' if n != 1 else ''}", 3000
            )
        )
        try:
            self.chat_dock.history.content_changed.connect(
                lambda: self._autosave_schedule_full(delay_ms=350)
            )
        except Exception:
            pass
        self._on_tts_speaking_changed(self._tts_manager.is_speaking())
        self._apply_speech_runtime_settings()

    # ──────────────────────────────────────────────────────────────────
    # Autosave (tmp project)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _as_bool(raw: object, default: bool) -> bool:
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return bool(default)
        text = str(raw).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    def _load_autosave_enabled(self) -> bool:
        raw = self._app_settings.value(self._AUTOSAVE_SETTING_KEY, True)
        return self._as_bool(raw, True)

    def _load_theme_id(self) -> str:
        raw = self._app_settings.value(self._THEME_SETTING_KEY, "dark")
        return normalize_theme_id(raw)

    def _persist_theme_id(self, theme_id: str):
        normalized = normalize_theme_id(theme_id)
        self._app_settings.setValue(self._THEME_SETTING_KEY, normalized)
        self._app_settings.sync()

    def get_theme_id(self) -> str:
        return normalize_theme_id(getattr(self, "_theme_id", "dark"))

    def _sync_theme_actions(self):
        current = self.get_theme_id()
        actions = getattr(self, "_theme_actions", {}) or {}
        for theme_id, action in actions.items():
            if not isinstance(action, QAction):
                continue
            old = action.blockSignals(True)
            action.setChecked(theme_id == current)
            action.blockSignals(old)

    def apply_theme_id(self, theme_id: object, persist: bool = True):
        normalized = normalize_theme_id(theme_id)
        app = QApplication.instance()
        if app is not None:
            normalized = apply_theme(app, normalized)
        self._theme_id = normalized
        self._apply_window_chrome_theme()
        self._sync_theme_actions()
        if hasattr(self, "canvas"):
            self._refresh_all_preview_overlays()
        if persist:
            self._persist_theme_id(normalized)
            if getattr(self, "_autosave_runtime_connected", False):
                self._autosave_schedule_full(delay_ms=220)

    def _persist_autosave_enabled(self, enabled: bool):
        self._app_settings.setValue(self._AUTOSAVE_SETTING_KEY, bool(enabled))
        self._app_settings.sync()

    def _load_preview_theme_id(self) -> str:
        value = self._app_settings.value(
            self._PREVIEW_THEME_KEY,
            CanvasPreviewPane._PREVIEW_THEME_DEFAULT,
        )
        return CanvasPreviewPane._normalize_preview_theme_id(value)

    def _persist_preview_theme_id(self, theme_id: object):
        normalized = CanvasPreviewPane._normalize_preview_theme_id(theme_id)
        self._app_settings.setValue(self._PREVIEW_THEME_KEY, normalized)
        self._app_settings.sync()

    def _load_preview_page_margin_settings(self) -> tuple[bool, float]:
        enabled_raw = self._app_settings.value(
            self._PREVIEW_MARGIN_ENABLED_KEY,
            True,
        )
        em_raw = self._app_settings.value(
            self._PREVIEW_MARGIN_EM_KEY,
            CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM,
        )
        enabled = self._as_bool(enabled_raw, True)
        try:
            em = float(em_raw)
        except Exception:
            em = float(CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM)
        return enabled, em

    def _persist_preview_page_margin_settings(self):
        settings = self.get_preview_page_margin_settings()
        self._app_settings.setValue(
            self._PREVIEW_MARGIN_ENABLED_KEY,
            bool(settings.get("enabled", True)),
        )
        self._app_settings.setValue(
            self._PREVIEW_MARGIN_EM_KEY,
            float(settings.get("em", CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM)),
        )
        self._app_settings.sync()

    def get_preview_page_margin_settings(self) -> dict:
        enabled, em = CanvasPreviewPane.global_page_margin_settings()
        return {
            "enabled": bool(enabled),
            "em": float(em),
        }

    def get_preview_theme_id(self) -> str:
        return CanvasPreviewPane.global_preview_theme_id()

    def _sync_preview_theme_actions(self):
        current = CanvasPreviewPane.global_preview_theme_id()
        for theme_id, action in list(
            getattr(self, "_preview_theme_actions", {}).items()
        ):
            if not isinstance(action, QAction):
                continue
            old = action.blockSignals(True)
            action.setChecked(str(theme_id) == str(current))
            action.blockSignals(old)

    def _sync_preview_page_margin_actions(self):
        enabled, em = CanvasPreviewPane.global_page_margin_settings()
        action_enabled = getattr(self, "_action_page_margin_enabled", None)
        if isinstance(action_enabled, QAction):
            old = action_enabled.blockSignals(True)
            action_enabled.setChecked(bool(enabled))
            action_enabled.blockSignals(old)

        for preset_em, action in list(
            getattr(self, "_page_margin_actions", []) or []
        ):
            if not isinstance(action, QAction):
                continue
            old = action.blockSignals(True)
            action.setEnabled(bool(enabled))
            action.setChecked(abs(float(preset_em) - float(em)) < 0.001)
            action.blockSignals(old)

    def _toggle_preview_page_margin_enabled(self, checked: bool):
        _enabled, em = CanvasPreviewPane.global_page_margin_settings()
        self.apply_preview_page_margin_settings(
            {
                "enabled": bool(checked),
                "em": float(em),
            }
        )

    def _set_preview_page_margin_preset(self, em: float):
        enabled, _em = CanvasPreviewPane.global_page_margin_settings()
        self.apply_preview_page_margin_settings(
            {
                "enabled": bool(enabled),
                "em": float(em),
            }
        )

    def apply_preview_page_margin_settings(self, raw: object):
        if not isinstance(raw, dict):
            return
        enabled = self._as_bool(raw.get("enabled", True), True)
        try:
            em = float(raw.get("em", CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM))
        except Exception:
            em = float(CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM)
        CanvasPreviewPane.apply_global_page_margin_settings(
            enabled=enabled,
            em=em,
        )
        self._persist_preview_page_margin_settings()
        self._sync_preview_page_margin_actions()

    def apply_preview_theme_id(self, theme_id: object, *, persist: bool = True):
        CanvasPreviewPane.apply_global_preview_theme(theme_id)
        self._sync_preview_theme_actions()
        if persist:
            self._persist_preview_theme_id(theme_id)
            if getattr(self, "_autosave_runtime_connected", False):
                self._autosave_schedule_full(delay_ms=220)

    @staticmethod
    def _resolve_autosave_dir() -> Path:
        return (Path.cwd() / "tmp" / "autosave_project").resolve()

    def _autosave_project_file(self) -> Path:
        return self._autosave_dir / "project.json"

    def _autosave_prepare_workspace(self):
        self._autosave_dir.mkdir(parents=True, exist_ok=True)
        (self._autosave_dir / "canvas").mkdir(parents=True, exist_ok=True)

    def _autosave_reset_workspace(self):
        if self._autosave_dir.exists():
            shutil.rmtree(self._autosave_dir, ignore_errors=True)

    def _maybe_restore_autosave_project(self) -> bool:
        if not self._autosave_enabled:
            return False
        if not self._autosave_project_file().exists():
            return False

        choice = QMessageBox.question(
            self,
            "Temporäres Projekt gefunden",
            (
                "Im tmp-Ordner wurde ein automatisch gespeichertes Projekt gefunden.\n\n"
                "Möchtest du daran weiterarbeiten?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if choice == QMessageBox.StandardButton.Yes:
            self._autosave_suspended = True
            try:
                loaded = self._project_manager.load_project(
                    self,
                    str(self._autosave_dir),
                )
            finally:
                self._autosave_suspended = False
            if loaded:
                self.statusBar().showMessage(
                    "Temporäres Projekt wiederhergestellt.",
                    4000,
                )
                return True

            self._autosave_reset_workspace()
            return False

        self._autosave_reset_workspace()
        return False

    def _toggle_autosave_enabled(self, checked: bool):
        enabled = bool(checked)
        if enabled == self._autosave_enabled:
            return

        self._autosave_enabled = enabled
        self._persist_autosave_enabled(enabled)

        if enabled:
            self._autosave_start_runtime()
            self._autosave_schedule_full(delay_ms=150)
            self.statusBar().showMessage(
                "Autosave aktiviert (tmp-Projekt).",
                3000,
            )
            return

        self._autosave_stop_runtime()
        self._autosave_reset_workspace()
        self.statusBar().showMessage(
            "Autosave deaktiviert. tmp-Projekt wurde entfernt.",
            3500,
        )

    def _autosave_start_runtime(self):
        if not self._autosave_enabled:
            return
        if not self._autosave_runtime_connected:
            tabs = self.canvas.tabs
            tab_widget = tabs.tab_widget
            tab_widget.currentChanged.connect(self._autosave_on_canvas_tab_changed)
            tab_widget.tabCloseRequested.connect(
                self._autosave_on_canvas_structure_changed
            )
            tab_widget.tabBar().tabMoved.connect(
                self._autosave_on_canvas_structure_changed
            )
            tabs.tab_renamed.connect(self._autosave_on_canvas_structure_changed)
            self._autosave_runtime_connected = True

        self._autosave_rewire_editors()
        self._autosave_last_tab_count = self.canvas.tabs.tab_widget.count()
        self._autosave_last_signature = self._autosave_signature()
        if not self._autosave_watch_timer.isActive():
            self._autosave_watch_timer.start(1200)

    def _autosave_stop_runtime(self):
        self._autosave_watch_timer.stop()
        self._autosave_draft_timer.stop()
        self._autosave_full_timer.stop()
        self._autosave_pending_editor = None

        self._autosave_disconnect_editor_hooks()

        if not self._autosave_runtime_connected:
            return

        tabs = self.canvas.tabs
        tab_widget = tabs.tab_widget
        try:
            tab_widget.currentChanged.disconnect(self._autosave_on_canvas_tab_changed)
        except Exception:
            pass
        try:
            tab_widget.tabCloseRequested.disconnect(
                self._autosave_on_canvas_structure_changed
            )
        except Exception:
            pass
        try:
            tab_widget.tabBar().tabMoved.disconnect(
                self._autosave_on_canvas_structure_changed
            )
        except Exception:
            pass
        try:
            tabs.tab_renamed.disconnect(self._autosave_on_canvas_structure_changed)
        except Exception:
            pass
        self._autosave_runtime_connected = False

    def _autosave_disconnect_editor_hooks(self):
        tabs = self.canvas.tabs.tab_widget
        for i in range(tabs.count()):
            panel = tabs.widget(i)
            editor = getattr(panel, "editor", None)
            if editor is None:
                continue
            try:
                editor.textChanged.disconnect(self._autosave_on_editor_text_changed)
            except Exception:
                continue
        self._autosave_editor_hooks.clear()

    def _autosave_rewire_editors(self):
        if not self._autosave_enabled:
            return
        tabs = self.canvas.tabs.tab_widget
        live_ids: set[int] = set()
        for i in range(tabs.count()):
            panel = tabs.widget(i)
            editor = getattr(panel, "editor", None)
            if editor is None:
                continue
            live_ids.add(id(editor))
        self._autosave_editor_hooks.intersection_update(live_ids)

        for i in range(tabs.count()):
            panel = tabs.widget(i)
            editor = getattr(panel, "editor", None)
            if editor is None:
                continue
            key = id(editor)
            if key in self._autosave_editor_hooks:
                continue
            editor.textChanged.connect(self._autosave_on_editor_text_changed)
            self._autosave_editor_hooks.add(key)

    def _autosave_on_editor_text_changed(self):
        if (not self._autosave_enabled) or self._autosave_suspended:
            return
        sender = self.sender()
        if isinstance(sender, MarkdownEditor):
            self._autosave_pending_editor = sender
        self._autosave_draft_timer.start(450)

    def _autosave_on_canvas_tab_changed(self, _index: int):
        if (not self._autosave_enabled) or self._autosave_suspended:
            return
        self._autosave_rewire_editors()
        count = self.canvas.tabs.tab_widget.count()
        if count != self._autosave_last_tab_count:
            self._autosave_last_tab_count = count
            self._autosave_schedule_full(delay_ms=220)

    def _autosave_on_canvas_structure_changed(self, *_args):
        if (not self._autosave_enabled) or self._autosave_suspended:
            return
        self._autosave_rewire_editors()
        self._autosave_schedule_full(delay_ms=220)

    def _autosave_schedule_full(self, delay_ms: int = 900):
        if (not self._autosave_enabled) or self._autosave_suspended:
            return
        if not self._autosave_runtime_connected:
            return
        self._autosave_full_timer.start(max(80, int(delay_ms)))

    def _autosave_watch_structure(self):
        if (not self._autosave_enabled) or self._autosave_suspended:
            return
        self._autosave_rewire_editors()
        signature = self._autosave_signature()
        if signature == self._autosave_last_signature:
            return
        self._autosave_last_signature = signature
        self._autosave_schedule_full(delay_ms=250)

    def _autosave_flush_pending_preview_edits(self, panel: QWidget | None = None):
        panels: list[QWidget] = []
        if panel is not None:
            panels = [panel]
        else:
            tabs = self.canvas.tabs.tab_widget
            panels = [
                tabs.widget(i)
                for i in range(tabs.count())
                if isinstance(tabs.widget(i), QWidget)
            ]

        for current in panels:
            flush = getattr(current, "flush_pending_preview_edits", None)
            if flush is None:
                continue
            try:
                flush()
            except Exception:
                continue

    def _autosave_show_saved_hint(self, *, full_snapshot: bool = False):
        sb = self.statusBar()
        if sb is None:
            return
        now = time.monotonic()
        if (not full_snapshot) and (now - self._autosave_last_hint_ts) < 1.0:
            return
        self._autosave_last_hint_ts = now
        text = (
            "Autosave: Snapshot gespeichert"
            if full_snapshot
            else "Autosave: gespeichert"
        )
        sb.showMessage(text, 1200)

    def _autosave_signature(self) -> str:
        tabs_data = self._autosave_collect_canvas_tabs_data()
        payload = {
            "canvas_tabs": [
                {
                    "title": row.get("title", ""),
                    "file_path": row.get("file_path", ""),
                    "read_only": bool(row.get("read_only", False)),
                }
                for row in tabs_data
            ],
            "imported_docs": sorted(self._file_registry.keys()),
            "user_mode": self._user_mode,
            "theme": self.get_theme_id(),
            "chat_tts_mode": self.chat_dock.chat_tts_mode(),
            "preview_page_margin": self.get_preview_page_margin_settings(),
            "preview_theme": self.get_preview_theme_id(),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _autosave_flush_draft(self):
        if (not self._autosave_enabled) or self._autosave_suspended:
            return
        self._autosave_prepare_workspace()
        if not self._autosave_project_file().exists():
            self._autosave_flush_full()
            return

        panel, index = self._autosave_find_panel_for_editor(
            self._autosave_pending_editor
        )
        self._autosave_pending_editor = None
        if panel is None or index < 0:
            return

        self._autosave_flush_pending_preview_edits(panel)
        editor = getattr(panel, "editor", None)
        if editor is None:
            return

        canvas_file = self._autosave_dir / "canvas" / f"doc_{index:04d}.md"
        try:
            self._write_text_atomic(canvas_file, editor.toPlainText())
            self._autosave_show_saved_hint(full_snapshot=False)
        except Exception:
            self._autosave_flush_full()

    def _autosave_find_panel_for_editor(
        self,
        editor: MarkdownEditor | None,
    ) -> tuple[QWidget | None, int]:
        tabs = self.canvas.tabs.tab_widget
        if editor is not None:
            for i in range(tabs.count()):
                panel = tabs.widget(i)
                if getattr(panel, "editor", None) is editor:
                    return panel, i
        panel = self.canvas.tabs.current_panel()
        if panel is None:
            return None, -1
        return panel, tabs.indexOf(panel)

    def _autosave_collect_canvas_tabs_data(self) -> list[dict]:
        tabs = self.canvas.tabs.tab_widget
        out: list[dict] = []
        for i in range(tabs.count()):
            panel = tabs.widget(i)
            editor = getattr(panel, "editor", None)
            if editor is None:
                continue
            out.append(
                {
                    "title": self.canvas.tabs.get_tab_full_title(i),
                    "file_path": str(getattr(panel, "file_path", "") or ""),
                    "canvas_file": f"doc_{i:04d}.md",
                    "read_only": bool(editor.isReadOnly()),
                }
            )
        return out

    def _autosave_flush_full(self):
        if (not self._autosave_enabled) or self._autosave_suspended:
            return
        self._autosave_prepare_workspace()
        self._autosave_flush_pending_preview_edits()
        ok = self._project_manager.save_project(self, str(self._autosave_dir))
        if not ok:
            return
        self._autosave_rewire_editors()
        self._autosave_last_tab_count = self.canvas.tabs.tab_widget.count()
        self._autosave_last_signature = self._autosave_signature()
        self._autosave_show_saved_hint(full_snapshot=True)

    @staticmethod
    def _write_text_atomic(path: Path, content: str):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(str(content or ""), encoding="utf-8")
        tmp.replace(target)

    def _autosave_flush_before_close(self):
        if (not self._autosave_enabled) or self._autosave_suspended:
            return
        self._autosave_watch_timer.stop()
        if self._autosave_draft_timer.isActive():
            self._autosave_draft_timer.stop()
            self._autosave_flush_draft()
        if self._autosave_full_timer.isActive():
            self._autosave_full_timer.stop()
        self._autosave_flush_full()

    # ──────────────────────────────────────────────────────────────────
    # Context builder  (called by ChatDock before each LLM request)
    # ──────────────────────────────────────────────────────────────────

    def _build_llm_context(self) -> dict:
        use_canvas, use_rag, doc_selection = self.chat_dock.get_context_selection()

        # Selected documents (full content). Be robust against stale/empty
        # context-panel payloads by falling back to the canonical registries.
        selected_docs: list[tuple[str, str]] = []
        for name_raw, content_raw in list(doc_selection or []):
            name = str(name_raw or "").strip()
            if not name:
                continue
            content = str(content_raw or "").strip()
            if not content:
                content = self._resolve_imported_doc_content(name)
            if not content:
                continue
            selected_docs.append((name, content))
        file_contents: list[tuple[str, str]] = list(selected_docs)
        selected_doc_count = len(selected_docs)

        # Currently visible canvas tab
        if use_canvas:
            canvas_text = self.canvas.get_current_text().strip()
            if canvas_text:
                tab_idx   = self.canvas.tabs.tab_widget.currentIndex()
                tab_title = self.canvas.tabs.tab_widget.tabText(tab_idx) or "Draft"
                file_contents.append((f"Draft: {tab_title}", canvas_text))

        # Currently visible RAG results tab
        rag_results: list[tuple[str, float, str]] = []
        rag_has_data = False
        if use_rag:
            rag_text = self.knowledge_dock.get_rag_results_text().strip()
            if rag_text and "### 1." in rag_text:
                rag_results = [("RAG Results", 1.0, rag_text)]
                rag_has_data = True

        grounding_required = bool(use_rag or selected_doc_count > 0)
        grounding_has_sources = bool(rag_has_data or selected_doc_count > 0)
        # Always capture current draft selection (including one-shot cached
        # handoff) so side actions like Faktencheck can use it reliably,
        # even when "Current Draft" context toggle is off.
        selection_needed = True
        selected_text = ""
        selected_span: tuple[int, int] | None = None
        if selection_needed:
            selected_text = str(
                self.canvas.get_selected_text(allow_cached=True) or ""
            )
            selected_span = self.canvas.get_selected_span(allow_cached=True)

        return {
            "file_contents": file_contents,
            "rag_results":   rag_results,
            "selected_text": selected_text,
            "selected_span": selected_span,
            "grounding_required": grounding_required,
            "grounding_has_sources": grounding_has_sources,
            "grounding_reason": (
                "rag_or_docs_selected" if grounding_required else "none"
            ),
            "grounding_selected_docs": selected_doc_count,
            "grounding_rag_selected": bool(use_rag),
            "grounding_rag_has_data": rag_has_data,
        }

    # ──────────────────────────────────────────────────────────────────
    # Slots
    # ──────────────────────────────────────────────────────────────────

    def _on_model_loaded(self, success: bool, message: str):
        self._model_lbl.setText(message)
        self._model_status_success = bool(success)
        self._apply_status_label_styles()
        if success:
            # Provide differentiated HyDE expanders to the RAG system
            self.rag_system.set_tfidf_query_expander(
                self.llm_manager.expand_query_tfidf_sync
            )
            self.rag_system.set_st_query_expander(
                self.llm_manager.expand_query_st_sync
            )
            self.rag_system.set_literal_query_expander(
                self.llm_manager.expand_query_literal_terms_sync
            )
            self.rag_system.set_rag_reranker(
                self.llm_manager.rerank_rag_results_sync
            )

    def _on_rag_status(self, message: str):
        if message:
            self.statusBar().showMessage(message)
        else:
            self.statusBar().showMessage("Ready")

    def _focused_markdown_editor(self) -> MarkdownEditor | None:
        w = QApplication.focusWidget()
        while w is not None:
            if isinstance(w, MarkdownEditor):
                return w
            w = w.parentWidget()
        return None

    def _select_next_draft_tab(self):
        tabs = self.canvas.tabs.tab_widget
        count = int(tabs.count())
        if count <= 1:
            return
        index = int(tabs.currentIndex())
        tabs.setCurrentIndex((index + 1) % count)

    def _select_previous_draft_tab(self):
        tabs = self.canvas.tabs.tab_widget
        count = int(tabs.count())
        if count <= 1:
            return
        index = int(tabs.currentIndex())
        tabs.setCurrentIndex((index - 1) % count)

    def _set_canvas_view_mode_shortcut(self, mode: str):
        panel = self._resolve_active_split_panel()
        if panel is None or not hasattr(panel, "set_view_mode"):
            return
        normalized = str(mode or "").strip().lower()
        if normalized not in {"markdown", "preview", "both"}:
            return
        panel.set_view_mode(normalized)
        label_map = {
            "markdown": "nur Markdown",
            "preview": "nur HTML",
            "both": "Split (Markdown + HTML)",
        }
        self.statusBar().showMessage(
            f"Ansicht: {label_map.get(normalized, normalized)}",
            1800,
        )

    def _toggle_autosave_shortcut(self):
        target = not bool(self._autosave_enabled)
        self._toggle_autosave_enabled(target)
        action = getattr(self, "_action_autosave_toggle", None)
        if action is None:
            return
        blocked = action.blockSignals(True)
        action.setChecked(bool(self._autosave_enabled))
        action.blockSignals(blocked)

    @staticmethod
    def _widget_belongs_to(widget: QWidget | None, root: QWidget | None) -> bool:
        w = widget
        while w is not None:
            if w is root:
                return True
            w = w.parentWidget()
        return False

    @staticmethod
    def _editor_from_widget_chain(widget: QWidget | None) -> MarkdownEditor | None:
        w = widget
        while w is not None:
            editor = getattr(w, "editor", None)
            if isinstance(editor, MarkdownEditor):
                return editor
            w = w.parentWidget()
        return None

    @staticmethod
    def _split_panel_from_widget_chain(widget: QWidget | None) -> QWidget | None:
        w = widget
        while w is not None:
            if (
                hasattr(w, "set_view_mode")
                and hasattr(w, "view_mode")
                and hasattr(w, "editor")
            ):
                return w
            w = w.parentWidget()
        return None

    def _resolve_active_split_panel(self) -> QWidget | None:
        focus = QApplication.focusWidget()
        panel = self._split_panel_from_widget_chain(focus)
        if panel is not None:
            return panel

        if self._widget_belongs_to(focus, self.knowledge_dock):
            current = self.knowledge_dock.tab_widget.currentWidget()
            if current is self.knowledge_dock.doc_viewer:
                return self.knowledge_dock.doc_viewer.tabs.current_panel()
            if current is self.knowledge_dock.rag_tab:
                return self.knowledge_dock.rag_panel.tabs.current_panel()

        return self.canvas.tabs.current_panel()

    def _is_valid_find_target(self, target: dict | None) -> bool:
        if not isinstance(target, dict):
            return False
        kind = str(target.get("kind", "")).strip().lower()
        if kind == "editor":
            editor = target.get("editor")
            if not isinstance(editor, MarkdownEditor):
                return False
            try:
                _ = editor.document()
                return True
            except Exception:
                return False
        if kind == "preview":
            panel = target.get("panel")
            return (
                panel is not None
                and hasattr(panel, "find_preview_text")
                and hasattr(panel, "count_preview_matches")
            )
        return False

    def _resolve_find_target(self) -> dict | None:
        focus = QApplication.focusWidget()
        panel = self._split_panel_from_widget_chain(focus)
        if panel is None:
            if self._widget_belongs_to(focus, self.knowledge_dock):
                current = self.knowledge_dock.tab_widget.currentWidget()
                if current is self.knowledge_dock.doc_viewer:
                    panel = self.knowledge_dock.doc_viewer.tabs.current_panel()
                elif current is self.knowledge_dock.rag_tab:
                    panel = self.knowledge_dock.rag_panel.tabs.current_panel()
            elif self._widget_belongs_to(focus, self.canvas):
                panel = self.canvas.tabs.current_panel()

        if panel is not None and hasattr(panel, "is_preview_widget"):
            try:
                if panel.is_preview_widget(focus):
                    target = {"kind": "preview", "panel": panel}
                    if self._is_valid_find_target(target):
                        self._find_target = target
                        return target
            except Exception:
                pass

        if panel is not None:
            editor = getattr(panel, "editor", None)
            if isinstance(editor, MarkdownEditor):
                target = {"kind": "editor", "editor": editor, "panel": panel}
                if self._is_valid_find_target(target):
                    self._find_target = target
                    self._find_editor = editor
                    return target

        cached_target = getattr(self, "_find_target", None)
        if self._is_valid_find_target(cached_target):
            return cached_target

        panel = self.canvas.tabs.current_panel()
        if panel is not None:
            editor = getattr(panel, "editor", None)
            if isinstance(editor, MarkdownEditor):
                target = {"kind": "editor", "editor": editor, "panel": panel}
                self._find_target = target
                self._find_editor = editor
                return target
        return None

    def _count_find_matches_editor(self, editor: MarkdownEditor, needle: str) -> int:
        query = str(needle or "")
        if not query:
            return 0
        flags = self._build_find_flags(backward=False)
        doc = editor.document()
        count = 0
        cursor = doc.find(query, 0, flags)
        while not cursor.isNull():
            count += 1
            cursor = doc.find(query, cursor.position(), flags)
        return count

    def _count_find_matches(self, target: dict, needle: str) -> int:
        kind = str(target.get("kind", "")).strip().lower()
        if kind == "editor":
            editor = target.get("editor")
            if isinstance(editor, MarkdownEditor):
                return self._count_find_matches_editor(editor, needle)
            return 0
        if kind == "preview":
            panel = target.get("panel")
            if panel is None:
                return 0
            case_cb = getattr(self, "_find_case_cb", None)
            whole_cb = getattr(self, "_find_whole_cb", None)
            case_sensitive = bool(case_cb is not None and case_cb.isChecked())
            whole_words = bool(whole_cb is not None and whole_cb.isChecked())
            try:
                return int(
                    panel.count_preview_matches(
                        str(needle or ""),
                        case_sensitive=case_sensitive,
                        whole_words=whole_words,
                    )
                )
            except Exception:
                return 0
        return 0

    def _disconnect_find_read_only_hook(self):
        hooked = getattr(self, "_find_read_only_editor", None)
        if isinstance(hooked, MarkdownEditor):
            try:
                hooked.read_only_changed.disconnect(
                    self._on_find_target_read_only_changed
                )
            except Exception:
                pass
        self._find_read_only_editor = None

    def _track_find_target_read_only(self, target: dict | None):
        if not self._is_valid_find_target(target):
            self._disconnect_find_read_only_hook()
            return
        if str(target.get("kind", "")).strip().lower() != "editor":
            self._disconnect_find_read_only_hook()
            return
        editor = target.get("editor")
        if not isinstance(editor, MarkdownEditor):
            self._disconnect_find_read_only_hook()
            return
        if editor is self._find_read_only_editor:
            return
        self._disconnect_find_read_only_hook()
        try:
            editor.read_only_changed.connect(self._on_find_target_read_only_changed)
        except Exception:
            return
        self._find_read_only_editor = editor

    def _on_find_target_read_only_changed(self, _read_only: bool):
        if self._find_replace_dialog is None:
            return
        if not self._find_replace_dialog.isVisible():
            return
        self._update_find_replace_controls_state()

    def _find_target_is_read_only(self, target: dict | None) -> bool:
        if not self._is_valid_find_target(target):
            return True
        kind = str(target.get("kind", "")).strip().lower()
        if kind == "editor":
            editor = target.get("editor")
            if isinstance(editor, MarkdownEditor):
                try:
                    return bool(editor.isReadOnly())
                except Exception:
                    return True
            return True
        # HTML preview search is supported, but replace is not handled there.
        return True

    def _update_find_replace_controls_state(self, target: dict | None = None):
        tgt = target if self._is_valid_find_target(target) else self._resolve_find_target()
        self._track_find_target_read_only(tgt)
        replace_enabled = bool(tgt is not None and not self._find_target_is_read_only(tgt))
        replace_edit = getattr(self, "_replace_query_edit", None)
        if replace_edit is not None:
            replace_edit.setEnabled(replace_enabled)
        replace_btn = getattr(self, "_find_replace_btn", None)
        if replace_btn is not None:
            replace_btn.setEnabled(replace_enabled)
        replace_all_btn = getattr(self, "_find_replace_all_btn", None)
        if replace_all_btn is not None:
            replace_all_btn.setEnabled(replace_enabled)

    def _update_find_match_count(self):
        label = getattr(self, "_find_count_lbl", None)
        if label is None:
            return
        find_edit = getattr(self, "_find_query_edit", None)
        query = str(find_edit.text() if find_edit is not None else "")
        target = self._resolve_find_target()
        if target is None:
            label.setText("Treffer: —")
            self._update_find_replace_controls_state(None)
            return
        label.setText(f"Treffer: {self._count_find_matches(target, query)}")
        self._update_find_replace_controls_state(target)

    def _build_find_flags(self, *, backward: bool = False):
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        case_cb = getattr(self, "_find_case_cb", None)
        if case_cb is not None and case_cb.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        whole_cb = getattr(self, "_find_whole_cb", None)
        if whole_cb is not None and whole_cb.isChecked():
            flags |= QTextDocument.FindFlag.FindWholeWords
        return flags

    def _find_in_target(self, target: dict, needle: str, *, backward: bool = False) -> bool:
        kind = str(target.get("kind", "")).strip().lower()
        if kind == "preview":
            panel = target.get("panel")
            if panel is None:
                return False
            case_cb = getattr(self, "_find_case_cb", None)
            whole_cb = getattr(self, "_find_whole_cb", None)
            case_sensitive = bool(case_cb is not None and case_cb.isChecked())
            whole_words = bool(whole_cb is not None and whole_cb.isChecked())
            try:
                return bool(
                    panel.find_preview_text(
                        needle,
                        backward=backward,
                        case_sensitive=case_sensitive,
                        whole_words=whole_words,
                        wrap=True,
                    )
                )
            except Exception:
                return False

        editor = target.get("editor")
        if not isinstance(editor, MarkdownEditor):
            return False
        flags = self._build_find_flags(backward=backward)
        doc = editor.document()
        cursor = editor.textCursor()
        current_start = int(cursor.selectionStart())
        current_end = int(cursor.selectionEnd())
        current_has_selection = current_end > current_start
        start = int(cursor.selectionStart()) if backward else int(cursor.selectionEnd())
        probe = QTextCursor(doc)
        if backward:
            probe.setPosition(max(0, start - 1))
        else:
            probe.setPosition(max(0, start))
        found = doc.find(str(needle or ""), probe, flags)
        if found.isNull():
            restart = QTextCursor(doc)
            if backward:
                restart.setPosition(max(0, int(doc.characterCount()) - 1))
            else:
                restart.setPosition(0)
            found = doc.find(str(needle or ""), restart, flags)
        if (
            not found.isNull()
            and current_has_selection
            and int(found.selectionStart()) == current_start
            and int(found.selectionEnd()) == current_end
        ):
            probe2 = QTextCursor(doc)
            if backward:
                probe2.setPosition(max(0, int(found.selectionStart()) - 1))
            else:
                probe2.setPosition(max(0, int(found.selectionEnd())))
            alt = doc.find(str(needle or ""), probe2, flags)
            if alt.isNull():
                restart = QTextCursor(doc)
                if backward:
                    restart.setPosition(max(0, int(doc.characterCount()) - 1))
                else:
                    restart.setPosition(0)
                alt = doc.find(str(needle or ""), restart, flags)
            if (
                not alt.isNull()
                and (
                    int(alt.selectionStart()) != current_start
                    or int(alt.selectionEnd()) != current_end
                )
            ):
                found = alt
        if found.isNull():
            return False
        editor.setTextCursor(found)
        editor.ensureCursorVisible()
        return True

    def _find_in_editor_from_dialog(self, *, backward: bool = False) -> bool:
        target = self._resolve_find_target()
        if target is None:
            self.statusBar().showMessage("Kein aktiver Editor für Suche.", 2000)
            self._update_find_replace_controls_state(None)
            return False
        self._update_find_replace_controls_state(target)

        find_edit = getattr(self, "_find_query_edit", None)
        needle = str(find_edit.text() if find_edit is not None else "").strip()
        if not needle:
            self.statusBar().showMessage("Bitte Suchtext eingeben.", 2000)
            return False

        if self._find_in_target(target, needle, backward=backward):
            return True

        self.statusBar().showMessage("Kein Treffer gefunden.", 1800)
        return False

    def _replace_from_dialog(self):
        target = self._resolve_find_target()
        if target is None:
            self.statusBar().showMessage("Kein aktiver Editor für Ersetzen.", 2000)
            return
        if self._find_target_is_read_only(target):
            self.statusBar().showMessage("Ersetzen ist in dieser Ansicht gesperrt.", 2000)
            self._update_find_replace_controls_state(target)
            return
        editor = target.get("editor")
        if not isinstance(editor, MarkdownEditor):
            self.statusBar().showMessage("Ersetzen ist in dieser Ansicht nicht verfügbar.", 2000)
            self._update_find_replace_controls_state(target)
            return

        find_edit = getattr(self, "_find_query_edit", None)
        replace_edit = getattr(self, "_replace_query_edit", None)
        needle = str(find_edit.text() if find_edit is not None else "")
        replacement = str(replace_edit.text() if replace_edit is not None else "")
        if not needle:
            self.statusBar().showMessage("Bitte Suchtext eingeben.", 2000)
            return

        cursor = editor.textCursor()
        selected = str(cursor.selectedText() or "").replace("\u2029", "\n")
        case_cb = getattr(self, "_find_case_cb", None)
        case_sensitive = bool(case_cb is not None and case_cb.isChecked())
        if case_sensitive:
            match_selected = selected == needle
        else:
            match_selected = selected.casefold() == needle.casefold()

        if match_selected:
            cursor.insertText(replacement)
            editor.setTextCursor(cursor)

        self._find_in_editor_from_dialog(backward=False)
        self._update_find_match_count()

    def _replace_all_from_dialog(self):
        target = self._resolve_find_target()
        if target is None:
            self.statusBar().showMessage("Kein aktiver Editor für Ersetzen.", 2000)
            return
        if self._find_target_is_read_only(target):
            self.statusBar().showMessage("Ersetzen ist in dieser Ansicht gesperrt.", 2000)
            self._update_find_replace_controls_state(target)
            return
        editor = target.get("editor")
        if not isinstance(editor, MarkdownEditor):
            self.statusBar().showMessage("Ersetzen ist in dieser Ansicht nicht verfügbar.", 2000)
            self._update_find_replace_controls_state(target)
            return

        find_edit = getattr(self, "_find_query_edit", None)
        replace_edit = getattr(self, "_replace_query_edit", None)
        needle = str(find_edit.text() if find_edit is not None else "")
        replacement = str(replace_edit.text() if replace_edit is not None else "")
        if not needle:
            self.statusBar().showMessage("Bitte Suchtext eingeben.", 2000)
            return

        flags = self._build_find_flags(backward=False)
        doc = editor.document()
        edit_cursor = editor.textCursor()
        edit_cursor.beginEditBlock()
        count = 0
        hit = doc.find(needle, 0, flags)
        while not hit.isNull():
            hit.insertText(replacement)
            count += 1
            hit = doc.find(needle, hit.position(), flags)
        edit_cursor.endEditBlock()

        self.statusBar().showMessage(
            f"{count} Treffer ersetzt." if count else "Keine Treffer zum Ersetzen.",
            2000,
        )
        self._update_find_match_count()

    def _open_find_replace_dialog(self):
        target = self._resolve_find_target()
        if target is None:
            self.statusBar().showMessage("Kein aktiver Editor für Suche.", 2000)
            return
        self._find_target = target
        editor = target.get("editor")
        if isinstance(editor, MarkdownEditor):
            self._find_editor = editor

        if self._find_replace_dialog is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Suchen / Ersetzen")
            dlg.setModal(False)
            dlg.resize(520, 170)
            layout = QVBoxLayout(dlg)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(6)

            row_find = QHBoxLayout()
            row_find.setContentsMargins(0, 0, 0, 0)
            row_find.setSpacing(6)
            row_find.addWidget(QLabel("Suchen:"))
            self._find_query_edit = QLineEdit()
            row_find.addWidget(self._find_query_edit, 1)
            layout.addLayout(row_find)

            row_replace = QHBoxLayout()
            row_replace.setContentsMargins(0, 0, 0, 0)
            row_replace.setSpacing(6)
            row_replace.addWidget(QLabel("Ersetzen:"))
            self._replace_query_edit = QLineEdit()
            row_replace.addWidget(self._replace_query_edit, 1)
            layout.addLayout(row_replace)

            flags_row = QHBoxLayout()
            flags_row.setContentsMargins(0, 0, 0, 0)
            flags_row.setSpacing(10)
            self._find_case_cb = QCheckBox("Groß/Kleinschreibung")
            self._find_whole_cb = QCheckBox("Ganzes Wort")
            flags_row.addWidget(self._find_case_cb)
            flags_row.addWidget(self._find_whole_cb)
            flags_row.addStretch(1)
            self._find_count_lbl = QLabel("Treffer: 0")
            self._find_count_lbl.setStyleSheet(
                "color: palette(placeholder-text); font-size: 10px;"
            )
            flags_row.addWidget(self._find_count_lbl)
            layout.addLayout(flags_row)

            btn_row = QHBoxLayout()
            btn_row.setContentsMargins(0, 0, 0, 0)
            btn_row.setSpacing(6)
            btn_prev = QPushButton("Vorheriges")
            btn_next = QPushButton("Nächstes")
            self._find_replace_btn = QPushButton("Ersetzen")
            self._find_replace_all_btn = QPushButton("Alle ersetzen")
            btn_close = QPushButton("Schließen")
            btn_prev.clicked.connect(
                lambda: self._find_in_editor_from_dialog(backward=True)
            )
            btn_next.clicked.connect(
                lambda: self._find_in_editor_from_dialog(backward=False)
            )
            self._find_replace_btn.clicked.connect(self._replace_from_dialog)
            self._find_replace_all_btn.clicked.connect(self._replace_all_from_dialog)
            btn_close.clicked.connect(dlg.hide)
            btn_row.addWidget(btn_prev)
            btn_row.addWidget(btn_next)
            btn_row.addWidget(self._find_replace_btn)
            btn_row.addWidget(self._find_replace_all_btn)
            btn_row.addStretch(1)
            btn_row.addWidget(btn_close)
            layout.addLayout(btn_row)

            self._find_query_edit.textChanged.connect(
                lambda _text: self._update_find_match_count()
            )
            self._find_case_cb.toggled.connect(
                lambda _on: self._update_find_match_count()
            )
            self._find_whole_cb.toggled.connect(
                lambda _on: self._update_find_match_count()
            )
            self._find_query_edit.returnPressed.connect(
                lambda: self._find_in_editor_from_dialog(backward=False)
            )
            self._replace_query_edit.returnPressed.connect(self._replace_from_dialog)
            self._find_replace_dialog = dlg

        find_edit = getattr(self, "_find_query_edit", None)
        if find_edit is not None:
            selected = ""
            if str(target.get("kind", "")).strip().lower() == "preview":
                panel = target.get("panel")
                if panel is not None and hasattr(panel, "get_preview_selected_text"):
                    try:
                        selected = str(panel.get_preview_selected_text() or "")
                    except Exception:
                        selected = ""
            else:
                if isinstance(editor, MarkdownEditor):
                    selected = str(editor.textCursor().selectedText() or "")
            selected = selected.replace("\u2029", "\n")
            if selected.strip():
                find_edit.setText(selected)
            find_edit.setFocus()
            find_edit.selectAll()

        self._update_find_match_count()
        self._find_replace_dialog.show()
        self._find_replace_dialog.raise_()
        self._find_replace_dialog.activateWindow()

    def _is_focus_on_html_preview(self) -> bool:
        return self.canvas.is_preview_widget(QApplication.focusWidget())

    def _show_zoom_status(self, label: str, percent: int):
        self.statusBar().showMessage(f"{label}: {percent}%", 1500)

    def _increase_active_text_size(self):
        editor = self._focused_markdown_editor()
        if editor is not None:
            if editor.increase_zoom():
                self._show_zoom_status("Markdown-Ansicht", editor.zoom_percent())
            return
        if self._is_focus_on_html_preview():
            if self.canvas.increase_preview_text_size():
                self._show_zoom_status("HTML-Vorschau", self.canvas.preview_zoom_percent())
            return
        panel = self.canvas.tabs.current_panel()
        if panel and panel.editor.increase_zoom():
            self._show_zoom_status("Markdown-Ansicht", panel.editor.zoom_percent())

    def _decrease_active_text_size(self):
        editor = self._focused_markdown_editor()
        if editor is not None:
            if editor.decrease_zoom():
                self._show_zoom_status("Markdown-Ansicht", editor.zoom_percent())
            return
        if self._is_focus_on_html_preview():
            if self.canvas.decrease_preview_text_size():
                self._show_zoom_status("HTML-Vorschau", self.canvas.preview_zoom_percent())
            return
        panel = self.canvas.tabs.current_panel()
        if panel and panel.editor.decrease_zoom():
            self._show_zoom_status("Markdown-Ansicht", panel.editor.zoom_percent())

    def _reset_active_text_size(self):
        editor = self._focused_markdown_editor()
        if editor is not None:
            if editor.reset_zoom():
                self._show_zoom_status("Markdown-Ansicht", editor.zoom_percent())
            return
        if self._is_focus_on_html_preview():
            if self.canvas.reset_preview_text_size():
                self._show_zoom_status("HTML-Vorschau", self.canvas.preview_zoom_percent())
            return
        panel = self.canvas.tabs.current_panel()
        if panel and panel.editor.reset_zoom():
            self._show_zoom_status("Markdown-Ansicht", panel.editor.zoom_percent())

    def _increase_preview_text_size(self):
        if self.canvas.increase_preview_text_size():
            self._show_zoom_status("HTML-Vorschau", self.canvas.preview_zoom_percent())

    def _decrease_preview_text_size(self):
        if self.canvas.decrease_preview_text_size():
            self._show_zoom_status("HTML-Vorschau", self.canvas.preview_zoom_percent())

    def _reset_preview_text_size(self):
        if self.canvas.reset_preview_text_size():
            self._show_zoom_status("HTML-Vorschau", self.canvas.preview_zoom_percent())

    def _apply_llm_selection_rewrite(
        self,
        replacement: str,
        expected_original: str,
        preferred_span: tuple[int, int] | None = None,
    ) -> tuple[bool, str]:
        return self.canvas.replace_selected_text(
            replacement,
            expected_original,
            preferred_span,
        )

    def _open_fact_check_canvas(
        self,
        title_hint: str,
        content: str,
    ) -> tuple[bool, str]:
        title = str(title_hint or "").strip()
        if title:
            title = f"Fakten: {title}"
        else:
            title = "Faktencheck"
        try:
            # Keep Faktencheck output stable in HTML preview:
            # preview->markdown roundtrips can rewrite long markdown tables.
            self.canvas.tabs.add_tab(title=title, content=content, read_only=True)
            self.statusBar().showMessage("Faktencheck im Draft-Workspace geöffnet.", 4000)
            return True, title
        except Exception as exc:
            return False, str(exc)

    def _refresh_context_bar(self):
        use_canvas, use_rag, docs = self.chat_dock.get_context_selection()
        parts = []
        if use_canvas and self.canvas.get_current_text().strip():
            parts.append("canvas")
        if use_rag and self.knowledge_dock.get_rag_results_text().strip():
            parts.append("RAG")
        if docs:
            parts.append(f"{len(docs)} doc{'s' if len(docs) != 1 else ''}")
        sel = ""
        sel = str(
            self.canvas.get_selected_text(
                allow_cached=True,
                consume_cached=False,
            ) or ""
        ).strip()
        if sel:
            parts.append("selection")
        self.chat_dock.update_context_bar(parts)

    def _resolve_imported_doc_content(self, name: str) -> str:
        """Resolve imported document content by display name across registries."""
        key = str(name or "").strip()
        if not key:
            return ""

        def _from_file_registry_exact() -> str:
            entry = self._file_registry.get(key)
            if isinstance(entry, tuple) and len(entry) >= 2:
                return str(entry[1] or "").strip()
            return ""

        def _from_imported_panel_exact() -> str:
            imported = getattr(
                getattr(self.knowledge_dock, "imported_files", None),
                "_entries",
                {},
            )
            if isinstance(imported, dict):
                return str(imported.get(key, "") or "").strip()
            return ""

        def _from_context_panel_exact() -> str:
            docs = getattr(
                getattr(self.chat_dock, "context_panel", None),
                "_docs",
                {},
            )
            if isinstance(docs, dict):
                return str(docs.get(key, "") or "").strip()
            return ""

        for getter in (
            _from_file_registry_exact,
            _from_imported_panel_exact,
            _from_context_panel_exact,
        ):
            value = getter()
            if value:
                return value

        key_low = key.casefold()

        for doc_name, entry in self._file_registry.items():
            if str(doc_name or "").strip().casefold() != key_low:
                continue
            if isinstance(entry, tuple) and len(entry) >= 2:
                value = str(entry[1] or "").strip()
                if value:
                    return value

        imported = getattr(
            getattr(self.knowledge_dock, "imported_files", None),
            "_entries",
            {},
        )
        if isinstance(imported, dict):
            for doc_name, value_raw in imported.items():
                if str(doc_name or "").strip().casefold() != key_low:
                    continue
                value = str(value_raw or "").strip()
                if value:
                    return value

        docs = getattr(
            getattr(self.chat_dock, "context_panel", None),
            "_docs",
            {},
        )
        if isinstance(docs, dict):
            for doc_name, value_raw in docs.items():
                if str(doc_name or "").strip().casefold() != key_low:
                    continue
                value = str(value_raw or "").strip()
                if value:
                    return value
        return ""

    def _build_glossary_context_text(
        self,
        max_chars: int = 22000,
        *,
        allow_current_draft_fallback: bool = True,
        prefer_selected_docs: bool = False,
    ) -> str:
        # Legacy wrapper: keep method name for compatibility, but route to
        # the canonical chat-context payload so all features share one path.
        _ = allow_current_draft_fallback
        _ = prefer_selected_docs
        return self._build_context_text_from_llm_context(
            self._build_llm_context(),
            max_chars=max_chars,
        )

    def _build_context_text_from_llm_context(
        self,
        ctx: dict,
        *,
        max_chars: int = 22000,
    ) -> str:
        parts: list[str] = []
        try:
            char_limit = max(1, int(max_chars))
        except Exception:
            char_limit = 22000
        total_len = 0
        truncated = False

        def add_chunk(label: str, content: str) -> bool:
            nonlocal total_len, truncated
            body = str(content or "").strip()
            if not body:
                return True
            header = f"## {label}\n"
            footer = "\n\n"
            room = char_limit - total_len - len(header) - len(footer)
            if room <= 0:
                truncated = True
                return False
            if len(body) > room:
                suffix = "\n\n[... gekürzt ...]"
                keep = max(0, room - len(suffix))
                body = body[:keep].rstrip()
                if keep > 0:
                    body += suffix
                truncated = True
            chunk = f"{header}{body}{footer}"
            parts.append(chunk)
            total_len += len(chunk)
            return total_len < char_limit

        # Exactly the same sources as Chat/Faktencheck (`_build_llm_context`):
        # file_contents + rag_results + selected_text and nothing else.
        for name, content in list(ctx.get("file_contents", []) or []):
            if not add_chunk(f"Quelle: {name}", str(content or "")):
                break

        if total_len < char_limit:
            for path, score, excerpt in list(ctx.get("rag_results", []) or []):
                label = str(path or "").strip() or "RAG Results"
                try:
                    score_text = f"{float(score):.2f}"
                except Exception:
                    score_text = "?"
                if not add_chunk(
                    f"RAG: {label} (score {score_text})",
                    str(excerpt or ""),
                ):
                    break

        if total_len < char_limit:
            selected_text = str(ctx.get("selected_text", "") or "").strip()
            if selected_text:
                add_chunk("Ausgewählter Text (Draft)", selected_text)

        # Recovery path: selected docs checked but context payload arrived empty.
        if not parts:
            _use_canvas, _use_rag, doc_selection = self.chat_dock.get_context_selection()
            for name, _content in list(doc_selection or []):
                doc_name = str(name or "").strip()
                if not doc_name:
                    continue
                resolved = self._resolve_imported_doc_content(doc_name)
                if not resolved:
                    continue
                if not add_chunk(f"Quelle: {doc_name}", resolved):
                    break

        text = "".join(parts).strip()
        if truncated and text:
            return f"{text}\n\n[Hinweis: Kontext wurde aus Platzgründen gekürzt.]"
        return text

    def _fallback_context_text_from_ctx(
        self,
        ctx: dict,
        *,
        max_chars: int = 22000,
    ) -> str:
        """
        Minimal robust fallback if structured chunk builder yielded empty output.

        Keeps exactly the same source set as chat context.
        """
        out: list[str] = []
        try:
            char_limit = max(1, int(max_chars))
        except Exception:
            char_limit = 22000
        total_len = 0
        truncated = False

        def add_raw(label: str, content: str) -> bool:
            nonlocal total_len, truncated
            body = str(content or "").strip()
            if not body:
                return True
            header = f"[{label}]\n"
            footer = "\n\n"
            room = char_limit - total_len - len(header) - len(footer)
            if room <= 0:
                truncated = True
                return False
            if len(body) > room:
                suffix = "\n\n[... gekürzt ...]"
                keep = max(0, room - len(suffix))
                body = body[:keep].rstrip()
                if keep > 0:
                    body += suffix
                truncated = True
            block = f"{header}{body}{footer}"
            out.append(block)
            total_len += len(block)
            return total_len < char_limit

        for item in list(ctx.get("file_contents", []) or []):
            if not isinstance(item, (tuple, list)) or len(item) < 2:
                continue
            name = str(item[0] or "").strip() or "Quelle"
            body = str(item[1] or "")
            if not body.strip():
                body = self._resolve_imported_doc_content(name)
            if not add_raw(f"Quelle: {name}", body):
                break

        if total_len < char_limit:
            for item in list(ctx.get("rag_results", []) or []):
                if not isinstance(item, (tuple, list)) or len(item) < 3:
                    continue
                path = str(item[0] or "").strip() or "RAG Results"
                excerpt = str(item[2] or "")
                if not add_raw(f"RAG: {path}", excerpt):
                    break

        if total_len < char_limit:
            selected = str(ctx.get("selected_text", "") or "")
            if selected.strip():
                add_raw("Ausgewählter Text (Draft)", selected)

        text = "".join(out).strip()
        if truncated and text:
            return f"{text}\n\n[Hinweis: Kontext wurde aus Platzgründen gekürzt.]"
        return text

    @staticmethod
    def _resolve_mindmap_mode_and_query(
        query_raw: str,
        *,
        mode_hint: str = "auto",
    ) -> tuple[str, str]:
        query = str(query_raw or "").strip()
        forced_mode = str(mode_hint or "").strip().casefold()
        mode = "mindmap"
        if forced_mode in {"mindmap", "graph", "chunkmap", "chunk"}:
            mode = "chunkmap" if forced_mode in {"chunkmap", "chunk"} else forced_mode
            low = query.casefold()
            if low.startswith("graph:") or low.startswith("wissensgraph:"):
                query = query.split(":", 1)[1].strip()
            elif low.startswith("mindmap:") or low.startswith("map:"):
                query = query.split(":", 1)[1].strip()
            elif low.startswith("chunkmap:") or low.startswith("chunk:"):
                query = query.split(":", 1)[1].strip()
        else:
            low = query.casefold()
            if low.startswith("graph:"):
                mode = "graph"
                query = query.split(":", 1)[1].strip()
            elif low.startswith("wissensgraph:"):
                mode = "graph"
                query = query.split(":", 1)[1].strip()
            elif low.startswith("mindmap:") or low.startswith("map:"):
                mode = "mindmap"
                query = query.split(":", 1)[1].strip()
            elif low.startswith("chunkmap:") or low.startswith("chunk:"):
                mode = "chunkmap"
                query = query.split(":", 1)[1].strip()
            elif "wissensgraph" in low:
                mode = "graph"
        if not query:
            if mode == "graph":
                query = (
                    "Welche zentralen Entitäten und Beziehungen sind im Kontext belegt?"
                )
            elif mode == "chunkmap":
                query = (
                    "Wie ist der Kontext nach Überschriften und Chunks strukturiert?"
                )
            else:
                query = (
                    "Welche zentralen Konzepte beantworten die Fragestellung im Kontext?"
                )
        return mode, query

    def _refresh_all_preview_overlays(self):
        for panel in self.findChildren(MarkdownSplitPanel):
            try:
                panel.refresh_preview_overlays()
            except Exception:
                continue

    def _toggle_glossary_overlays(self, checked: bool):
        enabled = bool(checked)
        store = get_highlight_store()
        store.set_glossary_enabled(enabled)
        self._refresh_all_preview_overlays()
        self.statusBar().showMessage(
            "Glossar-Overlay: AN" if enabled else "Glossar-Overlay: AUS",
            2500,
        )

    def _open_glossary_editor(self):
        dialog = GlossaryEditorDialog(self)
        dialog.glossary_saved.connect(self._on_glossary_saved_from_editor)
        dialog.exec()

    def _on_glossary_saved_from_editor(self, count: int):
        self._refresh_all_preview_overlays()
        overlays_on = get_highlight_store().is_glossary_enabled()
        self.statusBar().showMessage(
            (
                f"Glossar gespeichert: {int(count)} Begriffe."
                if overlays_on
                else (
                    f"Glossar gespeichert: {int(count)} Begriffe "
                    "(Overlay aktuell AUS)."
                )
            ),
            4500,
        )

    def _llm_side_task_active(self) -> bool:
        return self._llm_side_task_thread is not None

    def _start_llm_side_task(
        self,
        *,
        task: str,
        payload: dict,
        status_message: str,
        done_cb=None,
    ) -> tuple[bool, str]:
        if self._llm_side_task_active():
            return False, "Es läuft bereits eine Hintergrundaufgabe."

        thread = QThread(self)
        worker = _LLMSideTaskWorker(self.llm_manager, task=task, payload=payload)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_llm_side_task_finished)
        worker.failed.connect(self._on_llm_side_task_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._llm_side_task_thread = thread
        self._llm_side_task_worker = worker
        self._llm_side_task_kind = str(task or "")
        self._llm_side_task_done_cb = done_cb
        self.chat_dock.set_aux_task_running(True)
        self.statusBar().showMessage(status_message, 2500)
        thread.start()
        return True, ""

    def _finish_llm_side_task(self, ok: bool, info: str):
        callback = self._llm_side_task_done_cb
        self._llm_side_task_done_cb = None
        self._llm_side_task_kind = ""
        self._llm_side_task_worker = None
        self._llm_side_task_thread = None
        self.chat_dock.set_aux_task_running(False)
        if callable(callback):
            try:
                callback(bool(ok), str(info or ""))
            except Exception as exc:
                self.app_logger.error("LLM", f"Side-task callback failed: {exc}")

    def _on_llm_side_task_finished(self, payload: dict):
        task = str(payload.get("task", "") or "").strip().lower()
        if task == "glossary":
            ok, info = self._finalize_glossary_generation(
                entries=list(payload.get("entries", []) or []),
                meta=dict(payload.get("meta", {}) or {}),
                context_text=str(payload.get("context_text", "") or ""),
            )
            self._finish_llm_side_task(ok, info)
            return
        if task == "mindmap":
            ok, info = self._finalize_mindmap_generation(
                markdown=str(payload.get("markdown", "") or ""),
                meta=dict(payload.get("meta", {}) or {}),
                context_text=str(payload.get("context_text", "") or ""),
                query=str(payload.get("query", "") or ""),
                mode=str(payload.get("mode", "mindmap") or "mindmap"),
            )
            self._finish_llm_side_task(ok, info)
            return
        self._finish_llm_side_task(False, f"Unbekanntes Aufgaben-Ergebnis: {task}")

    def _on_llm_side_task_failed(self, message: str):
        detail = str(message or "").strip() or "Unbekannter Fehler"
        self.app_logger.error("LLM", f"Hintergrundaufgabe fehlgeschlagen: {detail}")
        self._finish_llm_side_task(False, detail)

    def _finalize_glossary_generation(
        self,
        *,
        entries: list[dict],
        meta: dict,
        context_text: str,
    ) -> tuple[bool, str]:
        reason = str(meta.get("reason", "") or "")
        if not entries:
            detail = str(meta.get("error", "") or "").strip()
            if reason == "context_too_large" and detail:
                return False, detail
            if reason in {"empty", "parse_failed"}:
                retried = bool(meta.get("retried", False))
                parse_mode = str(meta.get("parse", "") or "").strip() or "n/a"
                return (
                    False,
                    "Es konnten keine Glossar-Einträge erzeugt werden.\n"
                    "Die Modellausgabe war leer oder nicht als Glossar parsebar.\n"
                    f"Retry ausgeführt: {'ja' if retried else 'nein'} | Parse-Modus: {parse_mode}",
                )
            return (
                False,
                "Es konnten keine Glossar-Einträge erzeugt werden.\n"
                f"Grund: {reason or 'unbekannt'}",
            )

        count = get_highlight_store().replace_glossary_entries(
            entries=entries,
            panel_scope="*",
            apply_all_tabs=True,
        )
        self._status_feedback_payload = {
            "glossary": {
                "count": count,
                "entries": entries[:64],
            },
            "context_preview": context_text[:4000],
            "meta": meta,
        }
        self._glossary_feedback_bar.activate("glossary")
        self._refresh_all_preview_overlays()
        overlays_on = get_highlight_store().is_glossary_enabled()
        self.statusBar().showMessage(
            (
                f"Glossar aktualisiert: {count} Begriffe."
                if overlays_on
                else f"Glossar aktualisiert: {count} Begriffe (Overlay aktuell AUS)."
            ),
            4500,
        )
        return True, f"{count} Begriffe"

    def _finalize_mindmap_generation(
        self,
        *,
        markdown: str,
        meta: dict,
        context_text: str,
        query: str,
        mode: str,
    ) -> tuple[bool, str]:
        reason = str(meta.get("reason", "") or "")
        if not str(markdown or "").strip():
            detail = str(meta.get("error", "") or "").strip()
            if reason == "context_too_large" and detail:
                return False, detail
            return (
                False,
                "Es konnte keine Struktur erzeugt werden.\n"
                f"Grund: {reason or 'unbekannt'}",
            )

        kind = str(meta.get("kind", mode) or mode).strip().casefold()
        variant = str(meta.get("variant", mode) or mode).strip().casefold()
        if variant == "chunkmap" or mode.strip().casefold() == "chunkmap":
            label = "Chunk-MindMap"
        elif kind == "graph":
            label = "Graph"
        else:
            label = "MindMap"
        title = f"{label} {datetime.now().strftime('%H:%M')}"
        self.canvas.tabs.add_tab(title=title, content=markdown, read_only=False)
        self._status_feedback_payload = {
            "mindmap": {
                "query": query,
                "mode": mode,
                "markdown": markdown[:12000],
            },
            "context_preview": context_text[:4000],
            "meta": meta,
        }
        self._glossary_feedback_bar.activate("mindmap")
        self.statusBar().showMessage(
            (
                f"{label} erstellt: {int(meta.get('nodes', 0) or 0)} Knoten, "
                f"{int(meta.get('edges', 0) or 0)} Verbindungen."
            ),
            5000,
        )
        return (
            True,
            f"{label}: {int(meta.get('nodes', 0) or 0)} Knoten, "
            f"{int(meta.get('edges', 0) or 0)} Verbindungen",
        )

    def _generate_glossary_from_llm_context(
        self,
        ctx: dict,
        done_cb=None,
    ) -> tuple[bool, str]:
        if not self.llm_manager.is_model_loaded():
            return False, "Kein Modell geladen. Bitte zuerst ein GGUF-Modell laden."
        if self.llm_manager.worker.isRunning() or self._llm_side_task_active():
            return (
                False,
                "Das Modell ist gerade beschäftigt. Bitte erneut versuchen, "
                "wenn die aktuelle Generation fertig ist.",
            )

        context_text = self._build_context_text_from_llm_context(ctx)
        if not context_text:
            context_text = self._fallback_context_text_from_ctx(ctx)
        if not context_text:
            selected_text_len = len(str(ctx.get("selected_text", "") or "").strip())
            file_count = len(list(ctx.get("file_contents", []) or []))
            rag_count = len(list(ctx.get("rag_results", []) or []))
            file_lens = [
                (
                    str(item[0] if isinstance(item, (tuple, list)) and item else ""),
                    len(
                        str(
                            item[1]
                            if isinstance(item, (tuple, list)) and len(item) > 1
                            else ""
                        ).strip()
                    ),
                )
                for item in list(ctx.get("file_contents", []) or [])[:6]
            ]
            _use_canvas, _use_rag, doc_selection = self.chat_dock.get_context_selection()
            selected_doc_names = [
                str(name or "").strip()
                for name, _ in list(doc_selection or [])
                if str(name or "").strip()
            ]
            return (
                False,
                "Kein verwertbarer Kontext ausgewählt.\n"
                f"(ctx: files={file_count}, rag={rag_count}, selected_text_len={selected_text_len}; "
                f"selected_docs={selected_doc_names[:6]}; file_lens={file_lens})",
            )

        return self._start_llm_side_task(
            task="glossary",
            payload={
                "context_text": context_text,
                "max_terms": 32,
            },
            status_message="Generiere Glossar aus Kontext…",
            done_cb=done_cb,
        )

    def _generate_mindmap_from_llm_context(
        self,
        ctx: dict,
        query_raw: str = "",
        mode_hint: str = "auto",
        done_cb=None,
    ) -> tuple[bool, str]:
        mode, query = self._resolve_mindmap_mode_and_query(
            query_raw,
            mode_hint=mode_hint,
        )

        if mode != "chunkmap" and not self.llm_manager.is_model_loaded():
            return False, "Kein Modell geladen. Bitte zuerst ein GGUF-Modell laden."
        if self._llm_side_task_active():
            return (
                False, "Es läuft bereits eine Hintergrundaufgabe."
            )
        if mode != "chunkmap" and self.llm_manager.worker.isRunning():
            return (
                False,
                "Das Modell ist gerade beschäftigt. Bitte erneut versuchen, "
                "wenn die aktuelle Generation fertig ist.",
            )

        context_text = self._build_context_text_from_llm_context(ctx)
        if not context_text:
            context_text = self._fallback_context_text_from_ctx(ctx)
        if not context_text:
            selected_text_len = len(str(ctx.get("selected_text", "") or "").strip())
            file_count = len(list(ctx.get("file_contents", []) or []))
            rag_count = len(list(ctx.get("rag_results", []) or []))
            file_lens = [
                (
                    str(item[0] if isinstance(item, (tuple, list)) and item else ""),
                    len(
                        str(
                            item[1]
                            if isinstance(item, (tuple, list)) and len(item) > 1
                            else ""
                        ).strip()
                    ),
                )
                for item in list(ctx.get("file_contents", []) or [])[:6]
            ]
            _use_canvas, _use_rag, doc_selection = self.chat_dock.get_context_selection()
            selected_doc_names = [
                str(name or "").strip()
                for name, _ in list(doc_selection or [])
                if str(name or "").strip()
            ]
            return (
                False,
                "Kein verwertbarer Kontext ausgewählt.\n"
                f"(ctx: files={file_count}, rag={rag_count}, selected_text_len={selected_text_len}; "
                f"selected_docs={selected_doc_names[:6]}; file_lens={file_lens})",
            )

        rag_cfg = self.rag_system.config

        return self._start_llm_side_task(
            task="mindmap",
            payload={
                "context_text": context_text,
                "query": query,
                "mode": mode,
                "max_nodes": 32,
                "chunking_strategy": str(
                    getattr(rag_cfg, "chunking_strategy", "sliding_window")
                    or "sliding_window"
                ),
                "chunk_size": int(getattr(rag_cfg, "chunk_size", 900) or 900),
                "chunk_overlap": int(getattr(rag_cfg, "chunk_overlap", 160) or 160),
            },
            status_message="Generiere MindMap/Graph/Chunk-MindMap aus Kontext…",
            done_cb=done_cb,
        )

    def _generate_glossary_from_context(self):
        def done(ok: bool, info: str):
            if ok:
                return
            QMessageBox.information(self, "Glossar", info)

        ok, info = self._generate_glossary_from_llm_context(
            self._build_llm_context(),
            done_cb=done,
        )
        if ok:
            return
        QMessageBox.information(self, "Glossar", info)

    def _generate_mindmap_from_context(self):
        mode_label, ok = QInputDialog.getItem(
            self,
            "MindMap/Graph/Chunk-MindMap generieren",
            "Ausgabeformat:",
            ["Chunk-MindMap", "MindMap", "Graph"],
            0,
            False,
        )
        if not ok:
            return
        normalized_mode_label = str(mode_label or "").strip().casefold()
        if normalized_mode_label == "graph":
            mode_hint = "graph"
        elif "chunk" in normalized_mode_label:
            mode_hint = "chunkmap"
        else:
            mode_hint = "mindmap"
        if mode_hint == "graph":
            default_prompt = (
                "Welche zentralen Entitäten und Beziehungen sind im Kontext belegt?"
            )
        elif mode_hint == "chunkmap":
            default_prompt = (
                "Wie ist der Kontext nach Überschriften und Chunks strukturiert?"
            )
        else:
            default_prompt = (
                "Welche zentralen Konzepte beantworten die Fragestellung im Kontext?"
            )
        query_raw, ok = QInputDialog.getMultiLineText(
            self,
            "MindMap/Graph/Chunk-MindMap generieren",
            "Fragestellung (optional):",
            default_prompt,
        )
        if not ok:
            return
        def done(success: bool, info: str):
            if success:
                return
            QMessageBox.information(self, "MindMap/Graph", info)

        ok, info = self._generate_mindmap_from_llm_context(
            self._build_llm_context(),
            str(query_raw or ""),
            mode_hint=mode_hint,
            done_cb=done,
        )
        if ok:
            return
        QMessageBox.information(self, "MindMap/Graph", info)

    # ──────────────────────────────────────────────────────────────────
    # Project save / load
    # ──────────────────────────────────────────────────────────────────

    def _save_project(self) -> bool:
        folder = QFileDialog.getExistingDirectory(
            self, "Save Project — choose or create a folder", "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return False
        self._autosave_flush_pending_preview_edits()
        if self._project_manager.save_project(self, folder):
            self.statusBar().showMessage(
                f"Project saved to: {folder}", 5000
            )
            self._autosave_schedule_full(delay_ms=250)
            return True
        return False

    def _load_project(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Load Project — select project folder", "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return
        self._autosave_suspended = True
        try:
            loaded = self._project_manager.load_project(self, folder)
        finally:
            self._autosave_suspended = False
        if loaded:
            self._autosave_rewire_editors()
            self._autosave_schedule_full(delay_ms=250)
            self.statusBar().showMessage(
                f"Project loaded from: {folder}", 5000
            )

    # ──────────────────────────────────────────────────────────────────
    # File import
    # ──────────────────────────────────────────────────────────────────

    def _open_import_dialog(self):
        dlg = FileImportDialog(
            self,
            user_mode=self._user_mode,
            feedback_service=self._feedback_service,
        )
        dlg.files_imported.connect(self._on_files_imported)
        dlg.exec()

    def _on_files_imported(self, results: list):
        """Slot: receives [(name, path, markdown), …] from FileImportDialog."""
        newly_added: list[tuple[str, str]] = []   # (display_name, markdown)

        for name, path, markdown in results:
            # Disambiguate display name if already registered
            display_name = name
            counter = 1
            while display_name in self._file_registry:
                stem, _, ext = name.rpartition(".")
                display_name = f"{stem} ({counter}).{ext}" if ext else f"{name} ({counter})"
                counter += 1
            self._file_registry[display_name] = (path, markdown)
            newly_added.append((display_name, markdown))

        self._update_loaded_menu()

        for display_name, markdown in newly_added:
            # Register in Files panel (triggers RAG reindex automatically)
            self.knowledge_dock.add_imported_file(display_name, markdown)
            # Open in Document Viewer
            self.knowledge_dock.open_content(display_name, markdown, doc_key=display_name)
            # Register in Chat context selector
            self.chat_dock.add_document(display_name, markdown)
        self._autosave_schedule_full(delay_ms=120)

    def _update_loaded_menu(self):
        """Rebuild the 'Loaded Documents' submenu from the file registry."""
        self._loaded_menu.clear()
        if not self._file_registry:
            self._loaded_menu.setEnabled(False)
            return
        self._loaded_menu.setEnabled(True)
        for display_name in self._file_registry:
            act = self._loaded_menu.addAction(display_name)
            # Capture display_name by value in the lambda
            act.triggered.connect(
                lambda checked=False, n=display_name: self._open_loaded_file(n)
            )

    def _open_loaded_file(self, display_name: str):
        """Re-open an already-imported file in the Knowledge Dock viewer."""
        entry = self._file_registry.get(display_name)
        if entry:
            _path, markdown = entry
            self.knowledge_dock.open_content(display_name, markdown, doc_key=display_name)

    @staticmethod
    def _unique_imported_name(
        desired: str,
        existing: set[str],
        current: str,
    ) -> str:
        target = str(desired or "").strip() or str(current or "").strip() or "Document"
        if target == current or target not in existing:
            return target

        stem, dot, ext = target.rpartition(".")
        root = stem if dot else target
        suffix = f".{ext}" if dot else ""

        idx = 1
        while True:
            candidate = f"{root} ({idx}){suffix}"
            if candidate not in existing or candidate == current:
                return candidate
            idx += 1

    def _resolve_imported_registry_key(self, name: str) -> str:
        """
        Resolve a user-visible document title to the actual registry key.

        Viewer tab titles may be extension-stripped (e.g. ``report`` instead of
        ``report.md``), while registry keys often keep the original filename.
        """
        key = str(name or "").strip()
        if not key:
            return ""

        if key in self._file_registry:
            return key

        key_low = key.casefold()
        for existing in self._file_registry.keys():
            raw = str(existing or "").strip()
            if raw.casefold() == key_low:
                return raw

        key_stem = os.path.splitext(key)[0].strip().casefold()
        if not key_stem:
            return ""

        for existing in self._file_registry.keys():
            raw = str(existing or "").strip()
            if not raw:
                continue
            raw_stem = os.path.splitext(raw)[0].strip().casefold()
            if raw_stem == key_stem:
                return raw
        return ""

    def _rename_imported_document(self, old_name: str, new_name: str):
        """Rename one imported document across viewer, RAG list, chat context and registry."""
        old_key = self._resolve_imported_registry_key(old_name)
        requested = str(new_name or "").strip()
        if not old_key or not requested or old_key == requested:
            return

        existing = set(self._file_registry.keys())
        existing.discard(old_key)
        final_name = self._unique_imported_name(requested, existing, old_key)

        entry = self._file_registry.pop(old_key)
        self._file_registry[final_name] = entry
        self._update_loaded_menu()

        # Keep all surfaces in sync with the same final display name.
        self.knowledge_dock.rename_viewer_document(old_key, final_name)
        self.knowledge_dock.rename_imported_file(old_key, final_name)
        self.chat_dock.rename_document(old_key, final_name)
        self._refresh_context_bar()

        if final_name != requested:
            self.statusBar().showMessage(
                f"Dokument umbenannt: '{requested}' bereits vergeben, nutze '{final_name}'.",
                5000,
            )
        else:
            self.statusBar().showMessage(
                f"Dokument umbenannt: {old_key} -> {final_name}",
                4000,
            )
        self._autosave_schedule_full(delay_ms=250)

    def _remove_imported_document(self, display_name: str):
        """Remove one imported document from all app surfaces."""
        key = str(display_name or "").strip()
        if not key:
            return

        existed = key in self._file_registry
        self._file_registry.pop(key, None)
        self._update_loaded_menu()

        # Remove from RAG file selector (also triggers reindex through selection_changed).
        self.knowledge_dock.remove_imported_file(key)
        # Remove all matching viewer tabs.
        self.knowledge_dock.remove_viewer_document(key)
        # Remove from chat context selector.
        self.chat_dock.remove_document(key)
        self._refresh_context_bar()

        if existed:
            self.statusBar().showMessage(
                f"Dokument entfernt: {key}. Für Nutzung bitte erneut importieren.",
                5000,
            )
            self._autosave_schedule_full(delay_ms=250)

    # ──────────────────────────────────────────────────────────────────
    # Whisper dictation
    # ──────────────────────────────────────────────────────────────────

    def _set_dictation_running(self, running: bool):
        if hasattr(self, "_action_start_dictation"):
            self._action_start_dictation.setEnabled(not running)
        if hasattr(self, "_action_stop_dictation"):
            self._action_stop_dictation.setEnabled(running)

    def _start_whisper_dictation(self):
        if self._dictation_worker is not None and self._dictation_worker.isRunning():
            self.statusBar().showMessage("Whisper-Diktat läuft bereits.", 2500)
            return

        stt = self._speech_settings
        input_device = str(stt.stt_input_device or "").strip()
        if (
            not input_device
            and os.name != "nt"
            and str(stt.stt_backend or "auto").strip().lower() != "sounddevice"
        ):
            input_device = "pipewire"
        threads = max(1, min(int(stt.stt_cpu_threads), os.cpu_count() or 4))

        self._open_new_dictation_target_tab()
        worker = WhisperDictationWorker(
            parent=self,
            model_size=stt.stt_model_size or "tiny",
            language=stt.stt_language or "",
            device="cpu",
            audio_device=input_device,
            audio_backend=stt.stt_backend or "auto",
            compute_type=stt.stt_compute_type or "int8",
            cpu_threads=threads,
        )
        worker.started_ok.connect(self._on_dictation_started)
        worker.stopped_ok.connect(self._on_dictation_stopped)
        worker.status.connect(self._on_dictation_status)
        worker.text_chunk.connect(self._on_dictation_text_chunk)
        worker.failed.connect(self._on_dictation_failed)
        worker.finished.connect(self._on_dictation_finished)
        self._dictation_worker = worker
        self._set_dictation_running(True)
        self.app_logger.info(
            "STT",
            "Config | "
            f"backend={stt.stt_backend} "
            f"input={input_device or 'auto'} "
            f"model={stt.stt_model_size} "
            f"lang={stt.stt_language or 'auto'} "
            f"compute={stt.stt_compute_type} "
            f"threads={threads}",
        )
        self.app_logger.info("STT", "Whisper-Diktat gestartet.")
        self.statusBar().showMessage("Starte Whisper-Diktat…", 2500)
        worker.start()

    def _stop_whisper_dictation(self):
        worker = self._dictation_worker
        if worker is None or not worker.isRunning():
            self._set_dictation_running(False)
            self.statusBar().showMessage("Whisper-Diktat ist nicht aktiv.", 2000)
            return
        worker.request_stop()
        self.statusBar().showMessage("Stoppe Whisper-Diktat…", 3000)

    def _on_dictation_started(self):
        self.statusBar().showMessage("Whisper-Diktat läuft.", 2500)

    def _on_dictation_status(self, message: str):
        text = str(message or "").strip()
        if text:
            self.app_logger.debug("STT", text)
            self.statusBar().showMessage(text, 4000)

    def _on_dictation_text_chunk(self, text: str):
        chunk = str(text or "").strip()
        if not chunk:
            return
        self.statusBar().showMessage(
            f"Whisper erkannt: {chunk[:60]}{'…' if len(chunk) > 60 else ''}",
            1800,
        )
        panel = self._ensure_dictation_target_panel()
        editor = getattr(panel, "editor", None)
        if editor is None:
            return

        cursor = editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        existing = editor.toPlainText()
        joiner = ""
        if existing and not existing.endswith((" ", "\n", "\t")):
            joiner = " "
        ending = "\n\n" if chunk.endswith((".", "!", "?", "…")) else " "
        cursor.insertText(f"{joiner}{chunk}{ending}")
        editor.setTextCursor(cursor)

    def _on_dictation_failed(self, message: str):
        msg = str(message or "Unbekannter Fehler im Whisper-Diktat.")
        self.app_logger.error("STT", msg)
        self.statusBar().showMessage(f"Whisper-Fehler: {msg}", 6000)
        QMessageBox.warning(
            self,
            "Whisper Dictation",
            msg,
        )
        self._set_dictation_running(False)
        self._dictation_worker = None

    def _on_dictation_stopped(self):
        self.app_logger.info("STT", "Whisper-Diktat gestoppt.")
        self.statusBar().showMessage("Whisper-Diktat gestoppt.", 3000)
        self._set_dictation_running(False)
        self._dictation_worker = None

    def _on_dictation_finished(self):
        worker = self._dictation_worker
        if worker is not None and worker.isRunning():
            return
        self._set_dictation_running(False)
        self._dictation_worker = None

    def _is_canvas_panel_open(self, panel: QWidget | None) -> bool:
        if panel is None:
            return False
        tabs = self.canvas.tabs.tab_widget
        for idx in range(tabs.count()):
            if tabs.widget(idx) is panel:
                return True
        return False

    def _open_new_dictation_target_tab(self) -> QWidget:
        tabs = self.canvas.tabs.tab_widget
        previous_idx = tabs.currentIndex()
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = f"Transkript {datetime.now().strftime('%H:%M')}"
        header = (
            f"# {title}\n\n"
            f"_Whisper-Session gestartet: {stamp}_\n\n"
        )
        panel = self.canvas.tabs.add_tab(
            title=title,
            content=header,
            read_only=False,
        )
        self._dictation_target_panel = panel
        if 0 <= previous_idx < tabs.count():
            tabs.setCurrentIndex(previous_idx)
        return panel

    def _ensure_dictation_target_panel(self) -> QWidget:
        if self._is_canvas_panel_open(self._dictation_target_panel):
            return self._dictation_target_panel  # type: ignore[return-value]
        return self._open_new_dictation_target_tab()

    def _open_speech_settings(self):
        dialog = SpeechSettingsDialog(self._speech_settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._speech_settings = dialog.get_settings()
        self._apply_speech_runtime_settings()
        self.app_logger.info(
            "STT",
            "Speech settings updated | "
            f"backend={self._speech_settings.stt_backend} "
            f"input={self._speech_settings.stt_input_device or 'auto'} "
            f"model={self._speech_settings.stt_model_size}",
        )
        self._autosave_schedule_full(delay_ms=300)
        self.statusBar().showMessage("Speech settings gespeichert.", 2500)

    def get_speech_settings(self) -> dict:
        return self._speech_settings.to_dict()

    def apply_speech_settings(self, raw: object):
        self._speech_settings = SpeechSettings.from_dict(raw)
        self._apply_speech_runtime_settings()

    def _apply_speech_runtime_settings(self):
        self._tts_manager.update_settings(self._speech_settings)
        if hasattr(self, "chat_dock"):
            self.chat_dock.set_chat_tts_mode(
                self._speech_settings.chat_tts_mode
            )

    def _speak_draft_text(self, text: str):
        payload = str(text or "").strip()
        if not payload:
            self.statusBar().showMessage("Draft ist leer.", 2000)
            return
        self._tts_manager.speak(payload, interrupt=True)

    def _speak_chat_text(self, text: str):
        payload = str(text or "").strip()
        if not payload:
            self.statusBar().showMessage("Keine Chat-Antwort zum Vorlesen.", 2000)
            return
        self._tts_manager.speak(payload, interrupt=True)

    def _stop_tts(self):
        if not self._tts_manager.is_speaking():
            self.statusBar().showMessage("TTS ist nicht aktiv.", 1500)
            return
        self._tts_manager.stop()
        self.statusBar().showMessage("TTS gestoppt.", 2500)

    def _on_chat_tts_mode_changed(self, mode: str):
        self._speech_settings.chat_tts_mode = str(mode or "off")
        self._autosave_schedule_full(delay_ms=350)

    def _on_tts_status(self, message: str):
        text = str(message or "").strip()
        if not text:
            return
        self.app_logger.debug("TTS", text)
        self.statusBar().showMessage(text, 2500)

    def _on_tts_error(self, message: str):
        text = str(message or "").strip() or "Unbekannter TTS-Fehler."
        self.app_logger.error("TTS", text)
        self.statusBar().showMessage(f"TTS-Fehler: {text}", 6000)
        QMessageBox.warning(self, "Text to Speech", text)

    def _on_tts_speaking_changed(self, speaking: bool):
        state = bool(speaking)
        self.canvas.set_read_aloud_active(state)
        self.chat_dock.set_read_aloud_active(state)

    # ──────────────────────────────────────────────────────────────────
    # Menu actions
    # ──────────────────────────────────────────────────────────────────

    def _focus_model_panel(self):
        self.chat_dock.show()
        self.chat_dock.raise_()
        self.chat_dock.set_model_panel_visible(True)
        self._sync_model_controls_toggle_action()

    def _reset_layout(self):
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,  self.knowledge_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.chat_dock)
        self.knowledge_dock.show()
        self.chat_dock.show()
        self.chat_dock.set_model_panel_visible(True)
        self.resizeDocks(
            [self.knowledge_dock, self.chat_dock],
            [340, 380],
            Qt.Orientation.Horizontal,
        )
        self._sync_model_controls_toggle_action()

    def _set_model_controls_visible(self, visible: bool):
        show_model = bool(visible)
        if show_model:
            self.chat_dock.show()
            self.chat_dock.raise_()
        self.chat_dock.set_model_panel_visible(show_model)
        self._sync_model_controls_toggle_action()

    def _sync_model_controls_toggle_action(self):
        action = getattr(self, "_model_controls_toggle_action", None)
        if action is None or not hasattr(self, "chat_dock"):
            return
        checked = bool(
            self.chat_dock.isVisible() and self.chat_dock.is_model_panel_visible()
        )
        blocked = action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(blocked)

    def _edit_system_prompt(self):
        if self._user_mode == USER_MODE_SIMPLE:
            QMessageBox.information(
                self,
                "Prompt Editor",
                "Im Einfach-Modus ist der Prompt-Editor ausgeblendet.\n"
                "Wechsle zu Plus oder Experte.",
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Prompts")
        dlg.resize(980, 700)
        dlg.setStyleSheet("background: palette(window); color: palette(window-text);")

        layout = QVBoxLayout(dlg)
        lbl = QLabel(
            "Prompt-Editor: System/User/Struktur-Prompts sind hier getrennt organisiert.\n"
            "System = Rollenregeln, User = Aufgabenblock, Struktur = Aufbau-/Titeltexte.\n"
            "Ablauf pro LLM-Aufruf: <|system|> + (optional Strukturblöcke) + <|user|>."
        )
        lbl.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        prompt_values = self.llm_manager.get_prompt_set()
        prompt_defaults = self.llm_manager.get_prompt_defaults()
        top_tabs = QTabWidget()
        top_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid palette(mid);
                border-radius: 4px;
                background: palette(base);
            }
            QTabBar::tab {
                background: palette(alternate-base);
                color: palette(text);
                padding: 6px 12px;
                border: 1px solid palette(mid);
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background: palette(base);
                color: palette(highlight);
            }
        """)

        prompt_specs = {
            "chat_system": {
                "group": "Chat",
                "title": "Chat: System",
                "kind": "System",
                "desc": "Globale Rolle und Antwortstil des Chat-Modells.",
            },
            "chat_grounding_rules": {
                "group": "Chat",
                "title": "Chat: Grounding-Regeln",
                "kind": "System",
                "desc": "Erzwingt dokumentgebundenes Antworten bei RAG/Datei-Kontext.",
                "placeholders": "{insufficient_message}, {citation_rule}",
            },
            "chat_canvas_rewrite_rules": {
                "group": "Chat",
                "title": "Draft: Rewrite-Regeln",
                "kind": "System",
                "desc": "Regeln für direktes Umschreiben einer Draft-Auswahl.",
                "placeholders": "{canvas_open}, {canvas_close}, {grounding_note}, {insufficient_message}",
            },
            "chat_citation_rule_answer": {
                "group": "Chat",
                "title": "Chat: Zitatregel Antwort",
                "kind": "Baustein",
                "desc": "Zusatzregel für normale Antworten im Grounding-Modus.",
            },
            "chat_citation_rule_rewrite": {
                "group": "Chat",
                "title": "Chat: Zitatregel Rewrite",
                "kind": "Baustein",
                "desc": "Zusatzregel für Draft-Rewrite im Grounding-Modus.",
            },
            "chat_grounding_note_rewrite": {
                "group": "Chat",
                "title": "Chat: Grounding-Hinweis Rewrite",
                "kind": "Baustein",
                "desc": "Wird in Rewrite-Regeln eingeblendet, wenn Quellenpflicht aktiv ist.",
            },
            "claim_extract_system": {
                "group": "Faktencheck",
                "title": "Claim Extract: System",
                "kind": "System",
                "desc": "Rolle für atomare Claim-Extraktion aus EINEM Eingabetext.",
            },
            "claim_extract_user": {
                "group": "Faktencheck",
                "title": "Claim Extract: User",
                "kind": "User",
                "desc": "Konkreter Auftrag für atomare Claim-Extraktion.",
                "placeholders": "{input_label}, {fact_limit}",
            },
            "fact_verify_system": {
                "group": "Faktencheck",
                "title": "Verify: System",
                "kind": "System",
                "desc": "Rolle für Einzel-Fakt-Prüfung gegen Quellen.",
            },
            "fact_verify_user": {
                "group": "Faktencheck",
                "title": "Verify: User",
                "kind": "User",
                "desc": "Konkreter Auftrag für eine einzelne Faktprüfung.",
                "placeholders": "{allowed_sources}, {fact}",
            },
            "nli_verify_system": {
                "group": "Faktencheck",
                "title": "NLI Verify: System",
                "kind": "System",
                "desc": "Workflow-Beschreibung für Transformers-NLI (Claim-vs-Chunk).",
            },
            "nli_verify_user": {
                "group": "Faktencheck",
                "title": "NLI Verify: User",
                "kind": "User",
                "desc": "Input-Template je Chunk/Fakt-Paar (premise/hypothesis).",
                "placeholders": "{premise}, {hypothesis}",
            },
            "hyde_tfidf_system": {
                "group": "RAG",
                "title": "HyDE TF-IDF: System",
                "kind": "System",
                "desc": "Rolle für Begriffserweiterung im TF-IDF-Backend.",
            },
            "hyde_tfidf_user": {
                "group": "RAG",
                "title": "HyDE TF-IDF: User",
                "kind": "User",
                "desc": "Auftrag zur Generierung von Literal-Suchbegriffen.",
                "placeholders": "{query}",
            },
            "hyde_st_single_system": {
                "group": "RAG",
                "title": "HyDE ST Single: System",
                "kind": "System",
                "desc": "Rolle für 1 hypothetischen Absatz (semantische Suche).",
            },
            "hyde_st_single_user": {
                "group": "RAG",
                "title": "HyDE ST Single: User",
                "kind": "User",
                "desc": "Auftrag für eine einzelne hypothetische Passage.",
                "placeholders": "{query}",
            },
            "hyde_st_multi_system": {
                "group": "RAG",
                "title": "HyDE ST Multi: System",
                "kind": "System",
                "desc": "Rolle für mehrere hypothetische Absätze.",
            },
            "hyde_st_multi_user": {
                "group": "RAG",
                "title": "HyDE ST Multi: User",
                "kind": "User",
                "desc": "Auftrag für Multi-Passage-HyDE.",
                "placeholders": "{query}, {n_hypotheses}",
            },
            "literal_terms_system": {
                "group": "RAG",
                "title": "Literal Terms: System",
                "kind": "System",
                "desc": "Rolle für LLM-gestützte Literal-Begriffe.",
            },
            "literal_terms_user": {
                "group": "RAG",
                "title": "Literal Terms: User",
                "kind": "User",
                "desc": "Auftrag zur Begriffsgenerierung für Literal Search.",
                "placeholders": "{query}, {max_terms}",
            },
            "rag_rerank_system": {
                "group": "RAG",
                "title": "Rerank: System",
                "kind": "System",
                "desc": "Rolle für Klassifikation von Treffern (sinnvoll/nicht_sinnvoll).",
            },
            "rag_rerank_user": {
                "group": "RAG",
                "title": "Rerank: User",
                "kind": "User",
                "desc": "Auftrag zum Bewerten einzelner RAG-Trefferlisten.",
                "placeholders": "{query}, {items}",
            },
            "mindmap_system": {
                "group": "MindMap",
                "title": "MindMap: System",
                "kind": "System",
                "desc": "Rolle für vereinfachte MindMap-Ausgabe aus Kontext.",
            },
            "mindmap_user": {
                "group": "MindMap",
                "title": "MindMap: User",
                "kind": "User",
                "desc": "Auftrag + Ausgabeformat für mehrstufige MindMap-Hierarchie mit Blatt-Zitaten.",
                "placeholders": "{context}, {query}, {max_nodes}",
            },
            "graph_system": {
                "group": "MindMap",
                "title": "Graph: System",
                "kind": "System",
                "desc": "Rolle für Wissensgraph-Ausgabe mit Relationen.",
            },
            "graph_user": {
                "group": "MindMap",
                "title": "Graph: User",
                "kind": "User",
                "desc": "Auftrag + Ausgabeformat für Tripel mit möglichst zusammenhängender Graph-Struktur.",
                "placeholders": "{context}, {query}, {max_nodes}",
            },
            "glossary_system": {
                "group": "Glossar",
                "title": "Glossar: System",
                "kind": "System",
                "desc": "Rolle für automatische Glossar-Extraktion aus Kontext.",
            },
            "glossary_user": {
                "group": "Glossar",
                "title": "Glossar: User",
                "kind": "User",
                "desc": "Auftrag + Ausgabeformat für Glossar-JSON.",
                "placeholders": "{context}, {max_terms}",
            },
            "chat_section_grounding_title": {
                "group": "Erweitert",
                "title": "Struktur: Grounding-Überschrift",
                "kind": "Struktur",
                "desc": "Abschnittsüberschrift im finalen Prompt vor Grounding-Regeln.",
            },
            "chat_section_rewrite_title": {
                "group": "Erweitert",
                "title": "Struktur: Rewrite-Überschrift",
                "kind": "Struktur",
                "desc": "Abschnittsüberschrift im Prompt vor Rewrite-Regeln.",
            },
            "chat_section_context_title": {
                "group": "Erweitert",
                "title": "Struktur: Kontext-Start",
                "kind": "Struktur",
                "desc": "Starttitel für den gesamten Kontextblock.",
            },
            "chat_section_context_end": {
                "group": "Erweitert",
                "title": "Struktur: Kontext-Ende",
                "kind": "Struktur",
                "desc": "Schließt den Kontextblock im Prompt ab.",
            },
            "chat_section_files_title": {
                "group": "Erweitert",
                "title": "Struktur: Dateien-Titel",
                "kind": "Struktur",
                "desc": "Titel vor angehängten Dokumenten im Kontextblock.",
            },
            "chat_section_rag_title": {
                "group": "Erweitert",
                "title": "Struktur: RAG-Titel",
                "kind": "Struktur",
                "desc": "Titel vor RAG-Auszügen im Kontextblock.",
            },
            "chat_section_selected_title": {
                "group": "Erweitert",
                "title": "Struktur: Auswahl-Titel",
                "kind": "Struktur",
                "desc": "Titel vor markierter Draft-Auswahl im Kontextblock.",
            },
            "fact_check_system": {
                "group": "Legacy",
                "title": "Legacy: FactCheck (ungenutzt)",
                "kind": "Legacy",
                "desc": "Derzeit nicht aktiv im Codepfad. Nur für Rückwärtskompatibilität alter Projekte.",
            },
        }
        group_order = (
            ["Chat", "Faktencheck", "Glossar", "MindMap"]
            if self._user_mode == USER_MODE_PLUS
            else ["Chat", "Faktencheck", "Glossar", "MindMap", "RAG", "Erweitert", "Legacy"]
        )
        grouped: dict[str, list[str]] = {g: [] for g in group_order}
        for key in self.llm_manager.PROMPT_KEYS:
            spec = prompt_specs.get(key, {})
            grp = str(spec.get("group", "Erweitert"))
            if grp not in grouped:
                grouped[grp] = []
            grouped[grp].append(key)

        def _simple_flow(system_key: str, user_key: str, extra: list[str] | None = None) -> str:
            lines = [
                "<|system|>",
                "{" + system_key + "}",
            ]
            if extra:
                lines.extend(extra)
            lines.extend([
                "<|user|>",
                "{" + user_key + "}",
                "<|assistant|>",
            ])
            return "\n".join(lines)

        def _flow_preview_for_key(key: str) -> str:
            if key in {
                "chat_system",
                "chat_grounding_rules",
                "chat_canvas_rewrite_rules",
                "chat_citation_rule_answer",
                "chat_citation_rule_rewrite",
                "chat_grounding_note_rewrite",
                "chat_section_grounding_title",
                "chat_section_rewrite_title",
                "chat_section_context_title",
                "chat_section_context_end",
                "chat_section_files_title",
                "chat_section_rag_title",
                "chat_section_selected_title",
            }:
                return "\n".join([
                    "Beispiel-Flow (Chat):",
                    "<|system|>",
                    "{chat_system}",
                    "{chat_section_grounding_title}        # optional bei dokumentgebundenem Modus",
                    "{chat_grounding_rules}",
                    "{chat_section_rewrite_title}          # optional bei Draft-Rewrite",
                    "{chat_canvas_rewrite_rules}",
                    "{chat_section_context_title}          # optional wenn Kontext vorhanden",
                    "{chat_section_files_title}",
                    "{chat_section_rag_title}",
                    "{chat_section_selected_title}",
                    "{chat_section_context_end}",
                    "<|user|>",
                    "[Nutzeranfrage]",
                    "<|assistant|>",
                ])

            if key.startswith("claim_extract_"):
                return "\n".join([
                    "Beispiel-Flow (Faktencheck: Claim-Extraktion):",
                    "<|system|>",
                    "{claim_extract_system}",
                    "<|user|>",
                    "{claim_extract_user}   # mit {input_label}, {fact_limit}",
                    "<|assistant|>",
                ])
            if key.startswith("fact_verify_"):
                return "\n".join([
                    "Beispiel-Flow (Faktencheck: Verifikation):",
                    "<|system|>",
                    "{fact_verify_system}",
                    "<|user|>",
                    "{fact_verify_user}    # mit {allowed_sources}, {fact}",
                    "<|assistant|>",
                ])
            if key.startswith("nli_verify_"):
                return "\n".join([
                    "Beispiel-Flow (Faktencheck: NLI via Transformers):",
                    "Wird pro Fakt über alle Quell-Chunks iteriert.",
                    "[backend=transformers-cross-encoder]",
                    "<|workflow|>",
                    "{nli_verify_system}",
                    "<|input|>",
                    "{nli_verify_user}     # mit {premise}, {hypothesis}",
                ])
            if key == "fact_check_system":
                return "\n".join([
                    "Legacy-Hinweis:",
                    "Dieser Prompt ist aktuell nicht im aktiven Ablauf verdrahtet.",
                    "Aktiv genutzt werden stattdessen:",
                    "- claim_extract_system + claim_extract_user",
                    "- fact_verify_system + fact_verify_user",
                    "- nli_verify_system + nli_verify_user (wenn NLI aktiv)",
                ])

            if key.startswith("hyde_tfidf_"):
                return _simple_flow("hyde_tfidf_system", "hyde_tfidf_user")
            if key.startswith("hyde_st_single_"):
                return _simple_flow("hyde_st_single_system", "hyde_st_single_user")
            if key.startswith("hyde_st_multi_"):
                return _simple_flow("hyde_st_multi_system", "hyde_st_multi_user")
            if key.startswith("literal_terms_"):
                return _simple_flow("literal_terms_system", "literal_terms_user")
            if key.startswith("rag_rerank_"):
                return _simple_flow("rag_rerank_system", "rag_rerank_user")
            if key.startswith("mindmap_"):
                return _simple_flow("mindmap_system", "mindmap_user")
            if key.startswith("graph_"):
                return _simple_flow("graph_system", "graph_user")
            if key.startswith("glossary_"):
                return _simple_flow("glossary_system", "glossary_user")

            return "\n".join([
                "Beispiel-Flow:",
                "<|system|>",
                "{system_prompt}",
                "<|user|>",
                "{user_prompt}",
                "<|assistant|>",
            ])

        editors: dict[str, QTextEdit] = {}
        group_tabs: dict[str, QTabWidget] = {}
        group_keys: dict[str, list[str]] = {}
        tab_style_inner = """
            QTabWidget::pane {
                border: 1px solid palette(mid);
                border-radius: 4px;
                background: palette(base);
            }
            QTabBar::tab {
                background: palette(alternate-base);
                color: palette(text);
                padding: 5px 10px;
                border: 1px solid palette(mid);
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background: palette(base);
                color: palette(highlight);
            }
        """
        editor_style = """
            QTextEdit {
                background: palette(base); color: palette(text);
                border: 1px solid palette(mid); border-radius: 4px;
                padding: 6px; font-size: 11px;
            }
        """

        for group in group_order:
            keys = grouped.get(group, [])
            if not keys:
                continue

            group_page = QWidget()
            group_layout = QVBoxLayout(group_page)
            group_layout.setContentsMargins(8, 8, 8, 8)
            group_layout.setSpacing(8)

            info = QLabel(
                "Nur diese Prompts werden direkt in die jeweiligen LLM-Aufrufe übernommen."
                if group != "Legacy"
                else "Legacy-Prompts sind nur für alte Projekte vorhanden und aktuell nicht aktiv verdrahtet."
            )
            info.setWordWrap(True)
            info.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
            group_layout.addWidget(info)

            inner_tabs = QTabWidget()
            inner_tabs.setStyleSheet(tab_style_inner)

            group_keys[group] = []
            for key in keys:
                spec = prompt_specs.get(key, {})
                title = str(spec.get("title", key))
                kind = str(spec.get("kind", "Prompt"))
                desc = str(spec.get("desc", "")).strip()
                placeholders = str(spec.get("placeholders", "")).strip()

                tab = QWidget()
                tab_layout = QVBoxLayout(tab)
                tab_layout.setContentsMargins(8, 8, 8, 8)
                tab_layout.setSpacing(6)

                meta_lines = [f"Typ: {kind}"]
                if desc:
                    meta_lines.append(f"Verwendung: {desc}")
                if placeholders:
                    meta_lines.append(f"Platzhalter: {placeholders}")
                # Explain how paired system/user prompts work together in one call.
                pair_hint = ""
                if key.endswith("_system"):
                    partner = key[:-7] + "_user"
                    if partner in prompt_values:
                        pair_hint = (
                            f"Zusammenhang: Wird zusammen mit '{partner}' "
                            "im selben LLM-Aufruf verwendet "
                            "(Regeln im System-Block, Auftrag im User-Block)."
                        )
                elif key.endswith("_user"):
                    partner = key[:-5] + "_system"
                    if partner in prompt_values:
                        pair_hint = (
                            f"Zusammenhang: Nutzt die Leitplanken aus '{partner}' "
                            "im selben LLM-Aufruf "
                            "(dieser Prompt liefert den konkreten Auftrag)."
                        )
                if pair_hint:
                    meta_lines.append(pair_hint)
                meta = QLabel("\n".join(meta_lines))
                meta.setWordWrap(True)
                meta.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
                tab_layout.addWidget(meta)

                flow_lbl = QLabel("Prompt-Flow-Vorschau")
                flow_lbl.setStyleSheet("color: palette(highlight); font-size: 10px; font-weight: bold;")
                tab_layout.addWidget(flow_lbl)

                flow_view = QTextEdit()
                flow_view.setReadOnly(True)
                flow_view.setStyleSheet("""
                    QTextEdit {
                        background: palette(base); color: palette(placeholder-text);
                        border: 1px solid palette(mid); border-radius: 4px;
                        padding: 6px; font-size: 10px;
                    }
                """)
                flow_view.setPlainText(_flow_preview_for_key(key))
                flow_view.setMaximumHeight(170)
                tab_layout.addWidget(flow_view)

                editor = QTextEdit()
                editor.setPlainText(prompt_values.get(key, ""))
                editor.setStyleSheet(editor_style)
                tab_layout.addWidget(editor, 1)

                inner_tabs.addTab(tab, title)
                editors[key] = editor
                group_keys[group].append(key)

            group_layout.addWidget(inner_tabs, 1)
            top_tabs.addTab(group_page, group)
            group_tabs[group] = inner_tabs

        layout.addWidget(top_tabs, 1)

        reset_btn = QPushButton("Reset Current To Default")
        reset_group_btn = QPushButton("Reset Group To Default")
        reset_all_btn = QPushButton("Reset All To Default")
        reset_btn.setStyleSheet(
            "QPushButton{background:palette(alternate-base);color:palette(text);border:none;border-radius:4px;padding:6px 10px;}"
            "QPushButton:hover{border:1px solid palette(highlight);}"
        )
        reset_group_btn.setStyleSheet(
            "QPushButton{background:palette(alternate-base);color:palette(text);border:none;border-radius:4px;padding:6px 10px;}"
            "QPushButton:hover{border:1px solid palette(highlight);}"
        )
        reset_all_btn.setStyleSheet(
            "QPushButton{background:palette(alternate-base);color:palette(text);border:none;border-radius:4px;padding:6px 10px;}"
            "QPushButton:hover{border:1px solid palette(highlight);}"
        )

        def _current_key() -> str | None:
            gidx = top_tabs.currentIndex()
            if gidx < 0:
                return None
            group = top_tabs.tabText(gidx)
            inner = group_tabs.get(group)
            keys = group_keys.get(group, [])
            if inner is None:
                return None
            iidx = inner.currentIndex()
            if iidx < 0 or iidx >= len(keys):
                return None
            return keys[iidx]

        def _reset_current_prompt():
            key = _current_key()
            if not key:
                return
            ed = editors.get(key)
            if ed is not None:
                ed.setPlainText(prompt_defaults.get(key, ""))
        reset_btn.clicked.connect(_reset_current_prompt)

        def _reset_current_group():
            gidx = top_tabs.currentIndex()
            if gidx < 0:
                return
            group = top_tabs.tabText(gidx)
            for key in group_keys.get(group, []):
                ed = editors.get(key)
                if ed is not None:
                    ed.setPlainText(prompt_defaults.get(key, ""))
        reset_group_btn.clicked.connect(_reset_current_group)

        def _reset_all():
            for key, ed in editors.items():
                ed.setPlainText(prompt_defaults.get(key, ""))
        reset_all_btn.clicked.connect(_reset_all)

        action_row = QHBoxLayout()
        action_row.addWidget(reset_btn)
        action_row.addWidget(reset_group_btn)
        action_row.addWidget(reset_all_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_prompts = self.llm_manager.get_prompt_set()
            for key, editor in editors.items():
                new_prompts[key] = editor.toPlainText()
            self.llm_manager.set_prompt_set(new_prompts)
            self._autosave_schedule_full(delay_ms=300)

    def _open_rag_settings(self):
        dlg = RAGSettingsDialog(self.rag_system.config, self, user_mode=self._user_mode)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            old_model = self.rag_system.config.st_model_name
            new_cfg   = dlg.get_config()
            self.rag_system.config = new_cfg
            # If ST requested and model not loaded (or name changed), load it
            if new_cfg.use_st:
                if (self.rag_system._st_model is None
                        or new_cfg.st_model_name != old_model):
                    try:
                        self.knowledge_dock.rag_worker.st_loaded.disconnect(
                            self._on_st_loaded
                        )
                    except RuntimeError:
                        pass
                    self.knowledge_dock.rag_worker.st_loaded.connect(
                        self._on_st_loaded
                    )
                    self.knowledge_dock.rag_worker.enqueue_load_st(
                        new_cfg.st_model_name
                    )
            # Re-chunk and re-index with the new config
            self.knowledge_dock.reindex_rag()
            self.app_logger.info(
                "SYS",
                f"RAG reconfigured"
                f"  |  backends={self.rag_system.current_backend()}"
                f"  |  strategy={new_cfg.chunking_strategy}"
                f"  |  mode={new_cfg.selection_mode}  top_k={new_cfg.top_k}"
                f"  |  chunk={new_cfg.chunk_size}  overlap={new_cfg.chunk_overlap}"
                f"  |  headings={'on' if new_cfg.include_headings else 'off'}"
                f"  filename={'on' if new_cfg.include_filename else 'off'}"
                f"  hyde={'on' if new_cfg.use_hyde else 'off'}"
                f"  extended={'on' if new_cfg.extended_context else 'off'}"
                f"  regex={'on' if new_cfg.use_regex_search else 'off'}"
                f"  literal_llm={'on' if new_cfg.literal_use_llm_terms else 'off'}"
                f"  rerank={'on' if new_cfg.llm_rerank_enabled else 'off'}",
            )
            self.statusBar().showMessage(
                f"RAG re-indexed  ·  strategy: {new_cfg.chunking_strategy}"
                f"  ·  chunks: {new_cfg.chunk_size} chars"
                f"  ·  backends: {self.rag_system.current_backend()}",
                4000,
            )
            self._autosave_schedule_full(delay_ms=350)

    def _try_sentence_transformers(self):
        model_name = self.rag_system.config.st_model_name
        # Mark intent in config so current_backend() reflects it after load
        self.rag_system.config.use_st = True
        worker = self.knowledge_dock.rag_worker
        # Disconnect any previous one-shot connection to avoid duplicate dialogs
        try:
            worker.st_loaded.disconnect(self._on_st_loaded)
        except RuntimeError:
            pass
        worker.st_loaded.connect(self._on_st_loaded)
        worker.enqueue_load_st(model_name)
        self._autosave_schedule_full(delay_ms=350)

    @property
    def user_mode(self) -> str:
        return self._user_mode

    def set_user_mode(self, mode: str, notify: bool = True):
        normalized = normalize_user_mode(mode)
        self._user_mode = normalized

        if hasattr(self, "chat_dock"):
            self.chat_dock.set_user_mode(normalized)
        if hasattr(self, "log_dock"):
            self.log_dock.set_user_mode(normalized)

        if hasattr(self, "_action_edit_prompts"):
            self._action_edit_prompts.setVisible(normalized != USER_MODE_SIMPLE)

        if hasattr(self, "_log_toggle_action"):
            show_log = normalized != USER_MODE_SIMPLE
            self._log_toggle_action.setVisible(show_log)
            if not show_log and hasattr(self, "log_dock"):
                self.log_dock.hide()

        for mode_key, act in self._mode_actions.items():
            blocked = act.blockSignals(True)
            act.setChecked(mode_key == normalized)
            act.blockSignals(blocked)

        if hasattr(self, "_mode_lbl"):
            self._mode_lbl.setText(f"mode: {USER_MODE_LABELS[normalized]}")

        if notify and self.statusBar():
            self.statusBar().showMessage(
                f"Nutzermodus: {USER_MODE_LABELS[normalized]}",
                2500,
            )
            self._autosave_schedule_full(delay_ms=500)

    def _on_st_loaded(self, ok: bool):
        if ok:
            QMessageBox.information(
                self, "RAG Backend",
                "✓ sentence-transformers loaded.\n"
                "RAG now uses semantic (cosine-similarity) embeddings.",
            )
        else:
            QMessageBox.warning(
                self, "RAG Backend",
                "sentence-transformers not available — using TF-IDF.\n\n"
                "Install with:\n  pip install sentence-transformers",
            )

    def _show_shortcuts(self):
        QMessageBox.information(self, "Keyboard Shortcuts", """\
Ctrl+N         New canvas tab
Ctrl+O         Open file in canvas
Ctrl+S         Save current canvas tab
Ctrl+I         Import files

Ctrl+1         Toggle Knowledge Dock
Ctrl+2         Toggle AI Chat Dock
Ctrl+3         Toggle Debug Log
Ctrl+4         Toggle Model Load + Generation

Ctrl+Tab       Nächster Draft-Tab
Ctrl+Shift+Tab Vorheriger Draft-Tab
Ctrl+F         Suchen/Ersetzen im aktiven Editor
Alt+1          Ansicht: nur Markdown
Alt+2          Ansicht: nur HTML
Alt+3          Ansicht: Split (Markdown + HTML)
Ctrl+Alt+S     Auto-Save ein/aus

Ctrl+=         Aktive Ansicht größer
Ctrl+-         Aktive Ansicht kleiner
Ctrl+0         Aktive Ansicht auf 100%
Ctrl+Mausrad   Zoomen in fokussierter Markdown- oder HTML-Ansicht

Ctrl+Enter     Send chat message
Ctrl+.         Stop AI generation

Dock usage
──────────
• Drag dock title bars to float or re-dock them.
• Use View > Reset Layout to restore defaults.
""")

    # ──────────────────────────────────────────────────────────────────
    # Feedback
    # ──────────────────────────────────────────────────────────────────

    _FEEDBACK_SETTINGS_KEY = "feedback/"

    def _load_feedback_settings(self) -> FeedbackSettings:
        raw = {
            "ui_enabled": self._app_settings.value(
                self._FEEDBACK_SETTINGS_KEY + "ui_enabled", True
            ),
            "capture_payload_enabled": self._app_settings.value(
                self._FEEDBACK_SETTINGS_KEY + "capture_payload_enabled", True
            ),
            "storage_dir": self._app_settings.value(
                self._FEEDBACK_SETTINGS_KEY + "storage_dir", "runs/feedback"
            ),
        }
        return FeedbackSettings.from_dict(raw)

    def _save_feedback_settings(self, settings: FeedbackSettings):
        self._feedback_settings = settings
        self._feedback_service.update_settings(settings)
        self._app_settings.setValue(
            self._FEEDBACK_SETTINGS_KEY + "ui_enabled", bool(settings.ui_enabled)
        )
        self._app_settings.setValue(
            self._FEEDBACK_SETTINGS_KEY + "capture_payload_enabled",
            bool(settings.capture_payload_enabled),
        )
        self._app_settings.setValue(
            self._FEEDBACK_SETTINGS_KEY + "storage_dir", str(settings.storage_dir or "")
        )
        self._app_settings.sync()

    def _open_feedback_settings(self):
        dlg = FeedbackSettingsDialog(self._feedback_settings, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._save_feedback_settings(dlg.get_settings())
            self.statusBar().showMessage("Feedback-Einstellungen gespeichert.", 3000)

    def _open_feedback_stats(self):
        dlg = FeedbackStatsDialog(self._feedback_service, parent=self)
        dlg.exec()

    def _open_freeform_feedback(self):
        dlg = FeedbackFreeformDialog(self._feedback_service, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.statusBar().showMessage("Feedback gespeichert. Danke!", 3000)

    def _on_status_feedback(self, sentiment: str, tags: list, note: str):
        use_case = "other"
        bar = getattr(self, "_glossary_feedback_bar", None)
        if bar is not None:
            use_case = str(getattr(bar, "_use_case", "") or "").strip() or "other"
        payload = (
            dict(self._status_feedback_payload)
            if isinstance(self._status_feedback_payload, dict)
            else None
        )
        self._feedback_service.submit_feedback(
            use_case=use_case,
            sentiment=sentiment,
            payload=payload,
            error_tags=tags or None,
            note=note,
        )

    def _show_about(self):
        QMessageBox.about(self, "About draft2craift", """\
<h2>draft2craift</h2>
<p><i>Document Retrieval Augmented File Tool 2 Collaboratively Revised AI Formatted Text</i></p>
<p>A PySide6 application for LLM-assisted writing with local GGUF models.</p>
<ul>
  <li>GGUF inference via <b>llama-cpp-python</b></li>
  <li>RAG with TF-IDF (or <b>sentence-transformers</b>)</li>
  <li>Markdown syntax highlighting</li>
  <li>Flexible floating-dock UI</li>
</ul>
<p><small>Built with PySide6 &amp; llama-cpp-python</small></p>
""")

    # ──────────────────────────────────────────────────────────────────
    # Welcome content
    # ──────────────────────────────────────────────────────────────────

    def _show_welcome(self):
        welcome = """\
# Welcome to draft2craift

This tab is your writing workspace.
draft2craift is a local-first writing studio with a Markdown editor, AI chat, and RAG support.

---

## What is Markdown?

Markdown is a lightweight markup language for structured text.

Examples:

```md
# Heading 1
## Heading 2

**bold**, *italic*, `code`

- Item 1
- Item 2

[Link text](https://example.com)
```

---

## Getting started

1. **Write in the Draft workspace**
   - Use this tab as your main document.
   - Open additional tabs via `+ New`.

2. **Import files**
   - `File > Import Files…` or `Ctrl+I`
   - PDF, DOCX, HTML, CSV, TXT and more are converted to Markdown.

3. **Load a model**
   - `AI > Load GGUF Model…`
   - Select a GGUF model file, set parameters, then load.

4. **Work with AI**
   - Type in the **AI Chat** on the right and send with `Ctrl+Enter`.
   - Optionally rewrite selected Draft text directly with the LLM.

5. **Use RAG**
   - Select files in the **RAG** tab on the left, run a search, use the results as context.

6. **Save / Export**
   - `Ctrl+S` saves the current tab.
   - Export as PDF or Word via `File > Export`.

7. **HTML preview**
   - Use tab right-click to switch between HTML-only,
     Markdown-only, or split view.

---

## Tips

- `↶` / `↷` buttons for Undo / Redo.
- Panels can be freely docked and detached.
- `View > Reset Layout` restores the default layout.

---

Happy writing.
"""
        panel = self.canvas.tabs.current_panel()
        if panel:
            panel.editor.setPlainText(welcome)

    # ──────────────────────────────────────────────────────────────────
    # Cleanup
    # ──────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        choice = QMessageBox.question(
            self,
            "Projekt speichern?",
            "Möchtest du das aktuelle Projekt vor dem Beenden speichern?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )

        if choice == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return

        if choice == QMessageBox.StandardButton.Save and not self._save_project():
            event.ignore()
            return

        if self._llm_side_task_active():
            QMessageBox.information(
                self,
                "Bitte warten",
                "Es läuft noch eine Glossar/MindMap/Graph-Generierung.\n"
                "Bitte warten, bis die Aufgabe abgeschlossen ist.",
            )
            event.ignore()
            return

        self._persist_preview_page_margin_settings()
        self._persist_theme_id(self.get_theme_id())
        self._autosave_flush_before_close()

        # Stop Whisper dictation
        if self._dictation_worker is not None:
            self._dictation_worker.request_stop()
            self._dictation_worker.wait(3000)
        if hasattr(self, "_tts_manager"):
            self._tts_manager.stop()

        # Stop LLM generation
        llm_worker = self.llm_manager.worker
        if llm_worker.isRunning():
            llm_worker.request_stop()
            llm_worker.wait(3000)
        # Stop RAG background worker
        self.knowledge_dock.rag_worker.stop_and_wait(5000)
        event.accept()
