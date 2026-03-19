"""ChatDock method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _should_skip_stream_output(self) -> bool:
    return bool(
        self._pending_fact_check
        or bool(getattr(self, "_pending_chunk_claim_precompute", False))
    )

def _on_token(self, token: str):
    if _should_skip_stream_output(self):
        return
    self.history.append_token(token)


def _on_thinking_token(self, token: str):
    if _should_skip_stream_output(self):
        return
    append_think = getattr(self.history, "append_streaming_thinking_token", None)
    if callable(append_think):
        append_think(token)


def _on_complete(self, response: str):
    think_text = ""
    llm = getattr(self, "llm", None)
    if llm is not None:
        getter = getattr(llm, "last_think_text", None)
        if callable(getter):
            try:
                think_text = str(getter() or "")
            except Exception:
                think_text = ""
    if self._history_stream_open:
        self.history.finish_streaming()
        self._history_stream_open = False
        attach_think = getattr(self.history, "attach_last_assistant_thinking", None)
        if callable(attach_think):
            try:
                attach_think(think_text)
            except Exception:
                pass
    if self._pending_fact_check:
        self._handle_fact_pipeline_complete(response)
        if not self._pending_fact_check:
            self.history.activate_feedback("fact_check")
        return
    if bool(getattr(self, "_pending_chunk_claim_precompute", False)):
        self._handle_chunk_claim_precompute_complete(response)
        return
    self._last_assistant_msg = str(response or "").strip()
    if contains_structured_graph(self._last_assistant_msg):
        self._last_use_case = "mindmap"
    else:
        self._last_use_case = "chat_answer"
    self._maybe_auto_read_response(response)

    if not self._pending_apply_to_canvas:
        self._pending_apply_context = {}
        self._pending_apply_retry_count = 0
        self.history.activate_feedback(self._last_use_case)
        return

    draft_text = ""
    for name, content in list(
        self._pending_apply_context.get("file_contents", []) or []
    ):
        if str(name or "").startswith("Draft:"):
            draft_text = str(content or "")
            break

    raw_replacement = extract_canvas_rewrite(
        response,
        CANVAS_REWRITE_OPEN,
        CANVAS_REWRITE_CLOSE,
    )
    if not raw_replacement:
        if GROUNDING_INSUFFICIENT_MESSAGE in response:
            self._reset_pending_canvas_rewrite()
            self.history.add_message(
                "system",
                f"⚠ {GROUNDING_INSUFFICIENT_MESSAGE}",
            )
            return
        if self._retry_canvas_rewrite_format():
            return
        self._reset_pending_canvas_rewrite()
        self.history.add_message(
            "system",
            "⚠ No valid rewrite block found. Draft selection was not changed.",
        )
        return

    replacement = raw_replacement
    strict_full_draft_match = False
    selected_only_replacement = self._extract_selected_replacement_from_full_draft(
        draft_text,
        self._pending_selected_text,
        raw_replacement,
    )
    if selected_only_replacement:
        replacement = selected_only_replacement
        strict_full_draft_match = True

    if self._selection_apply_handler is None:
        self._reset_pending_canvas_rewrite()
        self.history.add_message(
            "system",
            "⚠ No draft apply handler configured.",
        )
        return

    ok, info = self._selection_apply_handler(
        replacement,
        self._pending_selected_text,
        self._pending_selected_span,
    )
    if ok:
        notify_success = getattr(self, "_notify_canvas_apply_success", None)
        if callable(notify_success):
            notify_success(info)
        else:
            self._reset_pending_canvas_rewrite()
            self.history.add_message(
                "system",
                f"✅ Selection updated in draft workspace. {info}".strip(),
            )
            self.history.activate_feedback("canvas_edit")
        return

    ambiguous_message = "Selection is ambiguous in source text."
    if ambiguous_message in str(info or ""):
        if strict_full_draft_match and draft_text:
            ok, info = self._selection_apply_handler(
                raw_replacement,
                draft_text,
                None,
            )
            if ok:
                notify_success = getattr(self, "_notify_canvas_apply_success", None)
                if callable(notify_success):
                    notify_success(info)
                else:
                    self._reset_pending_canvas_rewrite()
                    self.history.add_message(
                        "system",
                        f"✅ Selection updated in draft workspace. {info}".strip(),
                    )
                    self.history.activate_feedback("canvas_edit")
                return
        if (
            not strict_full_draft_match
            and self._contains_non_selected_canvas_repeat(
                draft_text,
                self._pending_selected_text,
                replacement,
            )
        ):
            if self._retry_canvas_rewrite_format(
                self._canvas_scope_retry_user_message()
            ):
                return
        self._reset_pending_canvas_rewrite()
        self.history.add_message(
            "system",
            (
                "⚠ Could not apply rewrite automatically. "
                "Please reselect the target passage and retry."
            ),
        )
        return

    self._reset_pending_canvas_rewrite()
    info_text = str(info or "")
    if ambiguous_message in info_text:
        info_text = (
            "Selection mapping unavailable. "
            "Please reselect the target passage and retry."
        )
    self.history.add_message("system", f"⚠ Could not apply rewrite: {info_text}")

def _play_last_answer(self):
    if self._read_aloud_active:
        self.read_aloud_stop_requested.emit()
        return
    text = self.history.get_last_message(role="assistant")
    if not text:
        self.history.add_message(
            "system",
            "⚠ Keine Assistenzantwort zum Vorlesen vorhanden.",
        )
        return
    self.read_aloud_requested.emit(text)

def _on_chat_tts_combo_changed(self, _index: int):
    mode = "off"
    combo = getattr(self, "chat_tts_combo", None)
    if combo is not None:
        mode = str(combo.currentData() or "off").strip().lower()
    normalized = self._normalize_tts_mode(mode)
    self._chat_tts_mode = normalized
    self.tts_mode_changed.emit(normalized)

@staticmethod
def _normalize_tts_mode(mode: str) -> str:
    clean = str(mode or "").strip().lower()
    if clean in {"off", "once", "always"}:
        return clean
    return "off"

def _maybe_auto_read_response(self, response: str):
    mode = self._normalize_tts_mode(self._chat_tts_mode)
    if mode == "off":
        return
    text = str(response or "").strip()
    if not text:
        return
    self.read_aloud_requested.emit(text)
    if mode == "once":
        self._chat_tts_mode = "off"
        combo = getattr(self, "chat_tts_combo", None)
        if combo is not None:
            for idx in range(combo.count()):
                if str(combo.itemData(idx) or "") == "off":
                    combo.blockSignals(True)
                    combo.setCurrentIndex(idx)
                    combo.blockSignals(False)
                    break
        self.tts_mode_changed.emit("off")

def _on_chat_feedback_submitted(
    self,
    use_case: str,
    sentiment: str,
    tags: list[str],
    note: str,
):
    if self._feedback_service is None:
        return
    model_info = ""
    model_backend = ""
    panel = getattr(self, "model_panel", None)
    if panel is not None:
        model_path_widget = getattr(panel, "model_path", None)
        if model_path_widget is not None:
            model_info = str(model_path_widget.text() or "")
        backend_getter = getattr(panel, "get_model_backend", None)
        if callable(backend_getter):
            try:
                model_backend = str(backend_getter() or "")
            except Exception:
                model_backend = ""
    payload = {
        "last_user_message": self._last_user_msg,
        "last_assistant_message": self._last_assistant_msg,
        "model": model_info,
        "model_backend": model_backend,
    }
    self._feedback_service.submit_feedback(
        use_case=use_case or self._last_use_case,
        sentiment=sentiment,
        payload=payload,
        error_tags=tags or None,
        note=note,
    )

def _on_error(self, msg: str):
    self._reset_pending_canvas_rewrite()
    self._reset_fact_pipeline_state()
    self._reset_chunk_claim_precompute_state()
    if self._history_stream_open:
        self.history.finish_streaming()
        self._history_stream_open = False
    self.history.add_message("system", f"❌ {msg}")

def _on_generating(self, generating: bool):
    self._llm_generating = bool(generating)
    self._apply_busy_state()

def _apply_busy_state(self):
    llm_active = bool(self._llm_generating)
    fact_async = bool(getattr(self, "_factcheck_async_running", False))
    claim_precompute = bool(getattr(self, "_chunk_claim_precompute_running", False))
    busy_any = bool(self._llm_generating or self._aux_generating or fact_async or claim_precompute)
    send_feature_visible = bool(getattr(self, "_send_feature_visible", True))
    stop_feature_visible = bool(getattr(self, "_stop_feature_visible", True))
    self.send_btn.setVisible(send_feature_visible and (not llm_active))
    self.stop_btn.setVisible(stop_feature_visible and llm_active)
    self.send_btn.setEnabled(not busy_any)
    self.fact_btn.setEnabled(not busy_any)
    self.claim_precompute_btn.setEnabled(not busy_any)
    self.glossary_btn.setEnabled(not busy_any)
    self.mindmap_btn.setEnabled(not busy_any)
    self.input_box.setReadOnly(busy_any)

__all__ = [
    "_on_token",
    "_on_thinking_token",
    "_on_complete",
    "_play_last_answer",
    "_on_chat_tts_combo_changed",
    "_normalize_tts_mode",
    "_maybe_auto_read_response",
    "_on_chat_feedback_submitted",
    "_on_error",
    "_on_generating",
    "_apply_busy_state",
]
