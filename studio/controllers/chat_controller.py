"""Chat context orchestration extracted from MainWindow."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from studio.canvas.tabs import CanvasTabWidget
    from studio.chat.dock import ChatDock
    from studio.knowledge.dock import KnowledgeDock


class ChatController:
    """Builds one canonical context payload for chat/side actions."""

    def __init__(
        self,
        *,
        chat_dock: ChatDock,
        canvas: CanvasTabWidget,
        knowledge_dock: KnowledgeDock,
        resolve_imported_doc_content: Callable[[str], str],
    ):
        self._chat_dock = chat_dock
        self._canvas = canvas
        self._knowledge_dock = knowledge_dock
        self._resolve_imported_doc_content = resolve_imported_doc_content

    def build_llm_context(self) -> dict:
        use_canvas, use_rag, doc_selection = self._chat_dock.get_context_selection()

        selected_docs: list[tuple[str, str]] = []
        for name_raw, content_raw in list(doc_selection or []):
            name = str(name_raw or "").strip()
            if not name:
                continue
            content = str(content_raw or "").strip()
            if not content:
                content = self._resolve_imported_doc_content(name)
            if not content:
                continue
            selected_docs.append((name, content))

        file_contents: list[tuple[str, str]] = list(selected_docs)
        selected_doc_count = len(selected_docs)

        if use_canvas:
            canvas_text = self._canvas.get_current_text().strip()
            if canvas_text:
                tab_idx = self._canvas.tabs.tab_widget.currentIndex()
                tab_title = self._canvas.tabs.tab_widget.tabText(tab_idx) or "Draft"
                file_contents.append((f"Draft: {tab_title}", canvas_text))

        rag_results: list[tuple[str, float, str]] = []
        rag_has_data = False
        if use_rag:
            rag_text = self._knowledge_dock.get_rag_results_text().strip()
            if rag_text and "### 1." in rag_text:
                rag_results = [("RAG Results", 1.0, rag_text)]
                rag_has_data = True

        selected_text = str(
            self._canvas.get_selected_text(allow_cached=True) or ""
        )
        selected_span = self._canvas.get_selected_span(allow_cached=True)
        query_hint = ""
        query_getter = getattr(self._chat_dock, "get_user_query_hint", None)
        if callable(query_getter):
            try:
                query_hint = str(query_getter() or "").strip()
            except Exception:
                query_hint = ""

        grounding_required = bool(use_rag or selected_doc_count > 0)
        grounding_has_sources = bool(rag_has_data or selected_doc_count > 0)
        return {
            "file_contents": file_contents,
            "rag_results": rag_results,
            "selected_text": selected_text,
            "selected_span": selected_span,
            "grounding_required": grounding_required,
            "grounding_has_sources": grounding_has_sources,
            "grounding_reason": (
                "rag_or_docs_selected" if grounding_required else "none"
            ),
            "grounding_selected_docs": selected_doc_count,
            "grounding_rag_selected": bool(use_rag),
            "grounding_rag_has_data": rag_has_data,
            "user_query": query_hint,
        }

    def get_tts_mode(self) -> str:
        """Return the current TTS mode setting from the chat dock."""
        try:
            return str(self._chat_dock.chat_tts_mode() or "off")
        except Exception:
            return "off"

    def canvas_selection_text(self) -> str:
        return str(self._canvas.get_selected_text(allow_cached=True) or "")

    def on_model_loaded(
        self,
        success: bool,
        message: str,
        *,
        set_model_label_text: Callable[[str], None],
        set_model_status_success: Callable[[bool], None],
        apply_status_label_styles: Callable[[], None],
        rag_system: object,
        llm_manager: object,
    ) -> None:
        set_model_label_text(str(message or ""))
        set_model_status_success(bool(success))
        apply_status_label_styles()
        if not success:
            return
        rag_system.set_tfidf_query_expander(llm_manager.expand_query_tfidf_sync)
        rag_system.set_st_query_expander(llm_manager.expand_query_st_sync)
        rag_system.set_literal_query_expander(llm_manager.expand_query_literal_terms_sync)
        rag_system.set_rag_reranker(llm_manager.rerank_rag_results_sync)

    def focus_model_panel(self, *, sync_toggle_action: Callable[[], None]) -> None:
        self._chat_dock.show()
        self._chat_dock.raise_()
        self._chat_dock.set_model_panel_visible(True)
        sync_toggle_action()

    def reset_layout(
        self,
        *,
        add_dock_widget: Callable[[Qt.DockWidgetArea, object], None],
        resize_docks: Callable[[list[object], list[int], Qt.Orientation], None],
        sync_toggle_action: Callable[[], None],
    ) -> None:
        add_dock_widget(Qt.DockWidgetArea.LeftDockWidgetArea, self._knowledge_dock)
        add_dock_widget(Qt.DockWidgetArea.RightDockWidgetArea, self._chat_dock)
        self._knowledge_dock.show()
        self._chat_dock.show()
        self._chat_dock.set_model_panel_visible(True)
        resize_docks(
            [self._knowledge_dock, self._chat_dock],
            [340, 380],
            Qt.Orientation.Horizontal,
        )
        sync_toggle_action()

    def set_model_controls_visible(
        self,
        visible: bool,
        *,
        sync_toggle_action: Callable[[], None],
    ) -> None:
        if bool(visible):
            self._chat_dock.show()
            self._chat_dock.raise_()
        self._chat_dock.set_model_panel_visible(bool(visible))
        sync_toggle_action()

    def sync_model_controls_toggle_action(self, action: object | None) -> None:
        if action is None:
            return
        checked = bool(self._chat_dock.isVisible() and self._chat_dock.is_model_panel_visible())
        blocked = action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(blocked)

    def refresh_context_bar(self) -> None:
        use_canvas, use_rag, docs = self._chat_dock.get_context_selection()
        parts: list[str] = []
        if use_canvas and self._canvas.get_current_text().strip():
            parts.append("canvas")
        if use_rag and self._knowledge_dock.get_rag_results_text().strip():
            parts.append("RAG")
        if docs:
            parts.append(f"{len(docs)} doc{'s' if len(docs) != 1 else ''}")
        selected = str(
            self._canvas.get_selected_text(
                allow_cached=True,
                consume_cached=False,
            ) or ""
        ).strip()
        if selected:
            parts.append("selection")
        self._chat_dock.update_context_bar(parts)
