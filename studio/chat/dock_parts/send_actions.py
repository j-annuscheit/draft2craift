"""ChatDock method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

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

    ok, info = self._glossary_request_handler(ctx, done)
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

    if mode != "chunkmap" and not self._require_loaded_model():
        return
    if mode != "chunkmap" and self.llm.worker.isRunning():
        self.history.add_message(
            "system",
            "⚠ Modell ist beschäftigt. Bitte nach aktueller Generation erneut versuchen.",
        )
        return

    query = self.input_box.toPlainText().strip()
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
            self.history.add_message(
                "system",
                f"✅ {mode_label} erstellt. {info}".strip(),
            )
            self.history.activate_feedback("mindmap")
            return
        self.history.add_message(
            "system",
            f"⚠ {mode_label} fehlgeschlagen: {info}",
        )

    ok, info = self._mindmap_request_handler(ctx, query, mode, done)
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
