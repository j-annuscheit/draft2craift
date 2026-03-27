"""Shared styles for markdown editor widgets and tab containers."""
from __future__ import annotations

_FONT_FALLBACKS: tuple[str, ...] = (
    "Cascadia Code",
    "JetBrains Mono",
    "Fira Code",
    "Consolas",
    "monospace",
)


def _css_quote_font_family(value: str) -> str:
    return "'" + str(value or "").replace("\\", "\\\\").replace("'", "\\'") + "'"


def _build_font_stack(primary_family: str | None) -> str:
    ordered: list[str] = []
    seen: set[str] = set()
    primary = str(primary_family or "").strip()
    if primary:
        key = primary.casefold()
        if key not in seen:
            seen.add(key)
            ordered.append(_css_quote_font_family(primary))
    for fallback in _FONT_FALLBACKS:
        key = fallback.casefold()
        if key in seen:
            continue
        seen.add(key)
        if fallback.lower() == "monospace":
            ordered.append("monospace")
        else:
            ordered.append(_css_quote_font_family(fallback))
    return ", ".join(ordered)


def editor_style(
    read_only: bool,
    font_size_pt: float,
    font_family: str | None = None,
) -> str:
    if read_only:
        bg, fg, border = "palette(base)", "palette(text)", "palette(mid)"
    else:
        bg, fg, border = "palette(base)", "palette(text)", "palette(highlight)"
    font_stack = _build_font_stack(font_family)
    return f"""
QPlainTextEdit {{
    background-color: {bg};
    color: {fg};
    border: 1px solid {border};
    padding: 8px;
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
    font-family: {font_stack};
    font-size: {font_size_pt:.1f}pt;
}}
"""


TOOLBAR_STYLE = """
QWidget#toolbar {
    background: palette(alternate-base);
    border-bottom: 1px solid palette(mid);
}
QPushButton {
    background: transparent;
    color: palette(text);
    border: none;
    padding: 2px 10px;
    font-size: 11px;
    border-radius: 3px;
}
QPushButton:hover  { background: palette(mid); }
QPushButton:checked { background: palette(highlight); color: palette(highlighted-text); }
QLabel { color: palette(placeholder-text); font-size: 10px; padding: 0 6px; }
"""


TAB_STYLE = """
QTabWidget::pane  { border: none; }
QTabBar::tab {
    background: palette(alternate-base);
    color: palette(placeholder-text);
    padding: 4px 14px;
    border: none;
    border-right: 1px solid palette(base);
    min-width: 80px;
}
QTabBar::tab:selected {
    background: palette(base);
    color: palette(text);
    border-top: 2px solid palette(highlight);
}
QTabBar::tab:hover { background: palette(mid); color: palette(text); }
"""


TAB_STYLE_COMPACT = """
QTabWidget::pane  { border: none; }
QTabBar::tab {
    background: palette(alternate-base);
    color: palette(placeholder-text);
    padding: 4px 6px;
    border: none;
    border-right: 1px solid palette(base);
    min-width: 18px;
}
QTabBar::tab:selected {
    background: palette(base);
    color: palette(text);
    border-top: 2px solid palette(highlight);
    min-width: 90px;
    padding: 4px 10px;
}
QTabBar::tab:hover { background: palette(mid); color: palette(text); }
"""
