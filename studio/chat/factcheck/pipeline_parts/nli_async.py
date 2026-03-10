"""FactCheckPipelineMixin method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _start_nli_verify_async(
    self,
    facts: list[str],
    source_chunks: list[tuple[str, str]],
    *,
    mode: str = "nli",
    chunk_units: list[dict[str, str]] | None = None,
    sentence_units: list[dict[str, str]] | None = None,
):
    if chunk_units is None:
        chunk_units = self._build_chunk_nli_units(source_chunks)
    if sentence_units is None:
        sentence_units = self._build_sentence_nli_units(source_chunks)
    mode_norm = self._normalize_factcheck_mode(mode) or "nli"
    if not facts or not chunk_units:
        self._pending_fact_results = []
        self._complete_fact_backend(mode_norm, [])
        return
    self._pending_fact_stage = "verify_nli"
    setattr(self, "_pending_nli_runtime_error", "")
    setattr(self, "_pending_nli_async_active", True)
    setattr(self, "_pending_nli_result_mode", mode_norm)
    setattr(self, "_pending_nli_chunk_units", chunk_units)
    setattr(self, "_pending_nli_sentence_units", sentence_units)
    setattr(self, "_pending_nli_fact_index", 0)
    setattr(self, "_pending_nli_pass_mode", "chunk")
    setattr(self, "_pending_nli_unit_index", 0)
    setattr(self, "_pending_nli_tracker", self._new_nli_tracker())
    total_checks = len(facts) * len(chunk_units)
    setattr(self, "_pending_nli_total_checks", max(0, int(total_checks)))
    setattr(self, "_pending_nli_done_checks", 0)
    setattr(self, "_pending_nli_next_progress", self._NLI_ASYNC_PROGRESS_STEP)
    self._set_factcheck_async_busy(True)
    self._schedule_nli_verify_tick()

def _schedule_nli_verify_tick(self):
    if not bool(getattr(self, "_pending_nli_async_active", False)):
        return
    QTimer.singleShot(0, self._run_nli_verify_tick)

def _run_nli_verify_tick(self):
    if (
        not self._pending_fact_check
        or self._pending_fact_stage != "verify_nli"
        or not bool(getattr(self, "_pending_nli_async_active", False))
    ):
        return

    facts = list(getattr(self, "_pending_fact_facts", []) or [])
    chunk_units = list(getattr(self, "_pending_nli_chunk_units", []) or [])
    sentence_units = list(getattr(self, "_pending_nli_sentence_units", []) or [])
    result_mode = self._normalize_factcheck_mode(
        str(getattr(self, "_pending_nli_result_mode", "nli") or "nli")
    ) or "nli"
    if not facts or not chunk_units:
        self._set_factcheck_async_busy(False)
        self._complete_fact_backend(result_mode, [])
        return

    fact_index = int(getattr(self, "_pending_nli_fact_index", 0) or 0)
    pass_mode = str(getattr(self, "_pending_nli_pass_mode", "chunk") or "chunk")
    unit_index = int(getattr(self, "_pending_nli_unit_index", 0) or 0)
    done_checks = int(getattr(self, "_pending_nli_done_checks", 0) or 0)
    tracker = dict(getattr(self, "_pending_nli_tracker", {}) or self._new_nli_tracker())
    total_checks = int(getattr(self, "_pending_nli_total_checks", 0) or 0)
    runtime_error = ""

    checks_done_in_slice = 0
    deadline = time.monotonic() + float(self._NLI_ASYNC_SLICE_BUDGET_SEC)
    max_checks = max(1, int(self._NLI_ASYNC_MAX_CHECKS_PER_SLICE))

    while (
        checks_done_in_slice < max_checks
        and time.monotonic() <= deadline
        and fact_index < len(facts)
    ):
        fact = facts[fact_index]
        units = chunk_units if pass_mode == "chunk" else sentence_units
        if not units:
            if pass_mode == "chunk":
                break
            self._pending_fact_results.append(
                self._build_nli_result_row(
                    fact_index,
                    fact,
                    tracker,
                    method=result_mode,
                )
            )
            fact_index += 1
            pass_mode = "chunk"
            unit_index = 0
            tracker = self._new_nli_tracker()
            continue

        unit = units[unit_index]
        source_name = str(unit.get("source", "") or "").strip()
        premise_text = str(unit.get("premise", "") or "").strip()
        evidence_text = str(unit.get("evidence", "") or "").strip()
        if not source_name or not premise_text:
            unit_index += 1
            if unit_index >= len(units):
                if pass_mode == "chunk" and (not self._tracker_has_entailment(tracker)) and sentence_units:
                    pass_mode = "sentence"
                    unit_index = 0
                    setattr(self, "_pending_nli_total_checks", total_checks + len(sentence_units))
                    total_checks += len(sentence_units)
                else:
                    self._pending_fact_results.append(
                        self._build_nli_result_row(
                            fact_index,
                            fact,
                            tracker,
                            method=result_mode,
                        )
                    )
                    fact_index += 1
                    pass_mode = "chunk"
                    unit_index = 0
                    tracker = self._new_nli_tracker()
            continue

        nli = self.llm.verify_nli_sync(premise_text, fact)
        label, score, reason, evidence_raw = self._normalize_nli_result_payload(nli)
        reason_low = reason.casefold()
        if (
            reason_low.startswith("nli_runtime_error")
            or reason_low.startswith("nli_backend_unavailable")
            or reason_low.startswith("nli_model_missing")
        ):
            runtime_error = (
                "Das geladene NLI-Transformers-Modell konnte nicht inferieren. "
                f"Quelle: {source_name}. Detail: {reason or 'n/a'}"
            )
            self._fact_log_info(
                "NLI runtime error; "
                f"source={source_name} reason={reason}"
            )
            break

        self._fact_log_debug(
            "NLI check\n"
            f"pass={pass_mode}\n"
            f"fact={fact}\n"
            f"source={source_name}\n"
            f"premise={premise_text}\n"
            f"evidence={evidence_text}\n"
            f"result_label={label}\n"
            f"result_score={score:.4f}\n"
            f"result_reason={reason}\n"
            f"result_evidence={evidence_raw}"
        )
        self._update_nli_tracker(
            tracker,
            label=label,
            score=score,
            source_name=source_name,
            evidence_text=(evidence_text or premise_text),
            reason=reason,
        )

        done_checks += 1
        checks_done_in_slice += 1
        unit_index += 1

        next_progress = int(
            getattr(
                self,
                "_pending_nli_next_progress",
                self._NLI_ASYNC_PROGRESS_STEP,
            )
            or self._NLI_ASYNC_PROGRESS_STEP
        )
        if total_checks > 0:
            progress = int((done_checks * 100) / total_checks)
            if progress >= next_progress:
                setattr(
                    self,
                    "_pending_nli_next_progress",
                    next_progress + self._NLI_ASYNC_PROGRESS_STEP,
                )

        if self._tracker_has_strong_entailment(tracker):
            self._fact_log_info(
                "NLI async early-stop strong entailment | "
                f"pass={pass_mode} fact_index={fact_index + 1} score>="
                f"{self._NLI_STRONG_ENTAILMENT_THRESHOLD:.2f}"
            )
            unit_index = len(units)

        if unit_index >= len(units):
            if pass_mode == "chunk" and (not self._tracker_has_entailment(tracker)) and sentence_units:
                self._fact_log_info(
                    f"NLI sentence-pass fallback | fact_index={fact_index + 1}"
                )
                pass_mode = "sentence"
                unit_index = 0
                setattr(self, "_pending_nli_total_checks", total_checks + len(sentence_units))
                total_checks += len(sentence_units)
            else:
                self._pending_fact_results.append(
                    self._build_nli_result_row(
                        fact_index,
                        fact,
                        tracker,
                        method=result_mode,
                    )
                )
                fact_index += 1
                pass_mode = "chunk"
                unit_index = 0
                tracker = self._new_nli_tracker()

    setattr(self, "_pending_nli_fact_index", fact_index)
    setattr(self, "_pending_nli_pass_mode", pass_mode)
    setattr(self, "_pending_nli_unit_index", unit_index)
    setattr(self, "_pending_nli_done_checks", done_checks)
    setattr(self, "_pending_nli_tracker", tracker)

    if runtime_error:
        setattr(self, "_pending_nli_runtime_error", runtime_error)
        setattr(self, "_pending_nli_async_active", False)
        self._set_factcheck_async_busy(False)
        self.history.add_message(
            "system",
            f"⚠ NLI-Model-Fehler: {runtime_error}",
        )
        self._complete_fact_backend(result_mode, [])
        return

    if fact_index >= len(facts):
        setattr(self, "_pending_nli_async_active", False)
        self._set_factcheck_async_busy(False)
        self._complete_fact_backend(result_mode, list(self._pending_fact_results))
        return

    self._schedule_nli_verify_tick()

__all__ = [
    "_start_nli_verify_async",
    "_schedule_nli_verify_tick",
    "_run_nli_verify_tick",
]
