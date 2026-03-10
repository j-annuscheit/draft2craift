"""FactCheckPipelineMixin method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _start_next_fact_backend(self):
    if not self._pending_fact_check:
        return
    run_order = list(getattr(self, "_pending_fact_run_order", []) or [])
    backend_index = int(getattr(self, "_pending_fact_backend_index", 0) or 0)
    if backend_index >= len(run_order):
        self._finalize_fact_check()
        return
    mode = self._normalize_factcheck_mode(run_order[backend_index])
    if mode not in {"nli", "llm_chunk", "llm_global", "llm_claim_nli"}:
        setattr(self, "_pending_fact_backend_index", backend_index + 1)
        self._start_next_fact_backend()
        return

    facts = list(getattr(self, "_pending_fact_facts", []) or [])
    source_chunks = list(getattr(self, "_pending_fact_source_chunks", []) or [])
    source_chunk_entries = list(getattr(self, "_pending_fact_source_chunk_entries", []) or [])
    if mode == "llm_global":
        if not facts or not list(getattr(self, "_pending_fact_sources", []) or []):
            self._complete_fact_backend(mode, [])
            return
    elif mode == "llm_claim_nli":
        if not facts or not source_chunk_entries:
            self._complete_fact_backend(mode, [])
            return
    elif not facts or not source_chunks:
        self._complete_fact_backend(mode, [])
        return

    setattr(self, "_pending_fact_active_method", mode)
    self._pending_fact_results = []
    method_label = self._FACTCHECK_MODE_LABELS.get(mode, mode)
    if mode == "nli":
        self._fact_log_info(
            f"NLI mode enabled | facts={len(facts)} chunks={len(source_chunks)}"
        )
        if self._supports_async_nli_verify():
            self._start_nli_verify_async(facts, source_chunks)
            return
        rows = self._verify_facts_with_nli(facts, source_chunks)
        runtime_error = str(getattr(self, "_pending_nli_runtime_error", "") or "").strip()
        if runtime_error:
            self.history.add_message(
                "system",
                f"⚠ NLI-Model-Fehler: {runtime_error}",
            )
            self._complete_fact_backend("nli", [])
            return
        self._complete_fact_backend("nli", rows)
        return

    _ = method_label
    if mode == "llm_global":
        self._pending_fact_stage = "verify"
        self._pending_fact_index = 0
        self._start_next_fact_verify_call()
        return
    if mode == "llm_claim_nli":
        self._start_llm_claim_nli_verify()
        return
    self._start_llm_chunk_verify(source_chunks)

def _start_llm_chunk_verify(self, source_chunks: list[tuple[str, str]]):
    self._pending_fact_stage = "verify_llm_chunk"
    setattr(self, "_pending_llm_chunk_units", self._build_chunk_nli_units(source_chunks))
    setattr(self, "_pending_llm_fact_index", 0)
    setattr(self, "_pending_llm_chunk_index", 0)
    setattr(self, "_pending_llm_tracker", self._new_nli_tracker())
    fact_count = len(self._pending_fact_facts)
    setattr(
        self,
        "_pending_llm_trackers",
        [self._new_nli_tracker() for _ in range(max(0, fact_count))],
    )
    setattr(self, "_pending_llm_fact_done", [False for _ in range(max(0, fact_count))])
    llm_units = list(getattr(self, "_pending_llm_chunk_units", []) or [])
    self._fact_log_info(
        "LLM chunk mode enabled | "
        f"facts={len(self._pending_fact_facts)} chunks={len(llm_units)} "
        "sentence_fallback=disabled iteration=chunk_first"
    )
    total_checks = len(self._pending_fact_facts) * len(llm_units)
    setattr(self, "_pending_llm_total_checks", int(max(0, total_checks)))
    setattr(self, "_pending_llm_done_checks", 0)
    setattr(self, "_pending_llm_next_progress", self._NLI_ASYNC_PROGRESS_STEP)
    self._start_next_llm_chunk_verify_call()

def _start_llm_claim_nli_verify(self):
    chunk_entries = list(getattr(self, "_pending_fact_source_chunk_entries", []) or [])
    if not chunk_entries:
        self._complete_fact_backend("llm_claim_nli", [])
        return

    missing: list[dict[str, object]] = []
    for entry in chunk_entries:
        cached_claims = self._get_cached_chunk_claims(entry)
        if cached_claims:
            continue
        missing.append(dict(entry))

    setattr(self, "_pending_claim_chunk_entries", chunk_entries)
    setattr(self, "_pending_claim_extract_tasks", missing)
    setattr(self, "_pending_claim_extract_index", 0)

    if not missing:
        self._fact_log_info(
            "Chunk-Claims cache hit | "
            f"chunks={len(chunk_entries)}"
        )
        self._start_claim_nli_verify_from_cache()
        return

    self._pending_fact_stage = "extract_chunk_claims"
    self._fact_log_info(
        "Chunk-Claims preprocessing | "
        f"total_chunks={len(chunk_entries)} uncached_chunks={len(missing)}"
    )
    self._start_next_chunk_claim_extract_call()

def _start_next_chunk_claim_extract_call(self):
    if not self._pending_fact_check or self._pending_fact_stage != "extract_chunk_claims":
        return

    tasks = list(getattr(self, "_pending_claim_extract_tasks", []) or [])
    idx = int(getattr(self, "_pending_claim_extract_index", 0) or 0)
    if idx >= len(tasks):
        self._start_claim_nli_verify_from_cache()
        return

    entry = dict(tasks[idx] or {})
    source_name = str(entry.get("source", "") or "").strip() or "Quelle"
    chunk_text = str(entry.get("chunk_text", "") or "").strip()
    if not chunk_text:
        self._store_cached_chunk_claims(entry, [])
        setattr(self, "_pending_claim_extract_index", idx + 1)
        self._start_next_chunk_claim_extract_call()
        return

    fact_limit = suggest_fact_limit(chunk_text)
    request = self.llm.render_prompt_template(
        "claim_extract_user",
        {
            "input_label": "Chunk",
            "fact_limit": str(fact_limit),
        },
    ).strip()
    if not request:
        request = (
            "Extrahiere atomare Claims aus genau diesem Chunk.\n"
            "Ausgabe NUR als JSON-Array von Strings.\n"
            f"Maximal {fact_limit} Claims."
        )
    self._fact_log_debug(
        "Chunk-Claim extract request\n"
        f"chunk_task_index={idx}\n"
        f"source={source_name}\n"
        f"chunk_hash={entry.get('chunk_hash', '')}\n"
        f"user_prompt={request}\n"
        f"chunk={chunk_text}"
    )

    gen_params = dict(self.model_panel.get_generation_params())
    gen_params["max_tokens"] = max(
        180,
        min(int(gen_params.get("max_tokens", 220)), 800),
    )
    gen_params["temperature"] = min(float(gen_params.get("temperature", 0.7)), 0.25)

    started = self.llm.send_message(
        user_message=request,
        file_contents=[(source_name, chunk_text)],
        rag_results=[],
        selected_text="",
        chat_history=[],
        selection_apply_mode=False,
        grounding_required=False,
        grounding_has_sources=True,
        system_prompt_key="claim_extract_system",
        **gen_params,
    )
    if started:
        return

    self._fact_log_info(
        "Chunk-Claim extraction start failed; cache empty claims.\n"
        f"source={source_name}"
    )
    self._store_cached_chunk_claims(entry, [])
    setattr(self, "_pending_claim_extract_index", idx + 1)
    self._start_next_chunk_claim_extract_call()

def _start_claim_nli_verify_from_cache(self):
    chunk_entries = list(getattr(self, "_pending_claim_chunk_entries", []) or [])
    facts = list(getattr(self, "_pending_fact_facts", []) or [])
    claim_units = self._build_claim_nli_units(chunk_entries)
    self._fact_log_info(
        "Chunk-Claim NLI verify start | "
        f"facts={len(facts)} claim_units={len(claim_units)} chunks={len(chunk_entries)}"
    )
    if not facts or not claim_units:
        rows: list[dict[str, str]] = []
        for fact_index, fact in enumerate(facts):
            rows.append(
                {
                    "id": f"C{fact_index + 1}",
                    "status": "nicht_belegt",
                    "fact": fact,
                    "sources": "",
                    "evidence": "",
                    "confidence": "0.0000",
                    "reason": "Keine extrahierten Chunk-Claims für NLI-Abgleich gefunden",
                }
            )
        self._pending_fact_results = list(rows)
        self._complete_fact_backend("llm_claim_nli", rows)
        return

    if self._supports_async_nli_verify():
        self._start_nli_verify_async(
            facts=facts,
            source_chunks=[],
            mode="llm_claim_nli",
            chunk_units=claim_units,
            sentence_units=[],
        )
        return

    rows = self._verify_facts_with_nli_units(
        facts=facts,
        chunk_units=claim_units,
        sentence_units=[],
        method="llm_claim_nli",
    )
    runtime_error = str(getattr(self, "_pending_nli_runtime_error", "") or "").strip()
    if runtime_error:
        self.history.add_message(
            "system",
            f"⚠ NLI-Model-Fehler: {runtime_error}",
        )
        self._complete_fact_backend("llm_claim_nli", [])
        return
    self._complete_fact_backend("llm_claim_nli", rows)

def _build_llm_chunk_rows(
    self,
    facts: list[str],
    trackers: list[dict[str, object]],
    method: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for fact_index, fact in enumerate(facts):
        tracker = (
            dict(trackers[fact_index])
            if fact_index < len(trackers)
            else self._new_nli_tracker()
        )
        rows.append(
            self._build_nli_result_row(
                fact_index,
                fact,
                tracker,
                method=method,
            )
        )
    return rows

def _start_next_llm_chunk_verify_call(self):
    if not self._pending_fact_check or self._pending_fact_stage != "verify_llm_chunk":
        return
    facts = list(self._pending_fact_facts or [])
    units = list(getattr(self, "_pending_llm_chunk_units", []) or [])
    active_method = self._normalize_factcheck_mode(
        getattr(self, "_pending_fact_active_method", "llm_chunk")
    )
    if active_method not in {"llm_chunk", "llm"}:
        active_method = "llm_chunk"
    if not facts or not units:
        self._complete_fact_backend(active_method, list(self._pending_fact_results))
        return

    fact_index = int(getattr(self, "_pending_llm_fact_index", 0) or 0)
    chunk_index = int(getattr(self, "_pending_llm_chunk_index", 0) or 0)
    trackers = list(getattr(self, "_pending_llm_trackers", []) or [])
    if len(trackers) < len(facts):
        trackers.extend(
            self._new_nli_tracker()
            for _ in range(len(facts) - len(trackers))
        )
    fact_done = list(getattr(self, "_pending_llm_fact_done", []) or [])
    if len(fact_done) < len(facts):
        fact_done.extend(False for _ in range(len(facts) - len(fact_done)))

    while chunk_index < len(units):
        if fact_index >= len(facts):
            chunk_index += 1
            fact_index = 0
            continue
        if fact_done[fact_index]:
            fact_index += 1
            continue
        break

    setattr(self, "_pending_llm_fact_index", fact_index)
    setattr(self, "_pending_llm_chunk_index", chunk_index)
    setattr(self, "_pending_llm_trackers", trackers)
    setattr(self, "_pending_llm_fact_done", fact_done)
    current_tracker = (
        dict(trackers[fact_index])
        if 0 <= fact_index < len(trackers)
        else self._new_nli_tracker()
    )
    setattr(self, "_pending_llm_tracker", current_tracker)

    if chunk_index >= len(units) or all(bool(v) for v in fact_done):
        rows = self._build_llm_chunk_rows(facts, trackers, active_method)
        self._pending_fact_results = list(rows)
        self._complete_fact_backend(active_method, rows)
        return

    fact = facts[fact_index]
    unit = units[chunk_index]
    source_name = str(unit.get("source", "") or "").strip() or "Quelle"
    premise_text = str(unit.get("premise", "") or "").strip()
    request = self.llm.render_prompt_template(
        "fact_verify_chunk_user",
        {
            "fact": fact,
            "source": source_name,
            "chunk": premise_text,
        },
    ).strip()
    if not request:
        request = (
            "Prüfe den Fakt gegen genau diesen einzelnen Chunk.\n"
            "Der Chunk ist die einzige Quelle. Kein externes Wissen.\n"
            "Antwort NUR als JSON: "
            "{\"decision\":\"entailment|neutral|contradiction\","
            "\"confidence\":0.0,\"reason\":\"...\",\"numeric_check\":\"...\","
            "\"evidence\":\"...\"}\n"
            f"Fakt:\n{fact}\nQuelle:\n{source_name}"
        )
    self._fact_log_debug(
        "LLM chunk verify request\n"
        f"fact_index={fact_index}\n"
        f"chunk_index={chunk_index}\n"
        f"source={source_name}\n"
        f"fact={fact}\n"
        f"chunk={premise_text}\n"
        f"user_prompt={request}"
    )

    gen_params = dict(self.model_panel.get_generation_params())
    gen_params["max_tokens"] = max(
        120,
        min(int(gen_params.get("max_tokens", 220)), 300),
    )
    gen_params["temperature"] = min(
        float(gen_params.get("temperature", 0.7)),
        0.20,
    )
    started = self.llm.send_message(
        user_message=request,
        file_contents=[(source_name, premise_text)],
        rag_results=[],
        selected_text="",
        chat_history=[],
        selection_apply_mode=False,
        grounding_required=True,
        grounding_has_sources=True,
        system_prompt_key="fact_verify_chunk_system",
        **gen_params,
    )
    if started:
        return
    self.history.add_message(
        "system",
        "⚠ LLM-Chunkprüfung konnte nicht fortgesetzt werden.",
    )
    self._reset_fact_pipeline_state()

__all__ = [
    "_start_next_fact_backend",
    "_start_llm_chunk_verify",
    "_start_llm_claim_nli_verify",
    "_start_next_chunk_claim_extract_call",
    "_start_claim_nli_verify_from_cache",
    "_build_llm_chunk_rows",
    "_start_next_llm_chunk_verify_call",
]
