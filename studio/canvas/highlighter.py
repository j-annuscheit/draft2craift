"""
Markdown Syntax Highlighter
Robust QSyntaxHighlighter for Markdown with fenced code block tracking.
"""
from __future__ import annotations

import re
import weakref

from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PySide6.QtCore import QRegularExpression


class MarkdownHighlighter(QSyntaxHighlighter):
    """
    Highlights Markdown syntax: H1-H6, bold, italic, inline code, links,
    lists, blockquotes, horizontal rules, and fenced code blocks.
    Uses block-state machine to track multi-line fenced code blocks.
    """

    # Block states
    STATE_NORMAL = 0
    STATE_CODE_BLOCK = 1
    _HEX_COLOR_RE = re.compile(r"^#(?:[0-9A-Fa-f]{6})$")
    _INSTANCES: "weakref.WeakSet[MarkdownHighlighter]" = weakref.WeakSet()
    _DEFAULT_STYLE: dict[str, object] = {
        "heading_h1_color": "#569CD6",
        "heading_h2_color": "#9CDCFE",
        "heading_h3_color": "#4EC9B0",
        "heading_h4_color": "#CE9178",
        "heading_h5_color": "#DCDCAA",
        "heading_h6_color": "#C586C0",
        "bold_color": "#DCDCAA",
        "italic_color": "#CE9178",
        "bold_italic_color": "#F2B26F",
        "inline_code_color": "#9CDCFE",
        "inline_code_bg_color": "#252526",
        "image_color": "#4EC9B0",
        "link_color": "#4EC9B0",
        "list_marker_color": "#C586C0",
        "quote_color": "#6A9955",
        "hr_color": "#555555",
        "html_tag_color": "#808080",
        "fence_color": "#608B4E",
    }
    _GLOBAL_STYLE: dict[str, object] = dict(_DEFAULT_STYLE)

    def __init__(self, document):
        super().__init__(document)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._style = self._normalize_style(self._GLOBAL_STYLE)
        self._INSTANCES.add(self)
        self._setup_rules()

    @classmethod
    def _normalize_hex_color(cls, value: object, fallback: str) -> str:
        text = str(value or "").strip()
        if len(text) == 4 and text.startswith("#"):
            text = f"#{text[1]}{text[1]}{text[2]}{text[2]}{text[3]}{text[3]}"
        if cls._HEX_COLOR_RE.match(text):
            return text.upper()
        return str(fallback)

    @classmethod
    def _normalize_style(cls, raw: object) -> dict[str, object]:
        payload = raw if isinstance(raw, dict) else {}
        out = dict(cls._DEFAULT_STYLE)
        for key, fallback in cls._DEFAULT_STYLE.items():
            out[key] = cls._normalize_hex_color(payload.get(key), str(fallback))
        return out

    @classmethod
    def apply_global_style(cls, raw: object) -> None:
        normalized = cls._normalize_style(raw)
        if normalized == cls._GLOBAL_STYLE:
            return
        cls._GLOBAL_STYLE = dict(normalized)
        for highlighter in list(cls._INSTANCES):
            try:
                highlighter.set_style(normalized)
            except Exception:
                continue

    @classmethod
    def global_style(cls) -> dict[str, object]:
        return dict(cls._GLOBAL_STYLE)

    def set_style(self, raw: object) -> None:
        normalized = self._normalize_style(raw)
        if normalized == self._style:
            return
        self._style = dict(normalized)
        self._setup_rules()
        self.rehighlight()

    # ------------------------------------------------------------------
    # Format helpers
    # ------------------------------------------------------------------

    def _fmt(
        self,
        color: str,
        bold: bool = False,
        italic: bool = False,
        bg: str | None = None,
    ) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        if bg:
            fmt.setBackground(QColor(bg))
        return fmt

    # ------------------------------------------------------------------
    # Rule setup
    # ------------------------------------------------------------------

    def _setup_rules(self):
        style = self._style
        self._rules = []
        # ── Headers H1 – H6 (order matters: longest prefix first)
        header_colors = [
            str(style["heading_h1_color"]),
            str(style["heading_h2_color"]),
            str(style["heading_h3_color"]),
            str(style["heading_h4_color"]),
            str(style["heading_h5_color"]),
            str(style["heading_h6_color"]),
        ]
        for level in range(6, 0, -1):  # 6 → 1 so shorter prefixes don't shadow longer
            pattern = QRegularExpression(rf"^{'#' * level}(?!#) .+")
            self._rules.append((pattern, self._fmt(header_colors[level - 1], bold=True)))

        # ── Bold+Italic ***text*** / ___text___ / **_text_** / __*text*__
        self._rules.append(
            (
                QRegularExpression(
                    r"(?<!\\)(\*\*\*[^*\n]+?\*\*\*|___[^_\n]+?___|\*\*_[^_\n]+?_\*\*|__\*[^*\n]+?\*__)"
                ),
                self._fmt(str(style["bold_italic_color"]), bold=True, italic=True),
            )
        )

        # ── Bold  **text** / __text__
        self._rules.append((
            QRegularExpression(r"\*\*(?!\s)(?:.|\n)+?(?<!\s)\*\*|__(?!\s)(?:.|\n)+?(?<!\s)__"),
            self._fmt(str(style["bold_color"]), bold=True),
        ))

        # ── Italic  *text* / _text_  (not ** or __)
        self._rules.append((
            QRegularExpression(
                r"(?<!\\)(?<!\*)\*(?!\*|\s)[^*\n]+?(?<!\s)(?<!\\)\*(?!\*)"
                r"|(?<!\\)(?<!_)_(?!_|\s)[^_\n]+?(?<!\s)(?<!\\)_(?!_)"
            ),
            self._fmt(str(style["italic_color"]), italic=True),
        ))

        # ── Inline code  `code`
        self._rules.append((
            QRegularExpression(r"`[^`\n]+`"),
            self._fmt(
                str(style["inline_code_color"]),
                bg=str(style["inline_code_bg_color"]),
            ),
        ))

        # ── Images  ![alt](url)  – before links to take priority
        self._rules.append((
            QRegularExpression(r"!\[[^\]]*\]\([^)]*\)"),
            self._fmt(str(style["image_color"]), italic=True),
        ))

        # ── Links  [text](url)
        self._rules.append((
            QRegularExpression(r"\[[^\]]*\]\([^)]*\)"),
            self._fmt(str(style["link_color"])),
        ))

        # ── Unordered list markers  - / * / +
        self._rules.append((
            QRegularExpression(r"^\s*[-*+] "),
            self._fmt(str(style["list_marker_color"])),
        ))

        # ── Ordered list markers  1. 2. …
        self._rules.append((
            QRegularExpression(r"^\s*\d+\. "),
            self._fmt(str(style["list_marker_color"])),
        ))

        # ── Blockquotes: color only leading marker run (">", ">>", "> >", ...)
        self._rules.append((
            QRegularExpression(r"^>(?:\s*>)*(?=\s|$)"),
            self._fmt(str(style["quote_color"])),
        ))

        # ── Horizontal rules  --- / === / ***
        self._rules.append((
            QRegularExpression(r"^(?:-{3,}|={3,}|\*{3,})\s*$"),
            self._fmt(str(style["hr_color"])),
        ))

        # ── HTML tags (basic)
        self._rules.append((
            QRegularExpression(r"<[^>\n]+>"),
            self._fmt(str(style["html_tag_color"])),
        ))

    # ------------------------------------------------------------------
    # Highlight logic
    # ------------------------------------------------------------------

    def highlightBlock(self, text: str):
        prev_state = self.previousBlockState()
        in_code_block = prev_state == self.STATE_CODE_BLOCK

        # ── Fence boundary line  (``` or ~~~)
        stripped = text.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence_fmt = self._fmt(
                str(self._style["fence_color"]),
                bg=str(self._style["inline_code_bg_color"]),
            )
            self.setFormat(0, len(text), fence_fmt)
            if in_code_block:
                self.setCurrentBlockState(self.STATE_NORMAL)
            else:
                self.setCurrentBlockState(self.STATE_CODE_BLOCK)
            return

        # ── Inside fenced code block
        if in_code_block:
            self.setCurrentBlockState(self.STATE_CODE_BLOCK)
            code_fmt = self._fmt(
                str(self._style["inline_code_color"]),
                bg=str(self._style["inline_code_bg_color"]),
            )
            self.setFormat(0, len(text), code_fmt)
            return

        # ── Normal markdown
        self.setCurrentBlockState(self.STATE_NORMAL)
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
