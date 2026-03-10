"""Shared UI palette and stylesheet for Testcase Studio."""
from __future__ import annotations

BG = "#1E1E2E"
SURFACE = "#181825"
MANTLE = "#313244"
OVERLAY = "#45475A"
TEXT = "#CDD6F4"
MUTED = "#6C7086"
BLUE = "#89B4FA"
GREEN = "#A6E3A1"
RED = "#F38BA8"
YELLOW = "#F9E2AF"
PURPLE = "#CBA6F7"

STYLE = f"""
QDialog, QWidget {{ background: {BG}; color: {TEXT}; }}
QGroupBox {{
  background: {SURFACE}; border: 1px solid {OVERLAY}; border-radius: 4px;
  margin-top: 8px; padding: 8px;
}}
QGroupBox::title {{
  subcontrol-origin: margin; subcontrol-position: top left;
  color: {PURPLE}; padding: 0 4px;
}}
QLineEdit, QComboBox, QPlainTextEdit {{
  background: {MANTLE}; color: {TEXT}; border: 1px solid {OVERLAY};
  border-radius: 3px; padding: 4px 6px;
}}
QPushButton {{
  background: {MANTLE}; color: {TEXT}; border: 1px solid {OVERLAY};
  border-radius: 3px; padding: 5px 10px;
}}
QPushButton:hover {{ background: {OVERLAY}; }}
QPushButton#primary {{ background: #1A3A5C; color: {BLUE}; border-color: {BLUE}; font-weight: bold; }}
QPushButton#success {{ background: #1E3A2F; color: {GREEN}; border-color: {GREEN}; }}
QPushButton#danger {{ background: #3A1E2A; color: {RED}; border-color: {RED}; }}
QTableWidget {{
  background: {SURFACE}; border: 1px solid {OVERLAY}; gridline-color: {MANTLE};
}}
QHeaderView::section {{
  background: {MANTLE}; color: {PURPLE}; border: none; border-right: 1px solid {OVERLAY};
  padding: 4px 6px;
}}
"""
