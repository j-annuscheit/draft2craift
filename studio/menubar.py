"""Menu bar builder for MainWindow."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QMainWindow

from shared.domain.user_mode import USER_MODE_LABELS, USER_MODE_ORDER
from shared.services.highlights.store import get_highlight_store
from studio.canvas.preview.pane import CanvasPreviewPane
from studio.theme import available_themes


def build_menubar(window: QMainWindow) -> None:
    """Populate window's menu bar and store action references on window."""
    bar = window.menuBar()

    # ── File ──────────────────────────────────────────────────────────
    file_menu = bar.addMenu("&File")
    window._add_action(file_menu, "New Draft Tab", "Ctrl+N", lambda: window.canvas.tabs.add_tab())
    window._add_action(file_menu, "Open File…", "Ctrl+O", window.canvas.open_file)
    window._add_action(file_menu, "Save", "Ctrl+S", window.canvas.save_current)
    window._add_action(file_menu, "Export Current Canvas…", "", window._export_active_canvas_document)
    file_menu.addSeparator()
    window._add_action(file_menu, "Save Project…", "Ctrl+Shift+S", window._save_project)
    window._add_action(file_menu, "Load Project…", "Ctrl+Shift+O", window._load_project)
    file_menu.addSeparator()
    window._add_action(file_menu, "Import Files…", "Ctrl+I", window._open_import_dialog)
    file_menu.addSeparator()
    window._loaded_menu = file_menu.addMenu("Loaded Documents")
    window._loaded_menu.setEnabled(False)
    file_menu.addSeparator()
    window._add_action(file_menu, "Quit", "Ctrl+Q", window.close)

    # ── View ──────────────────────────────────────────────────────────
    view_menu = bar.addMenu("&View")
    tk = window.knowledge_dock.toggleViewAction()
    tk.setText("Knowledge Dock")
    tk.setShortcut(QKeySequence("Ctrl+1"))
    tk.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    tc = window.chat_dock.toggleViewAction()
    tc.setText("AI Chat Dock")
    tc.setShortcut(QKeySequence("Ctrl+2"))
    tc.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    tl = window.log_dock.toggleViewAction()
    tl.setText("Debug Log")
    tl.setShortcut(QKeySequence("Ctrl+3"))
    tl.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    window._log_toggle_action = tl
    view_menu.addAction(tk)
    view_menu.addAction(tc)
    view_menu.addAction(tl)
    act_model = QAction("Model Load + Generation", window)
    act_model.setCheckable(True)
    act_model.setChecked(True)
    act_model.setShortcut(QKeySequence("Ctrl+4"))
    act_model.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    act_model.toggled.connect(window._set_model_controls_visible)
    window._model_controls_toggle_action = act_model
    view_menu.addAction(act_model)
    window._sync_model_controls_toggle_action()

    mode_menu = view_menu.addMenu("Nutzermodus")
    window._mode_group = QActionGroup(window)
    window._mode_group.setExclusive(True)
    for mode in USER_MODE_ORDER:
        act = QAction(USER_MODE_LABELS[mode], window)
        act.setCheckable(True)
        act.triggered.connect(lambda checked=False, m=mode: window.set_user_mode(m))
        window._mode_group.addAction(act)
        mode_menu.addAction(act)
        window._mode_actions[mode] = act

    theme_menu = view_menu.addMenu("Theme")
    window._theme_group = QActionGroup(window)
    window._theme_group.setExclusive(True)
    for theme_id, label in available_themes():
        act = QAction(label, window)
        act.setCheckable(True)
        act.triggered.connect(
            lambda _checked=False, t=theme_id: window.apply_theme_id(t, persist=True)
        )
        window._theme_group.addAction(act)
        theme_menu.addAction(act)
        window._theme_actions[theme_id] = act
    window._theme_ctrl.sync_theme_actions(window._theme_actions)

    view_menu.addSeparator()
    text_size_menu = view_menu.addMenu("Textgröße")
    window._add_action(text_size_menu, "Aktive Ansicht größer", "Ctrl+=", window._increase_active_text_size)
    window._add_action(text_size_menu, "Aktive Ansicht kleiner", "Ctrl+-", window._decrease_active_text_size)
    window._add_action(text_size_menu, "Aktive Ansicht Standard (100%)", "Ctrl+0", window._reset_active_text_size)
    text_size_menu.addSeparator()
    window._add_action(text_size_menu, "HTML-Vorschau größer", "", window._increase_preview_text_size)
    window._add_action(text_size_menu, "HTML-Vorschau kleiner", "", window._decrease_preview_text_size)
    window._add_action(text_size_menu, "HTML-Vorschau Standard (100%)", "", window._reset_preview_text_size)

    page_margin_menu = view_menu.addMenu("Seitenrand")
    act_margin = QAction("Seitenrand aktiv", window)
    act_margin.setCheckable(True)
    act_margin.triggered.connect(window._theme_ctrl.toggle_preview_page_margin_enabled)
    window._action_page_margin_enabled = act_margin
    page_margin_menu.addAction(act_margin)
    page_margin_menu.addSeparator()
    window._page_margin_group = QActionGroup(window)
    window._page_margin_group.setExclusive(True)
    window._page_margin_actions = []
    for label, em_value in CanvasPreviewPane._PAGE_MARGIN_PRESETS:
        action = QAction(str(label), window)
        action.setCheckable(True)
        action.triggered.connect(
            lambda _checked=False, em=float(em_value): window._theme_ctrl.set_preview_page_margin_preset(em)
        )
        window._page_margin_group.addAction(action)
        page_margin_menu.addAction(action)
        window._page_margin_actions.append((float(em_value), action))
    window._theme_ctrl.sync_preview_page_margin_actions(
        window._action_page_margin_enabled, window._page_margin_actions
    )

    preview_theme_menu = view_menu.addMenu("HTML-Stil")
    window._preview_theme_group = QActionGroup(window)
    window._preview_theme_group.setExclusive(True)
    for theme_id, label in CanvasPreviewPane.preview_theme_options():
        action = QAction(str(label), window)
        action.setCheckable(True)
        action.triggered.connect(
            lambda _checked=False, t=theme_id: window.apply_preview_theme_id(t)
        )
        window._preview_theme_group.addAction(action)
        preview_theme_menu.addAction(action)
        window._preview_theme_actions[str(theme_id)] = action
    window._theme_ctrl.sync_preview_theme_actions(window._preview_theme_actions)

    view_menu.addSeparator()
    act_glossary = QAction("Glossar-Overlay anzeigen", window)
    act_glossary.setCheckable(True)
    act_glossary.setChecked(get_highlight_store().is_glossary_enabled())
    act_glossary.triggered.connect(window._toggle_glossary_overlays)
    window._action_glossary_overlay = act_glossary
    view_menu.addAction(act_glossary)
    window._add_action(view_menu, "Glossar verwalten…", "", window._open_glossary_editor)
    view_menu.addSeparator()
    window._add_action(view_menu, "Reset Layout", "", window._reset_layout)

    # ── Einstellungen ─────────────────────────────────────────────────
    settings_menu = bar.addMenu("&Einstellungen")
    act_autosave = QAction("Autosave-Projekt aktivieren", window)
    act_autosave.setCheckable(True)
    act_autosave.setChecked(window._autosave_ctrl.enabled)
    act_autosave.triggered.connect(window._toggle_autosave_enabled)
    window._action_autosave_toggle = act_autosave
    settings_menu.addAction(act_autosave)
    settings_menu.addSeparator()
    window._add_action(settings_menu, "Feedback geben…", "", window._open_freeform_feedback)
    window._add_action(settings_menu, "Feedback Statistik…", "", window._open_feedback_stats)
    settings_menu.addSeparator()
    window._add_action(settings_menu, "Feedback Einstellungen…", "", window._open_feedback_settings)

    # ── AI ────────────────────────────────────────────────────────────
    ai_menu = bar.addMenu("&AI")
    window._add_action(ai_menu, "Load GGUF Model…", "", window._focus_model_panel)
    window._add_action(ai_menu, "Stop Generation", "Ctrl+.", window.llm_manager.stop)
    ai_menu.addSeparator()
    window._action_edit_prompts = window._add_action(
        ai_menu, "Edit Prompts…", "", window._edit_system_prompt
    )
    window._add_action(ai_menu, "Generate Glossary From Context", "", window._generate_glossary_from_context)
    window._add_action(ai_menu, "Generate MindMap/Graph From Context", "", window._generate_mindmap_from_context)
    ai_menu.addSeparator()
    window._add_action(ai_menu, "Enable sentence-transformers RAG", "", window._try_sentence_transformers)
    window._add_action(ai_menu, "RAG Settings…", "", window._open_rag_settings)
    window._add_action(ai_menu, "Speech Settings…", "", window._open_speech_settings)
    ai_menu.addSeparator()
    window._action_start_dictation = window._add_action(
        ai_menu, "Start Whisper Dictation", "", window._start_whisper_dictation
    )
    window._action_stop_dictation = window._add_action(
        ai_menu, "Stop Whisper Dictation", "", window._stop_whisper_dictation
    )
    window._action_stop_dictation.setEnabled(False)
    window._speech_ctrl.dictation_running_changed.connect(window._on_dictation_running_changed)

    # ── Help ──────────────────────────────────────────────────────────
    help_menu = bar.addMenu("&Help")
    window._add_action(help_menu, "Keyboard Shortcuts", "", window._show_shortcuts)
    window._add_action(help_menu, "About draft2craift", "", window._show_about)
    window._apply_window_chrome_theme()
