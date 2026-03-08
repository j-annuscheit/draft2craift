#!/usr/bin/env python3
"""
Fact-check evaluation runner.

Implements three test stages per case:
1) extract: claim/fact extraction compared against GT facts.
2) verify: status classification with GT facts provided.
3) full: end-to-end pipeline (extract -> verify) vs GT verdicts.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import difflib
import json
import logging
import os
import pathlib
import re
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Ensure project root is importable when script is launched from any cwd.
_THIS_FILE = pathlib.Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from features.chat.factcheck_utils import (  # noqa: E402
    contains_text,
    norm_source_name,
    parse_fact_candidates,
    parse_factcheck_rows,
    parse_single_fact_verification,
    split_sentences_for_facts,
    suggest_fact_limit,
    token_overlap,
)
from services.llm.manager import LLMManager  # noqa: E402


@dataclass
class SourceSpec:
    name: str
    path: pathlib.Path


@dataclass
class GTVerdict:
    fact: str
    status: str
    source: str


@dataclass
class CaseSpec:
    case_id: str
    labels: list[str]
    target_path: pathlib.Path
    gt_facts_path: pathlib.Path
    gt_verdicts_path: pathlib.Path
    sources: list[SourceSpec]
    threshold_extract_recall: float
    threshold_verify_status: float
    threshold_full_f1: float
    source_max_chars: int
    target_max_chars: int
    max_verify_facts: int
    mode: str


@dataclass
class CaseResult:
    case_id: str
    labels: list[str]
    target_path: str
    duration_ms: float
    expected_facts: int
    extracted_facts: int
    extracted_matched: int
    extract_precision: float
    extract_recall: float
    extract_f1: float
    verify_status_accuracy: float
    verify_source_accuracy: float
    full_precision: float
    full_recall: float
    full_f1: float
    full_correct_status: int
    full_predicted: int
    full_expected: int
    mode: str
    passed: bool
    fail_reasons: list[str]
    expected_preview: list[str]
    observed_preview: list[str]


class EvalLoggerBridge:
    """Adapter matching AppLogger-like API (info/debug/warning/error)."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def debug(self, category: str, message: str):
        self._logger.debug("[%s] %s", category, message)

    def info(self, category: str, message: str):
        self._logger.info("[%s] %s", category, message)

    def warning(self, category: str, message: str):
        self._logger.warning("[%s] %s", category, message)

    def error(self, category: str, message: str):
        self._logger.error("[%s] %s", category, message)


def setup_logger(
    output_dir: pathlib.Path,
    run_name: str,
    level: str,
) -> logging.Logger:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"factcheck_eval.{run_name}")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(
        output_dir / f"{run_name}.log",
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)
    return logger


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in suite: {path}")
    return data


def _read_text(path: pathlib.Path) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _write_json(path: pathlib.Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _write_text(path: pathlib.Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _normalise_labels(raw: Any) -> list[str]:
    if raw is None:
        return []
    labels: list[str] = []
    if isinstance(raw, str):
        labels = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        labels = [str(item).strip() for item in raw]
    else:
        raise ValueError("labels must be string or list[str]")
    out: list[str] = []
    seen: set[str] = set()
    for label in labels:
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def _normalise_status(text: str) -> str:
    raw = str(text or "").strip().casefold()
    if raw in {"belegt", "supported", "ja", "yes"}:
        return "belegt"
    if raw in {"teilweise", "partially", "partial"}:
        return "teilweise"
    if raw in {"widerspruch", "contradiction", "conflict"}:
        return "widerspruch"
    return "nicht_belegt"


def _resolve_path(raw: str, suite_dir: pathlib.Path) -> pathlib.Path:
    p = pathlib.Path(str(raw))
    if p.is_absolute():
        return p
    return (suite_dir / p).resolve()


def _clean_fact(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"\s+", " ", value).strip(" -\t")
    return value


def _read_gt_facts_markdown(path: pathlib.Path) -> list[str]:
    text = _read_text(path)
    table_rows = parse_factcheck_rows(text)
    if table_rows:
        out: list[str] = []
        seen: set[str] = set()
        for row in table_rows:
            fact = _clean_fact(str(row.get("fact", "")))
            if len(fact) < 6:
                continue
            key = fact.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(fact)
        if out:
            return out

    out = []
    seen = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = re.match(r"^\s*(?:[-*•]+|\d+[.)])\s+(.*)$", stripped)
        if not m:
            continue
        fact = _clean_fact(m.group(1))
        if len(fact) < 6:
            continue
        key = fact.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(fact)
    if out:
        return out

    out = []
    seen = set()
    for sent in split_sentences_for_facts(text):
        fact = _clean_fact(sent)
        if len(fact) < 12:
            continue
        key = fact.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(fact)
    return out


def _read_gt_verdicts_markdown(path: pathlib.Path) -> list[GTVerdict]:
    text = _read_text(path)
    rows = parse_factcheck_rows(text)
    if rows:
        out: list[GTVerdict] = []
        for row in rows:
            fact = _clean_fact(str(row.get("fact", "")))
            if len(fact) < 6:
                continue
            out.append(
                GTVerdict(
                    fact=fact,
                    status=_normalise_status(str(row.get("status", ""))),
                    source=_clean_fact(str(row.get("sources", ""))),
                )
            )
        if out:
            return out

    out = []
    line_re = re.compile(
        r"^\s*(?:[-*•]+|\d+[.)])\s*"
        r"(?:\[(?P<status>[^\]]+)\]\s*)?"
        r"(?P<fact>.+?)"
        r"(?:\s*\|\s*(?:source|quelle)\s*:\s*(?P<source>.+))?$",
        flags=re.IGNORECASE,
    )
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = line_re.match(stripped)
        if not match:
            continue
        fact = _clean_fact(match.group("fact") or "")
        if len(fact) < 6:
            continue
        status = _normalise_status(match.group("status") or "")
        source = _clean_fact(match.group("source") or "")
        out.append(GTVerdict(fact=fact, status=status, source=source))
    return out


def _parse_kv_override(item: str) -> tuple[str, Any]:
    if "=" not in item:
        raise ValueError(f"Invalid --set entry '{item}', expected key=value")
    key, raw = item.split("=", 1)
    key = key.strip()
    raw = raw.strip()
    low = raw.casefold()
    if low in {"true", "false"}:
        return key, (low == "true")
    try:
        if "." in raw:
            return key, float(raw)
        return key, int(raw)
    except ValueError:
        return key, raw


def _fact_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if contains_text(a, b) or contains_text(b, a):
        return 1.0
    overlap = token_overlap(a, b)
    ratio = difflib.SequenceMatcher(
        None,
        a.casefold().strip(),
        b.casefold().strip(),
        autojunk=False,
    ).ratio()
    return max(overlap, ratio * 0.8)


def _match_fact_lists(
    expected: list[str],
    observed: list[str],
    threshold: float = 0.36,
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    matches: list[tuple[int, int, float]] = []
    used_pred: set[int] = set()
    for gt_idx, gt_fact in enumerate(expected):
        best_idx = -1
        best_score = 0.0
        for pred_idx, pred_fact in enumerate(observed):
            if pred_idx in used_pred:
                continue
            score = _fact_similarity(gt_fact, pred_fact)
            if score > best_score:
                best_score = score
                best_idx = pred_idx
        if best_idx >= 0 and best_score >= threshold:
            used_pred.add(best_idx)
            matches.append((gt_idx, best_idx, best_score))
    matched_gt = {gt_idx for gt_idx, _, _ in matches}
    missing_gt = [idx for idx in range(len(expected)) if idx not in matched_gt]
    extra_pred = [idx for idx in range(len(observed)) if idx not in used_pred]
    return matches, missing_gt, extra_pred


def _load_llm_manager(
    *,
    args: argparse.Namespace,
    log_bridge: EvalLoggerBridge,
    logger: logging.Logger,
) -> LLMManager:
    model_path = pathlib.Path(str(args.llm_model or "")).expanduser().resolve()
    if not str(args.llm_model or "").strip():
        raise ValueError("--llm-model is required for fact-check evaluation")
    if not model_path.exists():
        raise FileNotFoundError(f"LLM model not found: {model_path}")

    try:
        from llama_cpp import Llama
    except Exception as exc:
        raise RuntimeError(
            "llama-cpp-python is required for --llm-model"
        ) from exc

    n_threads = args.llm_threads if args.llm_threads > 0 else (os.cpu_count() or 4)
    logger.info(
        "Loading LLM model %s | n_ctx=%s gpu_layers=%s threads=%s",
        model_path,
        args.llm_n_ctx,
        args.llm_gpu_layers,
        n_threads,
    )
    t0 = time.perf_counter()
    model = Llama(
        model_path=str(model_path),
        n_ctx=args.llm_n_ctx,
        n_gpu_layers=args.llm_gpu_layers,
        n_threads=n_threads,
        verbose=False,
    )
    logger.info("LLM loaded in %.2fs", time.perf_counter() - t0)

    llm = LLMManager(logger=log_bridge)
    llm.worker._model = model
    llm.worker._load_params = {
        "n_ctx": args.llm_n_ctx,
        "n_gpu_layers": args.llm_gpu_layers,
        "n_threads": n_threads,
    }
    return llm


def _apply_prompt_overrides(
    llm: LLMManager,
    prompts_json: str,
    logger: logging.Logger,
) -> None:
    path_s = str(prompts_json or "").strip()
    if not path_s:
        return
    path = pathlib.Path(path_s).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Prompt override file not found: {path}")
    data = _load_json(path)
    llm.set_prompt_set(data)
    logger.info("Loaded prompt overrides from %s", path)


def _parse_sources(raw: Any, suite_dir: pathlib.Path) -> list[SourceSpec]:
    if not isinstance(raw, list):
        raise ValueError("sources must be a list")
    out: list[SourceSpec] = []
    for item in raw:
        if isinstance(item, str):
            path = _resolve_path(item, suite_dir)
            name = path.name
        elif isinstance(item, dict):
            path = _resolve_path(str(item.get("path", "")), suite_dir)
            if not str(item.get("path", "")).strip():
                raise ValueError("source item missing 'path'")
            name = str(item.get("name", "")).strip() or path.name
        else:
            raise ValueError("source item must be string or object")
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")
        out.append(SourceSpec(name=name, path=path))
    if not out:
        raise ValueError("At least one source is required")
    return out


def _parse_case(
    raw: dict[str, Any],
    *,
    suite_dir: pathlib.Path,
    defaults: dict[str, Any],
    cli: dict[str, Any],
) -> CaseSpec:
    case_id = str(raw.get("id") or raw.get("case_id") or "").strip()
    if not case_id:
        raise ValueError("Each case requires id")

    target_raw = raw.get("target_markdown") or raw.get("target") or raw.get("generated")
    if not target_raw:
        raise ValueError(f"Case '{case_id}' missing target_markdown")
    target_path = _resolve_path(str(target_raw), suite_dir)
    if not target_path.exists():
        raise FileNotFoundError(f"Case '{case_id}' missing target file: {target_path}")

    gt_facts_raw = raw.get("gt_facts_markdown") or raw.get("gt_facts")
    if not gt_facts_raw:
        raise ValueError(f"Case '{case_id}' missing gt_facts_markdown")
    gt_facts_path = _resolve_path(str(gt_facts_raw), suite_dir)
    if not gt_facts_path.exists():
        raise FileNotFoundError(f"Case '{case_id}' missing gt facts file: {gt_facts_path}")

    gt_verdicts_raw = raw.get("gt_verdicts_markdown") or raw.get("gt_verdicts")
    if not gt_verdicts_raw:
        raise ValueError(f"Case '{case_id}' missing gt_verdicts_markdown")
    gt_verdicts_path = _resolve_path(str(gt_verdicts_raw), suite_dir)
    if not gt_verdicts_path.exists():
        raise FileNotFoundError(
            f"Case '{case_id}' missing gt verdicts file: {gt_verdicts_path}"
        )

    sources = _parse_sources(raw.get("sources"), suite_dir)

    labels = _normalise_labels(raw.get("labels"))

    threshold_extract_recall = _safe_float(
        raw.get(
            "threshold_extract_recall",
            defaults.get("threshold_extract_recall", 0.67),
        ),
        0.67,
    )
    threshold_verify_status = _safe_float(
        raw.get(
            "threshold_verify_status",
            defaults.get("threshold_verify_status", 0.67),
        ),
        0.67,
    )
    threshold_full_f1 = _safe_float(
        raw.get(
            "threshold_full_f1",
            defaults.get("threshold_full_f1", 0.50),
        ),
        0.50,
    )
    source_max_chars = _safe_int(
        raw.get("source_max_chars", defaults.get("source_max_chars", 24000)),
        24000,
    )
    target_max_chars = _safe_int(
        raw.get("target_max_chars", defaults.get("target_max_chars", 20000)),
        20000,
    )
    max_verify_facts = _safe_int(
        raw.get("max_verify_facts", defaults.get("max_verify_facts", 0)),
        0,
    )
    mode = str(raw.get("mode", defaults.get("mode", "all"))).strip().casefold() or "all"
    if mode not in {"all", "extract", "verify", "full"}:
        mode = "all"

    if "threshold_extract_recall" in cli:
        threshold_extract_recall = _safe_float(cli["threshold_extract_recall"], threshold_extract_recall)
    if "threshold_verify_status" in cli:
        threshold_verify_status = _safe_float(cli["threshold_verify_status"], threshold_verify_status)
    if "threshold_full_f1" in cli:
        threshold_full_f1 = _safe_float(cli["threshold_full_f1"], threshold_full_f1)
    if "source_max_chars" in cli:
        source_max_chars = _safe_int(cli["source_max_chars"], source_max_chars)
    if "target_max_chars" in cli:
        target_max_chars = _safe_int(cli["target_max_chars"], target_max_chars)
    if "max_verify_facts" in cli:
        max_verify_facts = _safe_int(cli["max_verify_facts"], max_verify_facts)
    if "mode" in cli and str(cli["mode"]).strip():
        mode = str(cli["mode"]).strip().casefold()
        if mode not in {"all", "extract", "verify", "full"}:
            mode = "all"

    return CaseSpec(
        case_id=case_id,
        labels=labels,
        target_path=target_path,
        gt_facts_path=gt_facts_path,
        gt_verdicts_path=gt_verdicts_path,
        sources=sources,
        threshold_extract_recall=max(0.0, min(1.0, threshold_extract_recall)),
        threshold_verify_status=max(0.0, min(1.0, threshold_verify_status)),
        threshold_full_f1=max(0.0, min(1.0, threshold_full_f1)),
        source_max_chars=max(500, source_max_chars),
        target_max_chars=max(500, target_max_chars),
        max_verify_facts=max(0, max_verify_facts),
        mode=mode,
    )


def _llm_generate(
    llm: LLMManager,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float,
    top_p: float = 0.9,
    repeat_penalty: float = 1.1,
) -> str:
    model = llm.worker._model
    result = model(
        prompt,
        max_tokens=int(max_tokens),
        temperature=float(temperature),
        top_p=float(top_p),
        repeat_penalty=float(repeat_penalty),
        stop=["<|"],
        stream=False,
    )
    return str(result["choices"][0].get("text", "") or "")


def _build_prompt_for_call(
    llm: LLMManager,
    *,
    user_message: str,
    file_contents: list[tuple[str, str]],
    system_prompt_key: str,
    grounding_required: bool,
    grounding_has_sources: bool,
) -> str:
    prompt_set = llm.get_prompt_set()
    system_prompt = str(
        prompt_set.get(system_prompt_key) or prompt_set.get("chat_system") or ""
    )
    system_prompt = llm._append_required_style_rules(system_prompt)
    return llm._build_prompt(
        user_message=user_message,
        file_contents=file_contents,
        rag_results=[],
        selected_text="",
        chat_history=[],
        selection_apply_mode=False,
        grounding_required=grounding_required,
        grounding_has_sources=grounding_has_sources,
        system_prompt_text=system_prompt,
    )


def _eval_extract_metrics(
    gt_facts: list[str],
    extracted: list[str],
) -> dict[str, Any]:
    matches, missing_gt_idx, extra_pred_idx = _match_fact_lists(gt_facts, extracted)
    matched = len(matches)
    exp_n = len(gt_facts)
    pred_n = len(extracted)
    recall = matched / exp_n if exp_n else 0.0
    precision = matched / pred_n if pred_n else 0.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if (precision + recall) > 0.0
        else 0.0
    )
    missing_gt = [gt_facts[idx] for idx in missing_gt_idx]
    extra_pred = [extracted[idx] for idx in extra_pred_idx]
    return {
        "matches": matches,
        "missing_gt": missing_gt,
        "extra_pred": extra_pred,
        "matched": matched,
        "expected": exp_n,
        "predicted": pred_n,
        "recall": recall,
        "precision": precision,
        "f1": f1,
    }


def _source_matches(expected_source: str, predicted_sources: str) -> bool:
    expected = norm_source_name(expected_source)
    if not expected:
        return True
    labels = [
        norm_source_name(token)
        for token in re.split(r"[;,]", str(predicted_sources or ""))
        if norm_source_name(token)
    ]
    if not labels:
        return False
    for label in labels:
        if label == expected or label in expected or expected in label:
            return True
    return False


def _eval_verify_metrics(
    gt_verdicts: list[GTVerdict],
    predicted_records: list[dict[str, str]],
) -> dict[str, Any]:
    pred_facts = [str(row.get("fact", "") or "") for row in predicted_records]
    gt_facts = [row.fact for row in gt_verdicts]
    matches, missing_gt_idx, _extra_pred_idx = _match_fact_lists(gt_facts, pred_facts)
    pred_by_gt: dict[int, dict[str, str]] = {
        gt_idx: predicted_records[pred_idx]
        for gt_idx, pred_idx, _score in matches
    }

    status_correct = 0
    source_correct = 0
    source_total = 0
    errors: list[str] = []
    for gt_idx, verdict in enumerate(gt_verdicts):
        pred = pred_by_gt.get(gt_idx)
        if pred is None:
            errors.append(f"missing prediction for fact: {verdict.fact[:80]}")
            continue
        got_status = _normalise_status(str(pred.get("status", "")))
        if got_status == verdict.status:
            status_correct += 1
        else:
            errors.append(
                f"status mismatch: expected={verdict.status} got={got_status} fact={verdict.fact[:80]}"
            )
        if verdict.source:
            source_total += 1
            if _source_matches(verdict.source, str(pred.get("sources", ""))):
                source_correct += 1

    total = len(gt_verdicts)
    status_accuracy = status_correct / total if total else 0.0
    source_accuracy = source_correct / source_total if source_total else 1.0
    missing_facts = [gt_verdicts[idx].fact for idx in missing_gt_idx]
    return {
        "status_accuracy": status_accuracy,
        "source_accuracy": source_accuracy,
        "status_correct": status_correct,
        "total": total,
        "missing_facts": missing_facts,
        "errors": errors,
    }


def _eval_full_metrics(
    gt_verdicts: list[GTVerdict],
    extracted_facts: list[str],
    predicted_records: list[dict[str, str]],
) -> dict[str, Any]:
    pred_facts = [str(row.get("fact", "") or "") for row in predicted_records]
    gt_facts = [row.fact for row in gt_verdicts]
    matches, missing_gt_idx, extra_pred_idx = _match_fact_lists(gt_facts, pred_facts)

    correct_status = 0
    wrong_status: list[str] = []
    for gt_idx, pred_idx, _score in matches:
        want = gt_verdicts[gt_idx].status
        got = _normalise_status(str(predicted_records[pred_idx].get("status", "")))
        if got == want:
            correct_status += 1
        else:
            wrong_status.append(
                f"expected={want} got={got} fact={gt_verdicts[gt_idx].fact[:90]}"
            )

    pred_n = len(extracted_facts)
    exp_n = len(gt_verdicts)
    precision = correct_status / pred_n if pred_n else 0.0
    recall = correct_status / exp_n if exp_n else 0.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if (precision + recall) > 0.0
        else 0.0
    )
    return {
        "correct_status": correct_status,
        "predicted": pred_n,
        "expected": exp_n,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "missing_facts": [gt_verdicts[idx].fact for idx in missing_gt_idx],
        "extra_facts": [extracted_facts[idx] for idx in extra_pred_idx],
        "wrong_status": wrong_status,
    }


def _evaluate_case(
    case: CaseSpec,
    *,
    llm: LLMManager,
    logger: logging.Logger,
    artifacts_dir: pathlib.Path | None,
    extract_base_max_tokens: int,
    verify_base_max_tokens: int,
    default_temperature: float,
) -> CaseResult:
    target_text = _read_text(case.target_path)[: case.target_max_chars].strip()
    if not target_text:
        raise ValueError(f"[{case.case_id}] target text is empty")
    gt_facts = _read_gt_facts_markdown(case.gt_facts_path)
    gt_verdicts = _read_gt_verdicts_markdown(case.gt_verdicts_path)
    if not gt_facts:
        raise ValueError(f"[{case.case_id}] GT facts empty: {case.gt_facts_path}")
    if not gt_verdicts:
        raise ValueError(f"[{case.case_id}] GT verdicts empty: {case.gt_verdicts_path}")

    source_contexts: list[tuple[str, str]] = []
    for source in case.sources:
        text = _read_text(source.path)[: case.source_max_chars].strip()
        if text:
            source_contexts.append((source.name, text))
    if not source_contexts:
        raise ValueError(f"[{case.case_id}] no non-empty source contexts")

    t0 = time.perf_counter()
    raw_extract = ""
    extracted_facts: list[str] = []
    extracted_eval = {
        "matched": 0,
        "expected": len(gt_facts),
        "predicted": 0,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "missing_gt": list(gt_facts),
        "extra_pred": [],
    }

    if case.mode in {"all", "extract", "full"}:
        fact_limit = suggest_fact_limit(target_text)
        req_extract = llm.render_prompt_template(
            "claim_extract_user",
            {
                "input_label": "Zieltext",
                "fact_limit": str(fact_limit),
            },
        ).strip()
        prompt_extract = _build_prompt_for_call(
            llm,
            user_message=req_extract,
            file_contents=[("Zieltext", target_text)],
            system_prompt_key="claim_extract_system",
            grounding_required=False,
            grounding_has_sources=True,
        )
        extract_max_tokens = max(384, min(int(extract_base_max_tokens), 2200))
        extract_max_tokens = max(extract_max_tokens, min(2600, 220 + fact_limit * 22))
        raw_extract = _llm_generate(
            llm,
            prompt_extract,
            max_tokens=extract_max_tokens,
            temperature=min(float(default_temperature), 0.35),
            top_p=0.9,
            repeat_penalty=1.1,
        )
        extracted_facts = parse_fact_candidates(raw_extract, target_text)
        if case.max_verify_facts > 0:
            extracted_facts = extracted_facts[: case.max_verify_facts]
        extracted_eval = _eval_extract_metrics(gt_facts, extracted_facts)

    verify_input_facts: list[str] = []
    if case.mode == "verify":
        verify_input_facts = [item.fact for item in gt_verdicts]
    elif case.mode in {"all", "full"}:
        verify_input_facts = list(extracted_facts)
    else:
        verify_input_facts = []
    if case.max_verify_facts > 0:
        verify_input_facts = verify_input_facts[: case.max_verify_facts]

    verify_records: list[dict[str, str]] = []
    verify_raw: list[str] = []
    if case.mode in {"all", "verify", "full"}:
        allowed_sources = ", ".join(
            dict.fromkeys(name for name, _ in source_contexts if str(name).strip())
        )
        verify_max_tokens = max(100, min(int(verify_base_max_tokens), 260))
        for idx, fact in enumerate(verify_input_facts):
            req_verify = llm.render_prompt_template(
                "fact_verify_user",
                {
                    "allowed_sources": allowed_sources or "Kontextquellen",
                    "fact": fact,
                },
            ).strip()
            prompt_verify = _build_prompt_for_call(
                llm,
                user_message=req_verify,
                file_contents=source_contexts,
                system_prompt_key="fact_verify_system",
                grounding_required=True,
                grounding_has_sources=bool(source_contexts),
            )
            raw = _llm_generate(
                llm,
                prompt_verify,
                max_tokens=verify_max_tokens,
                temperature=min(float(default_temperature), 0.25),
                top_p=0.9,
                repeat_penalty=1.1,
            )
            verify_raw.append(raw)
            parsed = parse_single_fact_verification(
                raw,
                fact,
                idx,
                source_contexts,
            )
            verify_records.append(parsed)

    if case.mode == "verify":
        verify_eval = _eval_verify_metrics(gt_verdicts, verify_records)
        full_eval = {
            "correct_status": verify_eval["status_correct"],
            "predicted": len(verify_records),
            "expected": len(gt_verdicts),
            "precision": verify_eval["status_accuracy"],
            "recall": verify_eval["status_accuracy"],
            "f1": verify_eval["status_accuracy"],
            "missing_facts": verify_eval["missing_facts"],
            "extra_facts": [],
            "wrong_status": verify_eval["errors"],
        }
    elif case.mode in {"all", "full"}:
        verify_eval = _eval_verify_metrics(gt_verdicts, verify_records)
        full_eval = _eval_full_metrics(gt_verdicts, verify_input_facts, verify_records)
    else:
        verify_eval = {
            "status_accuracy": 0.0,
            "source_accuracy": 1.0,
            "status_correct": 0,
            "total": len(gt_verdicts),
            "missing_facts": [v.fact for v in gt_verdicts],
            "errors": [],
        }
        full_eval = {
            "correct_status": 0,
            "predicted": 0,
            "expected": len(gt_verdicts),
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "missing_facts": [v.fact for v in gt_verdicts],
            "extra_facts": [],
            "wrong_status": [],
        }

    fail_reasons: list[str] = []
    extract_pass = extracted_eval["recall"] >= case.threshold_extract_recall
    verify_pass = verify_eval["status_accuracy"] >= case.threshold_verify_status
    full_pass = full_eval["f1"] >= case.threshold_full_f1

    if case.mode in {"all", "extract", "full"} and not extract_pass:
        fail_reasons.append(
            f"extract_recall={extracted_eval['recall']:.3f} < threshold={case.threshold_extract_recall:.3f}"
        )
    if case.mode in {"all", "verify", "full"} and not verify_pass:
        fail_reasons.append(
            f"verify_status_acc={verify_eval['status_accuracy']:.3f} < threshold={case.threshold_verify_status:.3f}"
        )
    if case.mode in {"all", "full"} and not full_pass:
        fail_reasons.append(
            f"full_f1={full_eval['f1']:.3f} < threshold={case.threshold_full_f1:.3f}"
        )

    if case.mode == "extract":
        passed = extract_pass
    elif case.mode == "verify":
        passed = verify_pass
    elif case.mode == "full":
        passed = full_pass
    else:
        passed = extract_pass and verify_pass and full_pass

    duration_ms = (time.perf_counter() - t0) * 1000.0
    expected_preview = [v.fact for v in gt_verdicts[:24]]
    observed_preview: list[str] = []
    observed_preview.append(
        f"extract p/r/f1={extracted_eval['precision']:.2f}/{extracted_eval['recall']:.2f}/{extracted_eval['f1']:.2f}"
    )
    observed_preview.append(
        f"verify status_acc/source_acc={verify_eval['status_accuracy']:.2f}/{verify_eval['source_accuracy']:.2f}"
    )
    observed_preview.append(
        f"full p/r/f1={full_eval['precision']:.2f}/{full_eval['recall']:.2f}/{full_eval['f1']:.2f}"
    )

    if artifacts_dir is not None:
        payload = {
            "case": dataclasses.asdict(case),
            "gt_facts": gt_facts,
            "gt_verdicts": [dataclasses.asdict(v) for v in gt_verdicts],
            "extract": {
                "raw": raw_extract,
                "facts": extracted_facts,
                "eval": extracted_eval,
            },
            "verify": {
                "input_facts": verify_input_facts,
                "raw": verify_raw,
                "records": verify_records,
                "eval": verify_eval,
            },
            "full": full_eval,
            "result": {
                "passed": passed,
                "fail_reasons": fail_reasons,
                "duration_ms": duration_ms,
            },
        }
        _write_json(artifacts_dir / f"{case.case_id}.json", payload)
        _write_text(artifacts_dir / f"{case.case_id}.target.md", target_text)

    logger.info(
        "[%s] pass=%s | extract_f1=%.3f verify_acc=%.3f full_f1=%.3f",
        case.case_id,
        passed,
        extracted_eval["f1"],
        verify_eval["status_accuracy"],
        full_eval["f1"],
    )

    return CaseResult(
        case_id=case.case_id,
        labels=case.labels,
        target_path=str(case.target_path),
        duration_ms=duration_ms,
        expected_facts=len(gt_verdicts),
        extracted_facts=len(extracted_facts),
        extracted_matched=int(extracted_eval["matched"]),
        extract_precision=float(extracted_eval["precision"]),
        extract_recall=float(extracted_eval["recall"]),
        extract_f1=float(extracted_eval["f1"]),
        verify_status_accuracy=float(verify_eval["status_accuracy"]),
        verify_source_accuracy=float(verify_eval["source_accuracy"]),
        full_precision=float(full_eval["precision"]),
        full_recall=float(full_eval["recall"]),
        full_f1=float(full_eval["f1"]),
        full_correct_status=int(full_eval["correct_status"]),
        full_predicted=int(full_eval["predicted"]),
        full_expected=int(full_eval["expected"]),
        mode=case.mode,
        passed=passed,
        fail_reasons=fail_reasons,
        expected_preview=expected_preview,
        observed_preview=observed_preview,
    )


def _write_cases_csv(path: pathlib.Path, rows: list[CaseResult]) -> None:
    cols = [
        "case_id",
        "labels",
        "mode",
        "passed",
        "duration_ms",
        "expected_facts",
        "extracted_facts",
        "extracted_matched",
        "extract_precision",
        "extract_recall",
        "extract_f1",
        "verify_status_accuracy",
        "verify_source_accuracy",
        "full_precision",
        "full_recall",
        "full_f1",
        "full_correct_status",
        "full_predicted",
        "full_expected",
        "fail_reasons",
        "target_path",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            rec = dataclasses.asdict(row)
            rec["labels"] = ",".join(row.labels)
            rec["fail_reasons"] = " | ".join(row.fail_reasons)
            writer.writerow({k: rec.get(k, "") for k in cols})


def _summarize(rows: list[CaseResult]) -> dict[str, Any]:
    if not rows:
        return {
            "cases": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "micro": {"precision": 0.0, "recall": 0.0, "f1": 0.0},
            "macro": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "hit_at_k": 0.0},
            "steps": {
                "extract": {"macro": {"precision": 0.0, "recall": 0.0, "f1": 0.0}},
                "verify": {"macro": {"status_accuracy": 0.0, "source_accuracy": 0.0}},
                "full": {"macro": {"precision": 0.0, "recall": 0.0, "f1": 0.0}},
            },
            "avg_duration_ms": 0.0,
        }

    tp = sum(row.full_correct_status for row in rows)
    pred = sum(row.full_predicted for row in rows)
    exp = sum(row.full_expected for row in rows)
    micro_precision = tp / pred if pred else 0.0
    micro_recall = tp / exp if exp else 0.0
    micro_f1 = (
        2.0 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if (micro_precision + micro_recall) > 0.0
        else 0.0
    )

    passed = sum(1 for row in rows if row.passed)
    return {
        "cases": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "pass_rate": passed / len(rows),
        "micro": {
            "precision": micro_precision,
            "recall": micro_recall,
            "f1": micro_f1,
        },
        "macro": {
            "precision": statistics.fmean(row.full_precision for row in rows),
            "recall": statistics.fmean(row.full_recall for row in rows),
            "f1": statistics.fmean(row.full_f1 for row in rows),
            "hit_at_k": statistics.fmean(row.verify_status_accuracy for row in rows),
        },
        "steps": {
            "extract": {
                "macro": {
                    "precision": statistics.fmean(row.extract_precision for row in rows),
                    "recall": statistics.fmean(row.extract_recall for row in rows),
                    "f1": statistics.fmean(row.extract_f1 for row in rows),
                }
            },
            "verify": {
                "macro": {
                    "status_accuracy": statistics.fmean(
                        row.verify_status_accuracy for row in rows
                    ),
                    "source_accuracy": statistics.fmean(
                        row.verify_source_accuracy for row in rows
                    ),
                }
            },
            "full": {
                "macro": {
                    "precision": statistics.fmean(row.full_precision for row in rows),
                    "recall": statistics.fmean(row.full_recall for row in rows),
                    "f1": statistics.fmean(row.full_f1 for row in rows),
                }
            },
        },
        "avg_duration_ms": statistics.fmean(row.duration_ms for row in rows),
    }


def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    suite_path = pathlib.Path(args.suite).expanduser().resolve()
    if not suite_path.exists():
        raise FileNotFoundError(f"Suite file not found: {suite_path}")
    suite_dir = suite_path.parent

    output_dir = pathlib.Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_name = str(args.run_name or "").strip() or datetime.now().strftime(
        "factcheck_%Y%m%d_%H%M%S"
    )
    logger = setup_logger(output_dir, run_name, args.log_level)
    log_bridge = EvalLoggerBridge(logger)

    llm = _load_llm_manager(args=args, log_bridge=log_bridge, logger=logger)
    _apply_prompt_overrides(llm, args.prompts_json, logger)

    suite = _load_json(suite_path)
    defaults_block = suite.get("defaults") if isinstance(suite.get("defaults"), dict) else {}
    defaults: dict[str, Any] = {
        "threshold_extract_recall": _safe_float(
            defaults_block.get("threshold_extract_recall", 0.67), 0.67
        ),
        "threshold_verify_status": _safe_float(
            defaults_block.get("threshold_verify_status", 0.67), 0.67
        ),
        "threshold_full_f1": _safe_float(defaults_block.get("threshold_full_f1", 0.50), 0.50),
        "source_max_chars": _safe_int(defaults_block.get("source_max_chars", 24000), 24000),
        "target_max_chars": _safe_int(defaults_block.get("target_max_chars", 20000), 20000),
        "max_verify_facts": _safe_int(defaults_block.get("max_verify_facts", 0), 0),
        "mode": str(defaults_block.get("mode", "all")).strip().casefold() or "all",
    }

    cli_overrides: dict[str, Any] = {}
    for item in args.set or []:
        key, value = _parse_kv_override(item)
        cli_overrides[key] = value
    if args.threshold_extract_recall >= 0.0:
        cli_overrides["threshold_extract_recall"] = float(args.threshold_extract_recall)
    if args.threshold_verify_status >= 0.0:
        cli_overrides["threshold_verify_status"] = float(args.threshold_verify_status)
    if args.threshold_full_f1 >= 0.0:
        cli_overrides["threshold_full_f1"] = float(args.threshold_full_f1)
    if args.source_max_chars > 0:
        cli_overrides["source_max_chars"] = int(args.source_max_chars)
    if args.target_max_chars > 0:
        cli_overrides["target_max_chars"] = int(args.target_max_chars)
    if args.max_verify_facts > 0:
        cli_overrides["max_verify_facts"] = int(args.max_verify_facts)
    if args.mode and args.mode != "all":
        cli_overrides["mode"] = args.mode

    raw_cases = suite.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("suite.cases must be a list")

    all_cases: list[CaseSpec] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("Each case must be an object")
        all_cases.append(
            _parse_case(
                raw,
                suite_dir=suite_dir,
                defaults=defaults,
                cli=cli_overrides,
            )
        )

    labels_filter = _normalise_labels(args.labels) if args.labels else []
    selected_cases = all_cases
    if labels_filter:
        wanted = {label.casefold() for label in labels_filter}
        selected_cases = [
            case for case in selected_cases
            if wanted.intersection({label.casefold() for label in case.labels})
        ]
    if args.max_cases > 0:
        selected_cases = selected_cases[: int(args.max_cases)]

    if not selected_cases:
        raise ValueError("No cases selected after filters")

    logger.info(
        "Loaded %d/%d fact-check cases from %s",
        len(selected_cases),
        len(all_cases),
        suite_path,
    )

    artifacts_dir = (
        output_dir / f"{run_name}.artifacts" if args.write_artifacts else None
    )

    rows: list[CaseResult] = []
    started = time.perf_counter()
    for case in selected_cases:
        row = _evaluate_case(
            case,
            llm=llm,
            logger=logger,
            artifacts_dir=artifacts_dir,
            extract_base_max_tokens=int(args.extract_max_tokens),
            verify_base_max_tokens=int(args.verify_max_tokens),
            default_temperature=float(args.temperature),
        )
        rows.append(row)
    elapsed = time.perf_counter() - started
    summary = _summarize(rows)

    payload_cases: list[dict[str, Any]] = []
    for row in rows:
        payload_cases.append(
            {
                "case_id": row.case_id,
                "query": f"Target: {pathlib.Path(row.target_path).name}",
                "labels": row.labels,
                "f1": row.full_f1,
                "precision": row.full_precision,
                "recall": row.full_recall,
                "hit_at_k": row.verify_status_accuracy,
                "expected_docs": row.expected_preview[:24],
                "predicted_docs": row.observed_preview[:24],
                "failed": (not row.passed),
            }
        )

    payload = {
        "run_name": run_name,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "suite": str(suite_path),
        "evaluation_type": "factcheck",
        "config": {
            "llm_model": str(args.llm_model),
            "llm_n_ctx": int(args.llm_n_ctx),
            "llm_gpu_layers": int(args.llm_gpu_layers),
            "llm_threads": int(args.llm_threads),
            "prompts_json": str(args.prompts_json or ""),
            "extract_max_tokens": int(args.extract_max_tokens),
            "verify_max_tokens": int(args.verify_max_tokens),
            "temperature": float(args.temperature),
            "settings_overrides": cli_overrides,
        },
        "summary": {
            **summary,
            "elapsed_sec": elapsed,
        },
        "cases": payload_cases,
    }

    _write_json(output_dir / f"{run_name}.summary.json", payload)
    _write_cases_csv(output_dir / f"{run_name}.cases.csv", rows)
    with open(output_dir / f"{run_name}.debug.jsonl", "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dataclasses.asdict(row), ensure_ascii=False) + "\n")

    logger.info(
        "Done | cases=%d pass=%d fail=%d pass_rate=%.3f elapsed=%.2fs",
        payload["summary"]["cases"],
        payload["summary"]["passed"],
        payload["summary"]["failed"],
        payload["summary"]["pass_rate"],
        elapsed,
    )
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fact-check extraction/verification eval runner")
    parser.add_argument("--suite", required=True, help="Path to fact-check suite JSON")
    parser.add_argument(
        "--output-dir",
        default="runs/factcheck_eval",
        help="Directory for run artifacts",
    )
    parser.add_argument("--run-name", default="", help="Optional run name")
    parser.add_argument("--labels", default="", help="Optional comma-separated labels filter")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument(
        "--mode",
        default="all",
        choices=["all", "extract", "verify", "full"],
        help="Run only a subset of the 3-stage pipeline",
    )
    parser.add_argument(
        "--llm-model",
        default="",
        help="GGUF model path (required)",
    )
    parser.add_argument("--llm-n-ctx", type=int, default=4096)
    parser.add_argument("--llm-gpu-layers", type=int, default=0)
    parser.add_argument("--llm-threads", type=int, default=0)
    parser.add_argument("--prompts-json", default="", help="Optional prompt override JSON")
    parser.add_argument("--extract-max-tokens", type=int, default=1024)
    parser.add_argument("--verify-max-tokens", type=int, default=220)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument(
        "--threshold-extract-recall",
        type=float,
        default=-1.0,
        help="Override minimum recall required for extract stage",
    )
    parser.add_argument(
        "--threshold-verify-status",
        type=float,
        default=-1.0,
        help="Override minimum status-accuracy required for verify stage",
    )
    parser.add_argument(
        "--threshold-full-f1",
        type=float,
        default=-1.0,
        help="Override minimum F1 required for full stage",
    )
    parser.add_argument("--source-max-chars", type=int, default=0)
    parser.add_argument("--target-max-chars", type=int, default=0)
    parser.add_argument("--max-verify-facts", type=int, default=0)
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        help="Generic setting override key=value (repeatable)",
    )
    parser.add_argument(
        "--write-artifacts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write per-case artifacts",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        run_suite(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
