"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _set_heading_level(self, level: int):
    def apply():
        cursor = self._view.textCursor()
        cursor.beginEditBlock()
        block_format = cursor.blockFormat()
        block_format.setHeadingLevel(level)
        cursor.setBlockFormat(block_format)
        cursor.endEditBlock()
        self._view.setTextCursor(cursor)

    self._apply_preview_format_change(apply)
def _clear_heading(self):
    def apply():
        cursor = self._view.textCursor()
        cursor.beginEditBlock()
        block_format = cursor.blockFormat()
        block_format.setHeadingLevel(0)
        cursor.setBlockFormat(block_format)

        # Qt may keep heading bold formatting on the block text when
        # heading level is removed; normalize back to paragraph weight.
        block_cursor = QTextCursor(cursor)
        block_cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        char_format = QTextCharFormat(block_cursor.charFormat())
        char_format.setFontWeight(int(QFont.Weight.Normal))
        block_cursor.mergeCharFormat(char_format)

        cursor.endEditBlock()
        self._view.setTextCursor(cursor)

    self._apply_preview_format_change(apply)
def _trimmed_selection_bounds(self) -> tuple[int, int] | None:
    cursor = self._view.textCursor()
    if not cursor.hasSelection():
        return None
    start = int(cursor.selectionStart())
    end = int(cursor.selectionEnd())
    if end <= start:
        return None
    doc = self._view.document()
    while start < end:
        ch = str(doc.characterAt(start) or "")
        if ch and (not ch.isspace()):
            break
        start += 1
    while end > start:
        ch = str(doc.characterAt(end - 1) or "")
        if ch and (not ch.isspace()):
            break
        end -= 1
    if end <= start:
        return None
    return start, end
def _selection_all_nonspace_chars_match(
    self,
    start: int,
    end: int,
    matcher: Callable[[QTextCharFormat], bool],
) -> tuple[bool, bool]:
    doc = self._view.document()
    probe = QTextCursor(doc)
    all_match = True
    has_nonspace = False
    for pos in range(int(start), int(end)):
        ch = str(doc.characterAt(pos) or "")
        if (not ch) or ch.isspace():
            continue
        has_nonspace = True
        probe.setPosition(min(pos + 1, doc.characterCount() - 1))
        if not matcher(probe.charFormat()):
            all_match = False
            break
    return all_match, has_nonspace
def _expand_selection_to_formatted_adjacent_whitespace(
    self,
    start: int,
    end: int,
    matcher: Callable[[QTextCharFormat], bool],
) -> tuple[int, int]:
    doc = self._view.document()
    probe = QTextCursor(doc)
    left = int(start)
    right = int(end)
    while left > 0:
        ch = str(doc.characterAt(left - 1) or "")
        if (not ch) or (not ch.isspace()):
            break
        probe.setPosition(min(left, doc.characterCount() - 1))
        if not matcher(probe.charFormat()):
            break
        left -= 1
    max_index = max(0, doc.characterCount() - 1)
    while right < max_index:
        ch = str(doc.characterAt(right) or "")
        if (not ch) or (not ch.isspace()):
            break
        probe.setPosition(min(right + 1, max_index))
        if not matcher(probe.charFormat()):
            break
        right += 1
    return left, right
def _expand_selection_to_bridge_formatted_neighbors(
    self,
    start: int,
    end: int,
    matcher: Callable[[QTextCharFormat], bool],
) -> tuple[int, int]:
    doc = self._view.document()
    probe = QTextCursor(doc)
    left = int(start)
    right = int(end)
    max_index = max(0, doc.characterCount() - 1)

    left_ws_start = left
    while left_ws_start > 0:
        ch = str(doc.characterAt(left_ws_start - 1) or "")
        if (not ch) or (not ch.isspace()):
            break
        left_ws_start -= 1
    if left_ws_start < left and left_ws_start > 0:
        probe.setPosition(min(left_ws_start, max_index))
        if matcher(probe.charFormat()):
            left = left_ws_start

    right_ws_end = right
    while right_ws_end < max_index:
        ch = str(doc.characterAt(right_ws_end) or "")
        if (not ch) or (not ch.isspace()):
            break
        right_ws_end += 1
    if right_ws_end > right and right_ws_end < max_index:
        probe.setPosition(min(right_ws_end + 1, max_index))
        if matcher(probe.charFormat()):
            right = right_ws_end

    return left, right
def _toggle_inline_char_format(
    self,
    *,
    matcher: Callable[[QTextCharFormat], bool],
    apply_state: Callable[[QTextCharFormat, bool], None],
):
    cursor = self._view.textCursor()
    if not cursor.hasSelection():
        fmt = self._view.currentCharFormat()
        apply_state(fmt, not matcher(fmt))
        self._view.mergeCurrentCharFormat(fmt)
        return

    bounds = self._trimmed_selection_bounds()
    if bounds is None:
        return
    start, end = bounds
    all_match, has_nonspace = self._selection_all_nonspace_chars_match(
        start,
        end,
        matcher,
    )
    if not has_nonspace:
        return
    target_enabled = not all_match
    if target_enabled:
        start, end = self._expand_selection_to_bridge_formatted_neighbors(
            start,
            end,
            matcher,
        )
    else:
        start, end = self._expand_selection_to_formatted_adjacent_whitespace(
            start,
            end,
            matcher,
        )

    selection = QTextCursor(self._view.document())
    selection.setPosition(int(start))
    selection.setPosition(int(end), QTextCursor.MoveMode.KeepAnchor)
    self._view.setTextCursor(selection)
    fmt = QTextCharFormat()
    apply_state(fmt, target_enabled)
    selection.mergeCharFormat(fmt)
    self._view.setTextCursor(selection)
def _toggle_bold(self):
    def apply():
        self._toggle_inline_char_format(
            matcher=lambda fmt: fmt.fontWeight() >= int(QFont.Weight.Bold),
            apply_state=lambda fmt, enabled: fmt.setFontWeight(
                int(QFont.Weight.Bold)
                if enabled
                else int(QFont.Weight.Normal)
            ),
        )

    self._apply_preview_format_change(apply)
def _toggle_italic(self):
    def apply():
        self._toggle_inline_char_format(
            matcher=lambda fmt: bool(fmt.fontItalic()),
            apply_state=lambda fmt, enabled: fmt.setFontItalic(bool(enabled)),
        )

    self._apply_preview_format_change(apply)
def _toggle_block_quote(self):
    def apply():
        cursor = self._view.textCursor()
        block_format = cursor.blockFormat()
        current_level = int(
            block_format.property(QTextFormat.Property.BlockQuoteLevel) or 0
        )
        block_format.setProperty(
            QTextFormat.Property.BlockQuoteLevel,
            0 if current_level > 0 else 1,
        )
        cursor.setBlockFormat(block_format)
        self._view.setTextCursor(cursor)

    self._apply_preview_format_change(apply)
def _insert_formula(self):
    """Open formula dialog and insert resulting LaTeX into preview selection."""
    from studio.canvas.formula_editor import FormulaEditorDialog

    dlg = FormulaEditorDialog(parent=self)
    if dlg.exec() != dlg.DialogCode.Accepted:
        return
    latex = str(dlg.result_latex() or "").strip()
    if not latex:
        return

    def apply():
        cursor = self._view.textCursor()
        cursor.insertText(latex)
        self._view.setTextCursor(cursor)

    self._apply_preview_format_change(apply)
def _toggle_bullet_list(self):
    self._toggle_list_style(QTextListFormat.Style.ListDisc)
def _toggle_numbered_list(self):
    self._toggle_list_style(QTextListFormat.Style.ListDecimal)
@staticmethod
def _build_markdown_table(rows: int, cols: int) -> str:
    r = max(1, int(rows))
    c = max(1, int(cols))
    header = "| " + " | ".join([" "] * c) + " |"
    separator = "| " + " | ".join(["---"] * c) + " |"
    body_row = "| " + " | ".join([" "] * c) + " |"
    body = [body_row for _ in range(max(0, r - 1))]
    lines = [header, separator, *body]
    return "\n".join(lines)
def _insert_markdown_table(self, rows: int, cols: int):
    def apply():
        cursor = self._view.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            cursor.removeSelectedText()

        table_markdown = self._build_markdown_table(rows, cols)
        if cursor.positionInBlock() != 0:
            cursor.insertBlock()
        cursor.insertText(table_markdown)
        cursor.insertBlock()
        cursor.endEditBlock()
        self._view.setTextCursor(cursor)

    self._apply_preview_format_change(apply)
def _show_table_insert_menu(self):
    if not self._allow_editing or self._structured_view_active:
        return
    button = self._table_insert_btn
    if button is None:
        return
    if self._table_insert_menu is not None:
        try:
            self._table_insert_menu.close()
        except Exception:
            pass

    menu = QMenu(self)
    menu.setToolTipsVisible(False)
    picker = TableInsertPicker(
        max_rows=12,
        max_cols=12,
        user_mode=str(getattr(self, "_user_mode", "") or ""),
        parent=menu,
    )

    def _insert_selected(rows: int, cols: int):
        try:
            menu.close()
        except Exception:
            pass
        self._insert_markdown_table(rows, cols)

    picker.size_chosen.connect(_insert_selected)
    action = QWidgetAction(menu)
    action.setDefaultWidget(picker)
    menu.addAction(action)

    def _clear_menu_ref():
        self._table_insert_menu = None

    menu.aboutToHide.connect(_clear_menu_ref)
    self._table_insert_menu = menu
    pos = button.mapToGlobal(QPoint(0, button.height()))
    menu.popup(pos)
def _insert_horizontal_rule(self):
    def apply():
        cursor = self._view.textCursor()
        cursor.beginEditBlock()
        cursor.insertBlock()
        cursor.insertText(self._HR_MARKER)
        cursor.insertBlock()
        cursor.endEditBlock()
        self._view.setTextCursor(cursor)

    self._apply_preview_format_change(apply)
def _indent_list_item(self):
    self._adjust_list_indent(+1)
def _outdent_list_item(self):
    self._adjust_list_indent(-1)
def _adjust_list_indent(self, delta: int):
    def apply():
        cursor = self._view.textCursor()
        current_list = cursor.currentList()
        if current_list is None:
            if delta <= 0:
                return
            list_format = QTextListFormat()
            list_format.setStyle(QTextListFormat.Style.ListDisc)
            list_format.setIndent(2)
            cursor.createList(list_format)
            self._view.setTextCursor(cursor)
            return

        list_format = QTextListFormat(current_list.format())
        old_indent = max(1, list_format.indent())
        new_indent = max(1, old_indent + delta)
        if new_indent == old_indent:
            return
        list_format.setIndent(new_indent)
        cursor.createList(list_format)
        self._view.setTextCursor(cursor)

    self._apply_preview_format_change(apply)
def _toggle_list_style(self, style: QTextListFormat.Style):
    def apply():
        cursor = self._view.textCursor()
        current_list = cursor.currentList()
        cursor.beginEditBlock()
        if (
            current_list is not None
            and current_list.format().style() == style
        ):
            block_format = cursor.blockFormat()
            block_format.setObjectIndex(-1)
            cursor.setBlockFormat(block_format)
        else:
            list_format = QTextListFormat()
            list_format.setStyle(style)
            cursor.createList(list_format)
        cursor.endEditBlock()
        self._view.setTextCursor(cursor)

    self._apply_preview_format_change(apply)

__all__ = [
    "_set_heading_level",
    "_clear_heading",
    "_trimmed_selection_bounds",
    "_selection_all_nonspace_chars_match",
    "_expand_selection_to_formatted_adjacent_whitespace",
    "_expand_selection_to_bridge_formatted_neighbors",
    "_toggle_inline_char_format",
    "_toggle_bold",
    "_toggle_italic",
    "_toggle_block_quote",
    "_insert_formula",
    "_toggle_bullet_list",
    "_toggle_numbered_list",
    "_build_markdown_table",
    "_insert_markdown_table",
    "_show_table_insert_menu",
    "_insert_horizontal_rule",
    "_indent_list_item",
    "_outdent_list_item",
    "_adjust_list_indent",
    "_toggle_list_style",
]
