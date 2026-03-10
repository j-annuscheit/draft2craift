"""Run-type specific parsers for Test Studio run summary files."""
from __future__ import annotations

import json
import pathlib
from typing import Any

from test_studio.components.run_parser_common import (
    build_run,
    load_case_entry,
    load_pdf_cases,
    normalise_labels,
    safe_bool,
    safe_float,
    safe_int,
)
from test_studio.models import CaseEntry, RunEntry


def _load_rag(path: pathlib.Path, payload: dict[str, Any]) -> RunEntry | None:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return None

    macro = summary.get("macro") if isinstance(summary.get("macro"), dict) else {}
    micro = summary.get("micro") if isinstance(summary.get("micro"), dict) else {}
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases = [load_case_entry(raw) for raw in raw_cases if isinstance(raw, dict)]
    cases_count = int(summary.get("cases", len(cases)) or 0)
    failures = sum(1 for case in cases if case.failed)

    return build_run(
        run_type="rag",
        path=path,
        payload=payload,
        cases=cases,
        cases_count=cases_count,
        micro_f1=safe_float(micro.get("f1")),
        macro_f1=safe_float(macro.get("f1")),
        hit_at_k=safe_float(macro.get("hit_at_k")),
        map_value=safe_float(macro.get("map")),
        mrr=safe_float(macro.get("mrr")),
        ndcg=safe_float(macro.get("ndcg")),
        failures=failures,
    )


def _load_pdf(path: pathlib.Path, payload: dict[str, Any]) -> RunEntry:
    macro = payload.get("macro") if isinstance(payload.get("macro"), dict) else {}
    cases = load_pdf_cases(path.with_name(path.name.replace(".summary.json", ".cases.csv")))
    cases_count = safe_int(payload.get("cases"), len(cases)) or len(cases)
    failures = safe_int(payload.get("failed"), sum(1 for case in cases if case.failed))

    return build_run(
        run_type="pdf",
        path=path,
        payload=payload,
        cases=cases,
        cases_count=cases_count,
        micro_f1=safe_float(macro.get("token_f1")),
        macro_f1=safe_float(macro.get("token_f1")),
        hit_at_k=safe_float(macro.get("paragraph_mean")),
        map_value=safe_float(macro.get("line_ratio")),
        mrr=safe_float(macro.get("char_ratio")),
        ndcg=safe_float(payload.get("pass_rate")),
        failures=failures,
    )


def _load_glossary(path: pathlib.Path, payload: dict[str, Any]) -> RunEntry:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    macro = summary.get("macro") if isinstance(summary.get("macro"), dict) else {}
    micro = summary.get("micro") if isinstance(summary.get("micro"), dict) else {}
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases = [load_case_entry(raw) for raw in raw_cases if isinstance(raw, dict)]
    cases_count = safe_int(summary.get("cases"), len(cases)) or len(cases)
    failures = safe_int(summary.get("failed"), sum(1 for case in cases if case.failed))

    return build_run(
        run_type="glossary",
        path=path,
        payload=payload,
        cases=cases,
        cases_count=cases_count,
        micro_f1=safe_float(micro.get("f1")),
        macro_f1=safe_float(macro.get("f1")),
        hit_at_k=safe_float(macro.get("recall")),
        map_value=safe_float(macro.get("precision")),
        mrr=safe_float(summary.get("pass_rate")),
        ndcg=safe_float(macro.get("hit_at_k")),
        failures=failures,
    )


def _load_factcheck(path: pathlib.Path, payload: dict[str, Any]) -> RunEntry:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    macro = summary.get("macro") if isinstance(summary.get("macro"), dict) else {}
    micro = summary.get("micro") if isinstance(summary.get("micro"), dict) else {}
    steps = summary.get("steps") if isinstance(summary.get("steps"), dict) else {}
    extract = steps.get("extract") if isinstance(steps.get("extract"), dict) else {}
    extract_macro = extract.get("macro") if isinstance(extract.get("macro"), dict) else {}
    verify = steps.get("verify") if isinstance(steps.get("verify"), dict) else {}
    verify_macro = verify.get("macro") if isinstance(verify.get("macro"), dict) else {}
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases = [load_case_entry(raw) for raw in raw_cases if isinstance(raw, dict)]
    cases_count = safe_int(summary.get("cases"), len(cases)) or len(cases)
    failures = safe_int(summary.get("failed"), sum(1 for case in cases if case.failed))

    return build_run(
        run_type="factcheck",
        path=path,
        payload=payload,
        cases=cases,
        cases_count=cases_count,
        micro_f1=safe_float(micro.get("f1")),
        macro_f1=safe_float(macro.get("f1")),
        hit_at_k=safe_float(extract_macro.get("f1")),
        map_value=safe_float(verify_macro.get("status_accuracy")),
        mrr=safe_float(summary.get("pass_rate")),
        ndcg=safe_float(macro.get("recall")),
        failures=failures,
    )


def _load_judge(path: pathlib.Path, payload: dict[str, Any]) -> RunEntry:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases: list[CaseEntry] = []

    for raw in raw_cases:
        if not isinstance(raw, dict):
            continue
        correct = safe_bool(raw.get("correct"), False)
        parsed = safe_bool(raw.get("parsed"), False)
        predicted = str(raw.get("predicted_winner", "")).strip()
        parse_mode = str(raw.get("parse_mode", "")).strip()
        reasons = raw.get("fail_reasons") if isinstance(raw.get("fail_reasons"), list) else []
        observed = [predicted or "unparsed"]
        if parse_mode:
            observed.append(f"mode={parse_mode}")
        fail_parts = [str(item).strip() for item in reasons if str(item).strip()]
        if fail_parts:
            observed.append(f"fail={', '.join(fail_parts)}")

        score = 1.0 if correct else 0.0
        expected = str(raw.get("expected_winner", "")).strip()
        cases.append(
            CaseEntry(
                case_id=str(raw.get("case_id", "")),
                query=str(raw.get("reason") or raw.get("raw_preview") or "").strip(),
                labels=normalise_labels(raw.get("labels", [])),
                f1=score,
                precision=score,
                recall=score,
                hit_at_k=(1.0 if parsed else 0.0),
                expected_docs=[expected] if expected else [],
                predicted_docs=observed,
                failed=(not correct),
            )
        )

    cases_count = safe_int(summary.get("cases"), len(cases)) or len(cases)
    failures = safe_int(summary.get("incorrect"), sum(1 for case in cases if case.failed))
    accuracy = safe_float(summary.get("accuracy"))
    return build_run(
        run_type="judge",
        path=path,
        payload=payload,
        cases=cases,
        cases_count=cases_count,
        micro_f1=accuracy,
        macro_f1=accuracy,
        hit_at_k=safe_float(summary.get("parsed_rate")),
        map_value=safe_float(summary.get("avg_confidence")),
        mrr=safe_float(summary.get("threshold_accuracy")),
        ndcg=(1.0 if safe_bool(summary.get("passed"), False) else 0.0),
        failures=failures,
    )


def _load_llmcompare(path: pathlib.Path, payload: dict[str, Any]) -> RunEntry:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    cfg_a = config.get("candidate_a") if isinstance(config.get("candidate_a"), dict) else {}
    cfg_b = config.get("candidate_b") if isinstance(config.get("candidate_b"), dict) else {}
    label_a = str(cfg_a.get("label", "A")).strip() or "A"
    label_b = str(cfg_b.get("label", "B")).strip() or "B"

    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases: list[CaseEntry] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            continue
        preferred = str(raw.get("preferred_setting", "")).strip().casefold()
        parsed = safe_bool(raw.get("parsed"), False)
        preferred_label = str(raw.get("preferred_label", "")).strip()
        if not preferred_label:
            preferred_label = label_a if preferred == "a" else label_b if preferred == "b" else "undecided"

        observed = [f"preferred={preferred_label}"]
        judge_winner = str(raw.get("judge_winner", "")).strip()
        parse_mode = str(raw.get("parse_mode", "")).strip()
        if judge_winner:
            observed.append(f"judge={judge_winner}")
        if parse_mode:
            observed.append(f"mode={parse_mode}")

        if preferred == "a":
            f1, precision = 1.0, 0.0
        elif preferred == "b":
            f1, precision = 0.0, 1.0
        else:
            f1, precision = 0.0, 0.0

        reason = str(raw.get("reason") or "").strip()
        preview = str(raw.get("prompt_preview") or "").strip()
        query = f"{preview} | reason={reason}" if reason else preview
        cases.append(
            CaseEntry(
                case_id=str(raw.get("case_id", "")),
                query=query,
                labels=normalise_labels(raw.get("labels", [])),
                f1=f1,
                precision=precision,
                recall=(1.0 if preferred in {"a", "b"} else 0.0),
                hit_at_k=(1.0 if parsed else 0.0),
                expected_docs=[f"A={label_a}", f"B={label_b}"],
                predicted_docs=observed,
                failed=(preferred not in {"a", "b"}),
            )
        )

    cases_count = safe_int(summary.get("cases"), len(cases)) or len(cases)
    failures = safe_int(summary.get("undecided"), sum(1 for case in cases if case.failed))
    return build_run(
        run_type="llmcompare",
        path=path,
        payload=payload,
        cases=cases,
        cases_count=cases_count,
        micro_f1=safe_float(summary.get("preference_b_rate")),
        macro_f1=safe_float(summary.get("preference_a_rate")),
        hit_at_k=safe_float(summary.get("parsed_rate")),
        map_value=safe_float(summary.get("avg_confidence")),
        mrr=safe_float(summary.get("win_gap")),
        ndcg=safe_float(summary.get("undecided_rate")),
        failures=failures,
    )


def load_run_entry(path: pathlib.Path) -> RunEntry | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    eval_type = str(payload.get("evaluation_type", "")).strip().casefold()
    if eval_type == "factcheck":
        return _load_factcheck(path, payload)
    if eval_type == "glossary":
        return _load_glossary(path, payload)
    if eval_type == "judge_pairwise":
        return _load_judge(path, payload)
    if eval_type == "llm_compare_judge":
        return _load_llmcompare(path, payload)
    if isinstance(payload.get("summary"), dict):
        return _load_rag(path, payload)
    if isinstance(payload.get("macro"), dict) and "pass_rate" in payload:
        return _load_pdf(path, payload)
    return None
