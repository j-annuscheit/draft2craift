"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _preview_theme_text_colors(self) -> dict[str, str]:
    theme = self._normalize_preview_theme_id(self._preview_theme_id)
    text_color = self._palette_hex(QPalette.ColorRole.Text, "#CDD6F4")
    link_color = self._palette_hex(QPalette.ColorRole.Highlight, "#89B4FA")
    if theme == "vivid":
        heading_h1 = self._mix_hex_colors(text_color, "#2563EB", 0.86)
        heading_h2 = self._mix_hex_colors(text_color, "#7C3AED", 0.82)
        heading_h3 = self._mix_hex_colors(text_color, "#DB2777", 0.76)
        strong_color = self._mix_hex_colors(text_color, "#F97316", 0.78)
        em_color = self._mix_hex_colors(text_color, "#22C55E", 0.72)
    else:
        heading_h1 = self._mix_hex_colors(text_color, "#60A5FA", 0.64)
        heading_h2 = self._mix_hex_colors(text_color, "#A78BFA", 0.54)
        heading_h3 = self._mix_hex_colors(text_color, "#34D399", 0.50)
        strong_color = self._mix_hex_colors(text_color, "#FB923C", 0.50)
        em_color = self._mix_hex_colors(text_color, link_color, 0.24)
    strong_em_color = self._mix_hex_colors(strong_color, em_color, 0.45)
    return {
        "heading_h1": heading_h1,
        "heading_h2": heading_h2,
        "heading_h3": heading_h3,
        "heading_default": heading_h3,
        "strong": strong_color,
        "em": em_color,
        "strong_em": strong_em_color,
    }
def _build_preview_theme_extra_selections(self) -> list[QTextEdit.ExtraSelection]:
    if self._normalize_preview_theme_id(self._preview_theme_id) == "classic":
        return []

    doc = self._view.document()
    colors = self._preview_theme_text_colors()
    heading_h1_q = QColor(colors["heading_h1"])
    heading_h2_q = QColor(colors["heading_h2"])
    heading_h3_q = QColor(colors["heading_h3"])
    heading_default_q = QColor(colors["heading_default"])
    strong_q = QColor(colors["strong"])
    em_q = QColor(colors["em"])
    strong_em_q = QColor(colors["strong_em"])

    selections: list[QTextEdit.ExtraSelection] = []
    block = doc.begin()
    while block.isValid():
        heading_level = int(block.blockFormat().headingLevel())
        block_start = int(block.position())
        block_end = block_start + max(0, int(block.length()) - 1)
        if heading_level > 0 and block_end > block_start:
            cursor = QTextCursor(doc)
            cursor.setPosition(block_start)
            cursor.setPosition(block_end, QTextCursor.MoveMode.KeepAnchor)
            fmt = QTextCharFormat()
            if heading_level == 1:
                fmt.setForeground(heading_h1_q)
            elif heading_level == 2:
                fmt.setForeground(heading_h2_q)
            elif heading_level == 3:
                fmt.setForeground(heading_h3_q)
            else:
                fmt.setForeground(heading_default_q)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            selections.append(sel)
            block = block.next()
            continue

        iterator = block.begin()
        while not iterator.atEnd():
            frag = iterator.fragment()
            if frag.isValid():
                frag_fmt = frag.charFormat()
                if not frag_fmt.fontFixedPitch():
                    is_bold = int(frag_fmt.fontWeight()) >= int(QFont.Weight.DemiBold)
                    is_italic = bool(frag_fmt.fontItalic())
                    if is_bold or is_italic:
                        color = strong_q if is_bold else em_q
                        if is_bold and is_italic:
                            color = strong_em_q
                        start = int(frag.position())
                        end = start + len(frag.text())
                        if end > start:
                            cursor = QTextCursor(doc)
                            cursor.setPosition(start)
                            cursor.setPosition(
                                end,
                                QTextCursor.MoveMode.KeepAnchor,
                            )
                            fmt = QTextCharFormat()
                            fmt.setForeground(color)
                            sel = QTextEdit.ExtraSelection()
                            sel.cursor = cursor
                            sel.format = fmt
                            selections.append(sel)
            iterator += 1

        block = block.next()

    return selections
def _apply_title_style(self):
    if self._title is None:
        return
    title_pt = self._TITLE_BASE_PT * (self._zoom_percent / 100.0)
    title_color = self._palette_hex(
        QPalette.ColorRole.PlaceholderText,
        "#6C7086",
    )
    if self._preview_theme_id == "accent":
        accent = self._palette_hex(QPalette.ColorRole.Highlight, "#89B4FA")
        title_color = self._mix_hex_colors(title_color, accent, 0.32)
    elif self._preview_theme_id == "vivid":
        title_color = self._mix_hex_colors(title_color, "#3B82F6", 0.62)
    self._title.setStyleSheet(
        f"color: {title_color}; "
        f"font-size: {title_pt:.1f}pt; font-weight: bold;"
    )
def _markdown_stylesheet(self) -> str:
    zoom = self._zoom_percent / 100.0
    body_pt = self._BASE_PT * zoom
    code_pt = max(8.0, body_pt * 0.95)
    paragraph_gap_em = 0.95
    preview_theme = self._normalize_preview_theme_id(self._preview_theme_id)
    base_color = self._palette_hex(QPalette.ColorRole.Base, "#11111B")
    alt_base_color = self._palette_hex(
        QPalette.ColorRole.AlternateBase,
        "#1E1E2E",
    )
    text_color = self._palette_hex(QPalette.ColorRole.Text, "#CDD6F4")
    code_color = self._palette_hex(
        QPalette.ColorRole.PlaceholderText,
        "#BAC2DE",
    )
    link_color = self._palette_hex(QPalette.ColorRole.Highlight, "#89B4FA")
    table_border = self._palette_hex(QPalette.ColorRole.Mid, "#D0D0D0")
    quote_border = self._palette_hex(QPalette.ColorRole.Mid, "#7A7A7A")
    quote_color = self._palette_hex(
        QPalette.ColorRole.PlaceholderText,
        "#BAC2DE",
    )
    heading_h1_color = text_color
    heading_h2_color = text_color
    heading_h3_color = text_color
    heading_default_color = text_color
    strong_color = text_color
    em_color = text_color
    code_bg = "transparent"
    quote_bg = "transparent"
    table_header_bg = "transparent"
    table_header_text = text_color
    hr_color = table_border
    if preview_theme == "accent":
        heading_h1_color = self._mix_hex_colors(text_color, "#60A5FA", 0.64)
        heading_h2_color = self._mix_hex_colors(text_color, "#A78BFA", 0.54)
        heading_h3_color = self._mix_hex_colors(text_color, "#34D399", 0.50)
        heading_default_color = heading_h3_color
        strong_color = self._mix_hex_colors(text_color, "#FB923C", 0.50)
        em_color = self._mix_hex_colors(text_color, link_color, 0.14)
        code_bg = self._mix_hex_colors(base_color, link_color, 0.12)
        quote_bg = self._mix_hex_colors(base_color, link_color, 0.08)
        table_header_bg = self._mix_hex_colors(
            alt_base_color,
            link_color,
            0.10,
        )
        table_header_text = self._mix_hex_colors(text_color, link_color, 0.30)
        hr_color = self._mix_hex_colors(table_border, link_color, 0.28)
        quote_color = self._mix_hex_colors(quote_color, link_color, 0.20)
    elif preview_theme == "vivid":
        heading_h1_color = self._mix_hex_colors(text_color, "#2563EB", 0.86)
        heading_h2_color = self._mix_hex_colors(text_color, "#7C3AED", 0.82)
        heading_h3_color = self._mix_hex_colors(text_color, "#DB2777", 0.76)
        heading_default_color = heading_h3_color
        strong_color = self._mix_hex_colors(text_color, "#F97316", 0.78)
        em_color = self._mix_hex_colors(text_color, "#22C55E", 0.72)
        code_bg = self._mix_hex_colors(base_color, "#A855F7", 0.24)
        quote_bg = self._mix_hex_colors(base_color, "#F97316", 0.18)
        table_header_bg = self._mix_hex_colors(alt_base_color, "#2563EB", 0.35)
        table_header_text = self._mix_hex_colors(text_color, "#F8FAFC", 0.32)
        hr_color = self._mix_hex_colors(table_border, "#F97316", 0.42)
        quote_color = self._mix_hex_colors(quote_color, "#F97316", 0.40)
        quote_border = self._mix_hex_colors(quote_border, "#F97316", 0.56)
        table_border = self._mix_hex_colors(table_border, "#2563EB", 0.34)
    body_rule = (
        "body { "
        "font-family: 'Segoe UI', sans-serif; "
        "font-size: 1em; "
        "line-height: 1.45; "
        f"color: {text_color}; "
        "background: transparent; "
        "}"
    )
    code_rule = (
        "pre, code { "
        "font-family: 'Cascadia Code', 'Consolas', monospace; "
        f"font-size: {code_pt:.1f}pt; "
        f"color: {code_color}; "
        "}"
    )
    return "".join(
        [
            body_rule,
            f"h1 {{ font-size: 2.00em; color: {heading_h1_color}; font-weight: 680; }} ",
            f"h2 {{ font-size: 1.60em; color: {heading_h2_color}; font-weight: 670; }} ",
            f"h3 {{ font-size: 1.30em; color: {heading_h3_color}; font-weight: 660; }} ",
            f"h4, h5, h6 {{ color: {heading_default_color}; font-weight: 650; }} ",
            f"strong, b {{ color: {strong_color}; font-weight: 700; }} ",
            f"em, i {{ color: {em_color}; }} ",
            f"p {{ margin: 0 0 {paragraph_gap_em:.2f}em 0; }} ",
            f"ul, ol {{ margin: 0.35em 0 {paragraph_gap_em:.2f}em 1.35em; }} ",
            "li { margin: 0.20em 0; } ",
            f"a {{ color: {link_color}; }} ",
            (
                "blockquote { "
                f"margin: 0.30em 0 {paragraph_gap_em:.2f}em 0; "
                "padding: 0.10em 0 0.10em 0.80em; "
                f"border-left: 4px solid {quote_border}; "
                f"color: {quote_color}; "
                f"background: {quote_bg}; "
                "}"
            ),
            code_rule,
            f"pre, code {{ background: {code_bg}; border-radius: 3px; }} ",
            "table { border-collapse: collapse; } ",
            (
                f"th, td {{ border: 1px solid {table_border}; "
                "padding: 4px 8px; }}"
            ),
            (
                f"th {{ background: {table_header_bg}; color: {table_header_text}; "
                "font-weight: 650; }}"
            ),
            f"hr {{ border: 0; border-top: 1px solid {hr_color}; }} ",
        ]
    )
def _apply_view_document_style(self):
    body_pt = self._BASE_PT * (self._zoom_percent / 100.0)
    doc = self._view.document()
    font = QFont(doc.defaultFont())
    font.setPointSizeF(body_pt)
    doc.setDefaultFont(font)
    self._apply_title_style()
    margin_px = 0.0
    if self._page_margin_enabled:
        margin_px = max(8.0, body_pt * float(self._page_margin_em))
    doc.setDocumentMargin(float(margin_px))
    doc.setDefaultStyleSheet(self._markdown_stylesheet())
@classmethod
def _normalize_page_margin_em(cls, value: float) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = float(cls._PAGE_MARGIN_DEFAULT_EM)
    choices = [float(v) for _label, v in cls._PAGE_MARGIN_PRESETS]
    if not choices:
        return float(cls._PAGE_MARGIN_DEFAULT_EM)
    nearest = min(choices, key=lambda current: abs(current - numeric))
    return float(nearest)
@classmethod
def global_page_margin_settings(cls) -> tuple[bool, float]:
    return (
        bool(cls._GLOBAL_PAGE_MARGIN_ENABLED),
        float(cls._normalize_page_margin_em(cls._GLOBAL_PAGE_MARGIN_EM)),
    )
@classmethod
def apply_global_page_margin_settings(
    cls,
    *,
    enabled: bool,
    em: float,
):
    normalized_em = cls._normalize_page_margin_em(em)
    cls._GLOBAL_PAGE_MARGIN_ENABLED = bool(enabled)
    cls._GLOBAL_PAGE_MARGIN_EM = float(normalized_em)
    for pane in list(cls._INSTANCES):
        try:
            pane.set_page_margin_settings(
                enabled=bool(enabled),
                em=float(normalized_em),
            )
        except Exception:
            continue
def page_margin_settings(self) -> tuple[bool, float]:
    return bool(self._page_margin_enabled), float(self._page_margin_em)
def _sync_page_margin_controls(self):
    # Page-margin controls are global and live in the main View menu.
    return
def set_page_margin_settings(
    self,
    *,
    enabled: bool | None = None,
    em: float | None = None,
) -> bool:
    changed = False
    if enabled is not None:
        next_enabled = bool(enabled)
        if next_enabled != bool(self._page_margin_enabled):
            self._page_margin_enabled = next_enabled
            changed = True
    if em is not None:
        next_em = self._normalize_page_margin_em(em)
        if abs(next_em - float(self._page_margin_em)) >= 0.001:
            self._page_margin_em = float(next_em)
            changed = True
    if not changed:
        self._sync_page_margin_controls()
        return False
    self._sync_page_margin_controls()
    self._apply_view_document_style()
    return True

__all__ = [
    "_preview_theme_text_colors",
    "_build_preview_theme_extra_selections",
    "_apply_title_style",
    "_markdown_stylesheet",
    "_apply_view_document_style",
    "_normalize_page_margin_em",
    "global_page_margin_settings",
    "apply_global_page_margin_settings",
    "page_margin_settings",
    "_sync_page_margin_controls",
    "set_page_margin_settings",
]
