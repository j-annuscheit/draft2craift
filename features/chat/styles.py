"""Shared styles for chat feature widgets."""

BTN_PRIMARY = """
QPushButton {
    background: #89B4FA; color: #1E1E2E;
    border: none; border-radius: 4px;
    padding: 5px 16px; font-weight: bold; font-size: 11px;
}
QPushButton:hover    { background: #B4BEFE; }
QPushButton:disabled { background: #45475A; color: #6C7086; }
"""

BTN_DANGER = """
QPushButton {
    background: #F38BA8; color: #1E1E2E;
    border: none; border-radius: 4px;
    padding: 5px 10px; font-weight: bold; font-size: 11px;
}
QPushButton:hover { background: #FF9EBA; }
"""

BTN_NEUTRAL = """
QPushButton {
    background: #45475A; color: #CDD6F4;
    border: none; border-radius: 4px;
    padding: 5px 8px; font-size: 11px;
}
QPushButton:hover { background: #585B70; }
"""

CTX_CB_STYLE = """
QCheckBox { color: #CDD6F4; font-size: 10px; padding: 1px 0; }
QCheckBox::indicator {
    width: 12px; height: 12px;
    border: 1px solid #45475A; border-radius: 2px;
    background: #181825;
}
QCheckBox::indicator:checked { background: #89B4FA; border-color: #89B4FA; }
"""

CTX_DOC_CB_STYLE = """
QCheckBox { color: #CDD6F4; font-size: 10px; padding: 1px 0; }
QCheckBox::indicator {
    width: 12px; height: 12px;
    border: 1px solid #45475A; border-radius: 2px;
    background: #181825;
}
QCheckBox::indicator:checked { background: #A6E3A1; border-color: #A6E3A1; }
"""
