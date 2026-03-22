"""ChatDock method implementations."""
from __future__ import annotations

import os

from .deps import *  # noqa: F403


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().casefold() in {"1", "true", "yes", "on"}

def _resolve_agentic_run_options(
    self,
    *,
    workflow_key: str,
    env_enabled_key: str,
    env_profile_key: str,
    default_profile_id: str,
) -> dict:
    getter = getattr(self, "get_agentic_settings", None)
    if callable(getter):
        try:
            settings = getter()
            run_options_for = getattr(settings, "run_options_for", None)
            if callable(run_options_for):
                options = dict(run_options_for(workflow_key) or {})
                if options:
                    return options
        except Exception:
            pass

    return {
        "enabled": _env_flag(env_enabled_key),
        "profile_id": str(
            os.environ.get(env_profile_key, default_profile_id) or default_profile_id
        ).strip() or default_profile_id,
        "policy_overrides": {},
        "overlay_profile_ids": [],
        "env_name": str(os.environ.get("D2C_AGENTIC_ENV", "") or "").strip(),
    }


def _collect_agentic_sources(self, ctx: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    builder = getattr(self, "_build_source_contexts_from_context", None)
    if callable(builder):
        try:
            rows = list(builder(ctx) or [])
            for name, content in rows:
                clean_name = str(name or "").strip()
                clean_content = str(content or "").strip()
                if not clean_name or not clean_content:
                    continue
                out.append((clean_name, clean_content))
        except Exception:
            pass
    for name, content in list(ctx.get("file_contents", []) or []):
        clean_name = str(name or "").strip()
        clean_content = str(content or "").strip()
        if not clean_name or not clean_content:
            continue
        out.append((clean_name, clean_content))
    for path, _score, excerpt in list(ctx.get("rag_results", []) or []):
        label = str(path or "").strip() or "RAG"
        text = str(excerpt or "").strip()
        if text:
            out.append((label, text))
    dedup: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name, text in out:
        key = (name.casefold(), text)
        if key in seen:
            continue
        seen.add(key)
        dedup.append((name, text))
    return dedup


def _prompt_map_depth_for_mode(self, *, mode: str) -> int | None:
    mode_clean = str(mode or "").strip().casefold()
    if mode_clean not in {"mindmap", "graph"}:
        return 0

    user_mode = str(getattr(self, "_user_mode", "") or "")
    title = resolve_feature_label(
        user_mode,
        "mindmap.generate.dialog.depth.title",
        "Ausbautiefe festlegen",
    )
    intro = resolve_feature_label(
        user_mode,
        "mindmap.generate.dialog.depth.intro",
        "Wie tief soll der Agent den Graph/Mindmap iterativ ausbauen? 0 = deaktiviert.",
    )
    value_prefix = resolve_feature_label(
        user_mode,
        "mindmap.generate.dialog.depth.value_prefix",
        "Tiefe",
    )
    ok_text = resolve_feature_label(
        user_mode,
        "mindmap.generate.dialog.button.ok",
        "OK",
    )
    cancel_text = resolve_feature_label(
        user_mode,
        "mindmap.generate.dialog.button.cancel",
        "Cancel",
    )

    dialog = QDialog(self)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)

    intro_label = QLabel(intro, dialog)
    intro_label.setWordWrap(True)
    layout.addWidget(intro_label)

    slider = QSlider(Qt.Orientation.Horizontal, dialog)
    slider.setRange(0, 6)
    slider.setSingleStep(1)
    slider.setPageStep(1)
    slider.setTickInterval(1)
    slider.setTickPosition(QSlider.TickPosition.TicksBelow)
    slider.setValue(2)
    layout.addWidget(slider)

    value_label = QLabel(dialog)
    layout.addWidget(value_label)

    def _sync_value(value: int) -> None:
        value_label.setText(f"{value_prefix}: {int(value)}")

    slider.valueChanged.connect(_sync_value)
    _sync_value(int(slider.value()))

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        parent=dialog,
    )
    ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
    if ok_btn is not None:
        ok_btn.setText(ok_text)
    cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
    if cancel_btn is not None:
        cancel_btn.setText(cancel_text)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return int(slider.value())


def _try_send_agentic_chat(self, *, msg: str, ctx: dict) -> bool:
    run_options = _resolve_agentic_run_options(
        self,
        workflow_key="chat",
        env_enabled_key="D2C_AGENTIC_CHAT",
        env_profile_key="D2C_AGENTIC_CHAT_PROFILE",
        default_profile_id="chat_grounded_strict",
    )
    if not bool(run_options.get("enabled", False)):
        return False
    try:
        from shared.services.agentic import AgenticWorkflowService, build_tools
    except Exception:
        return False
    profile_id = str(
        run_options.get("profile_id", "chat_grounded_strict")
        or "chat_grounded_strict"
    ).strip() or "chat_grounded_strict"
    sources = _collect_agentic_sources(self, ctx)
    try:
        result = AgenticWorkflowService().run_chat(
            request={"question": str(msg or "")},
            profile_id=profile_id,
            enabled=bool(run_options.get("enabled", False)),
            policy_overrides=dict(run_options.get("policy_overrides", {}) or {}),
            overlay_profile_ids=list(
                run_options.get("overlay_profile_ids", []) or []
            ),
            env_name=str(run_options.get("env_name", "") or ""),
            tools=build_tools(
                llm_manager=self.llm,
                source_texts=sources,
            ),
        )
    except Exception:
        return False
    if not bool(result.ok):
        return False

    payload = dict(result.result.get("response", {}) or {})
    answer = str(payload.get("text", "") or "").strip()
    if not answer:
        return False
    citations = list(payload.get("citations", []) or [])
    if citations:
        lines = [answer, "", "Quellen:"]
        for idx, row in enumerate(citations[:5], 1):
            lines.append(f"{idx}. {row}")
        answer = "\n".join(lines)
    self.history.add_message("assistant", answer)
    self._last_assistant_msg = answer
    self._last_use_case = "chat_answer"
    self._maybe_auto_read_response(answer)
    self.history.activate_feedback("chat_answer")
    return True


def _try_send_agentic_canvas(
    self,
    *,
    instruction: str,
    selected_text: str,
    selected_span: tuple[int, int] | None,
    ctx: dict,
) -> bool:
    run_options = _resolve_agentic_run_options(
        self,
        workflow_key="canvas",
        env_enabled_key="D2C_AGENTIC_CANVAS",
        env_profile_key="D2C_AGENTIC_CANVAS_PROFILE",
        default_profile_id="canvas_grounded_rewrite",
    )
    if not bool(run_options.get("enabled", False)):
        return False
    if self._selection_apply_handler is None:
        return False
    try:
        from shared.services.agentic import AgenticWorkflowService, build_tools
    except Exception:
        return False

    apply_state: dict[str, object] = {"ok": False, "info": "", "text": ""}

    def _apply_target(text: str):
        ok, info = self._selection_apply_handler(
            str(text or ""),
            str(selected_text or ""),
            selected_span,
        )
        apply_state["ok"] = bool(ok)
        apply_state["info"] = str(info or "")
        apply_state["text"] = str(text or "")
        if not ok:
            raise RuntimeError(str(info or "apply_failed"))

    profile_id = str(
        run_options.get("profile_id", "canvas_grounded_rewrite")
        or "canvas_grounded_rewrite"
    ).strip() or "canvas_grounded_rewrite"
    sources = _collect_agentic_sources(self, ctx)
    try:
        result = AgenticWorkflowService().run_canvas(
            request={
                "instruction": str(instruction or ""),
                "selected_text": str(selected_text or ""),
            },
            profile_id=profile_id,
            enabled=bool(run_options.get("enabled", False)),
            policy_overrides=dict(run_options.get("policy_overrides", {}) or {}),
            overlay_profile_ids=list(
                run_options.get("overlay_profile_ids", []) or []
            ),
            env_name=str(run_options.get("env_name", "") or ""),
            tools=build_tools(
                llm_manager=self.llm,
                source_texts=sources,
                canvas_apply=_apply_target,
            ),
        )
    except Exception:
        return False
    if not bool(result.ok):
        return False
    if not bool(apply_state.get("ok", False)):
        return False

    text = str(apply_state.get("text", "") or "")
    info = str(apply_state.get("info", "") or "")
    self._last_assistant_msg = text
    self._last_use_case = "canvas_edit"
    notify_success = getattr(self, "_notify_canvas_apply_success", None)
    if callable(notify_success):
        notify_success(info)
    else:
        self.history.add_message(
            "system",
            f"✅ Selection updated in draft workspace. {info}".strip(),
        )
        self.history.activate_feedback("canvas_edit")
    return True


def _send_glossary_generation(self):
    if not self._require_loaded_model():
        return
    if self._aux_generating:
        self.history.add_message(
            "system",
            "⚠ Eine Hintergrundaufgabe läuft bereits. Bitte kurz warten.",
        )
        return
    if self.llm.worker.isRunning():
        self.history.add_message(
            "system",
            "⚠ Modell ist beschäftigt. Bitte nach aktueller Generation erneut versuchen.",
        )
        return
    if self._glossary_request_handler is None:
        self.history.add_message(
            "system",
            "⚠ Kein Glossar-Handler konfiguriert.",
        )
        return

    ctx = self._collect_shared_context()
    if not self._has_any_context_content(ctx):
        self.history.add_message(
            "system",
            "⚠ Kein Kontext ausgewählt. Bitte im Context-Bereich Quellen aktivieren.",
        )
        return

    query = str(ctx.get("user_query", "") or self.input_box.toPlainText() or "").strip()
    if query:
        self.history.add_message(
            "user",
            f"Glossar aus aktuellem Kontext\nFokus: {query}",
        )
    else:
        self.history.add_message("user", "Glossar aus aktuellem Kontext")
    self.history.reset_feedback()

    def done(ok: bool, info: str):
        if ok:
            self._last_use_case = "glossary"
            self.history.add_message(
                "system",
                f"✅ Glossar erstellt. {info}".strip(),
            )
            self.history.activate_feedback("glossary")
            return
        self.history.add_message("system", f"⚠ Glossar fehlgeschlagen: {info}")

    ok, info = self._glossary_request_handler(ctx, query, done)
    if ok:
        self.history.add_message("system", "⏳ Glossar wird erstellt…")
        return
    self.history.add_message("system", f"⚠ Glossar fehlgeschlagen: {info}")

def _send_claim_precompute(self):
    if not self._require_loaded_model():
        return
    if self._aux_generating:
        self.history.add_message(
            "system",
            "⚠ Eine Hintergrundaufgabe läuft bereits. Bitte kurz warten.",
        )
        return
    if bool(getattr(self, "_pending_fact_check", False)):
        self.history.add_message(
            "system",
            "⚠ Faktencheck läuft bereits. Bitte zuerst abschließen.",
        )
        return
    if bool(getattr(self, "_pending_chunk_claim_precompute", False)):
        self.history.add_message(
            "system",
            "⚠ Chunk-Claim-Vorkalkulation läuft bereits.",
        )
        return
    if self.llm.worker.isRunning():
        self.history.add_message(
            "system",
            "⚠ Modell ist beschäftigt. Bitte nach aktueller Generation erneut versuchen.",
        )
        return

    ctx = self._collect_shared_context()
    if not bool(ctx.get("grounding_has_sources", False)):
        self.history.add_message(
            "system",
            "⚠ Keine Quellen ausgewählt. Bitte Dokumente und/oder RAG-Kontext aktivieren.",
        )
        return
    sources = self._build_source_contexts_from_context(ctx)
    if not sources:
        self.history.add_message(
            "system",
            "⚠ Keine verwertbaren Quelltexte für die Claim-Vorkalkulation gefunden.",
        )
        return

    ok, info = self._start_chunk_claim_precompute(sources)
    if ok:
        if "Cache vollständig" in str(info):
            self.history.add_message("system", f"ℹ {info}")
        else:
            self.history.add_message("system", f"⏳ {info}")
        return
    self.history.add_message("system", f"⚠ Claim-Vorkalkulation fehlgeschlagen: {info}")

def _send_mindmap_generation(self):
    if self._aux_generating:
        self.history.add_message(
            "system",
            "⚠ Eine Hintergrundaufgabe läuft bereits. Bitte kurz warten.",
        )
        return
    if self._mindmap_request_handler is None:
        self.history.add_message(
            "system",
            "⚠ Kein MindMap/Graph-Handler konfiguriert.",
        )
        return

    ctx = self._collect_shared_context()
    if not self._has_any_context_content(ctx):
        self.history.add_message(
            "system",
            "⚠ Kein Kontext ausgewählt. Bitte im Context-Bereich Quellen aktivieren.",
        )
        return

    mode_choice, accepted = QInputDialog.getItem(
        self,
        "MindMap/Graph/Chunk-MindMap aus Kontext",
        "Ausgabeformat:",
        ["Chunk-MindMap", "MindMap", "Graph"],
        0,
        False,
    )
    if not accepted:
        return
    mode_choice_clean = str(mode_choice or "").strip().casefold()
    if mode_choice_clean == "graph":
        mode = "graph"
        mode_label = "Graph"
    elif "chunk" in mode_choice_clean:
        mode = "chunkmap"
        mode_label = "Chunk-MindMap"
    else:
        mode = "mindmap"
        mode_label = "MindMap"

    map_depth = _prompt_map_depth_for_mode(self, mode=mode)
    if map_depth is None:
        return

    if mode != "chunkmap" and not self._require_loaded_model():
        return
    if mode != "chunkmap" and self.llm.worker.isRunning():
        self.history.add_message(
            "system",
            "⚠ Modell ist beschäftigt. Bitte nach aktueller Generation erneut versuchen.",
        )
        return

    query = str(
        ctx.get("user_query", "") or self.input_box.toPlainText() or ""
    ).strip()
    if query:
        self.history.add_message(
            "user",
            f"{mode_label} aus aktuellem Kontext\nQuery: {query}",
        )
    else:
        self.history.add_message("user", f"{mode_label} aus aktuellem Kontext")

    self.history.reset_feedback()

    def done(ok: bool, info: str):
        if ok:
            self._last_use_case = "mindmap"
            detail = str(info or "").strip()
            message = f"✅ {mode_label} erstellt."
            if detail:
                message = f"{message}\n{detail}"
            self.history.add_message(
                "system",
                message,
            )
            self.history.activate_feedback("mindmap")
            return
        self.history.add_message(
            "system",
            f"⚠ {mode_label} fehlgeschlagen: {info}",
        )

    ok, info = self._mindmap_request_handler(
        ctx,
        query_raw=query,
        mode_hint=mode,
        map_depth=int(map_depth or 0),
        done_cb=done,
    )
    if ok:
        self.history.add_message("system", f"⏳ {mode_label} wird erstellt…")
        return
    self.history.add_message(
        "system",
        f"⚠ {mode_label} fehlgeschlagen: {info}",
    )

def _send(self):
    msg = self.input_box.toPlainText().strip()
    if not msg:
        return

    self._last_user_msg = msg
    self._last_use_case = "chat_answer"
    self.history.reset_feedback()
    self._reset_fact_pipeline_state()
    if not self._require_loaded_model():
        return
    if self._aux_generating:
        self.history.add_message(
            "system",
            "⚠ Eine Hintergrundaufgabe läuft bereits. Bitte kurz warten.",
        )
        return

    ctx = self._collect_shared_context()

    selected_text = ctx.get("selected_text", "")
    selected_span = ctx.get("selected_span", None)
    selection_apply_mode = bool(
        self.apply_selection_cb.isChecked() and selected_text and selected_text.strip()
    )
    if self.apply_selection_cb.isChecked() and not selection_apply_mode:
        self.history.add_message(
            "system",
            "⚠ 'Apply rewrite' is enabled, but no draft text is selected.",
        )
        return

    grounding_required = bool(ctx.get("grounding_required", False))
    grounding_has_sources = bool(ctx.get("grounding_has_sources", True))
    if grounding_required and not grounding_has_sources:
        mode_hint = (
            "RAG" if bool(ctx.get("grounding_rag_selected", False)) else "Dokumente"
        )
        self.history.add_message(
            "system",
            "⚠ Dokumentgebundener Modus aktiv (" + mode_hint + "). "
            "Es liegen aber keine verwertbaren Inhalte vor. "
            "Bitte zuerst RAG-Ergebnisse erzeugen und/oder Dokumente auswählen. "
            "Ohne Quellen wird keine Antwort erzeugt.",
        )
        return

    self.history.add_message("user", msg)
    self.input_box.clear()

    self._reset_pending_canvas_rewrite()
    if selection_apply_mode and _try_send_agentic_canvas(
        self,
        instruction=msg,
        selected_text=str(selected_text or ""),
        selected_span=selected_span,
        ctx=ctx,
    ):
        return
    if (not selection_apply_mode) and _try_send_agentic_chat(
        self,
        msg=msg,
        ctx=ctx,
    ):
        return
    self._pending_apply_to_canvas = selection_apply_mode
    self._pending_selected_text = selected_text if selection_apply_mode else ""
    self._pending_selected_span = (
        selected_span if selection_apply_mode else None
    )

    file_contents = list(ctx.get("file_contents", []))
    if selection_apply_mode:
        # Keep full-draft context available for coherence, but avoid
        # duplicate payloads when the selected text already equals it.
        norm_selected = self._normalize_context_text(selected_text)
        filtered: list[tuple[str, str]] = []
        for name, content in file_contents:
            if not str(name).startswith("Draft:"):
                filtered.append((name, content))
                continue

            norm_full_draft = self._normalize_context_text(content)
            if norm_full_draft and norm_full_draft == norm_selected:
                continue
            filtered.append((name, content))
        file_contents = filtered

    history = self.history.get_history()[:-1]
    gen_params = self.model_panel.get_generation_params()
    if selection_apply_mode:
        self._pending_apply_context = {
            "file_contents": list(file_contents),
            "rag_results": list(ctx.get("rag_results", []) or []),
            "selected_text": selected_text,
            "selected_span": selected_span,
            "grounding_required": grounding_required,
            "grounding_has_sources": grounding_has_sources,
            "gen_params": dict(gen_params),
        }

    started = self.llm.send_message(
        user_message=msg,
        file_contents=file_contents,
        rag_results=ctx.get("rag_results", []),
        selected_text=selected_text,
        chat_history=history,
        selection_apply_mode=selection_apply_mode,
        grounding_required=grounding_required,
        grounding_has_sources=grounding_has_sources,
        **gen_params,
    )
    if started:
        self.history.begin_streaming()
        self._history_stream_open = True
        return
    self._reset_pending_canvas_rewrite()

__all__ = [
    "_send_glossary_generation",
    "_send_claim_precompute",
    "_send_mindmap_generation",
    "_send",
]
