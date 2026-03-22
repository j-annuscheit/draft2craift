"""Menu bar builder with explicit dependencies instead of MainWindow internals."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QMainWindow

from shared.domain.user_mode import available_user_modes, user_mode_label
from shared.services.highlights.store import get_highlight_store
from studio.canvas.preview.pane import CanvasPreviewPane
from studio.theme import available_themes


@dataclass(slots=True)
class MenuBuildInputs:
    """Explicit ports required to build the application menu bar."""

    host: QMainWindow
    canvas: object
    knowledge_dock: object
    chat_dock: object
    log_dock: object
    llm_stop: Callable[[], None]
    user_mode_changed: Callable[[str], None]
    apply_theme_id: Callable[[object], None]
    apply_preview_theme_id: Callable[[object], None]
    bind_feature_visibility: Callable[[object, str, bool], None]
    bind_feature_label: Callable[[object, str, str], None]
    action_handlers: Mapping[str, Callable[..., object]]
    theme_ctrl: object
    speech_ctrl: object
    autosave_enabled: bool


@dataclass(slots=True)
class MenuBuildResult:
    """Action references produced during menu construction."""

    loaded_menu: object
    log_toggle_action: QAction
    model_controls_toggle_action: QAction
    mode_group: QActionGroup
    mode_actions: dict[str, QAction]
    theme_group: QActionGroup
    theme_actions: dict[str, QAction]
    action_page_margin_enabled: QAction
    page_margin_group: QActionGroup
    page_margin_actions: list[tuple[float, QAction]]
    preview_theme_group: QActionGroup
    preview_theme_actions: dict[str, QAction]
    action_glossary_overlay: QAction
    action_autosave_toggle: QAction
    action_edit_prompts: QAction
    action_start_dictation: QAction
    action_stop_dictation: QAction


def build_menubar(inputs: MenuBuildInputs) -> MenuBuildResult:
    """Populate the menu bar using only explicit dependencies."""
    host = inputs.host
    bar = host.menuBar()

    def _require_handler(name: str) -> Callable[..., object]:
        fn = inputs.action_handlers.get(name)
        if not callable(fn):
            raise RuntimeError(f"Missing menu action handler: {name}")
        return fn

    def _bind_menu(menu, key: str, label: str) -> None:
        action = menu.menuAction()
        inputs.bind_feature_visibility(action, key, True)
        inputs.bind_feature_label(action, key, label)

    def _bind_action(
        action: QAction,
        key: str,
        label: str,
        *,
        visible_default: bool = True,
    ) -> None:
        inputs.bind_feature_visibility(action, key, bool(visible_default))
        inputs.bind_feature_label(action, key, label)

    def _add_action(menu, label: str, shortcut: str, slot, key: str) -> QAction:
        action = QAction(label, host)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        _bind_action(action, key, label)
        return action

    # ── File ──────────────────────────────────────────────────────────
    file_menu = bar.addMenu("&File")
    _bind_menu(file_menu, "menu.file", "&File")

    _add_action(
        file_menu,
        "New Draft Tab",
        "Ctrl+N",
        lambda: inputs.canvas.tabs.add_tab(),
        "menu.file.new_tab",
    )
    _add_action(
        file_menu,
        "Open File…",
        "Ctrl+O",
        inputs.canvas.open_file,
        "menu.file.open_file",
    )
    _add_action(file_menu, "Save", "Ctrl+S", inputs.canvas.save_current, "menu.file.save")
    _add_action(
        file_menu,
        "Export Current Canvas…",
        "",
        _require_handler("export_active_canvas_document"),
        "menu.file.export_canvas",
    )
    file_menu.addSeparator()
    _add_action(
        file_menu,
        "Save Project Folder…",
        "Ctrl+Shift+S",
        _require_handler("save_project"),
        "menu.file.save_project",
    )
    _add_action(
        file_menu,
        "Load Project Folder…",
        "Ctrl+Shift+O",
        _require_handler("load_project"),
        "menu.file.load_project",
    )
    _add_action(
        file_menu,
        "Export Project (.d2c)…",
        "",
        _require_handler("export_project_archive"),
        "menu.file.export_project_archive",
    )
    _add_action(
        file_menu,
        "Import Project (.d2c)…",
        "",
        _require_handler("import_project_archive"),
        "menu.file.import_project_archive",
    )
    file_menu.addSeparator()
    _add_action(
        file_menu,
        "Import Files…",
        "Ctrl+I",
        _require_handler("open_import_dialog"),
        "menu.file.import_files",
    )
    file_menu.addSeparator()
    loaded_menu = file_menu.addMenu("Loaded Documents")
    _bind_menu(loaded_menu, "menu.file.loaded_documents_menu", "Loaded Documents")
    loaded_menu.setEnabled(False)
    file_menu.addSeparator()
    _add_action(file_menu, "Quit", "Ctrl+Q", host.close, "menu.file.quit")

    # ── View ──────────────────────────────────────────────────────────
    view_menu = bar.addMenu("&View")
    _bind_menu(view_menu, "menu.view", "&View")

    tk = inputs.knowledge_dock.toggleViewAction()
    tk.setText("Knowledge Dock")
    tk.setShortcut(QKeySequence("Ctrl+1"))
    tk.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    _bind_action(tk, "menu.view.knowledge_dock", "Knowledge Dock")

    tc = inputs.chat_dock.toggleViewAction()
    tc.setText("AI Chat Dock")
    tc.setShortcut(QKeySequence("Ctrl+2"))
    tc.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    _bind_action(tc, "menu.view.chat_dock", "AI Chat Dock")

    tl = inputs.log_dock.toggleViewAction()
    tl.setText("Debug Log")
    tl.setShortcut(QKeySequence("Ctrl+3"))
    tl.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    _bind_action(tl, "menu.view.debug_log", "Debug Log")

    view_menu.addAction(tk)
    view_menu.addAction(tc)
    view_menu.addAction(tl)

    act_model = QAction("Model Load + Generation", host)
    act_model.setCheckable(True)
    act_model.setChecked(True)
    act_model.setShortcut(QKeySequence("Ctrl+4"))
    act_model.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    act_model.toggled.connect(_require_handler("set_model_controls_visible"))
    _bind_action(act_model, "menu.view.model_controls", "Model Load + Generation")
    view_menu.addAction(act_model)

    mode_menu = view_menu.addMenu("Nutzermodus")
    _bind_menu(mode_menu, "menu.view.user_mode", "Nutzermodus")
    mode_group = QActionGroup(host)
    mode_group.setExclusive(True)
    mode_actions: dict[str, QAction] = {}
    for mode in available_user_modes():
        act = QAction(user_mode_label(mode), host)
        act.setCheckable(True)
        act.triggered.connect(lambda checked=False, m=mode: inputs.user_mode_changed(m))
        mode_group.addAction(act)
        mode_menu.addAction(act)
        mode_actions[mode] = act

    theme_menu = view_menu.addMenu("Theme")
    _bind_menu(theme_menu, "menu.view.theme", "Theme")
    theme_group = QActionGroup(host)
    theme_group.setExclusive(True)
    theme_actions: dict[str, QAction] = {}
    for theme_id, label in available_themes():
        act = QAction(label, host)
        act.setCheckable(True)
        act.triggered.connect(
            lambda _checked=False, t=theme_id: inputs.apply_theme_id(t)
        )
        _bind_action(
            act,
            f"menu.view.theme.option.{theme_id}",
            str(label),
        )
        theme_group.addAction(act)
        theme_menu.addAction(act)
        theme_actions[theme_id] = act
    inputs.theme_ctrl.sync_theme_actions(theme_actions)

    view_menu.addSeparator()
    text_size_menu = view_menu.addMenu("Textgröße")
    _bind_menu(text_size_menu, "menu.view.text_size", "Textgröße")
    _add_action(
        text_size_menu,
        "Aktive Ansicht größer",
        "Ctrl+=",
        _require_handler("increase_active_text_size"),
        "menu.view.text_size.active_increase",
    )
    _add_action(
        text_size_menu,
        "Aktive Ansicht kleiner",
        "Ctrl+-",
        _require_handler("decrease_active_text_size"),
        "menu.view.text_size.active_decrease",
    )
    _add_action(
        text_size_menu,
        "Aktive Ansicht Standard (100%)",
        "Ctrl+0",
        _require_handler("reset_active_text_size"),
        "menu.view.text_size.active_reset",
    )
    text_size_menu.addSeparator()
    _add_action(
        text_size_menu,
        "HTML-Vorschau größer",
        "",
        _require_handler("increase_preview_text_size"),
        "menu.view.text_size.preview_increase",
    )
    _add_action(
        text_size_menu,
        "HTML-Vorschau kleiner",
        "",
        _require_handler("decrease_preview_text_size"),
        "menu.view.text_size.preview_decrease",
    )
    _add_action(
        text_size_menu,
        "HTML-Vorschau Standard (100%)",
        "",
        _require_handler("reset_preview_text_size"),
        "menu.view.text_size.preview_reset",
    )

    page_margin_menu = view_menu.addMenu("Seitenrand")
    _bind_menu(page_margin_menu, "menu.view.page_margin", "Seitenrand")
    act_margin = QAction("Seitenrand aktiv", host)
    act_margin.setCheckable(True)
    act_margin.triggered.connect(inputs.theme_ctrl.toggle_preview_page_margin_enabled)
    _bind_action(act_margin, "menu.view.page_margin.enabled", "Seitenrand aktiv")
    page_margin_menu.addAction(act_margin)
    page_margin_menu.addSeparator()
    page_margin_group = QActionGroup(host)
    page_margin_group.setExclusive(True)
    page_margin_actions: list[tuple[float, QAction]] = []
    for label, em_value in CanvasPreviewPane._PAGE_MARGIN_PRESETS:
        action = QAction(str(label), host)
        action.setCheckable(True)
        action.triggered.connect(
            lambda _checked=False, em=float(em_value): inputs.theme_ctrl.set_preview_page_margin_preset(em)
        )
        _bind_action(
            action,
            f"menu.view.page_margin.preset.{float(em_value):g}",
            str(label),
        )
        page_margin_group.addAction(action)
        page_margin_menu.addAction(action)
        page_margin_actions.append((float(em_value), action))
    inputs.theme_ctrl.sync_preview_page_margin_actions(
        act_margin,
        page_margin_actions,
    )

    preview_theme_menu = view_menu.addMenu("HTML-Stil")
    _bind_menu(preview_theme_menu, "menu.view.preview_theme", "HTML-Stil")
    preview_theme_group = QActionGroup(host)
    preview_theme_group.setExclusive(True)
    preview_theme_actions: dict[str, QAction] = {}
    for theme_id, label in CanvasPreviewPane.preview_theme_options():
        action = QAction(str(label), host)
        action.setCheckable(True)
        action.triggered.connect(
            lambda _checked=False, t=theme_id: inputs.apply_preview_theme_id(t)
        )
        _bind_action(
            action,
            f"menu.view.preview_theme.option.{theme_id}",
            str(label),
        )
        preview_theme_group.addAction(action)
        preview_theme_menu.addAction(action)
        preview_theme_actions[str(theme_id)] = action
    inputs.theme_ctrl.sync_preview_theme_actions(preview_theme_actions)

    view_menu.addSeparator()
    act_glossary = QAction("Glossar-Overlay anzeigen", host)
    act_glossary.setCheckable(True)
    act_glossary.setChecked(get_highlight_store().is_glossary_enabled())
    act_glossary.triggered.connect(_require_handler("toggle_glossary_overlays"))
    _bind_action(act_glossary, "menu.view.glossary_overlay", "Glossar-Overlay anzeigen")
    view_menu.addAction(act_glossary)
    _add_action(
        view_menu,
        "Glossar verwalten…",
        "",
        _require_handler("open_glossary_editor"),
        "menu.view.glossary_manage",
    )
    view_menu.addSeparator()
    _add_action(
        view_menu,
        "Reset Layout",
        "",
        _require_handler("reset_layout"),
        "menu.view.reset_layout",
    )

    # ── Einstellungen ─────────────────────────────────────────────────
    settings_menu = bar.addMenu("&Einstellungen")
    _bind_menu(settings_menu, "menu.settings", "&Einstellungen")

    act_autosave = QAction("Autosave-Projekt aktivieren", host)
    act_autosave.setCheckable(True)
    act_autosave.setChecked(bool(inputs.autosave_enabled))
    act_autosave.triggered.connect(_require_handler("toggle_autosave_enabled"))
    _bind_action(act_autosave, "menu.settings.autosave_toggle", "Autosave-Projekt aktivieren")
    settings_menu.addAction(act_autosave)
    _add_action(
        settings_menu,
        "Project Variables…",
        "",
        _require_handler("open_project_variables"),
        "menu.settings.project_variables",
    )

    settings_menu.addSeparator()
    _add_action(
        settings_menu,
        "Feedback geben…",
        "",
        _require_handler("open_freeform_feedback"),
        "menu.settings.feedback_form",
    )
    _add_action(
        settings_menu,
        "Feedback Statistik…",
        "",
        _require_handler("open_feedback_stats"),
        "menu.settings.feedback_stats",
    )
    settings_menu.addSeparator()
    _add_action(
        settings_menu,
        "Feedback Einstellungen…",
        "",
        _require_handler("open_feedback_settings"),
        "menu.settings.feedback_settings",
    )

    # ── AI ────────────────────────────────────────────────────────────
    ai_menu = bar.addMenu("&AI")
    _bind_menu(ai_menu, "menu.ai", "&AI")
    _add_action(ai_menu, "Load GGUF Model…", "", _require_handler("focus_model_panel"), "menu.ai.focus_model_panel")
    _add_action(ai_menu, "Stop Generation", "Ctrl+.", inputs.llm_stop, "menu.ai.stop_generation")
    ai_menu.addSeparator()
    action_edit_prompts = _add_action(
        ai_menu,
        "Edit Prompts…",
        "",
        _require_handler("edit_system_prompt"),
        "menu.ai.edit_prompts",
    )
    _add_action(
        ai_menu,
        "Generate Glossary From Context",
        "",
        _require_handler("generate_glossary_from_context"),
        "menu.ai.generate_glossary",
    )
    _add_action(
        ai_menu,
        "Generate MindMap/Graph From Context",
        "",
        _require_handler("generate_mindmap_from_context"),
        "menu.ai.generate_mindmap",
    )
    ai_menu.addSeparator()
    _add_action(
        ai_menu,
        "Enable sentence-transformers RAG",
        "",
        _require_handler("try_sentence_transformers"),
        "menu.ai.enable_st_rag",
    )
    _add_action(ai_menu, "RAG Settings…", "", _require_handler("open_rag_settings"), "menu.ai.rag_settings")
    _add_action(ai_menu, "Speech Settings…", "", _require_handler("open_speech_settings"), "menu.ai.speech_settings")
    _add_action(
        ai_menu,
        "Agentic Workflow Settings…",
        "",
        _require_handler("open_agentic_settings"),
        "menu.ai.agentic_settings",
    )
    _add_action(
        ai_menu,
        "Read Active Selection/Document",
        "",
        _require_handler("speak_active_workspace_text"),
        "menu.ai.read_active_workspace_text",
    )
    _add_action(
        ai_menu,
        "Stop Read Aloud",
        "",
        _require_handler("stop_tts"),
        "menu.ai.stop_read_aloud",
    )
    ai_menu.addSeparator()
    action_start_dictation = _add_action(
        ai_menu,
        "Start Whisper Dictation",
        "",
        _require_handler("start_whisper_dictation"),
        "menu.ai.start_dictation",
    )
    action_stop_dictation = _add_action(
        ai_menu,
        "Stop Whisper Dictation",
        "",
        _require_handler("stop_whisper_dictation"),
        "menu.ai.stop_dictation",
    )
    action_stop_dictation.setEnabled(False)
    inputs.speech_ctrl.dictation_running_changed.connect(
        _require_handler("on_dictation_running_changed")
    )

    # ── Help ──────────────────────────────────────────────────────────
    help_menu = bar.addMenu("&Help")
    _bind_menu(help_menu, "menu.help", "&Help")
    _add_action(help_menu, "Keyboard Shortcuts", "", _require_handler("show_shortcuts"), "menu.help.shortcuts")
    _add_action(help_menu, "About draft2craift", "", _require_handler("show_about"), "menu.help.about")
    _require_handler("apply_window_chrome_theme")()

    return MenuBuildResult(
        loaded_menu=loaded_menu,
        log_toggle_action=tl,
        model_controls_toggle_action=act_model,
        mode_group=mode_group,
        mode_actions=mode_actions,
        theme_group=theme_group,
        theme_actions=theme_actions,
        action_page_margin_enabled=act_margin,
        page_margin_group=page_margin_group,
        page_margin_actions=page_margin_actions,
        preview_theme_group=preview_theme_group,
        preview_theme_actions=preview_theme_actions,
        action_glossary_overlay=act_glossary,
        action_autosave_toggle=act_autosave,
        action_edit_prompts=action_edit_prompts,
        action_start_dictation=action_start_dictation,
        action_stop_dictation=action_stop_dictation,
    )


__all__ = [
    "MenuBuildInputs",
    "MenuBuildResult",
    "build_menubar",
]
