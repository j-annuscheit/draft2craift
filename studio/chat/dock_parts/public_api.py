"""ChatDock method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def set_feedback_service(self, service: FeedbackService):
    self._feedback_service = service

def set_context_getter(self, getter: Callable[[], dict]):
    self._context_getter = getter

def set_canvas_selection_getter(self, getter: Callable[[], str] | None):
    self._canvas_selection_getter = getter

def set_selection_apply_handler(
    self,
    handler: Callable[[str, str, tuple[int, int] | None], tuple[bool, str]],
):
    self._selection_apply_handler = handler

def set_fact_result_handler(self, handler: Callable[[str, str], tuple[bool, str]]):
    self._fact_result_handler = handler

def set_glossary_request_handler(
    self,
    handler: Callable[[dict, Callable[[bool, str], None]], tuple[bool, str]],
):
    self._glossary_request_handler = handler

def set_mindmap_request_handler(
    self,
    handler: Callable[[dict, str, str, Callable[[bool, str], None]], tuple[bool, str]],
):
    self._mindmap_request_handler = handler

def set_aux_task_running(self, running: bool):
    self._aux_generating = bool(running)
    self._apply_busy_state()

def add_document(self, name: str, content: str):
    """Register an imported document in the context selector."""
    self.context_panel.add_document(name, content)

def remove_document(self, name: str):
    """Remove an imported document from the context selector."""
    self.context_panel.remove_document(name)

def rename_document(self, old_name: str, new_name: str) -> str:
    """Rename an imported document in the context selector."""
    return self.context_panel.rename_document(old_name, new_name)

def get_context_selection(self) -> tuple[bool, bool, list[tuple[str, str]]]:
    """Return ``(use_canvas, use_rag, [(name, content), ...])``."""
    return self.context_panel.get_selection()

def get_context_document_content(self, name: str) -> str:
    """Return markdown content for one registered context document."""
    return self.context_panel.get_document_content(name)

def get_context_documents(self) -> dict[str, str]:
    """Return all registered context documents as ``{name: content}`` copy."""
    return self.context_panel.get_all_documents()

def update_context_bar(self, parts: list[str]):
    """Update the context indicator bar with part labels."""
    if parts:
        self._ctx_bar.setText("Context: " + " | ".join(parts))
        return
    self._ctx_bar.setText("Context: —")

def set_user_mode(self, mode: str):
    self._user_mode = normalize_user_mode(mode)
    self.model_panel.set_user_mode(self._user_mode)
    show_apply = mode_rank(self._user_mode) >= mode_rank(USER_MODE_PLUS)
    if not show_apply:
        self.apply_selection_cb.setChecked(False)
    self.apply_selection_cb.setVisible(show_apply)

def set_chat_tts_mode(self, mode: str):
    normalized = self._normalize_tts_mode(mode)
    self._chat_tts_mode = normalized
    combo = getattr(self, "chat_tts_combo", None)
    if combo is not None:
        for idx in range(combo.count()):
            data = str(combo.itemData(idx) or "").strip().lower()
            if data == normalized:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)
                break
    self.tts_mode_changed.emit(normalized)

def chat_tts_mode(self) -> str:
    return str(self._chat_tts_mode or "off")

def set_read_aloud_active(self, active: bool):
    self._read_aloud_active = bool(active)
    btn = getattr(self, "play_last_btn", None)
    if btn is None:
        return
    if self._read_aloud_active:
        btn.setText("⏹")
        btn.setToolTip("Vorlesen stoppen")
        return
    btn.setText("🔊")
    btn.setToolTip("Letzte Modellantwort vorlesen")

def is_model_panel_visible(self) -> bool:
    splitter = getattr(self, "_main_splitter", None)
    if splitter is None:
        return True
    sizes = splitter.sizes()
    if len(sizes) != 3:
        return True
    return int(sizes[0]) > 8

def set_model_panel_visible(self, visible: bool):
    splitter = getattr(self, "_main_splitter", None)
    if splitter is None:
        return
    sizes = splitter.sizes()
    if len(sizes) != 3:
        return

    total = int(sum(sizes))
    if total <= 0:
        total = 1
    model_size, ctx_size, chat_size = [int(s) for s in sizes]

    min_model = 72
    min_ctx = 52
    min_chat = 96

    if not bool(visible):
        if model_size > 8:
            self._model_panel_last_size = model_size
        remaining = total
        ctx_chat_total = max(1, ctx_size + chat_size)
        ctx_target = int(round(remaining * (ctx_size / ctx_chat_total)))
        ctx_target = max(min_ctx, min(ctx_target, max(min_ctx, remaining - min_chat)))
        chat_target = max(min_chat, remaining - ctx_target)
        splitter.setSizes([0, ctx_target, chat_target])
        return

    available_for_model = max(0, total - (min_ctx + min_chat))
    if available_for_model <= 0:
        splitter.setSizes([0, max(min_ctx, total // 3), max(min_chat, total // 2)])
        return

    desired = int(self._model_panel_last_size or min_model)
    model_target = max(min_model, min(desired, available_for_model))
    remaining = max(0, total - model_target)
    ctx_chat_total = max(1, ctx_size + chat_size)
    ctx_target = int(round(remaining * (ctx_size / ctx_chat_total)))
    ctx_target = max(min_ctx, min(ctx_target, max(min_ctx, remaining - min_chat)))
    chat_target = max(min_chat, remaining - ctx_target)
    splitter.setSizes([model_target, ctx_target, chat_target])

def toggle_model_panel(self) -> bool:
    new_visible = not self.is_model_panel_visible()
    self.set_model_panel_visible(new_visible)
    return new_visible

__all__ = [
    "set_feedback_service",
    "set_context_getter",
    "set_canvas_selection_getter",
    "set_selection_apply_handler",
    "set_fact_result_handler",
    "set_glossary_request_handler",
    "set_mindmap_request_handler",
    "set_aux_task_running",
    "add_document",
    "remove_document",
    "rename_document",
    "get_context_selection",
    "get_context_document_content",
    "get_context_documents",
    "update_context_bar",
    "set_user_mode",
    "set_chat_tts_mode",
    "chat_tts_mode",
    "set_read_aloud_active",
    "is_model_panel_visible",
    "set_model_panel_visible",
    "toggle_model_panel",
]
