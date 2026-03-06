"""Application theme profiles and Qt palette helpers."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


DEFAULT_THEME_ID = "dark"
_APP_THEME_PROP = "_d2c_theme_id"


@dataclass(frozen=True, slots=True)
class ThemeSpec:
    """One named theme profile."""

    theme_id: str
    label: str
    base_bg: str
    panel_bg: str
    panel_alt_bg: str
    input_bg: str
    text: str
    muted_text: str
    border: str
    border_strong: str
    accent: str
    accent_hover: str
    accent_pressed: str
    highlight_bg: str
    highlight_text: str
    success: str
    danger: str
    menu_bg: str
    menu_item_hover: str


_THEMES: dict[str, ThemeSpec] = {
    "dark": ThemeSpec(
        theme_id="dark",
        label="Dunkel",
        base_bg="#1E1E2E",
        panel_bg="#181825",
        panel_alt_bg="#313244",
        input_bg="#1E1E2E",
        text="#CDD6F4",
        muted_text="#6C7086",
        border="#45475A",
        border_strong="#313244",
        accent="#89B4FA",
        accent_hover="#B4BEFE",
        accent_pressed="#74C7EC",
        highlight_bg="#264F78",
        highlight_text="#CDD6F4",
        success="#A6E3A1",
        danger="#F38BA8",
        menu_bg="#181825",
        menu_item_hover="#313244",
    ),
    "darker": ThemeSpec(
        theme_id="darker",
        label="Dunkler",
        base_bg="#111318",
        panel_bg="#0C0E12",
        panel_alt_bg="#1C1F28",
        input_bg="#12151C",
        text="#D7DEEA",
        muted_text="#8790A2",
        border="#2E3440",
        border_strong="#212734",
        accent="#7AA2F7",
        accent_hover="#9DB8FF",
        accent_pressed="#6FBCFF",
        highlight_bg="#1F456A",
        highlight_text="#E2E8F0",
        success="#9ECE6A",
        danger="#F7768E",
        menu_bg="#0C0E12",
        menu_item_hover="#1C1F28",
    ),
    "light": ThemeSpec(
        theme_id="light",
        label="Hell",
        base_bg="#F5F7FB",
        panel_bg="#FFFFFF",
        panel_alt_bg="#E8EDF5",
        input_bg="#FFFFFF",
        text="#1F2937",
        muted_text="#64748B",
        border="#C9D4E3",
        border_strong="#B5C4DA",
        accent="#2563EB",
        accent_hover="#1D4ED8",
        accent_pressed="#1E40AF",
        highlight_bg="#DCEAFE",
        highlight_text="#0F172A",
        success="#15803D",
        danger="#DC2626",
        menu_bg="#FFFFFF",
        menu_item_hover="#EEF2FF",
    ),
    "colorful-light": ThemeSpec(
        theme_id="colorful-light",
        label="Farbig Hell",
        base_bg="#FFF9F3",
        panel_bg="#FFFFFF",
        panel_alt_bg="#FFF1E6",
        input_bg="#FFFFFF",
        text="#2A1D14",
        muted_text="#7A5A42",
        border="#E8C9B0",
        border_strong="#DCB493",
        accent="#0EA5A3",
        accent_hover="#0B8A87",
        accent_pressed="#0A6D6B",
        highlight_bg="#DDF9F8",
        highlight_text="#1F2937",
        success="#2E7D32",
        danger="#C62828",
        menu_bg="#FFFFFF",
        menu_item_hover="#FFF1E6",
    ),
    "colorful-dark": ThemeSpec(
        theme_id="colorful-dark",
        label="Farbig Dunkel",
        base_bg="#181026",
        panel_bg="#120B1D",
        panel_alt_bg="#2A1C3A",
        input_bg="#191228",
        text="#F5EFFF",
        muted_text="#B7A7D6",
        border="#4A3A63",
        border_strong="#37284D",
        accent="#2DD4BF",
        accent_hover="#5EEAD4",
        accent_pressed="#14B8A6",
        highlight_bg="#233B4D",
        highlight_text="#F5EFFF",
        success="#34D399",
        danger="#F87171",
        menu_bg="#120B1D",
        menu_item_hover="#2A1C3A",
    ),
}


def available_themes() -> list[tuple[str, str]]:
    """Return ``[(theme_id, label), ...]`` in menu order."""
    order = ["light", "dark", "darker", "colorful-light", "colorful-dark"]
    return [(theme_id, _THEMES[theme_id].label) for theme_id in order]


def normalize_theme_id(theme_id: object) -> str:
    text = str(theme_id or "").strip().lower()
    if text in _THEMES:
        return text
    aliases = {
        "default": DEFAULT_THEME_ID,
        "classic-dark": "dark",
        "colorful_light": "colorful-light",
        "colorful_dark": "colorful-dark",
    }
    mapped = aliases.get(text, DEFAULT_THEME_ID)
    return mapped if mapped in _THEMES else DEFAULT_THEME_ID


def theme_tokens(theme_id: object | None = None) -> dict[str, str]:
    resolved = normalize_theme_id(theme_id or current_theme_id())
    spec = _THEMES[resolved]
    return {
        "theme_id": spec.theme_id,
        "label": spec.label,
        "base_bg": spec.base_bg,
        "panel_bg": spec.panel_bg,
        "panel_alt_bg": spec.panel_alt_bg,
        "input_bg": spec.input_bg,
        "text": spec.text,
        "muted_text": spec.muted_text,
        "border": spec.border,
        "border_strong": spec.border_strong,
        "accent": spec.accent,
        "accent_hover": spec.accent_hover,
        "accent_pressed": spec.accent_pressed,
        "highlight_bg": spec.highlight_bg,
        "highlight_text": spec.highlight_text,
        "success": spec.success,
        "danger": spec.danger,
        "menu_bg": spec.menu_bg,
        "menu_item_hover": spec.menu_item_hover,
    }


def current_theme_id() -> str:
    app = QApplication.instance()
    if app is None:
        return DEFAULT_THEME_ID
    value = app.property(_APP_THEME_PROP)
    return normalize_theme_id(value)


def _qcolor(hex_color: str) -> QColor:
    color = QColor(str(hex_color or ""))
    if color.isValid():
        return color
    return QColor("#000000")


def _build_palette(spec: ThemeSpec) -> QPalette:
    palette = QPalette()
    base_bg = _qcolor(spec.base_bg)
    panel_bg = _qcolor(spec.panel_bg)
    panel_alt_bg = _qcolor(spec.panel_alt_bg)
    text = _qcolor(spec.text)
    muted = _qcolor(spec.muted_text)
    border = _qcolor(spec.border)
    accent = _qcolor(spec.accent)
    highlight_bg = _qcolor(spec.highlight_bg)
    highlight_text = _qcolor(spec.highlight_text)

    palette.setColor(QPalette.ColorRole.Window, base_bg)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, panel_bg)
    palette.setColor(QPalette.ColorRole.AlternateBase, panel_alt_bg)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, panel_alt_bg)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, _qcolor(spec.danger))
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, highlight_text)
    palette.setColor(QPalette.ColorRole.ToolTipBase, panel_bg)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Link, accent)
    palette.setColor(QPalette.ColorRole.Mid, border)
    palette.setColor(QPalette.ColorRole.Light, panel_alt_bg)
    palette.setColor(QPalette.ColorRole.Dark, border)
    palette.setColor(QPalette.ColorRole.PlaceholderText, muted)

    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        muted,
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        muted,
    )
    return palette


def _build_app_stylesheet(spec: ThemeSpec) -> str:
    return f"""
QWidget {{
    color: {spec.text};
}}
QToolTip {{
    color: {spec.text};
    background: {spec.panel_bg};
    border: 1px solid {spec.border};
    padding: 4px 6px;
}}
QDockWidget {{
    border: 1px solid {spec.border};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    text-align: left;
    background: {spec.panel_bg};
    border-bottom: 1px solid {spec.border};
    padding: 4px 8px;
}}
QMenuBar {{
    background: {spec.menu_bg};
    color: {spec.text};
    border-bottom: 1px solid {spec.border_strong};
}}
QMenuBar::item:selected {{
    background: {spec.menu_item_hover};
}}
QMenu {{
    background: {spec.panel_alt_bg};
    color: {spec.text};
    border: 1px solid {spec.border};
}}
QMenu::item:selected {{
    background: {spec.menu_item_hover};
}}
QMenu::separator {{
    background: {spec.border};
    height: 1px;
    margin: 2px 0;
}}
QStatusBar {{
    background: {spec.menu_bg};
    color: {spec.muted_text};
    border-top: 1px solid {spec.border_strong};
}}
QStatusBar::item {{
    border: 0;
}}
QMainWindow::separator {{
    background: {spec.border};
    width: 3px;
    height: 3px;
}}
QMainWindow::separator:hover {{
    background: {spec.accent};
}}
QSplitter::handle {{
    background: {spec.border};
}}
QSplitter::handle:hover {{
    background: {spec.accent};
}}
QTabWidget::pane {{
    border: 1px solid {spec.border};
}}
QTabBar::tab {{
    background: {spec.panel_alt_bg};
    color: {spec.muted_text};
    border: 1px solid {spec.border};
    padding: 5px 12px;
}}
QTabBar::tab:selected {{
    background: {spec.panel_bg};
    color: {spec.text};
    border-bottom-color: {spec.panel_bg};
}}
QTabBar::tab:hover {{
    background: {spec.menu_item_hover};
    color: {spec.text};
}}
QLineEdit, QTextEdit, QPlainTextEdit, QTextBrowser, QListWidget, QTreeWidget {{
    background: {spec.input_bg};
    color: {spec.text};
    border: 1px solid {spec.border};
    selection-background-color: {spec.highlight_bg};
    selection-color: {spec.highlight_text};
}}
QSpinBox, QDoubleSpinBox, QAbstractSpinBox, QComboBox, QTableWidget {{
    background: {spec.input_bg};
    color: {spec.text};
    border: 1px solid {spec.border};
    selection-background-color: {spec.highlight_bg};
    selection-color: {spec.highlight_text};
}}
QHeaderView::section {{
    background: {spec.panel_alt_bg};
    color: {spec.text};
    border: 1px solid {spec.border};
}}
QComboBox QAbstractItemView {{
    background: {spec.panel_alt_bg};
    color: {spec.text};
    selection-background-color: {spec.highlight_bg};
    selection-color: {spec.highlight_text};
}}
QPushButton {{
    background: {spec.panel_alt_bg};
    color: {spec.text};
    border: 1px solid {spec.border};
    border-radius: 4px;
    padding: 4px 10px;
}}
QPushButton:hover {{
    border-color: {spec.accent};
}}
QPushButton:pressed {{
    background: {spec.menu_item_hover};
}}
QPushButton:checked {{
    background: {spec.accent};
    color: {spec.highlight_text};
    border-color: {spec.accent};
}}
QPushButton:disabled {{
    color: {spec.muted_text};
}}
QCheckBox {{
    color: {spec.text};
}}
QCheckBox::indicator {{
    width: 12px;
    height: 12px;
    border: 1px solid {spec.border};
    border-radius: 2px;
    background: {spec.panel_bg};
}}
QCheckBox::indicator:checked {{
    background: {spec.accent};
    border-color: {spec.accent};
}}
"""


def apply_theme(app: QApplication, theme_id: object = DEFAULT_THEME_ID) -> str:
    """Apply one profile globally and return the normalized theme id."""
    if app is None:
        return normalize_theme_id(theme_id)
    resolved = normalize_theme_id(theme_id)
    spec = _THEMES[resolved]
    app.setProperty(_APP_THEME_PROP, resolved)
    app.setPalette(_build_palette(spec))
    app.setStyleSheet(_build_app_stylesheet(spec))
    return resolved


def apply_dark_theme(app: QApplication) -> str:
    """Backward-compatible wrapper."""
    return apply_theme(app, DEFAULT_THEME_ID)
