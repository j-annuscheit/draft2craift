"""Chat context orchestration extracted from MainWindow."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

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
        }

    def get_tts_mode(self) -> str:
        """Return the current TTS mode setting from the chat dock."""
        try:
            return str(self._chat_dock.chat_tts_mode() or "off")
        except Exception:
            return "off"

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
