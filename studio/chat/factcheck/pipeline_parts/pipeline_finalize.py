"""FactCheckPipelineMixin method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _complete_fact_backend(self, mode: str, rows: list[dict[str, str]]):
    run_order = list(getattr(self, "_pending_fact_run_order", []) or [])
    method_results = dict(getattr(self, "_pending_fact_method_results", {}) or {})
    method_results[str(mode)] = list(rows or [])
    setattr(self, "_pending_fact_method_results", method_results)
    next_index = int(getattr(self, "_pending_fact_backend_index", 0) or 0) + 1
    setattr(self, "_pending_fact_backend_index", next_index)
    if next_index < len(run_order):
        self._start_next_fact_backend()
        return
    if run_order:
        first_mode = run_order[0]
        self._pending_fact_results = list(method_results.get(first_mode, []) or [])
    self._finalize_fact_check()

def _finalize_fact_check(self):
    markdown = self._compose_factcheck_markdown_for_methods()
    self._fact_log_debug(
        "Final markdown table\n"
        f"{markdown}"
    )
    note = validate_fact_check_response(
        markdown,
        self._pending_fact_target_text,
        self._pending_fact_sources,
    )
    if note:
        note_text = self._WARNING_PREFIX_RE.sub("", str(note or "")).strip()
        markdown = f"{markdown}\n\n---\n\n## Qualitätsprüfung\n{note_text}"

    if self._fact_result_handler is not None:
        ok, info = self._fact_result_handler(
            self._pending_fact_target_label or "Faktencheck",
            markdown,
        )
        if not ok:
            self.history.add_message(
                "system",
                "⚠ Faktencheck konnte nicht im Draft-Workspace geöffnet "
                f"werden: {info}",
            )
            self.history.add_message("assistant", markdown)
    else:
        self.history.add_message("assistant", markdown)
    self._reset_fact_pipeline_state()

def _handle_fact_pipeline_complete(self, response: str):
    self._fact_log_debug(
        "Stage response\n"
        f"stage={self._pending_fact_stage}\n"
        f"response={response}"
    )
    if self._pending_fact_stage == "extract":
        facts = self._parse_atomic_claims_from_response(
            response,
            self._pending_fact_target_text,
        )
        self._fact_log_info(
            f"Extract parsed facts={len(facts)}"
        )
        for idx, fact in enumerate(facts, 1):
            self._fact_log_debug(f"Fact[{idx}] {fact}")
        if not facts:
            self.history.add_message(
                "system",
                "⚠ Es konnten keine stabilen Fakten aus dem Zieltext extrahiert werden.",
            )
            self._reset_fact_pipeline_state()
            return
        self.history.add_message("system", f"ℹ Fakten gefunden: {len(facts)}")
        self._pending_fact_facts = facts
        self._pending_fact_results = []
        self._pending_fact_index = 0
        chunk_entries = self._build_source_chunk_entries(self._pending_fact_sources)
        source_chunks = [
            (
                str(entry.get("source", "") or ""),
                str(entry.get("chunk_text", "") or ""),
            )
            for entry in chunk_entries
            if str(entry.get("source", "") or "").strip()
            and str(entry.get("chunk_text", "") or "").strip()
        ]
        if not source_chunks:
            self.history.add_message(
                "system",
                "⚠ Für den Faktencheck wurden keine verwertbaren Quell-Chunks gefunden.",
            )
            self._reset_fact_pipeline_state()
            return
        setattr(self, "_pending_fact_source_chunks", source_chunks)
        setattr(self, "_pending_fact_source_chunk_entries", chunk_entries)

        requested_methods = self._normalize_factcheck_selection(
            getattr(self, "_pending_fact_requested_methods", [])
        )
        if not requested_methods:
            requested_methods = self._normalize_factcheck_selection(
                getattr(self, "_pending_fact_mode", "nli")
            )
        nli_loaded = bool(getattr(self.llm, "is_nli_model_loaded", lambda: False)())
        run_order: list[str] = []
        for requested_mode in requested_methods:
            mode = self._normalize_factcheck_mode(requested_mode)
            if mode == "nli":
                if nli_loaded:
                    run_order.append("nli")
                else:
                    self.history.add_message(
                        "system",
                        "⚠ NLI-Modell nicht geladen. NLI-Lauf wird übersprungen.",
                    )
                continue
            if mode in {"llm_chunk", "llm_global"}:
                run_order.append(mode)
                continue
            if mode == "llm_claim_nli":
                if nli_loaded:
                    run_order.append(mode)
                else:
                    self.history.add_message(
                        "system",
                        "⚠ NLI-Modell nicht geladen. LLM-Claims+NLI wird übersprungen.",
                    )
        if not run_order:
            self.history.add_message(
                "system",
                "⚠ Keine verfügbare Faktencheck-Methode ausgewählt.",
            )
            self._reset_fact_pipeline_state()
            return

        setattr(self, "_pending_fact_run_order", run_order)
        setattr(self, "_pending_fact_backend_index", 0)
        setattr(self, "_pending_fact_method_results", {})
        self._start_next_fact_backend()
        return

    if self._pending_fact_stage == "extract_chunk_claims":
        tasks = list(getattr(self, "_pending_claim_extract_tasks", []) or [])
        idx = int(getattr(self, "_pending_claim_extract_index", 0) or 0)
        if idx < len(tasks):
            entry = dict(tasks[idx] or {})
            chunk_text = str(entry.get("chunk_text", "") or "")
            claims = self._parse_atomic_claims_from_response(response, chunk_text)
            self._store_cached_chunk_claims(entry, claims)
            self._fact_log_info(
                "Chunk-Claim extract parsed | "
                f"chunk_task_index={idx} claims={len(claims)} "
                f"source={entry.get('source', '')}"
            )
            setattr(self, "_pending_claim_extract_index", idx + 1)
        self._start_next_chunk_claim_extract_call()
        return

    if self._pending_fact_stage == "verify_llm_chunk":
        facts = list(self._pending_fact_facts or [])
        units = list(getattr(self, "_pending_llm_chunk_units", []) or [])
        fact_index = int(getattr(self, "_pending_llm_fact_index", 0) or 0)
        chunk_index = int(getattr(self, "_pending_llm_chunk_index", 0) or 0)
        if fact_index < len(facts) and chunk_index < len(units):
            unit = units[chunk_index]
            source_name = str(unit.get("source", "") or "").strip()
            chunk_text = str(unit.get("evidence", "") or "").strip()
            fact = facts[fact_index]
            label, score, reason, evidence_hint, numeric_check = self._parse_llm_chunk_verdict(response)
            label, score, reason, evidence_text = self._calibrate_llm_chunk_result(
                fact=fact,
                chunk_text=chunk_text,
                label=label,
                score=score,
                reason=reason,
                evidence_hint=evidence_hint,
                numeric_check=numeric_check,
            )
            self._fact_log_debug(
                "LLM chunk verify parsed\n"
                f"fact_index={fact_index}\n"
                f"chunk_index={chunk_index}\n"
                f"fact={fact}\n"
                f"source={source_name}\n"
                f"label={label}\n"
                f"score={score:.4f}\n"
                f"reason={reason}\n"
                f"evidence={evidence_text}"
            )
            trackers = list(getattr(self, "_pending_llm_trackers", []) or [])
            if len(trackers) < len(facts):
                trackers.extend(
                    self._new_nli_tracker()
                    for _ in range(len(facts) - len(trackers))
                )
            fact_done = list(getattr(self, "_pending_llm_fact_done", []) or [])
            if len(fact_done) < len(facts):
                fact_done.extend(False for _ in range(len(facts) - len(fact_done)))
            tracker = dict(trackers[fact_index] or self._new_nli_tracker())
            self._update_nli_tracker(
                tracker,
                label=label,
                score=score,
                source_name=source_name,
                evidence_text=evidence_text,
                reason=reason,
            )
            trackers[fact_index] = tracker
            setattr(self, "_pending_llm_trackers", trackers)
            setattr(self, "_pending_llm_fact_done", fact_done)
            setattr(self, "_pending_llm_tracker", tracker)
            done_checks = int(getattr(self, "_pending_llm_done_checks", 0) or 0) + 1
            total_checks = int(getattr(self, "_pending_llm_total_checks", 0) or 0)
            setattr(self, "_pending_llm_done_checks", done_checks)
            next_progress = int(
                getattr(self, "_pending_llm_next_progress", self._NLI_ASYNC_PROGRESS_STEP)
                or self._NLI_ASYNC_PROGRESS_STEP
            )
            if total_checks > 0:
                progress = int((done_checks * 100) / total_checks)
                if progress >= next_progress:
                    setattr(
                        self,
                        "_pending_llm_next_progress",
                        next_progress + self._NLI_ASYNC_PROGRESS_STEP,
                    )
            if self._tracker_has_strong_entailment(tracker):
                self._fact_log_info(
                    "LLM chunk early-stop strong entailment | "
                    f"fact_index={fact_index + 1} score>="
                    f"{self._NLI_STRONG_ENTAILMENT_THRESHOLD:.2f}"
                )
                fact_done[fact_index] = True
                setattr(self, "_pending_llm_fact_done", fact_done)
                remaining_chunks = max(0, len(units) - (chunk_index + 1))
                if remaining_chunks > 0:
                    adjusted_total = max(done_checks, total_checks - remaining_chunks)
                    setattr(self, "_pending_llm_total_checks", adjusted_total)
            setattr(self, "_pending_llm_fact_index", fact_index + 1)
            setattr(self, "_pending_llm_chunk_index", chunk_index)
        self._start_next_llm_chunk_verify_call()
        return

    if self._pending_fact_stage == "verify":
        if self._pending_fact_index < len(self._pending_fact_facts):
            fact = self._pending_fact_facts[self._pending_fact_index]
            record = parse_single_fact_verification(
                response,
                fact,
                self._pending_fact_index,
                self._pending_fact_sources,
            )
            self._fact_log_debug(
                "Verify parsed record\n"
                f"fact={fact}\n"
                f"record={record}"
            )
            self._pending_fact_results.append(record)
            self._pending_fact_index += 1
        self._start_next_fact_verify_call()
        return

    self._reset_fact_pipeline_state()

__all__ = [
    "_complete_fact_backend",
    "_finalize_fact_check",
    "_handle_fact_pipeline_complete",
]
