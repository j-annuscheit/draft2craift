"""Application shell package."""

from .window import MainWindow, CanvasTabWidget
from .theme import apply_dark_theme
from .logging import AppLogger, LogDock

__all__ = [
    "MainWindow",
    "CanvasTabWidget",
    "apply_dark_theme",
    "AppLogger",
    "LogDock",
]
