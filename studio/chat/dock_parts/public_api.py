"""ChatDock method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403
from studio.chat.runtime_ports import (
    ChatDockActionPorts,
    ChatDockContextPorts,
)
from studio.user_mode_bindings import (
    apply_combo_item_labels,
    apply_widget_placeholders,
    apply_widget_texts,
    apply_widget_tooltips,
    apply_widget_visibility,
)

_MODEL_PANEL_MIN_HEIGHT = 72
_CONTEXT_PANEL_MIN_HEIGHT = 52
_CHAT_PANEL_MIN_HEIGHT = 96
_CONTEXT_PANEL_MAX_HEIGHT = 220
_CONTEXT_PANEL_MAX_SHARE = 0.33


def _format_label(mode: str, key: str, default: str, **kwargs: object) -> str:
    template = resolve_feature_label(mode, key, default)
    try:
        return template.format(**kwargs)
    except Exception:
        return template


def _preferred_context_height(self, total: int) -> int:
    min_ctx = _CONTEXT_PANEL_MIN_HEIGHT
    preferred_fn = getattr(self, "context_panel", None)
    if preferred_fn is None or not hasattr(preferred_fn, "preferred_height"):
        preferred = min_ctx
    else:
        try:
            preferred = int(preferred_fn.preferred_height())
        except Exception:
            preferred = min_ctx
    soft_cap = max(
        min_ctx,
        min(_CONTEXT_PANEL_MAX_HEIGHT, int(total * _CONTEXT_PANEL_MAX_SHARE)),
    )
    return max(min_ctx, min(preferred, soft_cap))


def set_feedback_service(self, service: FeedbackService):
    self._feedback_service = service

def bind_context_ports(self, ports: ChatDockContextPorts) -> None:
    self._context_getter = ports.build_context
    self._canvas_selection_getter = ports.canvas_selection_text

def bind_action_ports(self, ports: ChatDockActionPorts) -> None:
    self._selection_apply_handler = ports.apply_selection_rewrite
    self._fact_result_handler = ports.open_fact_result
    self._glossary_request_handler = ports.generate_glossary
    self._mindmap_request_handler = ports.generate_mindmap

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
    values = [str(part or "").strip() for part in list(parts or []) if str(part or "").strip()]
    self._context_bar_parts = list(values)
    if values:
        self._ctx_bar.setText(
            _format_label(
                self._user_mode,
                "chat.context_bar.template",
                "Context: {parts}",
                parts=" | ".join(values),
            )
        )
        return
    self._ctx_bar.setText(
        resolve_feature_label(
            self._user_mode,
            "chat.context_bar.empty",
            "Context: —",
        )
    )

def set_user_mode(self, mode: str):
    self._user_mode = normalize_user_mode(mode)
    self.model_panel.set_user_mode(self._user_mode)
    panel_setter = getattr(self.context_panel, "set_user_mode", None)
    if callable(panel_setter):
        panel_setter(self._user_mode)

    visibility = apply_widget_visibility(
        self._user_mode,
        (
            (self.model_panel, "chat.model_panel", True),
            (self.input_box, "chat.input_box", True),
            (
                self.apply_selection_cb,
                "chat.apply_selection_checkbox",
                True,
            ),
            (self.fact_btn, "chat.fact_button", True),
            (
                self.claim_precompute_btn,
                "chat.claim_precompute_button",
                True,
            ),
            (self.glossary_btn, "chat.glossary_button", True),
            (self.mindmap_btn, "chat.mindmap_button", True),
            (self.new_tab_btn, "chat.new_tab_button", True),
            (self.clear_btn, "chat.clear_history_button", True),
            (self.play_last_btn, "chat.play_last_button", True),
            (self.chat_tts_combo, "chat.tts_mode_combo", True),
            (self.send_btn, "chat.send_button", True),
            (self.stop_btn, "chat.stop_button", True),
        ),
    )
    self._send_feature_visible = bool(visibility.get("chat.send_button", True))
    self._stop_feature_visible = bool(visibility.get("chat.stop_button", True))
    if not bool(visibility.get("chat.apply_selection_checkbox", True)):
        self.apply_selection_cb.setChecked(False)

    apply_widget_placeholders(
        self._user_mode,
        (
            (
                self.input_box,
                "chat.input_box.placeholder",
                "Ask the AI… (Ctrl+Enter to send)",
            ),
        ),
    )
    apply_widget_texts(
        self._user_mode,
        (
            (
                self.apply_selection_cb,
                "chat.apply_selection_checkbox",
                "Apply rewrite directly to selected Draft text",
            ),
            (self.fact_btn, "chat.fact_button", "Faktencheck"),
            (
                self.claim_precompute_btn,
                "chat.claim_precompute_button",
                "Claims vorkalk.",
            ),
            (self.glossary_btn, "chat.glossary_button", "Glossar"),
            (
                self.mindmap_btn,
                "chat.mindmap_button",
                "MindMap/Graph/Chunk",
            ),
            (self.new_tab_btn, "chat.new_tab_button", "+ Tab"),
            (self.clear_btn, "chat.clear_history_button", "🗑"),
            (self.play_last_btn, "chat.play_last_button", "🔊"),
            (self.stop_btn, "chat.stop_button", "⬛ Stop"),
            (self.send_btn, "chat.send_button", "Send ↵"),
        ),
    )
    apply_widget_tooltips(
        self._user_mode,
        (
            (
                self.apply_selection_cb,
                "chat.apply_selection_checkbox.tooltip",
                "If enabled and a draft selection exists, the model must return\n"
                "a structured rewrite block and the selected text is replaced directly.",
            ),
            (
                self.fact_btn,
                "chat.fact_button.tooltip",
                "Prüft den markierten Text (oder den aktuellen Draft-Text) "
                "gegen ausgewählte Dokumente/RAG-Quellen.\n"
                "Beim Start wählst du per Checkliste eine oder mehrere Methoden.\n"
                "Hinweis: LLM (Chunk-weise) ist sehr langsam.",
            ),
            (
                self.claim_precompute_btn,
                "chat.claim_precompute_button.tooltip",
                "Extrahiert atomare Claims pro ausgewähltem Quell-Chunk und speichert sie im Cache.\n"
                "Kann unabhängig vom Faktencheck laufen und wird für weitere Features wiederverwendet.",
            ),
            (
                self.glossary_btn,
                "chat.glossary_button.tooltip",
                "Erstellt ein Glossar nur aus den aktuell ausgewählten Kontextquellen.",
            ),
            (
                self.mindmap_btn,
                "chat.mindmap_button.tooltip",
                "Erstellt MindMap/Graph/Chunk-MindMap nur aus den aktuell ausgewählten Kontextquellen.\n"
                "Modus wird nach Klick im Popup gewählt.",
            ),
            (
                self.new_tab_btn,
                "chat.new_tab_button.tooltip",
                "Neue Unterhaltung starten",
            ),
            (
                self.clear_btn,
                "chat.clear_history_button.tooltip",
                "Clear chat",
            ),
            (
                self.stop_btn,
                "chat.stop_button.tooltip",
                "Stop current generation",
            ),
            (
                self.send_btn,
                "chat.send_button.tooltip",
                "Send request",
            ),
        ),
    )

    combo = self.chat_tts_combo
    apply_combo_item_labels(
        self._user_mode,
        combo,
        (
            (
                0,
                "chat.tts_mode_combo.option.off",
                "TTS: aus",
            ),
            (
                1,
                "chat.tts_mode_combo.option.once",
                "TTS: einmal",
            ),
            (
                2,
                "chat.tts_mode_combo.option.always",
                "TTS: an",
            ),
        ),
    )

    update_context_bar(
        self,
        list(getattr(self, "_context_bar_parts", []) or []),
    )

    self._apply_busy_state()

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
        btn.setText(
            resolve_feature_label(
                self._user_mode,
                "chat.play_last_button.active",
                "⏹",
            )
        )
        btn.setToolTip(
            resolve_feature_label(
                self._user_mode,
                "chat.play_last_button.active.tooltip",
                "Vorlesen stoppen",
            )
        )
        return
    btn.setText(
        resolve_feature_label(
            self._user_mode,
            "chat.play_last_button",
            "🔊",
        )
    )
    btn.setToolTip(
        resolve_feature_label(
            self._user_mode,
            "chat.play_last_button.tooltip",
            "Letzte Modellantwort vorlesen",
        )
    )

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

    min_model = _MODEL_PANEL_MIN_HEIGHT
    min_ctx = _CONTEXT_PANEL_MIN_HEIGHT
    min_chat = _CHAT_PANEL_MIN_HEIGHT

    if not bool(visible):
        if model_size > 8:
            self._model_panel_last_size = model_size
        remaining = total
        ctx_target = _preferred_context_height(self, remaining)
        ctx_target = max(
            min_ctx,
            min(ctx_target, max(min_ctx, remaining - min_chat)),
        )
        chat_target = max(min_chat, remaining - ctx_target)
        splitter.setSizes([0, ctx_target, chat_target])
        return

    available_for_model = max(0, total - (min_ctx + min_chat))
    if available_for_model <= 0:
        ctx_target = _preferred_context_height(self, total)
        ctx_target = max(
            min_ctx,
            min(ctx_target, max(min_ctx, total - min_chat)),
        )
        splitter.setSizes([0, ctx_target, max(min_chat, total - ctx_target)])
        return

    desired = int(self._model_panel_last_size or min_model)
    model_target = max(min_model, min(desired, available_for_model))
    remaining = max(0, total - model_target)
    ctx_chat_total = max(1, ctx_size + chat_size)
    ctx_target = int(round(remaining * (ctx_size / ctx_chat_total)))
    ctx_cap = _preferred_context_height(self, total)
    ctx_target = min(ctx_target, ctx_cap)
    ctx_target = max(min_ctx, min(ctx_target, max(min_ctx, remaining - min_chat)))
    chat_target = max(min_chat, remaining - ctx_target)
    splitter.setSizes([model_target, ctx_target, chat_target])

def toggle_model_panel(self) -> bool:
    new_visible = not self.is_model_panel_visible()
    self.set_model_panel_visible(new_visible)
    return new_visible

__all__ = [
    "set_feedback_service",
    "bind_context_ports",
    "bind_action_ports",
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
