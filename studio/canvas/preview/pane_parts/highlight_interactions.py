"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403


def _normalize_tab_label(value: object) -> str:
    text = str(value or "").strip()
    if text.startswith("🔒 "):
        text = text[2:].strip()
    return text


def _target_tabs_from_record(target: dict) -> list[str]:
    scope = str(target.get("tab_scope", "") or "tabs").strip().lower()
    if scope != "tabs":
        return []
    return [
        _normalize_tab_label(item)
        for item in list(target.get("tabs", []) or [])
        if _normalize_tab_label(item)
    ]


def _tab_match_indices(tabbed: object, preferred_titles: list[str]) -> list[int]:
    tab_widget = getattr(tabbed, "tab_widget", None)
    if tab_widget is None:
        return []
    wanted = [_normalize_tab_label(item) for item in list(preferred_titles or []) if _normalize_tab_label(item)]
    if not wanted:
        return []
    getter = getattr(tabbed, "get_tab_full_title", None)
    bar = tab_widget.tabBar()
    out: list[int] = []
    for idx in range(tab_widget.count()):
        variants = {
            _normalize_tab_label(tab_widget.tabText(idx)),
            _normalize_tab_label(bar.tabData(idx)),
        }
        if callable(getter):
            try:
                variants.add(_normalize_tab_label(getter(idx)))
            except Exception:
                pass
        if any(item in variants for item in wanted):
            out.append(idx)
    return out


def _open_highlight_context_menu(self, global_pos: QPoint):
    menu = self._view.createStandardContextMenu()

    vp_pos = self._view.viewport().mapFromGlobal(global_pos)
    cursor_at_pos = self._view.cursorForPosition(vp_pos)
    selected_text = self.get_selected_text().strip()
    active_span = self._span_at_position(cursor_at_pos.position())

    if menu.actions():
        menu.addSeparator()

    create_actions: dict = {}
    read_aloud_action = None
    if selected_text and is_feature_visible(
        getattr(self, "_user_mode", ""),
        "editor.context.read_aloud_selection",
        default=True,
    ):
        read_aloud_action = menu.addAction(
            resolve_feature_label(
                getattr(self, "_user_mode", ""),
                "editor.context.read_aloud_selection",
                "🔊 Vorlesen",
            )
        )
        current_menu = menu.addMenu("Markieren (aktueller Tab)")
        all_tabs_menu = menu.addMenu("Markieren (alle Tabs)")
        for label, color in self._HIGHLIGHT_COLORS:
            current_action = current_menu.addAction(label)
            all_action = all_tabs_menu.addAction(label)
            create_actions[current_action] = (color, False)
            create_actions[all_action] = (color, True)

    edit_actions: dict = {}
    if active_span is not None:
        menu.addSeparator()

        is_glossary = str(active_span.kind or "") == "glossary"
        if is_glossary:
            hover_action = menu.addAction("Glossar-Text setzen…")
            delete_action = menu.addAction("Glossar-Markierung löschen")
            edit_actions[hover_action] = ("hover", active_span.highlight_id)
            edit_actions[delete_action] = ("delete", active_span.highlight_id)
        else:
            hover_action = menu.addAction("Hover-Text setzen…")
            jump_action = menu.addAction("Jump-Ziel (Markierung) setzen…")
            clear_jump_action = menu.addAction("Jump-Ziel entfernen")
            delete_action = menu.addAction("Markierung löschen")
            color_menu = menu.addMenu("Farbe ändern")
            for label, color in self._HIGHLIGHT_COLORS:
                action = color_menu.addAction(label)
                edit_actions[action] = ("color", color)

            edit_actions[hover_action] = ("hover", active_span.highlight_id)
            edit_actions[jump_action] = ("jump", active_span.highlight_id)
            edit_actions[clear_jump_action] = (
                "jump_clear",
                active_span.highlight_id,
            )
            edit_actions[delete_action] = ("delete", active_span.highlight_id)

    picked = menu.exec(global_pos)
    if picked is None:
        return
    if self._is_copy_action(picked):
        # Normalize clipboard text so HTML copy never injects hidden chars
        # or paragraph separators into Markdown targets.
        self._copy_selection_to_clipboard()
        return
    if read_aloud_action is not None and picked is read_aloud_action:
        editor = getattr(self, "_editor", None)
        signal = getattr(editor, "read_aloud_requested", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit(selected_text)
        return

    create_payload = create_actions.get(picked)
    if create_payload is not None:
        color, apply_all = create_payload
        self._create_highlight_from_selection(
            color=color,
            apply_all_tabs=apply_all,
        )
        return

    edit_payload = edit_actions.get(picked)
    if edit_payload is None:
        return
    self._apply_highlight_edit_action(edit_payload, active_span)
@staticmethod
def _is_copy_action(action) -> bool:
    if action is None:
        return False
    try:
        match = action.shortcut().matches(QKeySequence.StandardKey.Copy)
        if match == QKeySequence.SequenceMatch.ExactMatch:
            return True
    except Exception:
        pass
    label = str(action.text() or "").replace("&", "").strip().lower()
    return label in {"copy", "kopieren"}
def _create_highlight_from_selection(
    self,
    *,
    color: str,
    apply_all_tabs: bool,
):
    cursor = self._view.textCursor()
    if not cursor.hasSelection():
        return
    start_qt = int(cursor.selectionStart())
    end_qt = int(cursor.selectionEnd())
    start = self._qt_to_py_pos(start_qt)
    end = self._qt_to_py_pos(end_qt)
    if end <= start:
        return
    text = self._preview_plain_text()
    store = get_highlight_store()
    highlight_id = store.add_from_selection(
        panel_scope=self._highlight_scope,
        tab_name=self._current_tab_name(),
        full_text=text,
        start=start,
        end=end,
        color=color,
        apply_all_tabs=apply_all_tabs,
    )
    if highlight_id:
        self.request_preserve_view_state()
        self.schedule_update()
def _apply_highlight_edit_action(
    self,
    payload: tuple,
    span: _RenderedHighlight | None,
):
    if span is None:
        return
    mode = str(payload[0] or "")
    store = get_highlight_store()
    if mode == "delete":
        if store.delete(span.highlight_id):
            self.request_preserve_view_state()
            self.schedule_update()
        return
    if mode == "hover":
        current = span.hover_text or ""
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Hover-Text",
            "Text beim Überfahren:",
            current,
        )
        if ok and store.set_hover_text(span.highlight_id, text):
            self.request_preserve_view_state()
            self.schedule_update()
        return
    if mode == "jump":
        target_id = self._pick_jump_target(span.highlight_id)
        if target_id is None:
            return
        if store.set_jump_target(span.highlight_id, target_id):
            self.request_preserve_view_state()
            self.schedule_update()
        return
    if mode == "jump_clear":
        if store.set_jump_target(span.highlight_id, ""):
            self.request_preserve_view_state()
            self.schedule_update()
        return
    if mode == "color":
        color = str(payload[1] or "")
        if store.set_color(span.highlight_id, color):
            self.request_preserve_view_state()
            self.schedule_update()
def _update_hover_tooltip(self, global_pos: QPoint):
    vp_pos = self._view.viewport().mapFromGlobal(global_pos)
    href = str(self._view.anchorAt(vp_pos) or "").strip()
    link_tips = dict(getattr(self, "_link_tooltips", {}) or {})
    link_tip = str(link_tips.get(href, "") or "").strip() if href else ""
    if link_tip:
        hover_id = f"link:{href}"
        if self._hovered_highlight_id == hover_id:
            return
        self._hovered_highlight_id = hover_id
        QToolTip.showText(
            global_pos,
            self._tooltip_text(link_tip),
            self._view.viewport(),
        )
        return

    cursor = self._view.cursorForPosition(vp_pos)
    span = self._span_at_position(cursor.position())
    if span is None or not span.hover_text:
        if self._hovered_highlight_id:
            QToolTip.hideText()
            self._hovered_highlight_id = ""
        return
    if self._hovered_highlight_id == span.highlight_id:
        return
    self._hovered_highlight_id = span.highlight_id
    QToolTip.showText(
        global_pos,
        self._tooltip_text(span.hover_text),
        self._view.viewport(),
    )
@staticmethod
def _tooltip_text(text: str) -> str:
    safe = html.escape(str(text or ""))
    return safe.replace("\n", "<br/>")
def _pick_jump_target(self, source_highlight_id: str) -> str | None:
    store = get_highlight_store()
    options = store.list_jump_targets()
    labels: list[str] = ["(kein Jump-Ziel)"]
    label_to_id: dict[str, str] = {"(kein Jump-Ziel)": ""}
    current_target = ""

    current = store.get_highlight(source_highlight_id)
    if isinstance(current, dict):
        current_target = str(current.get("jump_to", "") or "").strip()

    for row in options:
        target_id = str(row.get("id", "") or "").strip()
        if not target_id or target_id == source_highlight_id:
            continue
        scope = str(row.get("panel_scope", "") or "")
        tab_scope = str(row.get("tab_scope", "") or "tabs")
        tabs = list(row.get("tabs", []) or [])
        tabs_label = "all" if tab_scope == "all" else ",".join(tabs[:2])
        preview = str(row.get("exact_preview", "") or "")
        label = f"{target_id} | {scope}:{tabs_label} | {preview}"
        labels.append(label)
        label_to_id[label] = target_id

    if len(labels) == 1:
        return ""

    current_label = "(kein Jump-Ziel)"
    for label, target_id in label_to_id.items():
        if target_id == current_target:
            current_label = label
            break

    picked, ok = QInputDialog.getItem(
        self,
        "Jump-Ziel auswählen",
        "Ziel-Markierung:",
        labels,
        labels.index(current_label) if current_label in labels else 0,
        False,
    )
    if not ok:
        return None
    return label_to_id.get(str(picked), "")


def jump_to_highlight(self, target_id: str) -> bool:
    normalized = str(target_id or "").strip()
    if not normalized:
        return False
    self.request_preserve_view_state()
    self._render()
    if self._jump_to_highlight_id(normalized):
        return True
    self.schedule_update()
    QApplication.processEvents()
    return bool(self._jump_to_highlight_id(normalized))


def _jump_in_tabbed(self, tabbed: object, highlight_id: str, preferred_tabs: list[str]) -> bool:
    tab_widget = getattr(tabbed, "tab_widget", None)
    if tab_widget is None:
        return False
    target = str(highlight_id or "").strip()
    if not target:
        return False

    candidates = _tab_match_indices(tabbed, preferred_tabs)
    for idx in range(tab_widget.count()):
        if idx not in candidates:
            candidates.append(idx)
    if not candidates:
        return False

    current_panel = getattr(tabbed, "current_panel", None)
    for idx in candidates:
        tab_widget.setCurrentIndex(idx)
        QApplication.processEvents()
        panel = current_panel() if callable(current_panel) else tab_widget.widget(idx)
        jump = getattr(panel, "jump_to_highlight", None)
        if not callable(jump):
            continue
        try:
            if bool(jump(target)):
                return True
        except Exception:
            continue
    return False


def _navigate_to_highlight_target(self, target_id: str, target: dict) -> bool:
    target_scope = str(target.get("panel_scope", "") or "").strip().lower()
    effective_scope = target_scope or str(self._highlight_scope or "").strip().lower()
    target_tabs = _target_tabs_from_record(target)

    if effective_scope == self._highlight_scope and not target_tabs:
        if self._jump_to_highlight_id(target_id):
            return True

    window = self.window()
    if window is None:
        return False

    def _show_and_raise(widget: object | None) -> None:
        if widget is None:
            return
        show = getattr(widget, "show", None)
        if callable(show):
            show()
        raise_fn = getattr(widget, "raise_", None)
        if callable(raise_fn):
            try:
                raise_fn()
            except Exception:
                pass

    if effective_scope == "draft":
        canvas = getattr(window, "canvas", None)
        if canvas is None:
            return False
        return self._jump_in_tabbed(getattr(canvas, "tabs", None), target_id, target_tabs)

    if effective_scope in {"viewer", "rag"}:
        knowledge_dock = getattr(window, "knowledge_dock", None)
        if knowledge_dock is None:
            return False
        _show_and_raise(knowledge_dock)
        host_tabs = getattr(knowledge_dock, "tab_widget", None)
        if effective_scope == "viewer":
            viewer = getattr(knowledge_dock, "doc_viewer", None)
            if host_tabs is not None and viewer is not None:
                host_tabs.setCurrentWidget(viewer)
            return self._jump_in_tabbed(getattr(viewer, "tabs", None), target_id, target_tabs)
        rag_tab = getattr(knowledge_dock, "rag_tab", None)
        if host_tabs is not None and rag_tab is not None:
            host_tabs.setCurrentWidget(rag_tab)
        rag_panel = getattr(knowledge_dock, "rag_panel", None)
        return self._jump_in_tabbed(getattr(rag_panel, "tabs", None), target_id, target_tabs)

    if effective_scope == "chat":
        chat_dock = getattr(window, "chat_dock", None)
        if chat_dock is None:
            return False
        _show_and_raise(chat_dock)
        history = getattr(chat_dock, "history", None)
        jump = getattr(history, "jump_to_highlight", None)
        if not callable(jump):
            return False
        try:
            return bool(jump(target_id, preferred_tab_titles=target_tabs))
        except Exception:
            return False

    if effective_scope == self._highlight_scope:
        switcher = self._tab_switcher
        if callable(switcher):
            for tab_name in target_tabs:
                if not switcher(tab_name):
                    continue
                QApplication.processEvents()
                if self._jump_to_highlight_id(target_id):
                    return True
        return bool(self._jump_to_highlight_id(target_id))

    return False


def _handle_highlight_click(self, global_pos: QPoint) -> bool:
    vp_pos = self._view.viewport().mapFromGlobal(global_pos)
    cursor = self._view.cursorForPosition(vp_pos)
    span = self._span_at_position(cursor.position())
    if span is None:
        return False
    target_ref = str(span.jump_to or "").strip()
    if not target_ref:
        return False

    store = get_highlight_store()
    target = store.get_highlight(target_ref)
    if not isinstance(target, dict):
        return False

    if self._navigate_to_highlight_target(target_ref, target):
        return True

    target_scope = str(target.get("panel_scope", "") or "").strip().lower()
    if target_scope and target_scope != self._highlight_scope:
        QToolTip.showText(
            global_pos,
            (
                "Jump-Ziel konnte nicht geöffnet werden "
                f"(Panel: '{target_scope}')."
            ),
            self._view.viewport(),
        )
        return True

    target_tabs = _target_tabs_from_record(target)
    if target_tabs:
        QToolTip.showText(
            global_pos,
            f"Jump-Ziel konnte nicht gefunden werden (Tab: '{target_tabs[0]}').",
            self._view.viewport(),
        )
        return True
    return True
def _jump_to_highlight_id(self, target_id: str) -> bool:
    match = get_highlight_store().resolve_highlight_by_id(
        highlight_id=target_id,
        panel_scope=self._highlight_scope,
        tab_name=self._current_tab_name(),
        full_text=self._preview_plain_text(),
    )
    if match is None:
        return False
    qt_start = self._py_to_qt_pos(int(match.start))
    qt_end = self._py_to_qt_pos(int(match.end))
    if qt_end <= qt_start:
        return False
    cursor = self._view.textCursor()
    cursor.setPosition(qt_start)
    # Keep caret collapsed so the insertion cursor can blink at target.
    cursor.clearSelection()
    self._view.setTextCursor(cursor)
    self._view.setFocus(Qt.FocusReason.OtherFocusReason)
    self._view.ensureCursorVisible()
    return True
__all__ = [
    "_open_highlight_context_menu",
    "_is_copy_action",
    "_create_highlight_from_selection",
    "_apply_highlight_edit_action",
    "_update_hover_tooltip",
    "_tooltip_text",
    "_pick_jump_target",
    "jump_to_highlight",
    "_jump_in_tabbed",
    "_navigate_to_highlight_target",
    "_handle_highlight_click",
    "_jump_to_highlight_id",
]
