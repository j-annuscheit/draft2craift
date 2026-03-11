"""Styles used by the RAG settings dialog."""

RAG_SETTINGS_STYLE = """
QDialog          { background: palette(window); color: palette(window-text); }
QGroupBox {
    color: palette(highlight); font-weight: bold; font-size: 11px;
    border: 1px solid palette(mid); border-radius: 4px;
    margin-top: 8px; padding-top: 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QLabel           { color: palette(text); font-size: 11px; }
QSpinBox, QDoubleSpinBox, QLineEdit {
    background: palette(base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 3px;
    padding: 2px 6px; font-size: 11px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: palette(alternate-base); border: none; width: 16px;
}
QComboBox {
    background: palette(base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 3px;
    padding: 2px 6px; font-size: 11px;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: palette(alternate-base); color: palette(text);
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
    border: none;
}
QCheckBox              { color: palette(text); font-size: 11px; }
QCheckBox::indicator   { width: 14px; height: 14px; border: 1px solid palette(mid); border-radius: 2px; background: palette(base); }
QCheckBox::indicator:checked { background: palette(highlight); border-color: palette(highlight); }
QPushButton {
    background: palette(alternate-base); color: palette(text);
    border: 1px solid palette(mid); border-radius: 3px;
    padding: 4px 12px; font-size: 11px;
}
QPushButton:hover { border: 1px solid palette(highlight); }
QPushButton:disabled { color: palette(placeholder-text); }
"""
