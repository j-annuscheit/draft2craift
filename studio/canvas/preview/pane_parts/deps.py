"""Shared imports for CanvasPreviewPane method modules."""
from __future__ import annotations

from collections import deque
import html
import math
import re
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt, QUrl
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QPalette,
    QPainter,
    QPen,
    QPolygonF,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextListFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QStackedLayout,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from shared.domain.user_mode import normalize_user_mode, resolve_feature_label
from shared.services.highlights.store import HighlightMatch, get_highlight_store

from ...graph.renderer import (
    GraphSpec,
    extract_graph_spec,
    graph_spec_signature,
    render_graph_html,
)
from ...graph.view import GraphCanvasView, GraphNodeItem
from ...styles import PREVIEW_PANEL_STYLE, PREVIEW_VIEW_STYLE
from ..browser import PreviewTextBrowser
from ..table_picker import TableInsertPicker

from .models import _RenderedHighlight

try:
    import networkx as nx
except Exception:
    nx = None
