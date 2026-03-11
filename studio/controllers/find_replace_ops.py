"""Search/replace operation helpers for :mod:`find_replace_ctrl`."""
from __future__ import annotations

import logging

from PySide6.QtGui import QTextCursor, QTextDocument

from studio.canvas.editor import MarkdownEditor

_LOG = logging.getLogger(__name__)


def _count_find_matches_editor(self, editor: MarkdownEditor, needle: str) -> int:
    query = str(needle or "")
    if not query:
        return 0
    flags = self._build_find_flags(backward=False)
    doc = editor.document()
    count = 0
    cursor = doc.find(query, 0, flags)
    last_signature: tuple[int, int, int] | None = None
    max_iterations = max(1, int(doc.characterCount()) + 1)
    iterations = 0
    while not cursor.isNull() and iterations < max_iterations:
        start = int(cursor.selectionStart())
        end = int(cursor.selectionEnd())
        pos = int(cursor.position())
        signature = (start, end, pos)
        if signature == last_signature:
            _LOG.warning(
                "Find/Replace match counting aborted due to non-advancing cursor for %r",
                query,
            )
            break
        count += 1
        iterations += 1
        last_signature = signature
        cursor = doc.find(query, max(pos, end, start + 1), flags)
    if iterations >= max_iterations and not cursor.isNull():
        _LOG.warning(
            "Find/Replace match counting reached safety limit (%d) for %r",
            max_iterations,
            query,
        )
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
        case_sensitive = bool(
            self._find_case_cb is not None and self._find_case_cb.isChecked()
        )
        whole_words = bool(
            self._find_whole_cb is not None and self._find_whole_cb.isChecked()
        )
        try:
            return int(
                panel.count_preview_matches(
                    str(needle or ""),
                    case_sensitive=case_sensitive,
                    whole_words=whole_words,
                )
            )
        except Exception:
            _LOG.warning(
                "Find/Replace preview match count failed for panel %r",
                panel,
                exc_info=True,
            )
            return 0
    return 0


def _build_find_flags(self, *, backward: bool = False):
    flags = QTextDocument.FindFlag(0)
    if backward:
        flags |= QTextDocument.FindFlag.FindBackward
    if self._find_case_cb is not None and self._find_case_cb.isChecked():
        flags |= QTextDocument.FindFlag.FindCaseSensitively
    if self._find_whole_cb is not None and self._find_whole_cb.isChecked():
        flags |= QTextDocument.FindFlag.FindWholeWords
    return flags


def _find_in_target(self, target: dict, needle: str, *, backward: bool = False) -> bool:
    kind = str(target.get("kind", "")).strip().lower()
    if kind == "preview":
        panel = target.get("panel")
        if panel is None:
            return False
        case_sensitive = bool(
            self._find_case_cb is not None and self._find_case_cb.isChecked()
        )
        whole_words = bool(
            self._find_whole_cb is not None and self._find_whole_cb.isChecked()
        )
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
            _LOG.warning(
                "Find/Replace preview search failed for panel %r",
                panel,
                exc_info=True,
            )
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


def _replace_from_dialog(self):
    target = self._resolve_find_target()
    if target is None:
        self._show_status("Kein aktiver Editor für Ersetzen.", 2000)
        return
    if self._find_target_is_read_only(target):
        self._show_status("Ersetzen ist in dieser Ansicht gesperrt.", 2000)
        self._update_find_replace_controls_state(target)
        return
    editor = target.get("editor")
    if not isinstance(editor, MarkdownEditor):
        self._show_status("Ersetzen ist in dieser Ansicht nicht verfügbar.", 2000)
        self._update_find_replace_controls_state(target)
        return

    needle = str(
        self._find_query_edit.text() if self._find_query_edit is not None else ""
    )
    replacement = str(
        self._replace_query_edit.text() if self._replace_query_edit is not None else ""
    )
    if not needle:
        self._show_status("Bitte Suchtext eingeben.", 2000)
        return

    cursor = editor.textCursor()
    selected = str(cursor.selectedText() or "").replace("\u2029", "\n")
    case_sensitive = bool(
        self._find_case_cb is not None and self._find_case_cb.isChecked()
    )
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
        self._show_status("Kein aktiver Editor für Ersetzen.", 2000)
        return
    if self._find_target_is_read_only(target):
        self._show_status("Ersetzen ist in dieser Ansicht gesperrt.", 2000)
        self._update_find_replace_controls_state(target)
        return
    editor = target.get("editor")
    if not isinstance(editor, MarkdownEditor):
        self._show_status("Ersetzen ist in dieser Ansicht nicht verfügbar.", 2000)
        self._update_find_replace_controls_state(target)
        return

    needle = str(
        self._find_query_edit.text() if self._find_query_edit is not None else ""
    )
    replacement = str(
        self._replace_query_edit.text() if self._replace_query_edit is not None else ""
    )
    if not needle:
        self._show_status("Bitte Suchtext eingeben.", 2000)
        return

    flags = self._build_find_flags(backward=False)
    doc = editor.document()
    edit_cursor = editor.textCursor()
    edit_cursor.beginEditBlock()
    count = 0
    max_iterations = max(1, int(doc.characterCount()) + 1)
    hit = doc.find(needle, 0, flags)
    last_signature: tuple[int, int, int] | None = None
    while not hit.isNull() and count < max_iterations:
        start = int(hit.selectionStart())
        end = int(hit.selectionEnd())
        pos = int(hit.position())
        signature = (start, end, pos)
        if signature == last_signature:
            _LOG.warning(
                "Find/Replace replace-all aborted due to non-advancing cursor for %r",
                needle,
            )
            break
        last_signature = signature
        hit.insertText(replacement)
        count += 1
        next_pos = max(start + len(replacement), pos, end, start + 1)
        hit = doc.find(needle, next_pos, flags)
    edit_cursor.endEditBlock()
    if count >= max_iterations and not hit.isNull():
        _LOG.warning(
            "Find/Replace replace-all reached safety limit (%d) for %r",
            max_iterations,
            needle,
        )

    self._show_status(
        f"{count} Treffer ersetzt." if count else "Keine Treffer zum Ersetzen.",
        2000,
    )
    self._update_find_match_count()

