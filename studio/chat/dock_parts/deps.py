"""Shared imports for ChatDock method modules."""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import (
    is_feature_visible,
    normalize_user_mode,
    resolve_feature_label,
)
from shared.services.llm.manager import (
    CANVAS_REWRITE_CLOSE,
    CANVAS_REWRITE_OPEN,
    GROUNDING_INSUFFICIENT_MESSAGE,
)
from studio.canvas.graph.renderer import contains_structured_graph

from ..context_panel import ContextSelectorPanel
from ..history import ChatHistoryWidget
from ..model_panel import ModelLoadPanel
from ..rewrite import extract_canvas_rewrite
from ..styles import BTN_DANGER, BTN_NEUTRAL, BTN_PRIMARY, CTX_CB_STYLE
