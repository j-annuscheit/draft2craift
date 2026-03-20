#!/usr/bin/env python3
"""
RAG evaluation runner.

Features
--------
- Load Markdown documents from a JSON suite definition.
- Run RAG queries with full debug output.
- Optional local GGUF model loading for HyDE / literal-term expansion / reranking.
- Compute retrieval metrics (precision, recall, F1, hit-rate, MRR, MAP, nDCG).
- Persist logs + per-case debug artifacts for traceability.

Usage
-----
python -m eval.rag_eval \
  --suite tests/rag_suite.json \
  --output-dir runs/rag_eval \
  --run-name baseline
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import itertools
import json
import logging
import math
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

from shared.services.llm.manager import LLMManager
from shared.services.rag.config import RAGConfig
from shared.services.rag.orchestrator import RAGSystem


# ---------------------------------------------------------------------------
# Logging bridge
# ---------------------------------------------------------------------------


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


def setup_logger(output_dir: pathlib.Path, run_name: str, level: str) -> logging.Logger:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"rag_eval.{run_name}")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(output_dir / f"{run_name}.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    return logger


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class DocEntry:
    name: str
    path: pathlib.Path
    # If set, content is used directly instead of reading from path.
    # Allows feedback-generated suites to embed doc text inline.
    content: str | None = None


@dataclass
class CaseResult:
    case_id: str
    query: str
    labels: list[str]
    top_k: int
    duration_ms: float
    expected_docs: list[str]
    predicted_docs: list[str]
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    hit_at_k: float
    mrr: float
    ap: float
    ndcg: float
    expected_contains: list[str]
    contains_matches: int
    contains_recall: float | None
    warnings: list[str]
    # Docs that must NOT appear in results (from rag_exclude test intent).
    excluded_docs: list[str] = dataclasses.field(default_factory=list)
    excluded_hits: list[str] = dataclasses.field(default_factory=list)
    # Excerpt substrings that must NOT appear (quote-level exclusion).
    excluded_contains: list[str] = dataclasses.field(default_factory=list)
    excluded_contains_hits: list[str] = dataclasses.field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_name(name: str) -> str:
    base = os.path.basename(str(name or "")).strip()
    return base.casefold()


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _read_text(path: pathlib.Path) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def _parse_doc_entry(raw: Any, suite_dir: pathlib.Path) -> DocEntry:
    if isinstance(raw, str):
        path = (suite_dir / raw).resolve() if not os.path.isabs(raw) else pathlib.Path(raw)
        return DocEntry(name=path.name, path=path)
    if isinstance(raw, dict):
        # Inline-content mode: {"name": "doc.md", "content": "..."}
        # Used by feedback-generated suites that embed document text directly.
        if "content" in raw and "path" not in raw:
            name = str(raw.get("name") or "inline_doc")
            # Use a sentinel path; content field takes precedence in _index_docs.
            return DocEntry(
                name=name,
                path=pathlib.Path("<inline>") / name,
                content=str(raw["content"]),
            )
        if "path" not in raw:
            raise ValueError("Document object requires 'path' or 'content'")
        path_s = str(raw["path"])
        path = (suite_dir / path_s).resolve() if not os.path.isabs(path_s) else pathlib.Path(path_s)
        name = str(raw.get("name") or path.name)
        # Allow optional inline content override even for path-based entries
        content = str(raw["content"]) if "content" in raw else None
        return DocEntry(name=name, path=path, content=content)
    raise ValueError(f"Invalid document entry: {raw!r}")


def _parse_docs(raw_docs: list[Any], suite_dir: pathlib.Path) -> list[DocEntry]:
    docs = [_parse_doc_entry(d, suite_dir) for d in raw_docs]
    # Only check file existence for path-based entries (not inline content)
    missing = [str(d.path) for d in docs if d.content is None and not d.path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing markdown documents: {missing}")
    return docs


def _apply_config_overrides(base: RAGConfig, overrides: dict[str, Any]) -> RAGConfig:
    return base.with_overrides(overrides or {}, strict=True)


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


def _parse_case_labels(raw: Any) -> list[str]:
    """Normalise case labels from string/list input into a unique list."""
    if raw is None:
        return []

    tokens: list[str] = []
    if isinstance(raw, str):
        tokens = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        for item in raw:
            text = str(item).strip()
            if text:
                tokens.append(text)
    else:
        raise ValueError("case.labels must be a string or list of strings")

    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if not token:
            continue
        norm = token.casefold()
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(token)
    return deduped


def _as_str_list(raw: Any) -> list[str]:
    out: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            text = str(item or "").strip()
            if text:
                out.append(text)
        return out
    if isinstance(raw, str):
        for line in raw.splitlines():
            for part in line.split(","):
                token = part.strip()
                if token:
                    out.append(token)
        return out
    return out


def _load_llm_manager(
    args: argparse.Namespace,
    log_bridge: EvalLoggerBridge,
    py_logger: logging.Logger,
) -> LLMManager | None:
    if not args.llm_model:
        py_logger.info("No --llm-model specified. Running without LLM callbacks.")
        return None

    model_path = pathlib.Path(args.llm_model).expanduser().resolve()
    if not model_path.exists():
        raise FileNotFoundError(f"LLM model not found: {model_path}")

    try:
        from llama_cpp import Llama
    except Exception as exc:
        raise RuntimeError(
            "llama-cpp-python is required for --llm-model"
        ) from exc

    n_threads = args.llm_threads if args.llm_threads > 0 else (os.cpu_count() or 4)
    py_logger.info(
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
    dt = time.perf_counter() - t0
    py_logger.info("LLM loaded in %.2fs", dt)

    llm = LLMManager(logger=log_bridge)
    llm.worker._model = model
    llm.worker._load_params = {
        "n_ctx": args.llm_n_ctx,
        "n_gpu_layers": args.llm_gpu_layers,
        "n_threads": n_threads,
    }
    return llm


def _wire_llm_callbacks(rag: RAGSystem, llm: LLMManager | None):
    if not llm:
        return
    rag.set_tfidf_query_expander(llm.expand_query_tfidf_sync)
    rag.set_st_query_expander(llm.expand_query_st_sync)
    rag.set_literal_query_expander(llm.expand_query_literal_terms_sync)
    rag.set_rag_reranker(llm.rerank_rag_results_sync)


def _rank_metrics(pred_docs: list[str], expected_docs: list[str]) -> dict[str, float]:
    exp = {_canonical_name(x) for x in expected_docs}
    pred = [_canonical_name(x) for x in pred_docs]

    tp = sum(1 for d in pred if d in exp)
    fp = max(0, len(pred) - tp)
    fn = max(0, len(exp) - tp)
    precision = (tp / len(pred)) if pred else 0.0
    recall = (tp / len(exp)) if exp else (1.0 if not pred else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    hit_at_k = 1.0 if tp > 0 else 0.0

    rr = 0.0
    for rank, doc in enumerate(pred, 1):
        if doc in exp:
            rr = 1.0 / rank
            break

    if exp:
        rel_so_far = 0
        ap_sum = 0.0
        for rank, doc in enumerate(pred, 1):
            if doc in exp:
                rel_so_far += 1
                ap_sum += rel_so_far / rank
        ap = ap_sum / len(exp)
    else:
        ap = 0.0

    dcg = 0.0
    for rank, doc in enumerate(pred, 1):
        rel = 1.0 if doc in exp else 0.0
        if rel:
            dcg += rel / math.log2(rank + 1)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(exp), len(pred)) + 1)) if exp else 1.0
    ndcg = dcg / idcg if idcg > 0 else 0.0

    return {
        "tp": float(tp),
        "fp": float(fp),
        "fn": float(fn),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "hit_at_k": hit_at_k,
        "mrr": rr,
        "ap": ap,
        "ndcg": ndcg,
    }


def _contains_recall(expected_contains: list[str], result_excerpts: list[str]) -> tuple[int, float | None]:
    if not expected_contains:
        return 0, None
    blob = "\n".join(result_excerpts).casefold()
    matched = 0
    for needle in expected_contains:
        n = str(needle or "").strip().casefold()
        if n and n in blob:
            matched += 1
    return matched, (matched / len(expected_contains))


def _excluded_contains_hits(excluded_contains: list[str], result_excerpts: list[str]) -> list[str]:
    if not excluded_contains:
        return []
    blob = "\n".join(result_excerpts).casefold()
    hits: list[str] = []
    for needle in excluded_contains:
        token = str(needle or "").strip()
        if not token:
            continue
        if token.casefold() in blob:
            hits.append(token)
    return hits


def _summarise_subset(case_results: list[CaseResult]) -> dict[str, Any]:
    """Summarise one subset of cases using micro and macro retrieval metrics."""
    if not case_results:
        return {
            "micro": {
                "tp": 0,
                "fp": 0,
                "fn": 0,
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
            },
            "macro": {
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "hit_at_k": 0.0,
                "mrr": 0.0,
                "map": 0.0,
                "ndcg": 0.0,
                "contains_recall": None,
            },
        }

    tp = sum(r.tp for r in case_results)
    fp = sum(r.fp for r in case_results)
    fn = sum(r.fn for r in case_results)
    micro_p = tp / (tp + fp) if (tp + fp) else 0.0
    micro_r = tp / (tp + fn) if (tp + fn) else 0.0
    micro_f1 = (2 * micro_p * micro_r / (micro_p + micro_r)) if (micro_p + micro_r) else 0.0

    def avg(attr: str) -> float:
        vals = [float(getattr(r, attr)) for r in case_results]
        return statistics.fmean(vals) if vals else 0.0

    contains_vals = [r.contains_recall for r in case_results if r.contains_recall is not None]
    contains_avg = statistics.fmean(contains_vals) if contains_vals else None

    return {
        "micro": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": micro_p,
            "recall": micro_r,
            "f1": micro_f1,
        },
        "macro": {
            "precision": avg("precision"),
            "recall": avg("recall"),
            "f1": avg("f1"),
            "hit_at_k": avg("hit_at_k"),
            "mrr": avg("mrr"),
            "map": avg("ap"),
            "ndcg": avg("ndcg"),
            "contains_recall": contains_avg,
        },
    }


def _summarise(case_results: list[CaseResult]) -> dict[str, Any]:
    if not case_results:
        return {}

    total = _summarise_subset(case_results)
    label_buckets: dict[str, list[CaseResult]] = {}
    for case in case_results:
        labels = case.labels or ["__unlabeled__"]
        for label in labels:
            label_buckets.setdefault(label, []).append(case)

    by_label: dict[str, Any] = {}
    for label in sorted(label_buckets, key=str.casefold):
        bucket = label_buckets[label]
        subset = _summarise_subset(bucket)
        by_label[label] = {
            "cases": len(bucket),
            "micro": subset["micro"],
            "macro": subset["macro"],
        }

    return {
        "cases": len(case_results),
        "micro": total["micro"],
        "macro": total["macro"],
        "by_label": by_label,
    }


def _case_docs(case_data: dict[str, Any], global_docs: list[DocEntry]) -> list[DocEntry]:
    docs_spec = case_data.get("documents")
    if docs_spec is None:
        return global_docs
    if not isinstance(docs_spec, list):
        raise ValueError("case.documents must be a list")
    return docs_spec  # parsed by caller


def _docs_signature(docs: list[DocEntry]) -> tuple[tuple[str, str], ...]:
    import hashlib
    def _sig(d: DocEntry) -> tuple[str, str]:
        if d.content is not None:
            # Use a short content hash so identical inline docs share cache entries
            h = hashlib.md5(d.content.encode("utf-8", errors="replace")).hexdigest()[:12]
            return (d.name, f"inline:{h}")
        return (d.name, str(d.path))
    return tuple(sorted(_sig(d) for d in docs))


def _index_docs(rag: RAGSystem, docs: list[DocEntry], logger: logging.Logger):
    rag.clear()
    for d in docs:
        content = d.content if d.content is not None else _read_text(d.path)
        ok = rag.index_content(d.name, content)
        if not ok:
            raise RuntimeError(f"Failed to index {d.name}")
    logger.info("Indexed %d markdown documents", len(docs))


def _write_json(path: pathlib.Path, data: Any):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _write_jsonl(path: pathlib.Path, rows: list[dict[str, Any]]):
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")


def run_suite(
    suite_path: pathlib.Path,
    output_dir: pathlib.Path,
    run_name: str,
    config_overrides: dict[str, Any] | None = None,
    config_file_overrides: dict[str, Any] | None = None,
    cli_top_k: int | None = None,
    llm_model: str | None = None,
    llm_n_ctx: int = 4096,
    llm_gpu_layers: int = 0,
    llm_threads: int = 0,
    log_level: str = "INFO",
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logger(output_dir, run_name, log_level)
    bridge = EvalLoggerBridge(logger)

    suite = _load_json(suite_path)
    suite_dir = suite_path.parent.resolve()

    global_docs_raw = suite.get("documents", [])
    if not isinstance(global_docs_raw, list):
        raise ValueError("suite.documents must be a list")
    global_docs = _parse_docs(global_docs_raw, suite_dir) if global_docs_raw else []

    cases_raw = suite.get("cases", [])
    if not isinstance(cases_raw, list) or not cases_raw:
        raise ValueError("suite.cases must be a non-empty list")

    cfg = RAGConfig()
    cfg = _apply_config_overrides(cfg, suite.get("config", {}))
    cfg = _apply_config_overrides(cfg, config_file_overrides or {})
    cfg = _apply_config_overrides(cfg, config_overrides or {})
    if cli_top_k is not None:
        cfg = _apply_config_overrides(cfg, {"selection.top_k": int(cli_top_k)})

    logger.info("Using RAG config: %s", json.dumps(cfg.to_dict(), ensure_ascii=False))

    rag = RAGSystem(config=cfg, logger=bridge)
    llm = _load_llm_manager(
        argparse.Namespace(
            llm_model=llm_model,
            llm_n_ctx=llm_n_ctx,
            llm_gpu_layers=llm_gpu_layers,
            llm_threads=llm_threads,
        ),
        bridge,
        logger,
    )
    _wire_llm_callbacks(rag, llm)

    state_cache: dict[tuple[tuple[str, str], ...], dict[str, Any]] = {}
    case_results: list[CaseResult] = []
    debug_rows: list[dict[str, Any]] = []

    for idx, case in enumerate(cases_raw, 1):
        if not isinstance(case, dict):
            raise ValueError(f"Case #{idx} must be an object")
        query = str(case.get("query", "")).strip()
        if not query:
            raise ValueError(f"Case #{idx} has empty query")

        case_id = str(case.get("id") or f"case_{idx:03d}")
        case_docs: list[DocEntry]
        if "documents" in case:
            docs_raw = case.get("documents")
            if not isinstance(docs_raw, list):
                raise ValueError(f"{case_id}: documents must be a list")
            case_docs = _parse_docs(docs_raw, suite_dir)
        else:
            case_docs = global_docs
        if not case_docs:
            raise ValueError(f"{case_id}: no documents configured (case and global empty)")

        signature = _docs_signature(case_docs)
        if signature in state_cache:
            rag.load_state(state_cache[signature])
        else:
            _index_docs(rag, case_docs, logger)
            state_cache[signature] = rag.dump_state()

        top_k = int(case.get("top_k", cfg.selection.top_k))
        labels = _parse_case_labels(case.get("labels", []))
        expected_docs = _as_str_list(case.get("gt_docs") or case.get("expected_docs") or [])
        expected_contains = _as_str_list(
            case.get("gt_contains")
            or case.get("expected_contains")
            or case.get("include_quotes")
            or []
        )
        excluded_docs = _as_str_list(case.get("excluded_docs") or [])
        excluded_contains = _as_str_list(
            case.get("excluded_contains") or case.get("exclude_quotes") or []
        )

        t0 = time.perf_counter()
        results, debug = rag.search(query, top_k=top_k, with_debug=True)
        dt = (time.perf_counter() - t0) * 1000.0

        predicted_docs = [str(item.get("name", "")) for item in results if isinstance(item, dict)]
        excerpts       = [str(item.get("excerpt", "")) for item in results if isinstance(item, dict)]
        metrics = _rank_metrics(predicted_docs, expected_docs)
        contains_matches, contains_recall = _contains_recall(expected_contains, excerpts)
        warnings = [str(w) for w in (debug.get("warnings", []) or [])] if isinstance(debug, dict) else []

        # excluded_docs: flag any predicted doc that must NOT appear
        excluded_canon = {_canonical_name(x) for x in excluded_docs}
        excluded_hits  = [p for p in predicted_docs if _canonical_name(p) in excluded_canon]
        if excluded_hits:
            warnings = warnings + [f"excluded_doc appeared in results: {', '.join(excluded_hits)}"]

        excluded_contains_hits = _excluded_contains_hits(excluded_contains, excerpts)
        if excluded_contains_hits:
            warnings = warnings + [
                "excluded_contains appeared in excerpts: "
                + ", ".join(excluded_contains_hits)
            ]

        case_result = CaseResult(
            case_id=case_id,
            query=query,
            labels=labels,
            top_k=top_k,
            duration_ms=dt,
            expected_docs=expected_docs,
            predicted_docs=predicted_docs,
            tp=int(metrics["tp"]),
            fp=int(metrics["fp"]),
            fn=int(metrics["fn"]),
            precision=float(metrics["precision"]),
            recall=float(metrics["recall"]),
            f1=float(metrics["f1"]),
            hit_at_k=float(metrics["hit_at_k"]),
            mrr=float(metrics["mrr"]),
            ap=float(metrics["ap"]),
            ndcg=float(metrics["ndcg"]),
            expected_contains=expected_contains,
            contains_matches=contains_matches,
            contains_recall=contains_recall,
            warnings=warnings,
            excluded_docs=excluded_docs,
            excluded_hits=excluded_hits,
            excluded_contains=excluded_contains,
            excluded_contains_hits=excluded_contains_hits,
        )
        case_results.append(case_result)

        logger.info(
            "Case %s | %.1fms | F1=%.3f P=%.3f R=%.3f Hit=%.0f MRR=%.3f AP=%.3f nDCG=%.3f | expected=%s predicted=%s",
            case_id,
            dt,
            case_result.f1,
            case_result.precision,
            case_result.recall,
            case_result.hit_at_k,
            case_result.mrr,
            case_result.ap,
            case_result.ndcg,
            case_result.expected_docs,
            case_result.predicted_docs,
        )
        for w in warnings:
            logger.warning("Case %s warning: %s", case_id, w)

        debug_rows.append({
            "case_id": case_id,
            "query": query,
            "labels": labels,
            "top_k": top_k,
            "expected_docs": expected_docs,
            "predicted_docs": predicted_docs,
            "metrics": dataclasses.asdict(case_result),
            "results": results,
            "debug": debug,
        })

    summary = _summarise(case_results)
    run_payload = {
        "run_name": run_name,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "suite": str(suite_path.resolve()),
        "config": dataclasses.asdict(cfg),
        "llm": {
            "model_path": str(pathlib.Path(llm_model).resolve()) if llm_model else "",
            "n_ctx": llm_n_ctx,
            "gpu_layers": llm_gpu_layers,
            "threads": llm_threads if llm_threads > 0 else (os.cpu_count() or 4),
            "enabled": bool(llm_model),
        },
        "summary": summary,
        "cases": [dataclasses.asdict(r) for r in case_results],
    }

    _write_json(output_dir / f"{run_name}.summary.json", run_payload)
    _write_jsonl(output_dir / f"{run_name}.debug.jsonl", debug_rows)
    _write_case_csv(output_dir / f"{run_name}.cases.csv", case_results)

    logger.info("Summary written to %s", output_dir / f"{run_name}.summary.json")
    logger.info("Debug rows written to %s", output_dir / f"{run_name}.debug.jsonl")
    return run_payload


def _write_case_csv(path: pathlib.Path, cases: list[CaseResult]):
    cols = [
        "case_id",
        "query",
        "top_k",
        "duration_ms",
        "tp",
        "fp",
        "fn",
        "precision",
        "recall",
        "f1",
        "hit_at_k",
        "mrr",
        "ap",
        "ndcg",
        "contains_matches",
        "contains_recall",
        "labels",
        "expected_docs",
        "predicted_docs",
        "excluded_docs",
        "excluded_hits",
        "excluded_contains",
        "excluded_contains_hits",
        "warnings",
    ]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for c in cases:
            row = dataclasses.asdict(c)
            row["labels"]        = "|".join(c.labels)
            row["expected_docs"] = "|".join(c.expected_docs)
            row["predicted_docs"] = "|".join(c.predicted_docs)
            row["excluded_docs"] = "|".join(c.excluded_docs)
            row["excluded_hits"] = "|".join(c.excluded_hits)
            row["excluded_contains"] = "|".join(c.excluded_contains)
            row["excluded_contains_hits"] = "|".join(c.excluded_contains_hits)
            row["warnings"]      = " | ".join(c.warnings)
            writer.writerow({k: row.get(k, "") for k in cols})


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run RAG evaluation suite")
    p.add_argument("--suite", required=True, help="Path to suite JSON")
    p.add_argument("--output-dir", default="runs/rag_eval", help="Output directory")
    p.add_argument("--run-name", default="", help="Optional run name")

    p.add_argument("--config-json", default="", help="JSON file with RAGConfig overrides")
    p.add_argument(
        "--set",
        action="append",
        default=[],
        help="RAGConfig override key=value (repeatable)",
    )
    p.add_argument("--top-k", type=int, default=None, help="Global top_k override")

    p.add_argument("--llm-model", default="", help="Optional GGUF model for LLM-based RAG steps")
    p.add_argument("--llm-n-ctx", type=int, default=4096)
    p.add_argument("--llm-gpu-layers", type=int, default=0)
    p.add_argument("--llm-threads", type=int, default=0)

    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    suite_path = pathlib.Path(args.suite).expanduser().resolve()
    if not suite_path.exists():
        raise FileNotFoundError(f"Suite file not found: {suite_path}")

    output_dir = pathlib.Path(args.output_dir).expanduser().resolve()
    run_name = args.run_name.strip() or datetime.now().strftime("run_%Y%m%d_%H%M%S")

    config_file_overrides: dict[str, Any] = {}
    if args.config_json:
        config_file_overrides = _load_json(pathlib.Path(args.config_json).expanduser().resolve())

    set_overrides: dict[str, Any] = {}
    for item in args.set:
        k, v = _parse_kv_override(item)
        set_overrides[k] = v

    run_suite(
        suite_path=suite_path,
        output_dir=output_dir,
        run_name=run_name,
        config_overrides=set_overrides,
        config_file_overrides=config_file_overrides,
        cli_top_k=args.top_k,
        llm_model=(args.llm_model.strip() or None),
        llm_n_ctx=args.llm_n_ctx,
        llm_gpu_layers=args.llm_gpu_layers,
        llm_threads=args.llm_threads,
        log_level=args.log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
