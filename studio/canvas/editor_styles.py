"""Shared styles for markdown editor widgets and tab containers."""
from __future__ import annotations

_FONT_STACK = "'Cascadia Code', 'JetBrains Mono', 'Fira Code', 'Consolas', monospace"


def editor_style(read_only: bool, font_size_pt: float) -> str:
    if read_only:
        bg, fg, border = "palette(base)", "palette(text)", "palette(mid)"
    else:
        bg, fg, border = "palette(base)", "palette(text)", "palette(highlight)"
    return f"""
QPlainTextEdit {{
    background-color: {bg};
    color: {fg};
    border: 1px solid {border};
    padding: 8px;
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
    font-family: {_FONT_STACK};
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
