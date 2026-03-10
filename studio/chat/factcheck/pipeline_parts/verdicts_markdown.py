"""FactCheckPipelineMixin method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

@classmethod
def _extract_json_object(cls, raw: str) -> dict[str, object]:
    text = str(raw or "").strip()
    if not text:
        return {}
    fenced = cls._FENCED_JSON_RE.search(text)
    candidate = fenced.group(1).strip() if fenced else text
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    match = cls._JSON_OBJECT_RE.search(candidate)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}

def _parse_llm_chunk_verdict(
    self,
    response: str,
) -> tuple[str, float, str, str, str]:
    data = self._extract_json_object(response)
    decision_raw = str(
        data.get("decision", "")
        or data.get("label", "")
        or data.get("status", "")
        or data.get("class", "")
    ).strip().casefold()
    label = "neutral"
    if decision_raw in {"entailment", "belegt", "supported", "support", "ja", "yes"}:
        label = "entailment"
    elif decision_raw in {"teilweise", "partial", "partially"}:
        label = "entailment"
    elif decision_raw in {
        "contradiction", "widerspruch", "conflict", "refuted", "nein", "no"
    }:
        label = "contradiction"

    score_raw = data.get("confidence", data.get("score", data.get("probability", None)))
    score = 0.0
    try:
        score = float(score_raw) if score_raw is not None else 0.0
    except Exception:
        score = 0.0
    if not (0.0 <= score <= 1.0):
        score = 0.0
    if score <= 0.0:
        if label == "entailment":
            score = 0.45 if decision_raw in {"teilweise", "partial", "partially"} else 0.62
        elif label == "contradiction":
            score = 0.62
        else:
            score = 0.50

    numeric_check = str(
        data.get("numeric_check", "")
        or data.get("number_check", "")
        or data.get("numeric_relation", "")
    ).strip()
    evidence = str(
        data.get("evidence", "")
        or data.get("quote", "")
        or data.get("excerpt", "")
        or ""
    ).strip()
    reason = str(data.get("reason", "") or "").strip()
    if numeric_check:
        reason = (
            f"{reason}; numeric_check={numeric_check}"
            if reason else f"numeric_check={numeric_check}"
        )
    return label, max(0.0, min(1.0, float(score))), reason, evidence, numeric_check.casefold()

def _calibrate_llm_chunk_result(
    self,
    *,
    fact: str,
    chunk_text: str,
    label: str,
    score: float,
    reason: str,
    evidence_hint: str,
    numeric_check: str,
) -> tuple[str, float, str, str]:
    label_out = str(label or "neutral").strip().casefold() or "neutral"
    score_out = max(0.0, min(1.0, float(score)))
    evidence = str(evidence_hint or "").strip()
    reason_out = reason
    evidence_replaced = False

    # Hallucinated evidence must never be trusted for chunk-level verification.
    if evidence and not contains_text(chunk_text, evidence):
        reason_out = (
            f"{reason_out}; evidence_not_in_chunk_replaced"
            if reason_out else "evidence_not_in_chunk_replaced"
        )
        evidence = ""
        evidence_replaced = True
    if not evidence:
        evidence = select_evidence_snippet(fact, chunk_text, max_chars=260)

    overlap = token_overlap(fact, evidence or chunk_text)
    chunk_overlap = token_overlap(fact, chunk_text)

    if label_out == "entailment":
        # Prevent overconfident entailment on weak lexical grounding.
        score_out = min(score_out, 0.20 + 0.75 * overlap)
        if numeric_check == "conflict":
            label_out = "contradiction"
            score_out = max(score_out, 0.60)
            reason_out = (
                f"{reason_out}; numeric_conflict_overrides_entailment"
                if reason_out else "numeric_conflict_overrides_entailment"
            )
        elif overlap < 0.30:
            label_out = "neutral"
            score_out = min(score_out, 0.49)
            reason_out = (
                f"{reason_out}; low_overlap_downgraded_to_neutral"
                if reason_out else "low_overlap_downgraded_to_neutral"
            )
        elif overlap < 0.45:
            score_out = min(score_out, 0.72)
            reason_out = (
                f"{reason_out}; weak_overlap_confidence_capped"
                if reason_out else "weak_overlap_confidence_capped"
            )
        if evidence_replaced:
            if overlap < 0.55:
                label_out = "neutral"
                score_out = min(score_out, 0.49)
                reason_out = (
                    f"{reason_out}; hallucinated_evidence_downgraded"
                    if reason_out else "hallucinated_evidence_downgraded"
                )
            else:
                score_out = min(score_out, 0.58)
                reason_out = (
                    f"{reason_out}; hallucinated_evidence_confidence_capped"
                    if reason_out else "hallucinated_evidence_confidence_capped"
                )
    elif label_out == "contradiction":
        if numeric_check == "conflict":
            score_out = max(score_out, 0.65)
        else:
            score_out = min(score_out, 0.30 + 0.65 * max(overlap, chunk_overlap))
        if max(overlap, chunk_overlap) < 0.22 and numeric_check != "conflict":
            label_out = "neutral"
            score_out = min(score_out, 0.49)
            reason_out = (
                f"{reason_out}; low_overlap_contradiction_downgraded_to_neutral"
                if reason_out else "low_overlap_contradiction_downgraded_to_neutral"
            )
    else:
        score_out = min(score_out, 0.75)

    return (
        label_out,
        max(0.0, min(1.0, score_out)),
        reason_out,
        evidence,
    )

def _compose_factcheck_markdown_for_methods(self) -> str:
    method_results = dict(getattr(self, "_pending_fact_method_results", {}) or {})
    run_order = list(getattr(self, "_pending_fact_run_order", []) or [])

    def evidence_header_for_mode(mode: str) -> str:
        mode_norm = self._normalize_factcheck_mode(mode)
        if mode_norm == "llm_global":
            return self._LLM_GLOBAL_EVIDENCE_HEADER
        if mode_norm == "llm_claim_nli":
            return "Evidenz (extrahierter Chunk-Claim)"
        return "Evidenz"

    def reason_header_for_mode(mode: str) -> str:
        mode_norm = self._normalize_factcheck_mode(mode)
        if mode_norm in {"llm_chunk", "llm_global", "llm"}:
            return "Begründung"
        return ""

    if not method_results:
        return compose_fact_check_markdown(
            self._pending_fact_results,
            self._pending_fact_target_label,
        )
    if len(method_results) == 1:
        mode = run_order[0] if run_order else next(iter(method_results.keys()))
        label = self._FACTCHECK_MODE_LABELS.get(str(mode), str(mode))
        return compose_fact_check_markdown(
            method_results.get(mode, []),
            f"{self._pending_fact_target_label} | {label}",
            evidence_header=evidence_header_for_mode(str(mode)),
            reason_header=reason_header_for_mode(str(mode)),
        )

    def status_cell(row: dict[str, str] | None) -> str:
        if not isinstance(row, dict):
            return "—"
        status = str(row.get("status", "nicht_belegt") or "nicht_belegt").strip().casefold()
        icon = fact_status_icon(status)
        confidence_raw = row.get("confidence", "")
        confidence_text = ""
        if confidence_raw not in ("", None):
            try:
                conf = float(confidence_raw)
                conf = max(0.0, min(1.0, conf))
                confidence_text = f" ({conf:.2f})"
            except Exception:
                conf_txt = str(confidence_raw).strip()
                if conf_txt:
                    confidence_text = f" ({conf_txt})"
        return f"{icon} {status}{confidence_text}".strip()

    present_modes = [mode for mode in run_order if mode in method_results]
    if not present_modes:
        present_modes = list(method_results.keys())

    row_maps: dict[str, dict[str, dict[str, str]]] = {}
    ordered_keys: list[str] = []
    seen_keys: set[str] = set()
    for mode in present_modes:
        rows = list(method_results.get(mode, []) or [])
        local_map: dict[str, dict[str, str]] = {}
        for idx, row in enumerate(rows):
            row_dict = dict(row or {})
            key = str(row_dict.get("id", "") or "").strip() or f"C{idx + 1}"
            local_map[key] = row_dict
            if key not in seen_keys:
                seen_keys.add(key)
                ordered_keys.append(key)
        row_maps[mode] = local_map

    overview_lines: list[str] = []
    if ordered_keys and present_modes:
        header_cols = ["ID", "Fakt"]
        for idx, mode in enumerate(present_modes, 1):
            label = self._FACTCHECK_MODE_LABELS.get(str(mode), str(mode))
            header_cols.append(f"Status{idx}: {label}")
        overview_lines.append("### Übersicht")
        overview_lines.append("")
        overview_lines.append("| " + " | ".join(header_cols) + " |")
        overview_lines.append("|" + "|".join(["---"] * len(header_cols)) + "|")

        for key in ordered_keys:
            fact_text = ""
            for mode in present_modes:
                row = row_maps.get(mode, {}).get(key)
                if row:
                    fact_text = str(row.get("fact", "") or "").strip()
                    if fact_text:
                        break
            row_cells = [md_escape_cell(key), md_escape_cell(fact_text)]
            for mode in present_modes:
                cell = status_cell(row_maps.get(mode, {}).get(key))
                row_cells.append(md_escape_cell(cell))
            overview_lines.append("| " + " | ".join(row_cells) + " |")

        overview_lines.append("")

    sections: list[str] = [f"## Faktencheck ({self._pending_fact_target_label or 'Zieltext'})", ""]
    sections.extend(overview_lines)
    for mode in run_order:
        rows = list(method_results.get(mode, []) or [])
        label = self._FACTCHECK_MODE_LABELS.get(str(mode), str(mode))
        section = compose_fact_check_markdown(
            rows,
            f"{self._pending_fact_target_label} | {label}",
            evidence_header=evidence_header_for_mode(str(mode)),
            reason_header=reason_header_for_mode(str(mode)),
        )
        section_lines = section.splitlines()
        if section_lines and section_lines[0].startswith("## Faktencheck"):
            section_lines = section_lines[2:] if len(section_lines) >= 2 else []
        sections.append(f"### {label}")
        sections.extend(section_lines)
        sections.append("")
    return "\n".join(sections).strip()

__all__ = [
    "_extract_json_object",
    "_parse_llm_chunk_verdict",
    "_calibrate_llm_chunk_result",
    "_compose_factcheck_markdown_for_methods",
]
