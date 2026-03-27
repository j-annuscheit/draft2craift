"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def find_text(
    self,
    query: str,
    *,
    backward: bool = False,
    case_sensitive: bool = False,
    whole_words: bool = False,
    wrap: bool = True,
) -> bool:
    if self._structured_view_active:
        return False
    needle = str(query or "")
    if not needle:
        return False

    flags = QTextDocument.FindFlag(0)
    if backward:
        flags |= QTextDocument.FindFlag.FindBackward
    if case_sensitive:
        flags |= QTextDocument.FindFlag.FindCaseSensitively
    if whole_words:
        flags |= QTextDocument.FindFlag.FindWholeWords

    doc = self._view.document()
    cursor = self._view.textCursor()
    current_start = int(cursor.selectionStart())
    current_end = int(cursor.selectionEnd())
    current_has_selection = current_end > current_start
    start = int(cursor.selectionStart()) if backward else int(cursor.selectionEnd())
    probe = QTextCursor(doc)
    if backward:
        probe.setPosition(max(0, start - 1))
    else:
        probe.setPosition(max(0, start))

    found = doc.find(needle, probe, flags)
    if found.isNull() and wrap:
        restart = QTextCursor(doc)
        if backward:
            restart.setPosition(max(0, int(doc.characterCount()) - 1))
        else:
            restart.setPosition(0)
        found = doc.find(needle, restart, flags)

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
        alt = doc.find(needle, probe2, flags)
        if alt.isNull() and wrap:
            restart = QTextCursor(doc)
            if backward:
                restart.setPosition(max(0, int(doc.characterCount()) - 1))
            else:
                restart.setPosition(0)
            alt = doc.find(needle, restart, flags)
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

    self._view.setTextCursor(found)
    self._view.ensureCursorVisible()
    return True
def count_text_matches(
    self,
    query: str,
    *,
    case_sensitive: bool = False,
    whole_words: bool = False,
) -> int:
    if self._structured_view_active:
        return 0
    needle = str(query or "")
    if not needle:
        return 0

    flags = QTextDocument.FindFlag(0)
    if case_sensitive:
        flags |= QTextDocument.FindFlag.FindCaseSensitively
    if whole_words:
        flags |= QTextDocument.FindFlag.FindWholeWords

    doc = self._view.document()
    count = 0
    found = doc.find(needle, 0, flags)
    while not found.isNull():
        count += 1
        found = doc.find(needle, found.position(), flags)
    return count
def is_read_only(self) -> bool:
    return bool(self._view.isReadOnly())
def _span_at_position(self, position: int) -> _RenderedHighlight | None:
    for item in self._rendered_highlights:
        if item.start <= position < item.end:
            return item
    return None
def schedule_update(self, *_):
    if not self.isVisible():
        return
    if self._preview_edit_active:
        return
    if self._preview_timer.isActive():
        return
    self._preview_timer.start(120)
def schedule_cursor_sync(self, *_):
    if not self._sync_cursor_with_editor:
        return
    if not self.isVisible():
        return
    if self._editor is not None and not self._editor.isVisible():
        return
    if self._preview_edit_active:
        return
    self._cursor_timer.start(45)
def _current_tab_name(self) -> str:
    getter = self._tab_name_getter
    if getter is None:
        return ""
    try:
        return str(getter() or "").strip()
    except Exception:
        return ""
def _preview_plain_text(self) -> str:
    if self._structured_view_active:
        return str(self._graph_plain_text or "")
    return (self._view.toPlainText() or "").replace("\r\n", "\n")


def preview_plain_text(self) -> str:
    """Return currently rendered preview plain text."""
    return self._preview_plain_text()


def plain_text_for_markdown(self, markdown_text: str) -> str:
    """
    Build preview-equivalent plain text for markdown input.

    This does not depend on current widget visibility and can be used by
    export routines that must resolve highlight anchors while the preview
    pane is hidden.
    """
    source = str(markdown_text or "").replace("\r\n", "\n")
    if not source.strip():
        return ""
    render_md = self._markdown_for_render(source)
    render_md = self._apply_render_unordered_marker_gap(render_md)
    doc = QTextDocument()
    doc.setMarkdown(render_md)
    return (doc.toPlainText() or "").replace("\r\n", "\n")
@classmethod
def _tail_probe_from_markdown(cls, markdown: str) -> str:
    lines = str(markdown or "").splitlines()
    for raw in reversed(lines):
        normalized = cls._normalize_markdown_line(raw)
        if not normalized:
            continue
        tokens = [
            token.casefold()
            for token in cls._TOKEN_RE.findall(normalized)
            if token
        ]
        if not tokens:
            continue
        # Use the last words so end-of-document truncation is detectable.
        return " ".join(tokens[-12:])
    return ""
@classmethod
def _contains_tail_probe(cls, haystack: str, probe: str) -> bool:
    needle = str(probe or "").strip()
    if not needle:
        return True
    words = [
        token.casefold()
        for token in cls._TOKEN_RE.findall(str(haystack or ""))
        if token
    ]
    if not words:
        return False
    return needle in " ".join(words)
def _copy_selection_to_clipboard(self) -> bool:
    cursor = self._view.textCursor()
    if not cursor.hasSelection():
        return False
    text = str(cursor.selectedText() or "")
    text = (
        text.replace("\u2029", "\n")
        .replace("\u2028", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\uFFFC", "")
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("\ufeff", "")
    )
    QApplication.clipboard().setText(text)
    return True

__all__ = [
    "find_text",
    "count_text_matches",
    "is_read_only",
    "_span_at_position",
    "schedule_update",
    "schedule_cursor_sync",
    "_current_tab_name",
    "_preview_plain_text",
    "preview_plain_text",
    "plain_text_for_markdown",
    "_tail_probe_from_markdown",
    "_contains_tail_probe",
    "_copy_selection_to_clipboard",
]
