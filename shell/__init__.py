"""Application shell package."""

from .window import MainWindow, CanvasTabWidget
from .theme import (
    apply_dark_theme,
    apply_theme,
    available_themes,
    current_theme_id,
    normalize_theme_id,
)
from .logging import AppLogger, LogDock

__all__ = [
    "MainWindow",
    "CanvasTabWidget",
    "apply_dark_theme",
    "apply_theme",
    "available_themes",
    "current_theme_id",
    "normalize_theme_id",
    "AppLogger",
    "LogDock",
]
