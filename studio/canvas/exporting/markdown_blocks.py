"""Markdown parsing helpers for export rendering."""
from __future__ import annotations

from PySide6.QtGui import QTextDocument, QTextListFormat


ParsedMarkdownBlock = tuple[str, str]


def parse_markdown_lines(md_text: str) -> list[ParsedMarkdownBlock]:
    """
    Parse markdown into display blocks aligned with Qt markdown rendering.

    Single line breaks inside one paragraph stay in the same block,
    while real markdown block boundaries create new blocks.
    """
    out: list[ParsedMarkdownBlock] = []
    doc = QTextDocument()
    doc.setMarkdown(str(md_text or ""))

    bullet_styles = {
        QTextListFormat.Style.ListDisc,
        QTextListFormat.Style.ListCircle,
        QTextListFormat.Style.ListSquare,
    }
    number_styles = {
        QTextListFormat.Style.ListDecimal,
        QTextListFormat.Style.ListLowerAlpha,
        QTextListFormat.Style.ListUpperAlpha,
        QTextListFormat.Style.ListLowerRoman,
        QTextListFormat.Style.ListUpperRoman,
    }

    block = doc.begin()
    while block.isValid():
        text = str(block.text() or "").strip()
        if text:
            style = "normal"
            heading_level = int(block.blockFormat().headingLevel() or 0)
            if heading_level >= 3:
                style = "h3"
            elif heading_level == 2:
                style = "h2"
            elif heading_level == 1:
                style = "h1"
            else:
                text_list = block.textList()
                if text_list is not None:
                    list_style = text_list.format().style()
                    if list_style in bullet_styles:
                        style = "bullet"
                    elif list_style in number_styles:
                        style = "number"
            out.append((text, style))
        block = block.next()
    return out
