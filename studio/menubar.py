"""Menu bar builder for MainWindow."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QMainWindow

from shared.domain.user_mode import available_user_modes, user_mode_label
from shared.services.highlights.store import get_highlight_store
from studio.canvas.preview.pane import CanvasPreviewPane
from studio.theme import available_themes


def build_menubar(window: QMainWindow) -> None:
    """Populate window's menu bar and store action references on window."""
    bar = window.menuBar()

    def _bind_menu(menu, key: str, label: str):
        action = menu.menuAction()
        window._bind_feature_visibility(action, key, default=True)
        window._bind_feature_label(action, key, label)

    def _bind_action(action: QAction, key: str, label: str, *, visible_default: bool = True):
        window._bind_feature_visibility(action, key, default=bool(visible_default))
        window._bind_feature_label(action, key, label)

    def _add_action(menu, label: str, shortcut: str, slot, key: str):
        return window._add_action(
            menu,
            label,
            shortcut,
            slot,
            visibility_key=key,
            visible_default=True,
            label_key=key,
            label_default=label,
        )

    # ── File ──────────────────────────────────────────────────────────
    file_menu = bar.addMenu("&File")
    _bind_menu(file_menu, "menu.file", "&File")

    _add_action(
        file_menu,
        "New Draft Tab",
        "Ctrl+N",
        lambda: window.canvas.tabs.add_tab(),
        "menu.file.new_tab",
    )
    _add_action(
        file_menu,
        "Open File…",
        "Ctrl+O",
        window.canvas.open_file,
        "menu.file.open_file",
    )
    _add_action(file_menu, "Save", "Ctrl+S", window.canvas.save_current, "menu.file.save")
    _add_action(
        file_menu,
        "Export Current Canvas…",
        "",
        window._export_active_canvas_document,
        "menu.file.export_canvas",
    )
    file_menu.addSeparator()
    _add_action(
        file_menu,
        "Save Project Folder…",
        "Ctrl+Shift+S",
        window._save_project,
        "menu.file.save_project",
    )
    _add_action(
        file_menu,
        "Load Project Folder…",
        "Ctrl+Shift+O",
        window._load_project,
        "menu.file.load_project",
    )
    _add_action(
        file_menu,
        "Export Project (.d2c)…",
        "",
        window._export_project_archive,
        "menu.file.export_project_archive",
    )
    _add_action(
        file_menu,
        "Import Project (.d2c)…",
        "",
        window._import_project_archive,
        "menu.file.import_project_archive",
    )
    file_menu.addSeparator()
    _add_action(
        file_menu,
        "Import Files…",
        "Ctrl+I",
        window._open_import_dialog,
        "menu.file.import_files",
    )
    file_menu.addSeparator()
    window._loaded_menu = file_menu.addMenu("Loaded Documents")
    _bind_menu(window._loaded_menu, "menu.file.loaded_documents_menu", "Loaded Documents")
    window._loaded_menu.setEnabled(False)
    file_menu.addSeparator()
    _add_action(file_menu, "Quit", "Ctrl+Q", window.close, "menu.file.quit")

    # ── View ──────────────────────────────────────────────────────────
    view_menu = bar.addMenu("&View")
    _bind_menu(view_menu, "menu.view", "&View")

    tk = window.knowledge_dock.toggleViewAction()
    tk.setText("Knowledge Dock")
    tk.setShortcut(QKeySequence("Ctrl+1"))
    tk.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    _bind_action(tk, "menu.view.knowledge_dock", "Knowledge Dock")

    tc = window.chat_dock.toggleViewAction()
    tc.setText("AI Chat Dock")
    tc.setShortcut(QKeySequence("Ctrl+2"))
    tc.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    _bind_action(tc, "menu.view.chat_dock", "AI Chat Dock")

    tl = window.log_dock.toggleViewAction()
    tl.setText("Debug Log")
    tl.setShortcut(QKeySequence("Ctrl+3"))
    tl.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    _bind_action(tl, "menu.view.debug_log", "Debug Log")

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
    _bind_action(act_model, "menu.view.model_controls", "Model Load + Generation")
    window._model_controls_toggle_action = act_model
    view_menu.addAction(act_model)
    window._sync_model_controls_toggle_action()

    mode_menu = view_menu.addMenu("Nutzermodus")
    _bind_menu(mode_menu, "menu.view.user_mode", "Nutzermodus")
    window._mode_group = QActionGroup(window)
    window._mode_group.setExclusive(True)
    for mode in available_user_modes():
        act = QAction(user_mode_label(mode), window)
        act.setCheckable(True)
        act.triggered.connect(lambda checked=False, m=mode: window.set_user_mode(m))
        window._mode_group.addAction(act)
        mode_menu.addAction(act)
        window._mode_actions[mode] = act

    theme_menu = view_menu.addMenu("Theme")
    _bind_menu(theme_menu, "menu.view.theme", "Theme")
    window._theme_group = QActionGroup(window)
    window._theme_group.setExclusive(True)
    for theme_id, label in available_themes():
        act = QAction(label, window)
        act.setCheckable(True)
        act.triggered.connect(
            lambda _checked=False, t=theme_id: window.apply_theme_id(t, persist=True)
        )
        _bind_action(
            act,
            f"menu.view.theme.option.{theme_id}",
            str(label),
        )
        window._theme_group.addAction(act)
        theme_menu.addAction(act)
        window._theme_actions[theme_id] = act
    window._theme_ctrl.sync_theme_actions(window._theme_actions)

    view_menu.addSeparator()
    text_size_menu = view_menu.addMenu("Textgröße")
    _bind_menu(text_size_menu, "menu.view.text_size", "Textgröße")
    _add_action(
        text_size_menu,
        "Aktive Ansicht größer",
        "Ctrl+=",
        window._increase_active_text_size,
        "menu.view.text_size.active_increase",
    )
    _add_action(
        text_size_menu,
        "Aktive Ansicht kleiner",
        "Ctrl+-",
        window._decrease_active_text_size,
        "menu.view.text_size.active_decrease",
    )
    _add_action(
        text_size_menu,
        "Aktive Ansicht Standard (100%)",
        "Ctrl+0",
        window._reset_active_text_size,
        "menu.view.text_size.active_reset",
    )
    text_size_menu.addSeparator()
    _add_action(
        text_size_menu,
        "HTML-Vorschau größer",
        "",
        window._increase_preview_text_size,
        "menu.view.text_size.preview_increase",
    )
    _add_action(
        text_size_menu,
        "HTML-Vorschau kleiner",
        "",
        window._decrease_preview_text_size,
        "menu.view.text_size.preview_decrease",
    )
    _add_action(
        text_size_menu,
        "HTML-Vorschau Standard (100%)",
        "",
        window._reset_preview_text_size,
        "menu.view.text_size.preview_reset",
    )

    page_margin_menu = view_menu.addMenu("Seitenrand")
    _bind_menu(page_margin_menu, "menu.view.page_margin", "Seitenrand")
    act_margin = QAction("Seitenrand aktiv", window)
    act_margin.setCheckable(True)
    act_margin.triggered.connect(window._theme_ctrl.toggle_preview_page_margin_enabled)
    _bind_action(act_margin, "menu.view.page_margin.enabled", "Seitenrand aktiv")
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
        _bind_action(
            action,
            f"menu.view.page_margin.preset.{float(em_value):g}",
            str(label),
        )
        window._page_margin_group.addAction(action)
        page_margin_menu.addAction(action)
        window._page_margin_actions.append((float(em_value), action))
    window._theme_ctrl.sync_preview_page_margin_actions(
        window._action_page_margin_enabled, window._page_margin_actions
    )

    preview_theme_menu = view_menu.addMenu("HTML-Stil")
    _bind_menu(preview_theme_menu, "menu.view.preview_theme", "HTML-Stil")
    window._preview_theme_group = QActionGroup(window)
    window._preview_theme_group.setExclusive(True)
    for theme_id, label in CanvasPreviewPane.preview_theme_options():
        action = QAction(str(label), window)
        action.setCheckable(True)
        action.triggered.connect(
            lambda _checked=False, t=theme_id: window.apply_preview_theme_id(t)
        )
        _bind_action(
            action,
            f"menu.view.preview_theme.option.{theme_id}",
            str(label),
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
    _bind_action(act_glossary, "menu.view.glossary_overlay", "Glossar-Overlay anzeigen")
    window._action_glossary_overlay = act_glossary
    view_menu.addAction(act_glossary)
    _add_action(
        view_menu,
        "Glossar verwalten…",
        "",
        window._open_glossary_editor,
        "menu.view.glossary_manage",
    )
    view_menu.addSeparator()
    _add_action(view_menu, "Reset Layout", "", window._reset_layout, "menu.view.reset_layout")

    # ── Einstellungen ─────────────────────────────────────────────────
    settings_menu = bar.addMenu("&Einstellungen")
    _bind_menu(settings_menu, "menu.settings", "&Einstellungen")

    act_autosave = QAction("Autosave-Projekt aktivieren", window)
    act_autosave.setCheckable(True)
    act_autosave.setChecked(window._autosave_ctrl.enabled)
    act_autosave.triggered.connect(window._toggle_autosave_enabled)
    _bind_action(act_autosave, "menu.settings.autosave_toggle", "Autosave-Projekt aktivieren")
    window._action_autosave_toggle = act_autosave
    settings_menu.addAction(act_autosave)

    settings_menu.addSeparator()
    _add_action(
        settings_menu,
        "Feedback geben…",
        "",
        window._open_freeform_feedback,
        "menu.settings.feedback_form",
    )
    _add_action(
        settings_menu,
        "Feedback Statistik…",
        "",
        window._open_feedback_stats,
        "menu.settings.feedback_stats",
    )
    settings_menu.addSeparator()
    _add_action(
        settings_menu,
        "Feedback Einstellungen…",
        "",
        window._open_feedback_settings,
        "menu.settings.feedback_settings",
    )

    # ── AI ────────────────────────────────────────────────────────────
    ai_menu = bar.addMenu("&AI")
    _bind_menu(ai_menu, "menu.ai", "&AI")
    _add_action(ai_menu, "Load GGUF Model…", "", window._focus_model_panel, "menu.ai.focus_model_panel")
    _add_action(ai_menu, "Stop Generation", "Ctrl+.", window.llm_manager.stop, "menu.ai.stop_generation")
    ai_menu.addSeparator()
    window._action_edit_prompts = _add_action(
        ai_menu,
        "Edit Prompts…",
        "",
        window._edit_system_prompt,
        "menu.ai.edit_prompts",
    )
    _add_action(
        ai_menu,
        "Generate Glossary From Context",
        "",
        window._generate_glossary_from_context,
        "menu.ai.generate_glossary",
    )
    _add_action(
        ai_menu,
        "Generate MindMap/Graph From Context",
        "",
        window._generate_mindmap_from_context,
        "menu.ai.generate_mindmap",
    )
    ai_menu.addSeparator()
    _add_action(
        ai_menu,
        "Enable sentence-transformers RAG",
        "",
        window._try_sentence_transformers,
        "menu.ai.enable_st_rag",
    )
    _add_action(ai_menu, "RAG Settings…", "", window._open_rag_settings, "menu.ai.rag_settings")
    _add_action(ai_menu, "Speech Settings…", "", window._open_speech_settings, "menu.ai.speech_settings")
    ai_menu.addSeparator()
    window._action_start_dictation = _add_action(
        ai_menu,
        "Start Whisper Dictation",
        "",
        window._start_whisper_dictation,
        "menu.ai.start_dictation",
    )
    window._action_stop_dictation = _add_action(
        ai_menu,
        "Stop Whisper Dictation",
        "",
        window._stop_whisper_dictation,
        "menu.ai.stop_dictation",
    )
    window._action_stop_dictation.setEnabled(False)
    window._speech_ctrl.dictation_running_changed.connect(window._on_dictation_running_changed)

    # ── Help ──────────────────────────────────────────────────────────
    help_menu = bar.addMenu("&Help")
    _bind_menu(help_menu, "menu.help", "&Help")
    _add_action(help_menu, "Keyboard Shortcuts", "", window._show_shortcuts, "menu.help.shortcuts")
    _add_action(help_menu, "About draft2craift", "", window._show_about, "menu.help.about")
    window._apply_window_chrome_theme()
