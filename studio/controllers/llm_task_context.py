"""Context bundle for LLMSideTaskController dependencies."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.services.llm.manager import LLMManager
    from shared.services.rag.orchestrator import RAGSystem
    from studio.canvas.tabs import CanvasTabWidget
    from studio.chat.dock import ChatDock
    from studio.feedback.bar import FeedbackBar
    from studio.logger import AppLogger


@dataclass(slots=True)
class LLMTaskContext:
    """Explicit dependency and callback container for LLM side-task orchestration."""

    llm_manager: LLMManager
    rag_system: RAGSystem
    canvas: CanvasTabWidget
    chat_dock: ChatDock
    glossary_feedback_bar: FeedbackBar
    app_logger: AppLogger
    show_status: Callable[[str, int], None]
    resolve_imported_doc_content: Callable[[str], str]
    set_status_feedback_payload: Callable[[Mapping[str, object] | None], None]
    refresh_preview_overlays: Callable[[], None]
    autosave_schedule_fn: Callable[[int], None]
    build_llm_context: Callable[[], dict]
    get_user_mode: Callable[[], str]
    is_prompt_editor_allowed: Callable[[str | None], bool]
    dialog_manager: object
