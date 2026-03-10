"""Shared styles for chat feature widgets."""

BTN_PRIMARY = """
QPushButton {
    background: palette(highlight);
    color: palette(highlighted-text);
    border: none; border-radius: 4px;
    padding: 5px 16px; font-weight: bold; font-size: 11px;
}
QPushButton:hover    { border: 1px solid palette(highlight); }
QPushButton:disabled { background: palette(alternate-base); color: palette(placeholder-text); }
"""

BTN_DANGER = """
QPushButton {
    background: palette(bright-text);
    color: palette(highlighted-text);
    border: none; border-radius: 4px;
    padding: 5px 10px; font-weight: bold; font-size: 11px;
}
QPushButton:hover { border: 1px solid palette(bright-text); }
"""

BTN_NEUTRAL = """
QPushButton {
    background: palette(alternate-base);
    color: palette(text);
    border: none; border-radius: 4px;
    padding: 5px 8px; font-size: 11px;
}
QPushButton:hover { border: 1px solid palette(highlight); }
"""

CTX_CB_STYLE = """
QCheckBox { color: palette(text); font-size: 10px; padding: 1px 0; }
QCheckBox::indicator {
    width: 12px; height: 12px;
    border: 1px solid palette(mid); border-radius: 2px;
    background: palette(base);
}
QCheckBox::indicator:checked { background: palette(highlight); border-color: palette(highlight); }
"""

CTX_DOC_CB_STYLE = """
QCheckBox { color: palette(text); font-size: 10px; padding: 1px 0; }
QCheckBox::indicator {
    width: 12px; height: 12px;
    border: 1px solid palette(mid); border-radius: 2px;
    background: palette(base);
}
QCheckBox::indicator:checked { background: palette(highlight); border-color: palette(highlight); }
"""
