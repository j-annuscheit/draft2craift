#!/usr/bin/env python3
"""
PDF -> Markdown evaluation runner.

Purpose
-------
- Run fixed PDF conversion test cases against expected Markdown outputs.
- Compute robust similarity metrics (global + best-match style metrics).
- Classify likely error types (for example too many line breaks).
- Write per-run artifacts similar to the RAG eval tooling.

Usage
-----
python scripts/pdf_eval.py \
  --suite scripts/examples/pdf_suite.example.json \
  --output-dir runs/pdf_eval \
  --run-name baseline
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import difflib
import json
import logging
import pathlib
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Ensure project root is importable when script is launched from any cwd.
_THIS_FILE = pathlib.Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from features.importer.convert import convert_file  # noqa: E402
from features.importer.models import PDFImportSettings  # noqa: E402


_WORD_RE = re.compile(r"\w+(?:[+./-]\w+)*", flags=re.UNICODE)
_PAGE_MARKER_RE = re.compile(r"^\[Seite\s+\d+\]\s*$", flags=re.IGNORECASE)
_ORDERED_RE = re.compile(r"^\s*\d+[.)]\s+")
_BULLET_RE = re.compile(r"^\s*[-+*]\s+")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
_DEFAULT_THRESHOLDS = {
    "char_ratio": 0.92,
    "line_ratio": 0.90,
    "token_f1": 0.90,
    "paragraph_mean": 0.90,
}


@dataclass
class CaseSpec:
    case_id: str
    pdf_path: pathlib.Path
    expected_md_path: pathlib.Path
    labels: list[str]
    settings: PDFImportSettings
    thresholds: dict[str, float]


@dataclass
class CaseResult:
    case_id: str
    labels: list[str]
    pdf_path: str
    expected_path: str
    duration_ms: float
    passed: bool
    fail_reasons: list[str]
    error_tags: list[str]
    char_ratio: float
    line_ratio: float
    token_precision: float
    token_recall: float
    token_f1: float
    best_char_block_ratio: float
    best_line_block_ratio: float
    paragraph_mean: float
    paragraph_coverage_85: float
    newline_delta: int
    blank_line_delta: int
    heading_delta: int
    list_delta: int
    table_line_delta: int
    page_marker_delta: int
    short_prose_line_delta: int
    inserted_lines: int
    deleted_lines: int
    replaced_lines: int
    expected_chars: int
    actual_chars: int


def setup_logger(
    output_dir: pathlib.Path,
    run_name: str,
    level: str,
) -> logging.Logger:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"pdf_eval.{run_name}")
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


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"Expected JSON object in suite: {path}")
    return raw


def _read_text(path: pathlib.Path) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _write_text(path: pathlib.Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _write_json(path: pathlib.Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _normalize_text(text: str) -> str:
    src = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in src.split("\n")]
    clean = "\n".join(lines).strip()
    return clean


def _parse_labels(raw: Any) -> list[str]:
    if raw is None:
        return []
    values: list[str] = []
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw]
    else:
        raise ValueError("case.labels must be string or list[str]")

    out: list[str] = []
    seen: set[str] = set()
    for label in values:
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def _resolve_path(path_s: str, suite_dir: pathlib.Path) -> pathlib.Path:
    raw = pathlib.Path(str(path_s))
    if raw.is_absolute():
        return raw
    return (suite_dir / raw).resolve()


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


def _build_settings(raw: dict[str, Any]) -> PDFImportSettings:
    fields = {f.name for f in dataclasses.fields(PDFImportSettings)}
    clean: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        if key not in fields:
            raise KeyError(f"Unknown PDFImportSettings key: {key}")
        clean[key] = value
    return PDFImportSettings(**clean)


def _parse_case(
    raw_case: dict[str, Any],
    *,
    suite_dir: pathlib.Path,
    default_settings: dict[str, Any],
    default_thresholds: dict[str, float],
    cli_overrides: dict[str, Any],
) -> CaseSpec:
    case_id = str(
        raw_case.get("id")
        or raw_case.get("name")
        or raw_case.get("case_id")
        or ""
    ).strip()
    if not case_id:
        raise ValueError("Each case requires id")

    pdf_field = raw_case.get("pdf") or raw_case.get("pdf_path")
    exp_field = (
        raw_case.get("expected")
        or raw_case.get("expected_md")
        or raw_case.get("expected_markdown")
    )
    if not pdf_field or not exp_field:
        raise ValueError(f"Case '{case_id}' requires 'pdf' and 'expected'")

    pdf_path = _resolve_path(str(pdf_field), suite_dir)
    expected_path = _resolve_path(str(exp_field), suite_dir)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Case '{case_id}' missing PDF: {pdf_path}")
    if not expected_path.exists():
        raise FileNotFoundError(
            f"Case '{case_id}' missing expected markdown: {expected_path}"
        )

    labels = _parse_labels(raw_case.get("labels"))

    merged_settings = dict(default_settings)
    merged_settings.update(raw_case.get("settings") or {})
    merged_settings.update(cli_overrides)
    settings = _build_settings(merged_settings)

    thresholds = dict(default_thresholds)
    raw_thr = raw_case.get("thresholds") or {}
    if not isinstance(raw_thr, dict):
        raise ValueError(f"Case '{case_id}' thresholds must be object")
    for key, value in raw_thr.items():
        try:
            thresholds[str(key)] = float(value)
        except Exception as exc:
            raise ValueError(
                f"Case '{case_id}' invalid threshold '{key}={value}'"
            ) from exc

    return CaseSpec(
        case_id=case_id,
        pdf_path=pdf_path,
        expected_md_path=expected_path,
        labels=labels,
        settings=settings,
        thresholds=thresholds,
    )


def _tokenize(text: str) -> list[str]:
    return [token.casefold() for token in _WORD_RE.findall(text)]


def _split_paragraphs(text: str) -> list[str]:
    chunks = re.split(r"\n\s*\n+", text.strip())
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _count_short_prose_lines(lines: list[str]) -> int:
    count = 0
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if (
            _HEADING_RE.match(text)
            or _BULLET_RE.match(text)
            or _ORDERED_RE.match(text)
            or _PAGE_MARKER_RE.match(text)
            or _TABLE_RE.match(text)
        ):
            continue
        if len(text) <= 70:
            count += 1
    return count


def _collect_delta_stats(expected_lines: list[str], actual_lines: list[str]) -> dict[str, int]:
    exp_headings = sum(1 for line in expected_lines if _HEADING_RE.match(line))
    act_headings = sum(1 for line in actual_lines if _HEADING_RE.match(line))
    exp_list = sum(
        1
        for line in expected_lines
        if _BULLET_RE.match(line) or _ORDERED_RE.match(line)
    )
    act_list = sum(
        1
        for line in actual_lines
        if _BULLET_RE.match(line) or _ORDERED_RE.match(line)
    )
    exp_table = sum(1 for line in expected_lines if _TABLE_RE.match(line))
    act_table = sum(1 for line in actual_lines if _TABLE_RE.match(line))
    exp_page = sum(1 for line in expected_lines if _PAGE_MARKER_RE.match(line))
    act_page = sum(1 for line in actual_lines if _PAGE_MARKER_RE.match(line))
    exp_blank = sum(1 for line in expected_lines if not line.strip())
    act_blank = sum(1 for line in actual_lines if not line.strip())
    exp_short = _count_short_prose_lines(expected_lines)
    act_short = _count_short_prose_lines(actual_lines)
    return {
        "newline_delta": len(actual_lines) - len(expected_lines),
        "blank_line_delta": act_blank - exp_blank,
        "heading_delta": act_headings - exp_headings,
        "list_delta": act_list - exp_list,
        "table_line_delta": act_table - exp_table,
        "page_marker_delta": act_page - exp_page,
        "short_prose_line_delta": act_short - exp_short,
    }


def _token_scores(expected: str, actual: str) -> tuple[float, float, float]:
    exp_tokens = _tokenize(expected)
    act_tokens = _tokenize(actual)
    if not exp_tokens and not act_tokens:
        return 1.0, 1.0, 1.0
    if not exp_tokens or not act_tokens:
        return 0.0, 0.0, 0.0

    exp_c = Counter(exp_tokens)
    act_c = Counter(act_tokens)
    tp = sum((exp_c & act_c).values())
    precision = tp / len(act_tokens) if act_tokens else 0.0
    recall = tp / len(exp_tokens) if exp_tokens else 0.0
    if precision + recall == 0:
        return precision, recall, 0.0
    f1 = 2.0 * precision * recall / (precision + recall)
    return precision, recall, f1


def _paragraph_best_scores(expected: str, actual: str) -> tuple[float, float]:
    exp_paras = _split_paragraphs(expected)
    act_paras = _split_paragraphs(actual)
    if not exp_paras and not act_paras:
        return 1.0, 1.0
    if not exp_paras:
        return 0.0, 0.0
    if not act_paras:
        return 0.0, 0.0

    best: list[float] = []
    for para in exp_paras:
        score = 0.0
        for cand in act_paras:
            ratio = difflib.SequenceMatcher(
                None,
                para,
                cand,
                autojunk=False,
            ).ratio()
            if ratio > score:
                score = ratio
        best.append(score)

    mean_score = statistics.mean(best) if best else 0.0
    coverage_85 = (
        sum(1 for score in best if score >= 0.85) / len(best)
        if best
        else 0.0
    )
    return mean_score, coverage_85


def _compare_text(expected: str, actual: str) -> tuple[dict[str, Any], dict[str, Any]]:
    exp = _normalize_text(expected)
    act = _normalize_text(actual)

    sm_char = difflib.SequenceMatcher(None, exp, act, autojunk=False)
    sm_line = difflib.SequenceMatcher(
        None,
        exp.splitlines(),
        act.splitlines(),
        autojunk=False,
    )

    char_blocks = sm_char.get_matching_blocks()
    line_blocks = sm_line.get_matching_blocks()
    best_char_block = max((blk.size for blk in char_blocks), default=0)
    best_line_block = max((blk.size for blk in line_blocks), default=0)
    exp_lines = exp.splitlines()
    act_lines = act.splitlines()
    line_opcodes = sm_line.get_opcodes()

    inserted = 0
    deleted = 0
    replaced = 0
    for tag, i1, i2, j1, j2 in line_opcodes:
        if tag == "insert":
            inserted += j2 - j1
        elif tag == "delete":
            deleted += i2 - i1
        elif tag == "replace":
            replaced += max(i2 - i1, j2 - j1)

    token_precision, token_recall, token_f1 = _token_scores(exp, act)
    paragraph_mean, paragraph_coverage_85 = _paragraph_best_scores(exp, act)

    stats = _collect_delta_stats(exp_lines, act_lines)
    metrics = {
        "char_ratio": sm_char.ratio(),
        "line_ratio": sm_line.ratio(),
        "token_precision": token_precision,
        "token_recall": token_recall,
        "token_f1": token_f1,
        "best_char_block_ratio": (
            best_char_block / max(1, len(exp))
        ),
        "best_line_block_ratio": (
            best_line_block / max(1, len(exp_lines))
            if exp_lines
            else 1.0
        ),
        "paragraph_mean": paragraph_mean,
        "paragraph_coverage_85": paragraph_coverage_85,
        "inserted_lines": inserted,
        "deleted_lines": deleted,
        "replaced_lines": replaced,
        "expected_chars": len(exp),
        "actual_chars": len(act),
    }
    metrics.update(stats)

    diff_preview = "\n".join(
        difflib.unified_diff(
            exp_lines,
            act_lines,
            fromfile="expected",
            tofile="actual",
            n=2,
            lineterm="",
        )
    )
    debug = {
        "expected_normalized": exp,
        "actual_normalized": act,
        "line_opcodes": line_opcodes,
        "diff_preview": diff_preview[:12000],
    }
    return metrics, debug


def _detect_error_tags(metrics: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    newline_delta = int(metrics["newline_delta"])
    short_line_delta = int(metrics["short_prose_line_delta"])
    if newline_delta > 8 or short_line_delta > 6:
        tags.append("too_many_line_breaks")
    if newline_delta < -8:
        tags.append("too_few_line_breaks")
    if abs(int(metrics["heading_delta"])) >= 2:
        tags.append("heading_structure_drift")
    if abs(int(metrics["list_delta"])) >= 2:
        tags.append("list_structure_drift")
    if abs(int(metrics["table_line_delta"])) >= 2:
        tags.append("table_structure_drift")
    if abs(int(metrics["page_marker_delta"])) >= 1:
        tags.append("page_marker_drift")
    if int(metrics["deleted_lines"]) >= 8:
        tags.append("missing_content")
    if int(metrics["inserted_lines"]) >= 8:
        tags.append("extra_content")
    if float(metrics["paragraph_mean"]) < 0.80:
        tags.append("paragraph_alignment_low")
    if float(metrics["token_f1"]) < 0.85:
        tags.append("token_match_low")
    return tags


def _evaluate_pass(
    metrics: dict[str, Any],
    thresholds: dict[str, float],
) -> tuple[bool, list[str]]:
    checks = {
        "char_ratio": float(metrics["char_ratio"]),
        "line_ratio": float(metrics["line_ratio"]),
        "token_f1": float(metrics["token_f1"]),
        "paragraph_mean": float(metrics["paragraph_mean"]),
    }
    failed: list[str] = []
    for key, score in checks.items():
        threshold = float(thresholds.get(key, _DEFAULT_THRESHOLDS[key]))
        if score < threshold:
            failed.append(f"{key}={score:.4f} < {threshold:.4f}")
    return (len(failed) == 0), failed


def _evaluate_case(
    case: CaseSpec,
    *,
    artifacts_dir: pathlib.Path | None,
    logger: logging.Logger,
) -> tuple[CaseResult, dict[str, Any]]:
    expected = _read_text(case.expected_md_path)

    t0 = time.perf_counter()
    actual = convert_file(str(case.pdf_path), case.settings)
    duration_ms = (time.perf_counter() - t0) * 1000.0

    metrics, debug = _compare_text(expected, actual)
    error_tags = _detect_error_tags(metrics)
    passed, fail_reasons = _evaluate_pass(metrics, case.thresholds)

    if artifacts_dir is not None:
        _write_text(artifacts_dir / f"{case.case_id}.actual.md", actual)
        _write_text(artifacts_dir / f"{case.case_id}.expected.md", expected)
        _write_text(
            artifacts_dir / f"{case.case_id}.diff.txt",
            str(debug.get("diff_preview", "")),
        )

    result = CaseResult(
        case_id=case.case_id,
        labels=list(case.labels),
        pdf_path=str(case.pdf_path),
        expected_path=str(case.expected_md_path),
        duration_ms=duration_ms,
        passed=passed,
        fail_reasons=fail_reasons,
        error_tags=error_tags,
        char_ratio=float(metrics["char_ratio"]),
        line_ratio=float(metrics["line_ratio"]),
        token_precision=float(metrics["token_precision"]),
        token_recall=float(metrics["token_recall"]),
        token_f1=float(metrics["token_f1"]),
        best_char_block_ratio=float(metrics["best_char_block_ratio"]),
        best_line_block_ratio=float(metrics["best_line_block_ratio"]),
        paragraph_mean=float(metrics["paragraph_mean"]),
        paragraph_coverage_85=float(metrics["paragraph_coverage_85"]),
        newline_delta=int(metrics["newline_delta"]),
        blank_line_delta=int(metrics["blank_line_delta"]),
        heading_delta=int(metrics["heading_delta"]),
        list_delta=int(metrics["list_delta"]),
        table_line_delta=int(metrics["table_line_delta"]),
        page_marker_delta=int(metrics["page_marker_delta"]),
        short_prose_line_delta=int(metrics["short_prose_line_delta"]),
        inserted_lines=int(metrics["inserted_lines"]),
        deleted_lines=int(metrics["deleted_lines"]),
        replaced_lines=int(metrics["replaced_lines"]),
        expected_chars=int(metrics["expected_chars"]),
        actual_chars=int(metrics["actual_chars"]),
    )
    logger.info(
        "[%s] pass=%s char=%.4f line=%.4f token_f1=%.4f para=%.4f tags=%s",
        case.case_id,
        passed,
        result.char_ratio,
        result.line_ratio,
        result.token_f1,
        result.paragraph_mean,
        ",".join(error_tags) if error_tags else "-",
    )
    return result, debug


def _write_cases_csv(path: pathlib.Path, rows: list[CaseResult]):
    cols = [
        "case_id",
        "labels",
        "passed",
        "duration_ms",
        "char_ratio",
        "line_ratio",
        "token_precision",
        "token_recall",
        "token_f1",
        "best_char_block_ratio",
        "best_line_block_ratio",
        "paragraph_mean",
        "paragraph_coverage_85",
        "newline_delta",
        "blank_line_delta",
        "heading_delta",
        "list_delta",
        "table_line_delta",
        "page_marker_delta",
        "short_prose_line_delta",
        "inserted_lines",
        "deleted_lines",
        "replaced_lines",
        "expected_chars",
        "actual_chars",
        "error_tags",
        "fail_reasons",
        "pdf_path",
        "expected_path",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            item = dataclasses.asdict(row)
            item["labels"] = ",".join(row.labels)
            item["error_tags"] = ",".join(row.error_tags)
            item["fail_reasons"] = " | ".join(row.fail_reasons)
            writer.writerow({key: item.get(key, "") for key in cols})


def _summarize(rows: list[CaseResult]) -> dict[str, Any]:
    if not rows:
        return {
            "cases": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "macro": {},
            "error_tag_hist": {},
            "label_breakdown": {},
        }

    def _avg(field: str) -> float:
        return statistics.mean(float(getattr(item, field)) for item in rows)

    error_hist: dict[str, int] = {}
    for row in rows:
        for tag in row.error_tags:
            error_hist[tag] = error_hist.get(tag, 0) + 1

    label_rows: dict[str, list[CaseResult]] = {}
    for row in rows:
        if not row.labels:
            label_rows.setdefault("__unlabeled__", []).append(row)
        for label in row.labels:
            label_rows.setdefault(label, []).append(row)

    label_breakdown: dict[str, Any] = {}
    for label, items in label_rows.items():
        label_breakdown[label] = {
            "cases": len(items),
            "pass_rate": sum(1 for it in items if it.passed) / len(items),
            "char_ratio": statistics.mean(it.char_ratio for it in items),
            "line_ratio": statistics.mean(it.line_ratio for it in items),
            "token_f1": statistics.mean(it.token_f1 for it in items),
            "paragraph_mean": statistics.mean(it.paragraph_mean for it in items),
        }

    passed = sum(1 for row in rows if row.passed)
    return {
        "cases": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "pass_rate": passed / len(rows),
        "macro": {
            "char_ratio": _avg("char_ratio"),
            "line_ratio": _avg("line_ratio"),
            "token_f1": _avg("token_f1"),
            "paragraph_mean": _avg("paragraph_mean"),
            "paragraph_coverage_85": _avg("paragraph_coverage_85"),
            "duration_ms": _avg("duration_ms"),
        },
        "error_tag_hist": dict(sorted(error_hist.items())),
        "label_breakdown": label_breakdown,
    }


def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    suite_path = pathlib.Path(args.suite).expanduser().resolve()
    if not suite_path.exists():
        raise FileNotFoundError(f"Suite file not found: {suite_path}")
    suite_dir = suite_path.parent
    output_dir = pathlib.Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_name = str(args.run_name or f"pdf_eval_{datetime.now():%Y%m%d_%H%M%S}")
    logger = setup_logger(output_dir, run_name, args.log_level)

    suite = _load_json(suite_path)
    raw_defaults = suite.get("defaults") or {}
    if not isinstance(raw_defaults, dict):
        raise ValueError("suite.defaults must be an object")

    default_settings = raw_defaults.get("settings") or {}
    if not isinstance(default_settings, dict):
        raise ValueError("defaults.settings must be an object")

    default_thresholds = dict(_DEFAULT_THRESHOLDS)
    raw_thr = raw_defaults.get("thresholds") or {}
    if not isinstance(raw_thr, dict):
        raise ValueError("defaults.thresholds must be an object")
    for key, value in raw_thr.items():
        default_thresholds[str(key)] = float(value)

    cli_overrides: dict[str, Any] = {}
    for item in args.set or []:
        key, value = _parse_kv_override(item)
        cli_overrides[key] = value

    raw_cases = suite.get("cases") or []
    if not isinstance(raw_cases, list):
        raise ValueError("suite.cases must be a list")

    all_cases: list[CaseSpec] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("Each case entry must be an object")
        all_cases.append(
            _parse_case(
                raw,
                suite_dir=suite_dir,
                default_settings=default_settings,
                default_thresholds=default_thresholds,
                cli_overrides=cli_overrides,
            )
        )

    filter_labels = _parse_labels(args.labels) if args.labels else []
    cases = all_cases
    if filter_labels:
        wanted = {label.casefold() for label in filter_labels}
        cases = [
            case for case in all_cases
            if wanted.intersection({label.casefold() for label in case.labels})
        ]
    if args.max_cases and args.max_cases > 0:
        cases = cases[: int(args.max_cases)]

    if not cases:
        raise ValueError("No cases selected after filters")

    logger.info(
        "Loaded %d/%d cases from %s",
        len(cases),
        len(all_cases),
        suite_path,
    )
    if filter_labels:
        logger.info("Label filter: %s", ",".join(filter_labels))
    if cli_overrides:
        logger.info("CLI PDF setting overrides: %s", json.dumps(cli_overrides))

    artifacts_dir = (
        output_dir / f"{run_name}.artifacts" if args.write_artifacts else None
    )

    rows: list[CaseResult] = []
    debug_rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for case in cases:
        result, debug = _evaluate_case(
            case,
            artifacts_dir=artifacts_dir,
            logger=logger,
        )
        rows.append(result)
        debug_rows.append(
            {
                "case_id": case.case_id,
                "labels": case.labels,
                "thresholds": case.thresholds,
                "result": dataclasses.asdict(result),
                "diff_preview": debug.get("diff_preview", ""),
                "line_opcodes": debug.get("line_opcodes", []),
            }
        )

    elapsed = time.perf_counter() - started
    summary = _summarize(rows)
    summary["elapsed_sec"] = elapsed
    summary["suite"] = str(suite_path)
    summary["run_name"] = run_name
    summary["settings_overrides"] = cli_overrides
    summary["filters"] = {"labels": filter_labels, "max_cases": args.max_cases}

    _write_cases_csv(output_dir / f"{run_name}.cases.csv", rows)
    _write_json(output_dir / f"{run_name}.summary.json", summary)
    with open(
        output_dir / f"{run_name}.debug.jsonl",
        "w",
        encoding="utf-8",
    ) as fh:
        for row in debug_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    logger.info(
        "Done | cases=%d pass=%d fail=%d pass_rate=%.3f elapsed=%.2fs",
        summary["cases"],
        summary["passed"],
        summary["failed"],
        summary["pass_rate"],
        elapsed,
    )
    return {
        "summary": summary,
        "cases": [dataclasses.asdict(item) for item in rows],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PDF -> Markdown eval runner")
    parser.add_argument(
        "--suite",
        required=True,
        help="Path to PDF eval suite JSON",
    )
    parser.add_argument(
        "--output-dir",
        default="runs/pdf_eval",
        help="Directory for run artifacts",
    )
    parser.add_argument(
        "--run-name",
        default="",
        help="Run name prefix for output files",
    )
    parser.add_argument(
        "--labels",
        default="",
        help="Comma-separated label filter (only matching cases are run)",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=0,
        help="Optional limit for selected cases",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        help="Override PDFImportSettings, key=value (repeatable)",
    )
    parser.add_argument(
        "--write-artifacts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write per-case expected/actual/diff artifacts",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    try:
        run_suite(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
