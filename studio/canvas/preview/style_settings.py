"""Normalization and resolution helpers for markdown/HTML preview styling."""
from __future__ import annotations

import re

from shared.services.highlights.store_records import DEFAULT_GLOSSARY_COLOR


_HEX_RE = re.compile(r"^#(?:[0-9A-Fa-f]{6})$")

_HEADING_LEVELS = (1, 2, 3, 4, 5, 6)
IMAGE_MODE_OPTIONS: tuple[str, ...] = ("yes", "small", "no")

_DEFAULTS: dict[str, object] = {
    "html_font_family": "Segoe UI",
    "markdown_font_family": "Cascadia Code",
    # Legacy key kept for backward compatibility with already persisted settings.
    "font_family": "Segoe UI",
    "code_font_family": "Cascadia Code",
    "base_font_percent": 100,
    "line_height": 1.45,
    "paragraph_gap_em": 0.95,
    "list_margin_top_em": 0.35,
    "list_margin_bottom_em": 0.95,
    "list_item_gap_em": 0.20,
    "list_indent_em": 1.35,
    "list_marker_gap_em": 0.18,
    "blockquote_margin_top_em": 0.30,
    "blockquote_margin_bottom_em": 0.95,
    "table_margin_top_em": 0.40,
    "table_margin_bottom_em": 0.90,
    "hr_margin_top_em": 0.55,
    "hr_margin_bottom_em": 0.85,
    "image_mode": "yes",
    "image_small_max_width_percent": 40,
    "glossary_highlight_color": DEFAULT_GLOSSARY_COLOR,
    "body_background_color": "",
    "body_text_color": "",
    "formula_text_color": "",
    "code_text_color": "",
    "link_color": "",
    "table_border_color": "",
    "quote_border_color": "",
    "quote_text_color": "",
    "code_bg_color": "",
    "quote_bg_color": "",
    "table_header_bg_color": "",
    "table_header_text_color": "",
    "hr_color": "",
    "bold_color": "",
    "italic_color": "",
    "bold_italic_color": "",
}

for _lvl in _HEADING_LEVELS:
    _DEFAULTS[f"heading_h{_lvl}_color"] = ""

_DEFAULTS.update(
    {
        "heading_h1_size_em": 2.00,
        "heading_h2_size_em": 1.60,
        "heading_h3_size_em": 1.30,
        "heading_h4_size_em": 1.10,
        "heading_h5_size_em": 1.00,
        "heading_h6_size_em": 0.90,
        "heading_h1_margin_before_em": 0.80,
        "heading_h1_margin_after_em": 0.45,
        "heading_h2_margin_before_em": 0.72,
        "heading_h2_margin_after_em": 0.40,
        "heading_h3_margin_before_em": 0.64,
        "heading_h3_margin_after_em": 0.34,
        "heading_h4_margin_before_em": 0.56,
        "heading_h4_margin_after_em": 0.30,
        "heading_h5_margin_before_em": 0.50,
        "heading_h5_margin_after_em": 0.26,
        "heading_h6_margin_before_em": 0.44,
        "heading_h6_margin_after_em": 0.22,
    }
)


def default_preview_style_settings() -> dict[str, object]:
    return dict(_DEFAULTS)


def _coerce_float(
    value: object,
    *,
    default: float,
    min_value: float,
    max_value: float,
) -> float:
    try:
        raw = float(value)
    except Exception:
        raw = float(default)
    return max(min_value, min(max_value, raw))


def _coerce_int(
    value: object,
    *,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    try:
        raw = int(float(value))
    except Exception:
        raw = int(default)
    return max(min_value, min(max_value, raw))


def _coerce_font_family(value: object, *, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return str(default)
    if len(text) > 120:
        text = text[:120].strip()
    return text or str(default)


def _coerce_hex_or_empty(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.startswith("#") and len(text) in {3, 6}:
        text = f"#{text}"
    if len(text) == 4 and text.startswith("#"):
        text = f"#{text[1]}{text[1]}{text[2]}{text[2]}{text[3]}{text[3]}"
    if _HEX_RE.match(text):
        return text.upper()
    return ""


def _coerce_image_mode(value: object) -> str:
    token = str(value or "").strip().lower()
    if token in IMAGE_MODE_OPTIONS:
        return token
    return str(_DEFAULTS["image_mode"])


def normalize_preview_style_settings(raw: object) -> dict[str, object]:
    base = default_preview_style_settings()
    payload = raw if isinstance(raw, dict) else {}

    html_font = payload.get("html_font_family")
    if not str(html_font or "").strip():
        html_font = payload.get("font_family")
    base["html_font_family"] = _coerce_font_family(
        html_font,
        default=str(_DEFAULTS["html_font_family"]),
    )
    base["markdown_font_family"] = _coerce_font_family(
        payload.get("markdown_font_family"),
        default=str(_DEFAULTS["markdown_font_family"]),
    )
    base["font_family"] = str(base["html_font_family"])
    base["code_font_family"] = _coerce_font_family(
        payload.get("code_font_family"),
        default=str(_DEFAULTS["code_font_family"]),
    )
    base["line_height"] = _coerce_float(
        payload.get("line_height"),
        default=float(_DEFAULTS["line_height"]),
        min_value=1.0,
        max_value=2.6,
    )
    base["base_font_percent"] = _coerce_int(
        payload.get("base_font_percent"),
        default=int(_DEFAULTS["base_font_percent"]),
        min_value=70,
        max_value=220,
    )
    base["paragraph_gap_em"] = _coerce_float(
        payload.get("paragraph_gap_em"),
        default=float(_DEFAULTS["paragraph_gap_em"]),
        min_value=0.0,
        max_value=3.0,
    )
    base["list_margin_top_em"] = _coerce_float(
        payload.get("list_margin_top_em"),
        default=float(_DEFAULTS["list_margin_top_em"]),
        min_value=0.0,
        max_value=3.0,
    )
    base["list_margin_bottom_em"] = _coerce_float(
        payload.get("list_margin_bottom_em"),
        default=float(_DEFAULTS["list_margin_bottom_em"]),
        min_value=0.0,
        max_value=3.0,
    )
    base["list_item_gap_em"] = _coerce_float(
        payload.get("list_item_gap_em"),
        default=float(_DEFAULTS["list_item_gap_em"]),
        min_value=0.0,
        max_value=2.0,
    )
    base["list_indent_em"] = _coerce_float(
        payload.get("list_indent_em"),
        default=float(_DEFAULTS["list_indent_em"]),
        min_value=0.5,
        max_value=4.0,
    )
    base["list_marker_gap_em"] = _coerce_float(
        payload.get("list_marker_gap_em"),
        default=float(_DEFAULTS["list_marker_gap_em"]),
        min_value=0.0,
        max_value=1.5,
    )
    base["blockquote_margin_top_em"] = _coerce_float(
        payload.get("blockquote_margin_top_em"),
        default=float(_DEFAULTS["blockquote_margin_top_em"]),
        min_value=0.0,
        max_value=3.0,
    )
    base["blockquote_margin_bottom_em"] = _coerce_float(
        payload.get("blockquote_margin_bottom_em"),
        default=float(_DEFAULTS["blockquote_margin_bottom_em"]),
        min_value=0.0,
        max_value=3.0,
    )
    base["table_margin_top_em"] = _coerce_float(
        payload.get("table_margin_top_em"),
        default=float(_DEFAULTS["table_margin_top_em"]),
        min_value=0.0,
        max_value=3.0,
    )
    base["table_margin_bottom_em"] = _coerce_float(
        payload.get("table_margin_bottom_em"),
        default=float(_DEFAULTS["table_margin_bottom_em"]),
        min_value=0.0,
        max_value=3.0,
    )
    base["hr_margin_top_em"] = _coerce_float(
        payload.get("hr_margin_top_em"),
        default=float(_DEFAULTS["hr_margin_top_em"]),
        min_value=0.0,
        max_value=3.0,
    )
    base["hr_margin_bottom_em"] = _coerce_float(
        payload.get("hr_margin_bottom_em"),
        default=float(_DEFAULTS["hr_margin_bottom_em"]),
        min_value=0.0,
        max_value=3.0,
    )
    base["image_mode"] = _coerce_image_mode(payload.get("image_mode"))
    base["image_small_max_width_percent"] = _coerce_int(
        payload.get("image_small_max_width_percent"),
        default=int(_DEFAULTS["image_small_max_width_percent"]),
        min_value=10,
        max_value=100,
    )
    base["glossary_highlight_color"] = _coerce_hex_or_empty(
        payload.get("glossary_highlight_color")
    ) or str(_DEFAULTS["glossary_highlight_color"])

    color_keys = (
        "body_background_color",
        "body_text_color",
        "formula_text_color",
        "code_text_color",
        "link_color",
        "table_border_color",
        "quote_border_color",
        "quote_text_color",
        "code_bg_color",
        "quote_bg_color",
        "table_header_bg_color",
        "table_header_text_color",
        "hr_color",
        "bold_color",
        "italic_color",
        "bold_italic_color",
    )
    for key in color_keys:
        base[key] = _coerce_hex_or_empty(payload.get(key))

    for lvl in _HEADING_LEVELS:
        size_key = f"heading_h{lvl}_size_em"
        before_key = f"heading_h{lvl}_margin_before_em"
        after_key = f"heading_h{lvl}_margin_after_em"
        color_key = f"heading_h{lvl}_color"
        base[size_key] = _coerce_float(
            payload.get(size_key),
            default=float(_DEFAULTS[size_key]),
            min_value=0.5,
            max_value=4.0,
        )
        base[before_key] = _coerce_float(
            payload.get(before_key),
            default=float(_DEFAULTS[before_key]),
            min_value=0.0,
            max_value=3.0,
        )
        base[after_key] = _coerce_float(
            payload.get(after_key),
            default=float(_DEFAULTS[after_key]),
            min_value=0.0,
            max_value=3.0,
        )
        base[color_key] = _coerce_hex_or_empty(payload.get(color_key))

    return base


def _mix_hex_colors(primary: str, secondary: str, secondary_weight: float) -> str:
    p = _coerce_hex_or_empty(primary)
    s = _coerce_hex_or_empty(secondary)
    if not p and not s:
        return "#000000"
    if not p:
        return s
    if not s:
        return p
    w = max(0.0, min(1.0, float(secondary_weight)))
    inv = 1.0 - w
    pr, pg, pb = int(p[1:3], 16), int(p[3:5], 16), int(p[5:7], 16)
    sr, sg, sb = int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)
    r = int(round((pr * inv) + (sr * w)))
    g = int(round((pg * inv) + (sg * w)))
    b = int(round((pb * inv) + (sb * w)))
    return f"#{r:02X}{g:02X}{b:02X}"


def resolve_preview_style_tokens(
    *,
    preview_theme_id: str,
    style_settings: object,
    base_color: str,
    alt_base_color: str,
    text_color: str,
    placeholder_color: str,
    highlight_color: str,
    mid_color: str,
) -> dict[str, object]:
    style = normalize_preview_style_settings(style_settings)
    theme = str(preview_theme_id or "").strip().lower()

    base_hex = _coerce_hex_or_empty(base_color) or "#11111B"
    alt_base_hex = _coerce_hex_or_empty(alt_base_color) or "#1E1E2E"
    text_hex = _coerce_hex_or_empty(text_color) or "#CDD6F4"
    placeholder_hex = _coerce_hex_or_empty(placeholder_color) or "#BAC2DE"
    highlight_hex = _coerce_hex_or_empty(highlight_color) or "#89B4FA"
    mid_hex = _coerce_hex_or_empty(mid_color) or "#7A7A7A"

    heading_h1 = text_hex
    heading_h2 = text_hex
    heading_h3 = text_hex
    heading_h4 = text_hex
    heading_h5 = text_hex
    heading_h6 = text_hex
    strong_color = text_hex
    em_color = text_hex
    code_bg = "transparent"
    quote_bg = "transparent"
    table_header_bg = "transparent"
    table_header_text = text_hex
    hr_color = mid_hex
    quote_border = mid_hex
    quote_color = placeholder_hex
    table_border = mid_hex

    if theme == "accent":
        heading_h1 = _mix_hex_colors(text_hex, "#60A5FA", 0.64)
        heading_h2 = _mix_hex_colors(text_hex, "#A78BFA", 0.54)
        heading_h3 = _mix_hex_colors(text_hex, "#34D399", 0.50)
        heading_h4 = _mix_hex_colors(text_hex, "#F97316", 0.46)
        heading_h5 = _mix_hex_colors(text_hex, "#F43F5E", 0.42)
        heading_h6 = _mix_hex_colors(text_hex, "#22D3EE", 0.38)
        strong_color = _mix_hex_colors(text_hex, "#FB923C", 0.50)
        em_color = _mix_hex_colors(text_hex, highlight_hex, 0.24)
        code_bg = _mix_hex_colors(base_hex, highlight_hex, 0.12)
        quote_bg = _mix_hex_colors(base_hex, highlight_hex, 0.08)
        table_header_bg = _mix_hex_colors(alt_base_hex, highlight_hex, 0.10)
        table_header_text = _mix_hex_colors(text_hex, highlight_hex, 0.30)
        hr_color = _mix_hex_colors(mid_hex, highlight_hex, 0.28)
        quote_color = _mix_hex_colors(placeholder_hex, highlight_hex, 0.20)
    elif theme == "vivid":
        heading_h1 = _mix_hex_colors(text_hex, "#2563EB", 0.86)
        heading_h2 = _mix_hex_colors(text_hex, "#7C3AED", 0.82)
        heading_h3 = _mix_hex_colors(text_hex, "#DB2777", 0.76)
        heading_h4 = _mix_hex_colors(text_hex, "#F97316", 0.74)
        heading_h5 = _mix_hex_colors(text_hex, "#22C55E", 0.70)
        heading_h6 = _mix_hex_colors(text_hex, "#06B6D4", 0.66)
        strong_color = _mix_hex_colors(text_hex, "#F97316", 0.78)
        em_color = _mix_hex_colors(text_hex, "#22C55E", 0.72)
        code_bg = _mix_hex_colors(base_hex, "#A855F7", 0.24)
        quote_bg = _mix_hex_colors(base_hex, "#F97316", 0.18)
        table_header_bg = _mix_hex_colors(alt_base_hex, "#2563EB", 0.35)
        table_header_text = _mix_hex_colors(text_hex, "#F8FAFC", 0.32)
        hr_color = _mix_hex_colors(mid_hex, "#F97316", 0.42)
        quote_color = _mix_hex_colors(placeholder_hex, "#F97316", 0.40)
        quote_border = _mix_hex_colors(mid_hex, "#F97316", 0.56)
        table_border = _mix_hex_colors(mid_hex, "#2563EB", 0.34)

    bold_italic_color = _mix_hex_colors(strong_color, em_color, 0.45)

    body_background_resolved = (
        _coerce_hex_or_empty(style["body_background_color"]) or "transparent"
    )
    body_text_resolved = _coerce_hex_or_empty(style["body_text_color"]) or text_hex
    formula_text_resolved = (
        _coerce_hex_or_empty(style["formula_text_color"]) or body_text_resolved
    )

    resolved = {
        "html_font_family": str(style["html_font_family"]),
        "markdown_font_family": str(style["markdown_font_family"]),
        # Keep legacy mirror for older callers.
        "font_family": str(style["html_font_family"]),
        "code_font_family": str(style["code_font_family"]),
        "base_font_percent": int(style["base_font_percent"]),
        "line_height": float(style["line_height"]),
        "paragraph_gap_em": float(style["paragraph_gap_em"]),
        "list_margin_top_em": float(style["list_margin_top_em"]),
        "list_margin_bottom_em": float(style["list_margin_bottom_em"]),
        "list_item_gap_em": float(style["list_item_gap_em"]),
        "list_indent_em": float(style["list_indent_em"]),
        "list_marker_gap_em": float(style["list_marker_gap_em"]),
        "blockquote_margin_top_em": float(style["blockquote_margin_top_em"]),
        "blockquote_margin_bottom_em": float(style["blockquote_margin_bottom_em"]),
        "table_margin_top_em": float(style["table_margin_top_em"]),
        "table_margin_bottom_em": float(style["table_margin_bottom_em"]),
        "hr_margin_top_em": float(style["hr_margin_top_em"]),
        "hr_margin_bottom_em": float(style["hr_margin_bottom_em"]),
        "image_mode": str(style["image_mode"]),
        "image_small_max_width_percent": int(style["image_small_max_width_percent"]),
        "glossary_highlight_color": str(style["glossary_highlight_color"]),
        "base_color": base_hex,
        "alt_base_color": alt_base_hex,
        "text_color": text_hex,
        "placeholder_color": placeholder_hex,
        "highlight_color": highlight_hex,
        "mid_color": mid_hex,
        "body_background_color": body_background_resolved,
        "body_text_color": body_text_resolved,
        "formula_text_color": formula_text_resolved,
        "code_text_color": _coerce_hex_or_empty(style["code_text_color"]) or placeholder_hex,
        "link_color": _coerce_hex_or_empty(style["link_color"]) or highlight_hex,
        "table_border_color": _coerce_hex_or_empty(style["table_border_color"]) or table_border,
        "quote_border_color": _coerce_hex_or_empty(style["quote_border_color"]) or quote_border,
        "quote_text_color": _coerce_hex_or_empty(style["quote_text_color"]) or quote_color,
        "code_bg_color": _coerce_hex_or_empty(style["code_bg_color"]) or code_bg,
        "quote_bg_color": _coerce_hex_or_empty(style["quote_bg_color"]) or quote_bg,
        "table_header_bg_color": _coerce_hex_or_empty(style["table_header_bg_color"]) or table_header_bg,
        "table_header_text_color": _coerce_hex_or_empty(style["table_header_text_color"]) or table_header_text,
        "hr_color": _coerce_hex_or_empty(style["hr_color"]) or hr_color,
        "bold_color": _coerce_hex_or_empty(style["bold_color"]) or strong_color,
        "italic_color": _coerce_hex_or_empty(style["italic_color"]) or em_color,
        "bold_italic_color": _coerce_hex_or_empty(style["bold_italic_color"]) or bold_italic_color,
        "heading_h1_color": _coerce_hex_or_empty(style["heading_h1_color"]) or heading_h1,
        "heading_h2_color": _coerce_hex_or_empty(style["heading_h2_color"]) or heading_h2,
        "heading_h3_color": _coerce_hex_or_empty(style["heading_h3_color"]) or heading_h3,
        "heading_h4_color": _coerce_hex_or_empty(style["heading_h4_color"]) or heading_h4,
        "heading_h5_color": _coerce_hex_or_empty(style["heading_h5_color"]) or heading_h5,
        "heading_h6_color": _coerce_hex_or_empty(style["heading_h6_color"]) or heading_h6,
        "heading_h1_size_em": float(style["heading_h1_size_em"]),
        "heading_h2_size_em": float(style["heading_h2_size_em"]),
        "heading_h3_size_em": float(style["heading_h3_size_em"]),
        "heading_h4_size_em": float(style["heading_h4_size_em"]),
        "heading_h5_size_em": float(style["heading_h5_size_em"]),
        "heading_h6_size_em": float(style["heading_h6_size_em"]),
        "heading_h1_margin_before_em": float(style["heading_h1_margin_before_em"]),
        "heading_h1_margin_after_em": float(style["heading_h1_margin_after_em"]),
        "heading_h2_margin_before_em": float(style["heading_h2_margin_before_em"]),
        "heading_h2_margin_after_em": float(style["heading_h2_margin_after_em"]),
        "heading_h3_margin_before_em": float(style["heading_h3_margin_before_em"]),
        "heading_h3_margin_after_em": float(style["heading_h3_margin_after_em"]),
        "heading_h4_margin_before_em": float(style["heading_h4_margin_before_em"]),
        "heading_h4_margin_after_em": float(style["heading_h4_margin_after_em"]),
        "heading_h5_margin_before_em": float(style["heading_h5_margin_before_em"]),
        "heading_h5_margin_after_em": float(style["heading_h5_margin_after_em"]),
        "heading_h6_margin_before_em": float(style["heading_h6_margin_before_em"]),
        "heading_h6_margin_after_em": float(style["heading_h6_margin_after_em"]),
    }
    return resolved


__all__ = [
    "IMAGE_MODE_OPTIONS",
    "default_preview_style_settings",
    "normalize_preview_style_settings",
    "resolve_preview_style_tokens",
]
