"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403
from ..style_settings import (
    normalize_preview_style_settings,
    resolve_preview_style_tokens,
)

def _preview_theme_text_colors(self) -> dict[str, str]:
    resolved = self._resolved_preview_style_tokens()
    return {
        "heading_h1": str(resolved["heading_h1_color"]),
        "heading_h2": str(resolved["heading_h2_color"]),
        "heading_h3": str(resolved["heading_h3_color"]),
        "heading_h4": str(resolved["heading_h4_color"]),
        "heading_h5": str(resolved["heading_h5_color"]),
        "heading_h6": str(resolved["heading_h6_color"]),
        "strong": str(resolved["bold_color"]),
        "em": str(resolved["italic_color"]),
        "strong_em": str(resolved["bold_italic_color"]),
    }


def _resolved_preview_style_tokens(self) -> dict[str, object]:
    settings = normalize_preview_style_settings(
        getattr(self, "_preview_style_settings", {})
    )
    preview_theme = self._normalize_preview_theme_id(self._preview_theme_id)
    app = QApplication.instance()
    palette = app.palette() if app is not None else self.palette()
    return resolve_preview_style_tokens(
        preview_theme_id=preview_theme,
        style_settings=settings,
        base_color=palette.color(QPalette.ColorRole.Base).name(QColor.NameFormat.HexRgb),
        alt_base_color=palette.color(QPalette.ColorRole.AlternateBase).name(QColor.NameFormat.HexRgb),
        text_color=palette.color(QPalette.ColorRole.Text).name(QColor.NameFormat.HexRgb),
        placeholder_color=palette.color(QPalette.ColorRole.PlaceholderText).name(
            QColor.NameFormat.HexRgb
        ),
        highlight_color=palette.color(QPalette.ColorRole.Highlight).name(QColor.NameFormat.HexRgb),
        mid_color=palette.color(QPalette.ColorRole.Mid).name(QColor.NameFormat.HexRgb),
    )


def _build_preview_theme_extra_selections(self) -> list[QTextEdit.ExtraSelection]:
    if str(self.preview_theme_id() or "") == "classic":
        return []
    doc = self._view.document()
    colors = self._preview_theme_text_colors()
    heading_h1_q = QColor(colors["heading_h1"])
    heading_h2_q = QColor(colors["heading_h2"])
    heading_h3_q = QColor(colors["heading_h3"])
    heading_h4_q = QColor(colors["heading_h4"])
    heading_h5_q = QColor(colors["heading_h5"])
    heading_h6_q = QColor(colors["heading_h6"])
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
            elif heading_level == 4:
                fmt.setForeground(heading_h4_q)
            elif heading_level == 5:
                fmt.setForeground(heading_h5_q)
            else:
                fmt.setForeground(heading_h6_q)
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
    resolved = self._resolved_preview_style_tokens()
    title_color = str(resolved["heading_h4_color"])
    self._title.setStyleSheet(
        f"color: {title_color}; "
        f"font-size: {title_pt:.1f}pt; font-weight: bold;"
    )


def _markdown_stylesheet(self) -> str:
    resolved = self._resolved_preview_style_tokens()
    code_pt = self._code_pt()
    image_mode = str(resolved["image_mode"])
    if image_mode == "no":
        image_rule = "img { display: none; } "
    elif image_mode == "small":
        max_w = int(resolved["image_small_max_width_percent"])
        image_rule = (
            "img { display:block; height:auto; "
            f"max-width: {max_w}%; margin: 0.35em 0; }} "
        )
    else:
        image_rule = (
            "img { display:block; height:auto; "
            "max-width: 100%; margin: 0.35em 0; } "
        )
    body_rule = (
        "body { "
        f"font-family: '{resolved['html_font_family']}', sans-serif; "
        "font-size: 1em; "
        f"line-height: {float(resolved['line_height']):.2f}; "
        f"color: {resolved['body_text_color']}; "
        f"background: {resolved['body_background_color']}; "
        "}"
    )
    inline_code_rule = (
        "code { "
        f"font-family: '{resolved['code_font_family']}', 'Consolas', monospace; "
        f"font-size: {code_pt:.1f}pt; "
        f"color: {resolved['code_text_color']}; "
        f"background: {resolved['code_bg_color']}; "
        "border-radius: 3px; "
        "padding: 0.06em 0.30em; "
        "}"
    )
    code_block_rule = (
        "pre { "
        f"font-family: '{resolved['code_font_family']}', 'Consolas', monospace; "
        f"font-size: {code_pt:.1f}pt; "
        f"color: {resolved['code_text_color']}; "
        f"background: {resolved['code_bg_color']}; "
        f"border: 1px solid {resolved['table_border_color']}; "
        "border-radius: 6px; "
        "padding: 0.55em 0.75em; "
        "margin: 0.55em 0 0.85em 0; "
        "}"
    )
    code_block_inner_rule = (
        "pre code { "
        "display: block; "
        "background: transparent; "
        "border: 0; "
        "padding: 0; "
        "border-radius: 0; "
        "margin: 0; "
        "}"
    )
    return "".join(
        [
            body_rule,
            (
                "h1 { "
                f"font-size: {float(resolved['heading_h1_size_em']):.2f}em; "
                f"color: {resolved['heading_h1_color']}; font-weight: 680; "
                f"margin: {float(resolved['heading_h1_margin_before_em']):.2f}em 0 "
                f"{float(resolved['heading_h1_margin_after_em']):.2f}em 0; "
                "} "
            ),
            (
                "h2 { "
                f"font-size: {float(resolved['heading_h2_size_em']):.2f}em; "
                f"color: {resolved['heading_h2_color']}; font-weight: 670; "
                f"margin: {float(resolved['heading_h2_margin_before_em']):.2f}em 0 "
                f"{float(resolved['heading_h2_margin_after_em']):.2f}em 0; "
                "} "
            ),
            (
                "h3 { "
                f"font-size: {float(resolved['heading_h3_size_em']):.2f}em; "
                f"color: {resolved['heading_h3_color']}; font-weight: 660; "
                f"margin: {float(resolved['heading_h3_margin_before_em']):.2f}em 0 "
                f"{float(resolved['heading_h3_margin_after_em']):.2f}em 0; "
                "} "
            ),
            (
                "h4 { "
                f"font-size: {float(resolved['heading_h4_size_em']):.2f}em; "
                f"color: {resolved['heading_h4_color']}; font-weight: 650; "
                f"margin: {float(resolved['heading_h4_margin_before_em']):.2f}em 0 "
                f"{float(resolved['heading_h4_margin_after_em']):.2f}em 0; "
                "} "
            ),
            (
                "h5 { "
                f"font-size: {float(resolved['heading_h5_size_em']):.2f}em; "
                f"color: {resolved['heading_h5_color']}; font-weight: 650; "
                f"margin: {float(resolved['heading_h5_margin_before_em']):.2f}em 0 "
                f"{float(resolved['heading_h5_margin_after_em']):.2f}em 0; "
                "} "
            ),
            (
                "h6 { "
                f"font-size: {float(resolved['heading_h6_size_em']):.2f}em; "
                f"color: {resolved['heading_h6_color']}; font-weight: 650; "
                f"margin: {float(resolved['heading_h6_margin_before_em']):.2f}em 0 "
                f"{float(resolved['heading_h6_margin_after_em']):.2f}em 0; "
                "} "
            ),
            f"strong, b {{ color: {resolved['bold_color']}; font-weight: 700; }} ",
            f"em, i {{ color: {resolved['italic_color']}; }} ",
            f"strong em, em strong, b i, i b {{ color: {resolved['bold_italic_color']}; }} ",
            (
                "p { "
                f"margin: 0 0 {float(resolved['paragraph_gap_em']):.2f}em 0; "
                "} "
            ),
            (
                "ul, ol { "
                "margin: 0 0 0 0; "
                "padding-left: 0.00em; "
                "} "
            ),
            (
                "li { "
                "margin: 0 0 0 0; "
                "padding-left: 0.00em; "
                "} "
            ),
            f"a {{ color: {resolved['link_color']}; }} ",
            (
                "blockquote { "
                f"margin: {float(resolved['blockquote_margin_top_em']):.2f}em 0 "
                f"{float(resolved['blockquote_margin_bottom_em']):.2f}em 0; "
                "padding: 0.10em 0 0.10em 0.80em; "
                f"border-left: 4px solid {resolved['quote_border_color']}; "
                f"color: {resolved['quote_text_color']}; "
                f"background: {resolved['quote_bg_color']}; "
                "}"
            ),
            inline_code_rule,
            code_block_rule,
            code_block_inner_rule,
            (
                "table { "
                "border-collapse: collapse; "
                f"margin: {float(resolved['table_margin_top_em']):.2f}em 0 "
                f"{float(resolved['table_margin_bottom_em']):.2f}em 0; "
                "} "
            ),
            (
                f"th, td {{ border: 1px solid {resolved['table_border_color']}; "
                "padding: 4px 8px; }}"
            ),
            (
                f"th {{ background: {resolved['table_header_bg_color']}; "
                f"color: {resolved['table_header_text_color']}; "
                "font-weight: 650; }}"
            ),
            (
                "hr { "
                "border: 0; "
                f"border-top: 1px solid {resolved['hr_color']}; "
                f"margin: {float(resolved['hr_margin_top_em']):.2f}em 0 "
                f"{float(resolved['hr_margin_bottom_em']):.2f}em 0; "
                "} "
            ),
            image_rule,
        ]
    )


def _apply_view_document_style(self):
    resolved = self._resolved_preview_style_tokens()
    body_pt = self._BASE_PT * (self._zoom_percent / 100.0)
    body_pt *= int(resolved["base_font_percent"]) / 100.0
    doc = self._view.document()
    font = QFont(doc.defaultFont())
    html_family = str(
        resolved.get("html_font_family")
        or resolved.get("font_family")
        or "Segoe UI"
    )
    try:
        font.setFamilies([html_family, "Segoe UI", "sans-serif"])
    except Exception:
        font.setFamily(html_family)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setFixedPitch(False)
    font.setPointSizeF(body_pt)
    doc.setDefaultFont(font)
    self._apply_title_style()
    margin_px = 0.0
    if self._page_margin_enabled:
        margin_px = max(8.0, body_pt * float(self._page_margin_em))
    doc.setDocumentMargin(float(margin_px))
    doc.setDefaultStyleSheet(self._markdown_stylesheet())
    body_bg = str(resolved.get("body_background_color", "") or "").strip()
    body_text = str(resolved.get("body_text_color", "") or "").strip()
    bg_q = QColor(body_bg)
    fg_q = QColor(body_text)
    view_bg = body_bg if bg_q.isValid() and body_bg.lower() != "transparent" else "palette(base)"
    view_fg = body_text if fg_q.isValid() else "palette(text)"
    self._view.setStyleSheet(
        "QTextBrowser {"
        f"background: {view_bg};"
        f"color: {view_fg};"
        "border: 1px solid palette(mid);"
        "border-radius: 6px;"
        "padding: 2px;"
        "}"
    )
    self._view.setProperty(
        "_quote_border_color",
        str(resolved.get("quote_border_color", "") or ""),
    )
    self._view.setProperty(
        "_hr_color",
        str(resolved.get("hr_color", "") or ""),
    )
    self._view.setProperty(
        "_formula_text_color",
        str(resolved.get("formula_text_color", "") or ""),
    )


def _spacing_px(self, em: object) -> float:
    resolved = self._resolved_preview_style_tokens()
    body_pt = self._BASE_PT * (self._zoom_percent / 100.0)
    body_pt *= int(resolved["base_font_percent"]) / 100.0
    try:
        value = float(em)
    except Exception:
        value = 0.0
    return max(0.0, body_pt * value)


def _code_pt(self) -> float:
    resolved = self._resolved_preview_style_tokens()
    body_pt = self._BASE_PT * (self._zoom_percent / 100.0)
    body_pt *= int(resolved["base_font_percent"]) / 100.0
    return max(1.0, body_pt * 0.95)


def _is_code_fragment(self, block_obj, frag_obj) -> bool:
    block_fmt = block_obj.blockFormat()
    has_code_fence = bool(
        str(
            block_fmt.stringProperty(int(QTextFormat.Property.BlockCodeFence))
            or ""
        ).strip()
    )
    if has_code_fence:
        return True
    frag_fmt = frag_obj.charFormat()
    if bool(frag_fmt.fontFixedPitch()):
        return True
    families = [str(item or "").strip().lower() for item in (frag_fmt.fontFamilies() or [])]
    return any("mono" in item for item in families)


def _apply_code_typography_overrides(self):
    if self._structured_view_active:
        return
    doc = self._view.document()
    if doc is None:
        return
    resolved = self._resolved_preview_style_tokens()
    code_pt = self._code_pt()
    code_family = str(resolved.get("code_font_family", "Cascadia Code") or "Cascadia Code")
    code_color = QColor(str(resolved.get("code_text_color", "") or ""))
    code_bg = QColor(str(resolved.get("code_bg_color", "") or ""))

    block = doc.begin()
    while block.isValid():
        is_fenced_code_block = bool(
            str(
                block.blockFormat().stringProperty(
                    int(QTextFormat.Property.BlockCodeFence)
                )
                or ""
            ).strip()
        )
        iterator = block.begin()
        while not iterator.atEnd():
            frag = iterator.fragment()
            if not frag.isValid():
                iterator += 1
                continue
            text = str(frag.text() or "")
            if not text:
                iterator += 1
                continue
            if not self._is_code_fragment(block, frag):
                iterator += 1
                continue
            start = int(frag.position())
            end = start + len(text)
            if end <= start:
                iterator += 1
                continue
            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            fmt = QTextCharFormat()
            fmt.setFontFixedPitch(True)
            fmt.setFontPointSize(float(code_pt))
            try:
                fmt.setFontFamilies([code_family, "Consolas", "monospace"])
            except Exception:
                pass
            if code_color.isValid():
                fmt.setForeground(code_color)
            if code_bg.isValid() and (not is_fenced_code_block):
                fmt.setBackground(code_bg)
            cursor.mergeCharFormat(fmt)
            iterator += 1
        block = block.next()


def _apply_block_spacing_overrides(self):
    if self._structured_view_active:
        return
    doc = self._view.document()
    if doc is None:
        return

    resolved = self._resolved_preview_style_tokens()
    paragraph_bottom_px = self._spacing_px(resolved["paragraph_gap_em"])
    list_top_px = self._spacing_px(resolved["list_margin_top_em"])
    list_bottom_px = self._spacing_px(resolved["list_margin_bottom_em"])
    list_item_px = self._spacing_px(resolved["list_item_gap_em"])
    list_indent_px = self._spacing_px(resolved["list_indent_em"])
    list_marker_gap_em = max(0.0, float(resolved["list_marker_gap_em"]))
    marker_space_count = max(
        1,
        min(12, 1 + int(list_marker_gap_em * 4.0)),
    )
    quote_top_px = self._spacing_px(resolved["blockquote_margin_top_em"])
    quote_bottom_px = self._spacing_px(resolved["blockquote_margin_bottom_em"])
    hr_top_px = self._spacing_px(resolved["hr_margin_top_em"])
    hr_bottom_px = self._spacing_px(resolved["hr_margin_bottom_em"])
    table_top_px = self._spacing_px(resolved["table_margin_top_em"])
    table_bottom_px = self._spacing_px(resolved["table_margin_bottom_em"])
    code_outer_top_px = self._spacing_px(0.55)
    code_outer_bottom_px = self._spacing_px(0.85)
    code_inner_vertical_px = self._spacing_px(0.02)
    code_side_px = self._spacing_px(0.70)
    code_bg = QColor(str(resolved.get("code_bg_color", "") or ""))
    if (not code_bg.isValid()) or code_bg.alpha() <= 0:
        code_bg = QColor(str(resolved.get("alt_base_color", "") or ""))
    if (not code_bg.isValid()) or code_bg.alpha() <= 0:
        code_bg = self.palette().color(QPalette.ColorRole.AlternateBase)
    if (not code_bg.isValid()) or code_bg.alpha() <= 0:
        code_bg = QColor("#1E1E2E")

    list_bounds: dict[int, tuple[int, int]] = {}
    table_bounds: dict[int, tuple[int, int]] = {}
    code_run_bounds: list[tuple[int, int]] = []
    code_run_start: int | None = None
    last_block_number = -1
    block = doc.begin()
    while block.isValid():
        block_number = int(block.blockNumber())
        last_block_number = block_number
        has_code_fence = bool(
            str(
                block.blockFormat().stringProperty(
                    int(QTextFormat.Property.BlockCodeFence)
                )
                or ""
            ).strip()
        )
        if has_code_fence:
            if code_run_start is None:
                code_run_start = block_number
        elif code_run_start is not None:
            code_run_bounds.append((code_run_start, block_number - 1))
            code_run_start = None
        text_list = block.textList()
        if text_list is not None:
            object_index_fn = getattr(text_list, "objectIndex", None)
            if callable(object_index_fn):
                key = int(object_index_fn())
            else:
                key = int(block_number)
            entry = list_bounds.get(key)
            if entry is None:
                list_bounds[key] = (block_number, block_number)
            else:
                list_bounds[key] = (
                    min(entry[0], block_number),
                    max(entry[1], block_number),
                )
        probe = QTextCursor(block)
        table = probe.currentTable()
        if table is not None:
            object_index_fn = getattr(table, "objectIndex", None)
            if callable(object_index_fn):
                table_key = int(object_index_fn())
            else:
                table_key = int(block_number)
            table_entry = table_bounds.get(table_key)
            if table_entry is None:
                table_bounds[table_key] = (block_number, block_number)
            else:
                table_bounds[table_key] = (
                    min(table_entry[0], block_number),
                    max(table_entry[1], block_number),
                )
        block = block.next()
    if code_run_start is not None:
        code_run_bounds.append((code_run_start, max(code_run_start, last_block_number)))

    code_bounds: dict[int, tuple[int, int]] = {}
    for first_no, last_no in code_run_bounds:
        for block_no in range(int(first_no), int(last_no) + 1):
            code_bounds[int(block_no)] = (int(first_no), int(last_no))

    cursor = QTextCursor(doc)
    ordered_list_styles = {
        QTextListFormat.Style.ListDecimal,
        QTextListFormat.Style.ListLowerAlpha,
        QTextListFormat.Style.ListUpperAlpha,
        QTextListFormat.Style.ListLowerRoman,
        QTextListFormat.Style.ListUpperRoman,
    }
    list_suffix_applied: set[int] = set()

    def target_list_number_suffix(list_format: QTextListFormat) -> str:
        style = list_format.style()
        if style in ordered_list_styles:
            core_suffix = str(list_format.numberSuffix() or "").rstrip()
            marker = core_suffix[:1]
            if marker not in {".", ")"}:
                marker = "."
            return f"{marker}{' ' * marker_space_count}"
        return " " * marker_space_count

    def set_block_format(
        block_obj,
        *,
        top: float | None = None,
        bottom: float | None = None,
        left: float | None = None,
        right: float | None = None,
        background: QColor | None = None,
    ) -> None:
        fmt = block_obj.blockFormat()
        changed = False
        if top is not None and abs(float(fmt.topMargin()) - float(top)) >= 0.25:
            fmt.setTopMargin(float(top))
            changed = True
        if (
            bottom is not None
            and abs(float(fmt.bottomMargin()) - float(bottom)) >= 0.25
        ):
            fmt.setBottomMargin(float(bottom))
            changed = True
        if left is not None and abs(float(fmt.leftMargin()) - float(left)) >= 0.25:
            fmt.setLeftMargin(float(left))
            changed = True
        if right is not None and abs(float(fmt.rightMargin()) - float(right)) >= 0.25:
            fmt.setRightMargin(float(right))
            changed = True
        if background is not None:
            target_bg = QColor(background)
            current_bg = fmt.background().color()
            if (
                target_bg.isValid()
                and (
                    (not current_bg.isValid())
                    or (int(current_bg.rgba()) != int(target_bg.rgba()))
                )
            ):
                fmt.setBackground(target_bg)
                changed = True
        if not changed:
            return
        cursor_for_block = QTextCursor(block_obj)
        cursor_for_block.setBlockFormat(fmt)

    block = doc.begin()
    while block.isValid():
        block_number = int(block.blockNumber())
        text = str(block.text() or "").strip()
        fmt = block.blockFormat()
        heading_level = int(fmt.headingLevel())
        quote_level = int(
            fmt.intProperty(int(QTextFormat.Property.BlockQuoteLevel))
            or 0
        )
        has_hr = bool(
            fmt.hasProperty(int(QTextFormat.Property.BlockTrailingHorizontalRulerWidth))
        )
        text_list = block.textList()
        probe = QTextCursor(block)
        table = probe.currentTable()
        code_first_last = code_bounds.get(block_number)

        if code_first_last is not None:
            first_no, last_no = code_first_last
            top_margin = code_inner_vertical_px
            bottom_margin = code_inner_vertical_px
            if block_number == first_no:
                top_margin = max(top_margin, code_outer_top_px)
            if block_number == last_no:
                bottom_margin = max(bottom_margin, code_outer_bottom_px)
            set_block_format(
                block,
                top=top_margin,
                bottom=bottom_margin,
                left=code_side_px,
                right=code_side_px,
                background=code_bg,
            )
            block = block.next()
            continue

        if heading_level > 0:
            level = min(6, max(1, heading_level))
            before = self._spacing_px(
                resolved.get(f"heading_h{level}_margin_before_em", 0.0)
            )
            after = self._spacing_px(
                resolved.get(f"heading_h{level}_margin_after_em", 0.0)
            )
            set_block_format(
                block,
                top=before,
                bottom=after,
            )
            block = block.next()
            continue

        if text_list is not None:
            object_index_fn = getattr(text_list, "objectIndex", None)
            if callable(object_index_fn):
                list_key = int(object_index_fn())
            else:
                list_key = int(block_number)
            if list_key not in list_suffix_applied:
                list_fmt = QTextListFormat(text_list.format())
                target_suffix = target_list_number_suffix(list_fmt)
                if str(list_fmt.numberSuffix() or "") != target_suffix:
                    list_fmt.setNumberSuffix(target_suffix)
                    text_list.setFormat(list_fmt)
                list_suffix_applied.add(list_key)
            first_no, last_no = list_bounds.get(
                list_key,
                (block_number, block_number),
            )
            top_margin = list_item_px
            bottom_margin = list_item_px
            if block_number == first_no:
                top_margin = max(top_margin, list_top_px)
            if block_number == last_no:
                bottom_margin = max(bottom_margin, list_bottom_px)
            list_level = max(1, int(text_list.format().indent() or 1))
            set_block_format(
                block,
                top=top_margin,
                bottom=bottom_margin,
                left=(list_indent_px * float(list_level)),
            )
            block = block.next()
            continue

        if quote_level > 0:
            set_block_format(
                block,
                top=quote_top_px,
                bottom=quote_bottom_px,
            )
            block = block.next()
            continue

        if has_hr:
            set_block_format(
                block,
                top=hr_top_px,
                bottom=hr_bottom_px,
            )
            block = block.next()
            continue

        if table is not None:
            object_index_fn = getattr(table, "objectIndex", None)
            if callable(object_index_fn):
                table_key = int(object_index_fn())
            else:
                table_key = int(block_number)
            first_no, last_no = table_bounds.get(
                table_key,
                (block_number, block_number),
            )
            top_margin = table_top_px if block_number == first_no else 0.0
            bottom_margin = table_bottom_px if block_number == last_no else 0.0
            set_block_format(
                block,
                top=top_margin,
                bottom=bottom_margin,
            )
            block = block.next()
            continue

        if text:
            set_block_format(
                block,
                top=0.0,
                bottom=paragraph_bottom_px,
            )

        block = block.next()


@classmethod
def global_preview_style_settings(cls) -> dict[str, object]:
    return normalize_preview_style_settings(cls._GLOBAL_PREVIEW_STYLE_SETTINGS)


@classmethod
def apply_global_preview_style_settings(cls, raw: object, *, force: bool = False):
    normalized = normalize_preview_style_settings(raw)
    current = normalize_preview_style_settings(cls._GLOBAL_PREVIEW_STYLE_SETTINGS)
    if (not force) and normalized == current:
        return
    cls._GLOBAL_PREVIEW_STYLE_SETTINGS = dict(normalized)
    for pane in list(cls._INSTANCES):
        try:
            pane.set_preview_style_settings(normalized, force=force)
        except Exception:
            continue


def preview_style_settings(self) -> dict[str, object]:
    return normalize_preview_style_settings(
        getattr(self, "_preview_style_settings", {})
    )


def set_preview_style_settings(self, raw: object, *, force: bool = False) -> bool:
    normalized = normalize_preview_style_settings(raw)
    current = normalize_preview_style_settings(
        getattr(self, "_preview_style_settings", {})
    )
    if (not force) and normalized == current:
        return False
    marker_gap_changed = (
        abs(
            float(normalized.get("list_marker_gap_em", 0.0))
            - float(current.get("list_marker_gap_em", 0.0))
        )
        >= 0.001
    )
    self._preview_style_settings = dict(normalized)
    self._apply_view_document_style()
    self._apply_block_spacing_overrides()
    self._apply_code_typography_overrides()
    if marker_gap_changed:
        self.invalidate_render_cache()
        if self.isVisible() and (not self._preview_edit_active):
            try:
                self._render()
            except Exception:
                self.schedule_update()
        else:
            self.schedule_update()
    try:
        self._apply_highlights()
    except Exception:
        pass
    self._view.viewport().update()
    return True


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
def normalize_page_margin_em(cls, value: float) -> float:
    """Public wrapper for page-margin normalization."""
    return float(cls._normalize_page_margin_em(value))


@classmethod
def page_margin_default_em(cls) -> float:
    return float(cls._PAGE_MARGIN_DEFAULT_EM)


@classmethod
def page_margin_presets(cls) -> tuple[tuple[str, float], ...]:
    return tuple((str(label), float(em)) for label, em in cls._PAGE_MARGIN_PRESETS)


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
    "_resolved_preview_style_tokens",
    "_build_preview_theme_extra_selections",
    "_apply_title_style",
    "_markdown_stylesheet",
    "_apply_view_document_style",
    "_spacing_px",
    "_code_pt",
    "_is_code_fragment",
    "_apply_code_typography_overrides",
    "_apply_block_spacing_overrides",
    "global_preview_style_settings",
    "apply_global_preview_style_settings",
    "preview_style_settings",
    "set_preview_style_settings",
    "_normalize_page_margin_em",
    "normalize_page_margin_em",
    "page_margin_default_em",
    "page_margin_presets",
    "global_page_margin_settings",
    "apply_global_page_margin_settings",
    "page_margin_settings",
    "_sync_page_margin_controls",
    "set_page_margin_settings",
]
