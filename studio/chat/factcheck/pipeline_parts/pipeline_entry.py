"""FactCheckPipelineMixin method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _reset_fact_pipeline_state(self):
    self._pending_fact_check = False
    self._pending_fact_stage = ""
    self._pending_fact_target_text = ""
    self._pending_fact_target_label = ""
    self._pending_fact_sources = []
    self._pending_fact_facts = []
    self._pending_fact_results = []
    self._pending_fact_index = 0
    setattr(self, "_pending_nli_runtime_error", "")
    setattr(self, "_pending_nli_async_active", False)
    setattr(self, "_pending_nli_result_mode", "nli")
    setattr(self, "_pending_nli_chunk_units", [])
    setattr(self, "_pending_nli_sentence_units", [])
    setattr(self, "_pending_nli_fact_index", 0)
    setattr(self, "_pending_nli_pass_mode", "chunk")
    setattr(self, "_pending_nli_unit_index", 0)
    setattr(self, "_pending_nli_tracker", self._new_nli_tracker())
    setattr(self, "_pending_nli_total_checks", 0)
    setattr(self, "_pending_nli_done_checks", 0)
    setattr(self, "_pending_nli_next_progress", self._NLI_ASYNC_PROGRESS_STEP)
    setattr(self, "_pending_fact_mode", "nli")
    setattr(self, "_pending_fact_requested_methods", [])
    setattr(self, "_pending_fact_run_order", [])
    setattr(self, "_pending_fact_backend_index", 0)
    setattr(self, "_pending_fact_active_method", "")
    setattr(self, "_pending_fact_method_results", {})
    setattr(self, "_pending_fact_source_chunks", [])
    setattr(self, "_pending_fact_source_chunk_entries", [])
    setattr(self, "_pending_llm_chunk_units", [])
    setattr(self, "_pending_llm_fact_index", 0)
    setattr(self, "_pending_llm_chunk_index", 0)
    setattr(self, "_pending_llm_tracker", self._new_nli_tracker())
    setattr(self, "_pending_llm_trackers", [])
    setattr(self, "_pending_llm_fact_done", [])
    setattr(self, "_pending_llm_total_checks", 0)
    setattr(self, "_pending_llm_done_checks", 0)
    setattr(self, "_pending_llm_next_progress", self._NLI_ASYNC_PROGRESS_STEP)
    setattr(self, "_pending_claim_chunk_entries", [])
    setattr(self, "_pending_claim_extract_tasks", [])
    setattr(self, "_pending_claim_extract_index", 0)
    self._set_factcheck_async_busy(False)
    self._fact_log_info(
        "Reset pipeline state."
    )

def _resolve_canvas_selected_text(self) -> str:
    """
    Resolve current canvas selection for fact-check target fallback.

    Uses explicit getter when available and falls back to host window's
    canvas widget, including cached one-shot selection after focus handoff.
    """
    getter = getattr(self, "_canvas_selection_getter", None)
    if callable(getter):
        try:
            return str(getter() or "").strip()
        except Exception:
            pass

    parent_fn = getattr(self, "parent", None)
    host = None
    if callable(parent_fn):
        try:
            host = parent_fn()
        except Exception:
            host = None
    if host is None:
        return ""

    canvas = getattr(host, "canvas", None)
    if canvas is None:
        return ""
    get_selected = getattr(canvas, "get_selected_text", None)
    if not callable(get_selected):
        return ""
    try:
        return str(get_selected(allow_cached=True) or "").strip()
    except TypeError:
        try:
            return str(get_selected() or "").strip()
        except Exception:
            return ""
    except Exception:
        return ""

def _send_fact_check(self):
    if not self.llm.is_model_loaded():
        self.history.add_message(
            "system",
            "⚠ No model loaded. Load a GGUF model first.",
        )
        return
    if bool(getattr(self, "_aux_generating", False)) or bool(
        getattr(self, "_factcheck_async_running", False)
    ):
        self.history.add_message(
            "system",
            "⚠ Eine Hintergrundaufgabe läuft bereits. Bitte kurz warten.",
        )
        return

    ctx: dict = {}
    collector = getattr(self, "_collect_shared_context", None)
    if callable(collector):
        ctx = collector()
    elif self._context_getter:
        raw = self._context_getter()
        if isinstance(raw, dict):
            ctx = raw

    grounding_has_sources = bool(ctx.get("grounding_has_sources", False))
    if not grounding_has_sources:
        self.history.add_message(
            "system",
            "⚠ Faktencheck benötigt Quellen. "
            "Bitte mindestens ein Dokument auswählen und/oder RAG-Treffer erzeugen.",
        )
        return

    file_contents = list(ctx.get("file_contents", []) or [])

    selected_text = str(ctx.get("selected_text", "") or "").strip()
    target_text = ""
    target_label = ""
    if not selected_text:
        selected_text = self._resolve_canvas_selected_text()

    if selected_text:
        target_text = selected_text
        target_label = "markierte Draft-Auswahl"
    else:
        for name, content in file_contents:
            if str(name).startswith("Draft:") and str(content or "").strip():
                target_text = str(content).strip()
                target_label = str(name)
                break

    if not target_text:
        typed_text = self.input_box.toPlainText().strip()
        if typed_text:
            target_text = typed_text
            target_label = "Text aus Eingabefeld"

    if not target_text:
        self.history.add_message(
            "system",
            "⚠ Kein Zieltext für Faktencheck gefunden. "
            "Markiere Text im Draft-Workspace oder aktiviere Draft als Kontextquelle.",
        )
        return

    source_contexts = self._build_source_contexts_from_context(ctx)

    if not source_contexts:
        self.history.add_message(
            "system",
            "⚠ Für den Faktencheck wurden keine verwertbaren Quelltexte gefunden.",
        )
        return

    selected_methods = self._select_factcheck_modes()
    if selected_methods is None:
        return
    if not selected_methods:
        self.history.add_message(
            "system",
            "⚠ Bitte mindestens eine Faktencheck-Methode auswählen.",
        )
        return
    mode_labels = [
        self._FACTCHECK_MODE_LABELS.get(mode, mode)
        for mode in selected_methods
    ]
    mode_label = ", ".join(mode_labels)
    nli_loaded = bool(getattr(self.llm, "is_nli_model_loaded", lambda: False)())
    nli_requested = any(mode in {"nli", "llm_claim_nli"} for mode in selected_methods)
    nli_required_modes = {"nli", "llm_claim_nli"}
    all_selected_need_nli = all(mode in nli_required_modes for mode in selected_methods)
    if nli_requested and not nli_loaded and all_selected_need_nli:
        self.history.add_message(
            "system",
            "⚠ NLI-Modell ist nicht geladen. "
            "Bitte zuerst ein NLI-Transformers-Modell laden oder LLM-Modus wählen.",
        )
        return

    self._fact_log_info(
        "Start fact-check\n"
        f"modes={mode_label}\n"
        f"target_label={target_label or 'Zieltext'}\n"
        f"target_text={target_text}\n"
        f"sources={len(source_contexts)}"
    )
    for idx, (name, content) in enumerate(source_contexts, 1):
        self._fact_log_debug(
            f"Source[{idx}] name={name}\ncontent={content}"
        )

    self._pending_apply_to_canvas = False
    self._pending_selected_text = ""
    self._pending_user_message = ""
    self.history.reset_feedback()
    self._reset_fact_pipeline_state()

    self._pending_fact_check = True
    self._pending_fact_stage = "extract"
    self._pending_fact_target_text = target_text
    self._pending_fact_target_label = target_label or "Zieltext"
    self._pending_fact_sources = source_contexts
    self._pending_fact_facts = []
    self._pending_fact_results = []
    self._pending_fact_index = 0
    setattr(self, "_pending_fact_mode", selected_methods[0])
    setattr(self, "_pending_fact_requested_methods", selected_methods)
    setattr(self, "_pending_fact_run_order", [])
    setattr(self, "_pending_fact_backend_index", 0)
    setattr(self, "_pending_fact_active_method", "")
    setattr(self, "_pending_fact_method_results", {})
    setattr(self, "_pending_fact_source_chunks", [])
    self._start_fact_extract_call()

def _start_fact_extract_call(self):
    if not self._pending_fact_check or self._pending_fact_stage != "extract":
        return

    target_text = self._pending_fact_target_text.strip()
    if not target_text:
        self.history.add_message(
            "system", "⚠ Faktencheck abgebrochen: Zieltext fehlt."
        )
        self._reset_fact_pipeline_state()
        return

    fact_limit = suggest_fact_limit(target_text)
    request = self.llm.render_prompt_template(
        "claim_extract_user",
        {
            "input_label": "Zieltext",
            "fact_limit": str(fact_limit),
        },
    ).strip()
    self._fact_log_debug(
        "Extract request\n"
        f"fact_limit={fact_limit}\n"
        f"target={target_text}\n"
        f"user_prompt={request}"
    )

    gen_params = dict(self.model_panel.get_generation_params())
    base_max = max(256, int(gen_params.get("max_tokens", 1024)))
    max_tokens = max(384, min(base_max, 2200))
    max_tokens = max(max_tokens, min(2600, 220 + fact_limit * 22))
    gen_params["max_tokens"] = max_tokens
    gen_params["temperature"] = min(
        float(gen_params.get("temperature", 0.7)),
        0.35,
    )

    started = self.llm.send_message(
        user_message=request,
        file_contents=[("Zieltext", target_text)],
        rag_results=[],
        selected_text="",
        chat_history=[],
        selection_apply_mode=False,
        grounding_required=False,
        grounding_has_sources=True,
        system_prompt_key="claim_extract_system",
        **gen_params,
    )
    if not started:
        self.history.add_message(
            "system", "⚠ Faktenextraktion konnte nicht gestartet werden."
        )
        self._fact_log_info("Extract start failed.")
        self._reset_fact_pipeline_state()

def _start_next_fact_verify_call(self):
    if not self._pending_fact_check or self._pending_fact_stage != "verify":
        return

    if self._pending_fact_index >= len(self._pending_fact_facts):
        active_method = self._normalize_factcheck_mode(
            getattr(self, "_pending_fact_active_method", "")
        )
        if active_method == "llm_global":
            self._complete_fact_backend("llm_global", list(self._pending_fact_results))
            return
        self._finalize_fact_check()
        return

    fact = self._pending_fact_facts[self._pending_fact_index]
    allowed_sources = ", ".join(
        dict.fromkeys(
            name for name, _ in self._pending_fact_sources if str(name).strip()
        )
    )
    request = self.llm.render_prompt_template(
        "fact_verify_user",
        {
            "allowed_sources": allowed_sources or "Kontextquellen",
            "fact": fact,
        },
    ).strip()
    self._fact_log_debug(
        "Verify request\n"
        f"fact_index={self._pending_fact_index}\n"
        f"fact={fact}\n"
        f"allowed_sources={allowed_sources}\n"
        f"user_prompt={request}"
    )

    gen_params = dict(self.model_panel.get_generation_params())
    gen_params["max_tokens"] = max(
        100,
        min(int(gen_params.get("max_tokens", 220)), 260),
    )
    gen_params["temperature"] = min(
        float(gen_params.get("temperature", 0.7)),
        0.25,
    )

    started = self.llm.send_message(
        user_message=request,
        file_contents=self._pending_fact_sources,
        rag_results=[],
        selected_text="",
        chat_history=[],
        selection_apply_mode=False,
        grounding_required=True,
        grounding_has_sources=bool(self._pending_fact_sources),
        system_prompt_key="fact_verify_system",
        **gen_params,
    )
    if not started:
        self.history.add_message(
            "system",
            "⚠ Faktprüfung konnte nicht fortgesetzt werden.",
        )
        self._fact_log_info("Verify start failed.")
        self._reset_fact_pipeline_state()

__all__ = [
    "_reset_fact_pipeline_state",
    "_resolve_canvas_selected_text",
    "_send_fact_check",
    "_start_fact_extract_call",
    "_start_next_fact_verify_call",
]
