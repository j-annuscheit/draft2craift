"""Dock widget wiring for :mod:`studio.window`."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt

from studio.app_context import AppContext
from studio.chat.dock import ChatDock
from studio.knowledge.dock import KnowledgeDock
from studio.logger import LogDock

@dataclass(slots=True)
class DockBundle:
    """All top-level dock widgets created during startup."""

    knowledge_dock: KnowledgeDock
    chat_dock: ChatDock
    log_dock: LogDock


def init_docks(ctx: AppContext, *, feedback_service) -> DockBundle:
    """Initialize and connect all top-level dock widgets."""
    window = ctx.window

    knowledge_dock = KnowledgeDock(ctx.rag_system, window)
    knowledge_dock.setObjectName("knowledge_dock")
    window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, knowledge_dock)

    chat_dock = ChatDock(ctx.llm_manager, window)
    chat_dock.setObjectName("chat_dock")
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, chat_dock)

    chat_dock.set_feedback_service(feedback_service)
    chat_dock.read_aloud_requested.connect(window._speak_chat_text)
    chat_dock.read_aloud_stop_requested.connect(window._stop_tts)
    chat_dock.visibilityChanged.connect(window._on_chat_dock_visibility_changed)
    knowledge_dock.set_feedback_service(feedback_service)

    log_dock = LogDock(ctx.app_logger, window)
    log_dock.setObjectName("log_dock")
    window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, log_dock)
    log_dock.hide()
    window.resizeDocks(
        [knowledge_dock, chat_dock],
        [340, 380],
        Qt.Orientation.Horizontal,
    )
    return DockBundle(
        knowledge_dock=knowledge_dock,
        chat_dock=chat_dock,
        log_dock=log_dock,
    )
