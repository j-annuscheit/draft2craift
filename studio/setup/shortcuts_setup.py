"""Global shortcut setup for :mod:`studio.window`."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut


def init_global_shortcuts(window: Any) -> None:
    """Create app-wide shortcuts and keep strong references on *window*."""
    window._global_shortcuts = []

    def _bind(seq: str, slot) -> None:
        shortcut = QShortcut(QKeySequence(seq), window)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.activated.connect(slot)
        window._global_shortcuts.append(shortcut)

    _bind("Ctrl+Tab", window._select_next_draft_tab)
    _bind("Ctrl+Shift+Tab", window._select_previous_draft_tab)
    _bind("Ctrl+F", lambda: window._find_replace_ctrl.open_dialog())
    _bind("Alt+1", lambda: window._set_canvas_view_mode_shortcut("markdown"))
    _bind("Alt+2", lambda: window._set_canvas_view_mode_shortcut("preview"))
    _bind("Alt+3", lambda: window._set_canvas_view_mode_shortcut("both"))
    _bind("Ctrl+Alt+S", window._toggle_autosave_shortcut)
