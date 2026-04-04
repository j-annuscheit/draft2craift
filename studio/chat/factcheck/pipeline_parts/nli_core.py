"""FactCheckPipelineMixin method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _set_factcheck_async_busy(self, running: bool):
    setattr(self, "_factcheck_async_running", bool(running))
    apply_busy_state = getattr(self, "_apply_busy_state", None)
    if callable(apply_busy_state):
        try:
            apply_busy_state()
        except Exception:
            pass

def _supports_async_nli_verify(self) -> bool:
    return isinstance(self, QObject)

@staticmethod
def _new_nli_tracker() -> dict[str, object]:
    return {
        "best_label": "neutral",
        "best_score": 0.0,
        "best_source": "",
        "best_chunk": "",
        "best_reason": "",
        "best_entail_score": -1.0,
        "best_entail_source": "",
        "best_entail_chunk": "",
        "best_entail_reason": "",
        "best_contra_score": -1.0,
        "best_contra_source": "",
        "best_contra_chunk": "",
        "best_contra_reason": "",
    }

@staticmethod
def _normalize_nli_result_payload(nli: dict[str, object]) -> tuple[str, float, str, str]:
    label = str(nli.get("label", "neutral") or "neutral").strip().casefold()
    score = float(nli.get("score", 0.0) or 0.0)
    score = max(0.0, min(1.0, score))
    reason = str(nli.get("reason", "") or "").strip()
    evidence_raw = str(nli.get("evidence", "") or "").strip()
    return label, score, reason, evidence_raw

@staticmethod
def _build_chunk_nli_units(
    source_chunks: list[tuple[str, str]],
) -> list[dict[str, str]]:
    units: list[dict[str, str]] = []
    for source_name, chunk_text in source_chunks:
        clean_source = str(source_name or "").strip()
        clean_chunk = str(chunk_text or "").strip()
        if not clean_source or not clean_chunk:
            continue
        units.append(
            {
                "source": clean_source,
                "premise": clean_chunk,
                "evidence": clean_chunk,
                "mode": "chunk",
            }
        )
    return units

@classmethod
def _build_sentence_nli_units(
    cls,
    source_chunks: list[tuple[str, str]],
) -> list[dict[str, str]]:
    units: list[dict[str, str]] = []
    seen: set[str] = set()
    for source_name, chunk_text in source_chunks:
        clean_source = str(source_name or "").strip()
        clean_chunk = str(chunk_text or "").strip()
        if not clean_source or not clean_chunk:
            continue
        for sentence in split_sentences_for_facts(clean_chunk):
            sent = cls._collapse_ws(sentence)
            if len(sent) < 12:
                continue
            key = f"{clean_source}\n{sent.casefold()}"
            if key in seen:
                continue
            seen.add(key)
            units.append(
                {
                    "source": clean_source,
                    "premise": sent,
                    "evidence": clean_chunk,
                    "mode": "sentence",
                }
            )
    return units

@staticmethod
def _tracker_has_entailment(tracker: dict[str, object]) -> bool:
    best_entail_score = float(tracker.get("best_entail_score", -1.0) or -1.0)
    best_entail_source = str(tracker.get("best_entail_source", "") or "")
    return best_entail_score >= 0.0 and bool(best_entail_source)

def _tracker_has_strong_entailment(self, tracker: dict[str, object]) -> bool:
    best_entail_score = float(tracker.get("best_entail_score", -1.0) or -1.0)
    best_entail_source = str(tracker.get("best_entail_source", "") or "")
    return (
        best_entail_score >= float(self._NLI_STRONG_ENTAILMENT_THRESHOLD)
        and bool(best_entail_source)
    )

def _update_nli_tracker(
    self,
    tracker: dict[str, object],
    *,
    label: str,
    score: float,
    source_name: str,
    evidence_text: str,
    reason: str,
):
    best_score = float(tracker.get("best_score", 0.0) or 0.0)
    if score > best_score:
        tracker["best_label"] = label
        tracker["best_score"] = score
        tracker["best_source"] = source_name
        tracker["best_chunk"] = evidence_text
        tracker["best_reason"] = reason

    best_entail_score = float(tracker.get("best_entail_score", -1.0) or -1.0)
    if label == "entailment" and score > best_entail_score:
        tracker["best_entail_score"] = score
        tracker["best_entail_source"] = source_name
        tracker["best_entail_chunk"] = evidence_text
        tracker["best_entail_reason"] = reason

    best_contra_score = float(tracker.get("best_contra_score", -1.0) or -1.0)
    if label == "contradiction" and score > best_contra_score:
        tracker["best_contra_score"] = score
        tracker["best_contra_source"] = source_name
        tracker["best_contra_chunk"] = evidence_text
        tracker["best_contra_reason"] = reason

def _verify_fact_against_nli_units(
    self,
    *,
    fact: str,
    units: list[dict[str, str]],
    tracker: dict[str, object],
    pass_mode: str,
) -> str:
    for unit in units:
        source_name = str(unit.get("source", "") or "").strip()
        premise_text = str(unit.get("premise", "") or "").strip()
        evidence_text = str(unit.get("evidence", "") or "").strip()
        if not source_name or not premise_text:
            continue
        nli = self.llm.verify_nli_sync(premise_text, fact)
        label, score, reason, evidence_raw = self._normalize_nli_result_payload(nli)
        reason_low = reason.casefold()
        if (
            reason_low.startswith("nli_runtime_error")
            or reason_low.startswith("nli_backend_unavailable")
            or reason_low.startswith("nli_model_missing")
        ):
            self._fact_log_info(
                "NLI runtime error; "
                f"source={source_name} reason={reason}"
            )
            return (
                "Das geladene NLI-Modell konnte nicht inferieren. "
                f"Quelle: {source_name}. Detail: {reason or 'n/a'}"
            )
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
        if self._tracker_has_strong_entailment(tracker):
            self._fact_log_info(
                "NLI early-stop strong entailment | "
                f"pass={pass_mode} fact={fact} score>="
                f"{self._NLI_STRONG_ENTAILMENT_THRESHOLD:.2f}"
            )
            break
    return ""

def _build_nli_result_row(
    self,
    fact_index: int,
    fact: str,
    tracker: dict[str, object],
    *,
    method: str = "nli",
) -> dict[str, str]:
    method_norm = self._normalize_factcheck_mode(method) or "nli"
    is_llm_chunk = method_norm in {"llm_chunk", "llm"}
    is_claim_nli = method_norm == "llm_claim_nli"
    if is_llm_chunk:
        entail_prefix = "LLM-chunk entailment score="
        entail_low_prefix = "LLM-chunk entailment score niedrig="
        contradiction_prefix = "LLM-chunk contradiction score="
        pass_desc = "Chunk-Pass"
    elif is_claim_nli:
        entail_prefix = "Claim-NLI entailment score="
        entail_low_prefix = "Claim-NLI entailment score niedrig="
        contradiction_prefix = "Claim-NLI contradiction score="
        pass_desc = "Claim-Pass über extrahierte Chunk-Claims"
    else:
        entail_prefix = "NLI entailment score="
        entail_low_prefix = "NLI entailment score niedrig="
        contradiction_prefix = "NLI contradiction score="
        pass_desc = "Chunk- und Satz-Pass"
    best_label = str(tracker.get("best_label", "neutral") or "neutral")
    best_score = float(tracker.get("best_score", 0.0) or 0.0)
    best_source = str(tracker.get("best_source", "") or "")
    best_chunk = str(tracker.get("best_chunk", "") or "")
    best_reason = str(tracker.get("best_reason", "") or "")
    best_entail_score = float(tracker.get("best_entail_score", -1.0) or -1.0)
    best_entail_source = str(tracker.get("best_entail_source", "") or "")
    best_entail_chunk = str(tracker.get("best_entail_chunk", "") or "")
    best_entail_reason = str(tracker.get("best_entail_reason", "") or "")
    best_contra_score = float(tracker.get("best_contra_score", -1.0) or -1.0)
    best_contra_source = str(tracker.get("best_contra_source", "") or "")
    best_contra_chunk = str(tracker.get("best_contra_chunk", "") or "")
    best_contra_reason = str(tracker.get("best_contra_reason", "") or "")

    # Rule: always prefer the strongest entailment over all chunks.
    if best_entail_score >= 0.0 and best_entail_source:
        status = (
            "belegt"
            if best_entail_score >= self._NLI_ENTAILMENT_GREEN_THRESHOLD
            else "teilweise"
        )
        reason_prefix = (
            entail_prefix
            if status == "belegt"
            else entail_low_prefix
        )
        return {
            "id": f"C{fact_index + 1}",
            "status": status,
            "fact": fact,
            "sources": best_entail_source,
            "evidence": best_entail_chunk,
            "confidence": f"{best_entail_score:.4f}",
            "reason": (
                f"{reason_prefix}{best_entail_score:.2f}"
                + (
                    f" ({best_entail_reason})"
                    if best_entail_reason
                    else ""
                )
            ),
        }

    # Only when no entailment exists, return the strongest contradiction.
    if best_contra_score >= 0.0 and best_contra_source:
        return {
            "id": f"C{fact_index + 1}",
            "status": "widerspruch",
            "fact": fact,
            "sources": best_contra_source,
            "evidence": best_contra_chunk,
            "confidence": f"{best_contra_score:.4f}",
            "reason": (
                f"{contradiction_prefix}{best_contra_score:.2f}"
                + (
                    f" ({best_contra_reason})"
                    if best_contra_reason
                    else ""
                )
            ),
        }

    if best_score > 0.0 and best_source:
        return {
            "id": f"C{fact_index + 1}",
            "status": "nicht_belegt",
            "fact": fact,
            "sources": best_source,
            "evidence": "",
            "confidence": f"{best_score:.4f}",
            "reason": (
                f"Kein Entailment in {pass_desc}; bester Treffer="
                f"{best_label} ({best_score:.2f})"
                + (f" ({best_reason})" if best_reason else "")
            ),
        }

    return {
        "id": f"C{fact_index + 1}",
        "status": "nicht_belegt",
        "fact": fact,
        "sources": "",
        "evidence": "",
        "confidence": "0.0000",
        "reason": "Kein passender Chunk gefunden",
    }

def _verify_facts_with_nli(
    self,
    facts: list[str],
    source_chunks: list[tuple[str, str]],
) -> list[dict[str, str]]:
    chunk_units = self._build_chunk_nli_units(source_chunks)
    sentence_units = self._build_sentence_nli_units(source_chunks)
    return self._verify_facts_with_nli_units(
        facts=facts,
        chunk_units=chunk_units,
        sentence_units=sentence_units,
        method="nli",
    )

def _verify_facts_with_nli_units(
    self,
    *,
    facts: list[str],
    chunk_units: list[dict[str, str]],
    sentence_units: list[dict[str, str]] | None = None,
    method: str = "nli",
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    runtime_error = ""
    sentence_units = list(sentence_units or [])

    for fact_index, fact in enumerate(facts):
        tracker = self._new_nli_tracker()
        runtime_error = self._verify_fact_against_nli_units(
            fact=fact,
            units=chunk_units,
            tracker=tracker,
            pass_mode="chunk",
        )
        if runtime_error:
            break
        if (not self._tracker_has_entailment(tracker)) and sentence_units:
            self._fact_log_info(
                f"NLI sentence-pass fallback | fact_index={fact_index + 1}"
            )
            runtime_error = self._verify_fact_against_nli_units(
                fact=fact,
                units=sentence_units,
                tracker=tracker,
                pass_mode="sentence",
            )
            if runtime_error:
                break

        results.append(
            self._build_nli_result_row(fact_index, fact, tracker, method=method)
        )

    setattr(self, "_pending_nli_runtime_error", runtime_error)
    return results

__all__ = [
    "_set_factcheck_async_busy",
    "_supports_async_nli_verify",
    "_new_nli_tracker",
    "_normalize_nli_result_payload",
    "_build_chunk_nli_units",
    "_build_sentence_nli_units",
    "_tracker_has_entailment",
    "_tracker_has_strong_entailment",
    "_update_nli_tracker",
    "_verify_fact_against_nli_units",
    "_build_nli_result_row",
    "_verify_facts_with_nli",
    "_verify_facts_with_nli_units",
]
