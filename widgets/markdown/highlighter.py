"""
Markdown Syntax Highlighter
Robust QSyntaxHighlighter for Markdown with fenced code block tracking.
"""
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

    def __init__(self, document):
        super().__init__(document)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._setup_rules()

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
        # ── Headers H1 – H6 (order matters: longest prefix first)
        header_colors = [
            "#569CD6",  # H1 – vivid blue
            "#9CDCFE",  # H2 – light blue
            "#4EC9B0",  # H3 – teal
            "#CE9178",  # H4 – orange
            "#DCDCAA",  # H5 – yellow
            "#C586C0",  # H6 – pink
        ]
        for level in range(6, 0, -1):  # 6 → 1 so shorter prefixes don't shadow longer
            pattern = QRegularExpression(rf"^{'#' * level}(?!#) .+")
            self._rules.append((pattern, self._fmt(header_colors[level - 1], bold=True)))

        # ── Bold  **text** / __text__
        self._rules.append((
            QRegularExpression(r"\*\*(?!\s)(?:.|\n)+?(?<!\s)\*\*|__(?!\s)(?:.|\n)+?(?<!\s)__"),
            self._fmt("#DCDCAA", bold=True),
        ))

        # ── Italic  *text* / _text_  (not ** or __)
        self._rules.append((
            QRegularExpression(
                r"(?<!\*)\*(?!\*|\s)[^*\n]+?(?<!\s)\*(?!\*)"
                r"|(?<!_)_(?!_|\s)[^_\n]+?(?<!\s)_(?!_)"
            ),
            self._fmt("#CE9178", italic=True),
        ))

        # ── Inline code  `code`
        self._rules.append((
            QRegularExpression(r"`[^`\n]+`"),
            self._fmt("#9CDCFE", bg="#252526"),
        ))

        # ── Images  ![alt](url)  – before links to take priority
        self._rules.append((
            QRegularExpression(r"!\[[^\]]*\]\([^)]*\)"),
            self._fmt("#4EC9B0", italic=True),
        ))

        # ── Links  [text](url)
        self._rules.append((
            QRegularExpression(r"\[[^\]]*\]\([^)]*\)"),
            self._fmt("#4EC9B0"),
        ))

        # ── Unordered list markers  - / * / +
        self._rules.append((
            QRegularExpression(r"^\s*[-*+] "),
            self._fmt("#C586C0"),
        ))

        # ── Ordered list markers  1. 2. …
        self._rules.append((
            QRegularExpression(r"^\s*\d+\. "),
            self._fmt("#C586C0"),
        ))

        # ── Blockquotes  > …
        self._rules.append((
            QRegularExpression(r"^>\s.*"),
            self._fmt("#6A9955", italic=True),
        ))

        # ── Horizontal rules  --- / === / ***
        self._rules.append((
            QRegularExpression(r"^(?:-{3,}|={3,}|\*{3,})\s*$"),
            self._fmt("#555555"),
        ))

        # ── HTML tags (basic)
        self._rules.append((
            QRegularExpression(r"<[^>\n]+>"),
            self._fmt("#808080"),
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
            fence_fmt = self._fmt("#608B4E")
            self.setFormat(0, len(text), fence_fmt)
            if in_code_block:
                self.setCurrentBlockState(self.STATE_NORMAL)
            else:
                self.setCurrentBlockState(self.STATE_CODE_BLOCK)
            return

        # ── Inside fenced code block
        if in_code_block:
            self.setCurrentBlockState(self.STATE_CODE_BLOCK)
            code_fmt = self._fmt("#9CDCFE", bg="#252526")
            self.setFormat(0, len(text), code_fmt)
            return

        # ── Normal markdown
        self.setCurrentBlockState(self.STATE_NORMAL)
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
