"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _open_highlight_context_menu(self, global_pos: QPoint):
    menu = self._view.createStandardContextMenu()

    vp_pos = self._view.viewport().mapFromGlobal(global_pos)
    cursor_at_pos = self._view.cursorForPosition(vp_pos)
    selected_text = self.get_selected_text().strip()
    active_span = self._span_at_position(cursor_at_pos.position())

    if menu.actions():
        menu.addSeparator()

    create_actions: dict = {}
    if selected_text:
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
    if isinstance(target, dict):
        target_scope = str(target.get("panel_scope", "") or "").strip().lower()
        if target_scope and target_scope != self._highlight_scope:
            QToolTip.showText(
                global_pos,
                (
                    "Jump-Ziel liegt in anderem Panel "
                    f"('{target_scope}')."
                ),
                self._view.viewport(),
            )
            return True

        target_tab_scope = str(target.get("tab_scope", "") or "tabs")
        current_tab = self._current_tab_name()
        if target_tab_scope == "tabs":
            tabs = [
                str(item or "").strip()
                for item in list(target.get("tabs", []) or [])
                if str(item or "").strip()
            ]
            if tabs and current_tab not in tabs:
                switcher = self._tab_switcher
                if switcher is not None and switcher(tabs[0]):
                    return True
                QToolTip.showText(
                    global_pos,
                    f"Jump-Ziel ist im Tab '{tabs[0]}'.",
                    self._view.viewport(),
                )
                return True
        if self._jump_to_highlight_id(target_ref):
            return True
        return True

    # Backward compatibility for older free-text jump targets.
    return self._jump_to_text(target_ref)
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
    cursor.setPosition(qt_end, QTextCursor.MoveMode.KeepAnchor)
    self._view.setTextCursor(cursor)
    self._view.ensureCursorVisible()
    return True
def _jump_to_text(self, needle: str) -> bool:
    query = str(needle or "").strip()
    if not query:
        return False
    cursor = self._view.textCursor()
    start_pos = int(cursor.selectionEnd())
    doc = self._view.document()

    probe = QTextCursor(doc)
    probe.setPosition(max(0, start_pos))
    found = doc.find(query, probe)
    if found.isNull():
        found = doc.find(query)
    if found.isNull():
        return False
    self._view.setTextCursor(found)
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
    "_handle_highlight_click",
    "_jump_to_highlight_id",
    "_jump_to_text",
]
