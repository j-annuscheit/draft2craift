from __future__ import annotations

import unittest

from PySide6.QtGui import QTextDocument

from studio.canvas.highlighter import MarkdownHighlighter
from studio.canvas.editor import MarkdownEditor


def _italic_ranges(text: str) -> list[tuple[int, int]]:
    doc = QTextDocument(str(text or ""))
    hl = MarkdownHighlighter(doc)
    hl.rehighlight()
    block = doc.firstBlock()
    layout = block.layout()
    if layout is None:
        return []
    out: list[tuple[int, int]] = []
    for fr in layout.formats():
        if fr.length > 0 and fr.format.fontItalic():
            out.append((int(fr.start), int(fr.length)))
    return out


def _quote_color_ranges(text: str) -> list[tuple[int, int]]:
    doc = QTextDocument(str(text or ""))
    hl = MarkdownHighlighter(doc)
    hl.rehighlight()
    block = doc.firstBlock()
    layout = block.layout()
    if layout is None:
        return []
    expected = str(MarkdownHighlighter.global_style().get("quote_color", "") or "").upper()
    out: list[tuple[int, int]] = []
    for fr in layout.formats():
        if fr.length <= 0:
            continue
        color = fr.format.foreground().color()
        if not color.isValid():
            continue
        if color.name().upper() == expected:
            out.append((int(fr.start), int(fr.length)))
    return out


def _bg_color_ranges_per_block(text: str, block_index: int) -> list[tuple[int, int]]:
    doc = QTextDocument(str(text or ""))
    hl = MarkdownHighlighter(doc)
    hl.rehighlight()
    block = doc.firstBlock()
    index = 0
    while block.isValid() and index < block_index:
        block = block.next()
        index += 1
    if not block.isValid():
        return []
    layout = block.layout()
    if layout is None:
        return []
    expected = str(
        MarkdownHighlighter.global_style().get("inline_code_bg_color", "") or ""
    ).upper()
    out: list[tuple[int, int]] = []
    for fr in layout.formats():
        if fr.length <= 0:
            continue
        color = fr.format.background().color()
        if not color.isValid():
            continue
        if color.name().upper() == expected:
            out.append((int(fr.start), int(fr.length)))
    return out


class MarkdownHighlighterEscapeTests(unittest.TestCase):
    def test_unescaped_binnenstern_is_seen_as_italic(self):
        ranges = _italic_ranges("Künstler*innen und Sportler*innen")
        self.assertGreater(len(ranges), 0)

    def test_escaped_binnenstern_is_not_italic(self):
        ranges = _italic_ranges(r"Künstler\*innen und Sportler\*innen")
        self.assertEqual(ranges, [])

    def test_editor_paste_normalization_escapes_binnenstern(self):
        out = MarkdownEditor._normalize_paste_text("Künstler*innen")
        self.assertEqual(out, r"Künstler\*innen")

    def test_blockquote_highlights_only_leading_marker(self):
        ranges = _quote_color_ranges("> Zitat")
        self.assertEqual(ranges, [(0, 1)])

    def test_nested_blockquote_markers_are_colored(self):
        ranges = _quote_color_ranges(">> Zitat")
        self.assertEqual(ranges, [(0, 2)])

    def test_spaced_nested_blockquote_markers_are_colored(self):
        ranges = _quote_color_ranges("> > Zitat")
        self.assertEqual(ranges, [(0, 3)])

    def test_fence_marker_line_uses_code_block_background(self):
        ranges = _bg_color_ranges_per_block("```python\nprint('x')\n```", 0)
        self.assertEqual(ranges, [(0, 9)])


if __name__ == "__main__":
    unittest.main()
