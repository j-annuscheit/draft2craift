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


if __name__ == "__main__":
    unittest.main()
