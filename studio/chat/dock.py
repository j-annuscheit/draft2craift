"""Chat dock orchestration for model load, chat and fact-check flows."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDockWidget

from shared.domain.user_mode import default_user_mode
from shared.services.feedback.service import FeedbackService
from shared.services.llm.manager import LLMManager

from .dock_parts import bind_chat_dock
from .factcheck.pipeline import FactCheckPipelineMixin

class ChatDock(FactCheckPipelineMixin, QDockWidget):
    """
    AI Chat Dock.

    ``context_getter`` must return:
    ``{file_contents, rag_results, selected_text, grounding_required,
    grounding_has_sources}``.
    """

    read_aloud_requested = Signal(str)
    read_aloud_stop_requested = Signal()
    tts_mode_changed = Signal(str)
    _NO_MODEL_LOADED_MESSAGE = "⚠ No model loaded. Load a model first."

    def __init__(self, llm_manager: LLMManager, parent=None):
        super().__init__("AI Chat", parent)
        self.llm = llm_manager
        self._user_mode = default_user_mode()
        self._context_getter: Callable[[], dict] | None = None
        self._canvas_selection_getter: Callable[[], str] | None = None
        self._agentic_settings_getter: Callable[[], object] | None = None
        self._selection_apply_handler: (
            Callable[[str, str, tuple[int, int] | None], tuple[bool, str]] | None
        ) = None
        self._fact_result_handler: Callable[[str, str], tuple[bool, str]] | None = None
        self._glossary_request_handler: (
            Callable[[dict, str, dict | None, Callable[[bool, str], None]], tuple[bool, str]] | None
        ) = None
        self._mindmap_request_handler: (
            Callable[
                [dict, str, str, int, dict | None, Callable[[bool, str], None]],
                tuple[bool, str],
            ]
            | None
        ) = None

        self._pending_apply_to_canvas = False
        self._pending_selected_text = ""
        self._pending_selected_span: tuple[int, int] | None = None
        self._pending_apply_retry_count = 0
        self._pending_apply_retry_limit = 1
        self._pending_apply_context: dict = {}
        self._history_stream_open = False
        self._chat_tts_mode = "off"
        self._read_aloud_active = False

        self._pending_fact_check = False
        self._pending_fact_stage = ""
        self._pending_fact_target_text = ""
        self._pending_fact_target_label = ""
        self._pending_fact_sources: list[tuple[str, str]] = []
        self._pending_fact_facts: list[str] = []
        self._pending_fact_results: list[dict[str, str]] = []
        self._pending_fact_index = 0
        self._factcheck_async_running = False
        self._chunk_claim_cache = self._empty_chunk_claim_cache()
        self._chunk_claim_precompute_running = False
        self._llm_generating = False
        self._aux_generating = False
        self._model_panel_last_size = 160
        self._send_feature_visible = True
        self._stop_feature_visible = True

        self._feedback_service: FeedbackService | None = None
        self._last_user_msg = ""
        self._last_assistant_msg = ""
        self._last_use_case = "chat_answer"

        self._setup_dock()
        self._connect_signals()
        self.set_user_mode(self._user_mode)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        features = QDockWidget.DockWidgetFeature.DockWidgetMovable
        features |= QDockWidget.DockWidgetFeature.DockWidgetFloatable
        features |= QDockWidget.DockWidgetFeature.DockWidgetClosable
        self.setFeatures(features)

    def export_chunk_claim_cache(self) -> dict[str, object]:
        return super().export_chunk_claim_cache()

    def import_chunk_claim_cache(self, payload: object):
        super().import_chunk_claim_cache(payload)

bind_chat_dock(ChatDock)

__all__ = ["ChatDock"]
