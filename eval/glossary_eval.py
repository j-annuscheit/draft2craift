#!/usr/bin/env python3
"""
Glossary generation evaluation runner.

Purpose
-------
- Evaluate glossary extraction quality from Markdown context files.
- Use the same local LLM stack and glossary prompts as the main app.
- Score whether target glossary terms were found.

Usage
-----
python -m eval.glossary_eval \
  --suite eval/examples/glossary_suite.example.json \
  --output-dir runs/glossary_eval \
  --run-name baseline \
  --llm-model /path/to/model.gguf
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

from shared.services.llm.manager import LLMManager  # noqa: E402


@dataclass
class CaseSpec:
    case_id: str
    markdown_path: pathlib.Path | None
    markdown_text: str
    labels: list[str]
    target_terms: list[str]
    excluded_terms: list[str]
    max_terms: int
    context_max_chars: int
    threshold_recall: float


@dataclass
class CaseResult:
    case_id: str
    labels: list[str]
    markdown_path: str
    duration_ms: float
    expected_terms: int
    generated_terms: int
    found_terms: int
    recall: float
    precision: float
    f1: float
    hit_all_terms: float
    passed: bool
    missing_terms: list[str]
    excluded_hits: list[str]
    found_term_pairs: list[dict[str, Any]]
    generated_preview: list[str]
    fail_reasons: list[str]


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
    logger = logging.getLogger(f"glossary_eval.{run_name}")
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


def _normalise_term(term: str) -> str:
    src = str(term or "").casefold().strip()
    out_chars: list[str] = []
    prev_sep = False
    for ch in src:
        if ch.isalnum():
            out_chars.append(ch)
            prev_sep = False
            continue
        if ch in {" ", "-", "_", "/", "+", "."}:
            if not prev_sep:
                out_chars.append(" ")
                prev_sep = True
    return "".join(out_chars).strip()


def _resolve_path(raw: str, suite_dir: pathlib.Path) -> pathlib.Path:
    p = pathlib.Path(str(raw))
    if p.is_absolute():
        return p
    return (suite_dir / p).resolve()


def _parse_terms(raw: Any) -> list[str]:
    values: list[str] = []
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw]
    else:
        raise ValueError("target_terms must be string or list[str]")
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if len(value) < 2:
            continue
        key = _normalise_term(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
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


def _extract_generated_terms(entries: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in entries:
        term = str(item.get("term", "")).strip()
        aliases = item.get("aliases", [])
        candidates = [term]
        if isinstance(aliases, list):
            candidates.extend(str(alias).strip() for alias in aliases)
        for cand in candidates:
            if len(cand) < 2:
                continue
            key = _normalise_term(cand)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(cand)
    return out


def _best_match(expected: str, generated_terms: list[str]) -> tuple[bool, str, float]:
    exp_norm = _normalise_term(expected)
    if not exp_norm:
        return False, "", 0.0

    best_term = ""
    best_score = 0.0
    for cand in generated_terms:
        cand_norm = _normalise_term(cand)
        if not cand_norm:
            continue
        if exp_norm == cand_norm:
            return True, cand, 1.0
        if exp_norm in cand_norm or cand_norm in exp_norm:
            score = 0.92
        else:
            score = difflib.SequenceMatcher(
                None,
                exp_norm,
                cand_norm,
                autojunk=False,
            ).ratio()
        if score > best_score:
            best_score = score
            best_term = cand

    found = best_score >= 0.9
    return found, best_term, best_score


def _load_llm_manager(
    *,
    args: argparse.Namespace,
    log_bridge: EvalLoggerBridge,
    logger: logging.Logger,
) -> LLMManager:
    model_path = pathlib.Path(str(args.llm_model or "")).expanduser().resolve()
    if not str(args.llm_model or "").strip():
        raise ValueError("--llm-model is required for glossary evaluation")
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

    md_field = raw.get("markdown") or raw.get("path")
    md_text = str(raw.get("markdown_text") or "").strip()
    md_path: pathlib.Path | None = None

    if md_field:
        md_path = _resolve_path(str(md_field), suite_dir)
        if not md_path.exists():
            raise FileNotFoundError(f"Case '{case_id}' missing markdown file: {md_path}")

    if md_path is None and not md_text:
        raise ValueError(
            f"Case '{case_id}' needs 'markdown' path or direct 'markdown_text' content"
        )

    targets = _parse_terms(raw.get("target_terms") or raw.get("targets") or [])
    if not targets:
        raise ValueError(f"Case '{case_id}' has no target terms")
    excluded_terms = _parse_terms(
        raw.get("excluded_terms") or raw.get("excluded_targets") or []
    )

    labels = _normalise_labels(raw.get("labels"))
    max_terms = int(raw.get("max_terms", defaults.get("max_terms", 24)))
    context_max_chars = int(
        raw.get("context_max_chars", defaults.get("context_max_chars", 22000))
    )
    threshold_recall = float(
        raw.get("threshold_recall", defaults.get("threshold_recall", 1.0))
    )

    if "max_terms" in cli:
        max_terms = int(cli["max_terms"])
    if "context_max_chars" in cli:
        context_max_chars = int(cli["context_max_chars"])
    if "threshold_recall" in cli:
        threshold_recall = float(cli["threshold_recall"])

    return CaseSpec(
        case_id=case_id,
        markdown_path=md_path,
        markdown_text=md_text,
        labels=labels,
        target_terms=targets,
        excluded_terms=excluded_terms,
        max_terms=max(1, min(128, max_terms)),
        context_max_chars=max(500, context_max_chars),
        threshold_recall=max(0.0, min(1.0, threshold_recall)),
    )


def _evaluate_case(
    case: CaseSpec,
    *,
    llm: LLMManager,
    logger: logging.Logger,
    artifacts_dir: pathlib.Path | None,
) -> CaseResult:
    context_full = case.markdown_text if case.markdown_text else _read_text(case.markdown_path)
    context = context_full[: case.context_max_chars]

    t0 = time.perf_counter()
    entries, meta = llm.generate_glossary_sync(context, max_terms=case.max_terms)
    duration_ms = (time.perf_counter() - t0) * 1000.0

    generated_terms = _extract_generated_terms(entries)
    found_pairs: list[dict[str, Any]] = []
    missing: list[str] = []
    found = 0
    for expected in case.target_terms:
        ok, matched, score = _best_match(expected, generated_terms)
        if ok:
            found += 1
        else:
            missing.append(expected)
        found_pairs.append(
            {
                "expected": expected,
                "found": bool(ok),
                "matched": matched,
                "score": round(float(score), 4),
            }
        )

    expected_n = len(case.target_terms)
    generated_n = len(generated_terms)
    recall = found / expected_n if expected_n else 0.0
    precision = found / generated_n if generated_n else 0.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if (precision + recall) > 0.0
        else 0.0
    )
    hit_all = 1.0 if found >= expected_n and expected_n > 0 else 0.0

    fail_reasons: list[str] = []
    if recall < case.threshold_recall:
        fail_reasons.append(
            f"recall={recall:.3f} < threshold={case.threshold_recall:.3f}"
        )
    excluded_hits: list[str] = []
    for excluded in case.excluded_terms:
        ok, _, _ = _best_match(excluded, generated_terms)
        if ok:
            excluded_hits.append(excluded)
    if excluded_hits:
        fail_reasons.append("excluded_terms detected: " + ", ".join(excluded_hits[:24]))
    if not meta.get("applied", False):
        fail_reasons.append(f"llm_applied={meta.get('reason', 'false')}")

    passed = len(fail_reasons) == 0

    generated_preview = generated_terms[:48]
    if artifacts_dir is not None:
        payload = {
            "case": {
                **dataclasses.asdict(case),
                "markdown_path": str(case.markdown_path) if case.markdown_path else "",
            },
            "llm_meta": meta,
            "generated_entries": entries,
            "generated_terms": generated_terms,
            "found_pairs": found_pairs,
            "missing_terms": missing,
            "excluded_hits": excluded_hits,
            "metrics": {
                "expected_terms": expected_n,
                "generated_terms": generated_n,
                "found_terms": found,
                "recall": recall,
                "precision": precision,
                "f1": f1,
                "hit_all_terms": hit_all,
                "passed": passed,
                "duration_ms": duration_ms,
            },
        }
        _write_json(artifacts_dir / f"{case.case_id}.json", payload)
        _write_text(artifacts_dir / f"{case.case_id}.context.md", context)

    logger.info(
        "[%s] pass=%s recall=%.3f precision=%.3f f1=%.3f found=%d/%d",
        case.case_id,
        passed,
        recall,
        precision,
        f1,
        found,
        expected_n,
    )

    return CaseResult(
        case_id=case.case_id,
        labels=case.labels,
        markdown_path=str(case.markdown_path) if case.markdown_path else "<inline_markdown>",
        duration_ms=duration_ms,
        expected_terms=expected_n,
        generated_terms=generated_n,
        found_terms=found,
        recall=recall,
        precision=precision,
        f1=f1,
        hit_all_terms=hit_all,
        passed=passed,
        missing_terms=missing,
        excluded_hits=excluded_hits,
        found_term_pairs=found_pairs,
        generated_preview=generated_preview,
        fail_reasons=fail_reasons,
    )


def _write_cases_csv(path: pathlib.Path, rows: list[CaseResult]) -> None:
    cols = [
        "case_id",
        "labels",
        "passed",
        "duration_ms",
        "expected_terms",
        "generated_terms",
        "found_terms",
        "recall",
        "precision",
        "f1",
        "hit_all_terms",
        "missing_terms",
        "excluded_hits",
        "generated_preview",
        "fail_reasons",
        "markdown_path",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            rec = dataclasses.asdict(row)
            rec["labels"] = ",".join(row.labels)
            rec["missing_terms"] = " | ".join(row.missing_terms)
            rec["excluded_hits"] = " | ".join(row.excluded_hits)
            rec["generated_preview"] = " | ".join(row.generated_preview)
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
        }

    total_found = sum(row.found_terms for row in rows)
    total_expected = sum(row.expected_terms for row in rows)
    total_generated = sum(row.generated_terms for row in rows)
    micro_recall = total_found / total_expected if total_expected else 0.0
    micro_precision = total_found / total_generated if total_generated else 0.0
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
            "precision": statistics.fmean(row.precision for row in rows),
            "recall": statistics.fmean(row.recall for row in rows),
            "f1": statistics.fmean(row.f1 for row in rows),
            "hit_at_k": statistics.fmean(row.hit_all_terms for row in rows),
        },
        "avg_generated_terms": statistics.fmean(row.generated_terms for row in rows),
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
        "glossary_%Y%m%d_%H%M%S"
    )
    logger = setup_logger(output_dir, run_name, args.log_level)
    log_bridge = EvalLoggerBridge(logger)

    llm = _load_llm_manager(args=args, log_bridge=log_bridge, logger=logger)
    _apply_prompt_overrides(llm, args.prompts_json, logger)

    suite = _load_json(suite_path)
    defaults_block = suite.get("defaults") if isinstance(suite.get("defaults"), dict) else {}
    defaults = {
        "max_terms": int(defaults_block.get("max_terms", 24)),
        "context_max_chars": int(defaults_block.get("context_max_chars", 22000)),
        "threshold_recall": _safe_float(defaults_block.get("threshold_recall", 1.0), 1.0),
    }

    cli_overrides: dict[str, Any] = {}
    for item in args.set or []:
        key, value = _parse_kv_override(item)
        cli_overrides[key] = value
    if args.max_terms > 0:
        cli_overrides["max_terms"] = int(args.max_terms)
    if args.context_max_chars > 0:
        cli_overrides["context_max_chars"] = int(args.context_max_chars)
    if args.threshold_recall >= 0.0:
        cli_overrides["threshold_recall"] = float(args.threshold_recall)

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
        "Loaded %d/%d glossary cases from %s",
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
        )
        rows.append(row)
    elapsed = time.perf_counter() - started
    summary = _summarize(rows)

    payload_cases: list[dict[str, Any]] = []
    for row in rows:
        found_terms = [
            str(item["expected"])
            for item in row.found_term_pairs
            if bool(item.get("found"))
        ]
        missing_terms = [str(term) for term in row.missing_terms]
        observed: list[str] = []
        if found_terms:
            observed.append("FOUND: " + ", ".join(found_terms[:24]))
        if missing_terms:
            observed.append("MISS: " + ", ".join(missing_terms[:24]))
        if row.excluded_hits:
            observed.append("EXCLUDED_HIT: " + ", ".join(row.excluded_hits[:24]))
        if row.generated_preview:
            observed.append("GEN: " + ", ".join(row.generated_preview[:24]))
        payload_cases.append(
            {
                "case_id": row.case_id,
                "query": f"Markdown: {pathlib.Path(row.markdown_path).name}",
                "labels": row.labels,
                "f1": row.f1,
                "precision": row.precision,
                "recall": row.recall,
                "hit_at_k": row.hit_all_terms,
                "expected_docs": (
                    [item["expected"] for item in row.found_term_pairs]
                ),
                "predicted_docs": observed,
                "failed": (not row.passed),
            }
        )

    payload = {
        "run_name": run_name,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "suite": str(suite_path),
        "evaluation_type": "glossary",
        "config": {
            "llm_model": str(args.llm_model),
            "llm_n_ctx": int(args.llm_n_ctx),
            "llm_gpu_layers": int(args.llm_gpu_layers),
            "llm_threads": int(args.llm_threads),
            "prompts_json": str(args.prompts_json or ""),
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
    parser = argparse.ArgumentParser(description="Glossary extraction eval runner")
    parser.add_argument("--suite", required=True, help="Path to glossary suite JSON")
    parser.add_argument(
        "--output-dir",
        default="runs/glossary_eval",
        help="Directory for run artifacts",
    )
    parser.add_argument("--run-name", default="", help="Optional run name")
    parser.add_argument("--labels", default="", help="Optional comma-separated labels filter")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument(
        "--llm-model",
        default="",
        help="GGUF model path (required)",
    )
    parser.add_argument("--llm-n-ctx", type=int, default=4096)
    parser.add_argument("--llm-gpu-layers", type=int, default=0)
    parser.add_argument("--llm-threads", type=int, default=0)
    parser.add_argument("--prompts-json", default="", help="Optional prompt override JSON")
    parser.add_argument("--max-terms", type=int, default=0, help="Override max glossary terms")
    parser.add_argument(
        "--context-max-chars",
        type=int,
        default=0,
        help="Override context char limit",
    )
    parser.add_argument(
        "--threshold-recall",
        type=float,
        default=-1.0,
        help="Override minimum recall required to pass",
    )
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
