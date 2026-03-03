#!/usr/bin/env python3
"""
Pairwise LLM-as-a-Judge evaluation runner.

Goal
----
- Evaluate whether a local LLM judge picks the correct winner between
  two candidate answers for the same user prompt.

Usage
-----
python scripts/judge_eval.py \
  --suite scripts/examples/judge_suite.example.json \
  --output-dir runs/judge_eval \
  --run-name demo_judge \
  --llm-model /path/to/model.gguf
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
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

from services.llm.manager import LLMManager  # noqa: E402

DEFAULT_JUDGE_PROMPT = (
    "Du bist ein strenger Pairwise-Judge fuer Antwortqualitaet.\n"
    "Vergleiche Antwort A und Antwort B zur Nutzeraufgabe.\n"
    "Bewerte in dieser Reihenfolge: "
    "1) Korrektheit/Faktentreue, "
    "2) Instruktionsbefolgung, "
    "3) Vollstaendigkeit, "
    "4) Klarheit.\n"
    "Wenn eine Antwort halluziniert oder Vorgaben verletzt, "
    "bevorzuge die andere Antwort.\n"
    "Ausgabeformat strikt als JSON-Objekt:\n"
    "{\"winner\":\"A|B\",\"confidence\":0.0,\"reason\":\"<kurz>\"}\n"
    "Nur JSON, kein Markdown, keine Zusatzsaetze."
)


@dataclass
class CaseSpec:
    case_id: str
    labels: list[str]
    prompt_text: str
    answer_a: str
    answer_b: str
    expected_winner: str
    prompt_max_chars: int
    answer_max_chars: int


@dataclass
class JudgeDecision:
    winner: str
    confidence: float | None
    reason: str
    parsed: bool
    parse_mode: str


@dataclass
class CaseResult:
    case_id: str
    labels: list[str]
    expected_winner: str
    predicted_winner: str
    correct: bool
    parsed: bool
    parse_mode: str
    confidence: float | None
    duration_ms: float
    prompt_chars: int
    answer_a_chars: int
    answer_b_chars: int
    fail_reasons: list[str]
    reason: str
    raw_preview: str


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
    logger = logging.getLogger(f"judge_eval.{run_name}")
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


def _resolve_path(raw: str, suite_dir: pathlib.Path) -> pathlib.Path:
    p = pathlib.Path(str(raw))
    if p.is_absolute():
        return p
    return (suite_dir / p).resolve()


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


def _normalise_winner(value: Any) -> str:
    if isinstance(value, (int, float)):
        if int(value) == 1:
            return "A"
        if int(value) == 2:
            return "B"
    raw = str(value or "").strip().casefold()
    mapping = {
        "a": "A",
        "answer_a": "A",
        "answer a": "A",
        "option_a": "A",
        "option a": "A",
        "candidate_a": "A",
        "candidate a": "A",
        "left": "A",
        "1": "A",
        "b": "B",
        "answer_b": "B",
        "answer b": "B",
        "option_b": "B",
        "option b": "B",
        "candidate_b": "B",
        "candidate b": "B",
        "right": "B",
        "2": "B",
    }
    return mapping.get(raw, "")


def _extract_case_text(
    raw: dict[str, Any],
    *,
    value_keys: tuple[str, ...],
    path_keys: tuple[str, ...],
    suite_dir: pathlib.Path,
) -> str:
    for key in value_keys:
        value = raw.get(key, None)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    for key in path_keys:
        value = raw.get(key, None)
        if value is None:
            continue
        path_raw = str(value).strip()
        if not path_raw:
            continue
        path = _resolve_path(path_raw, suite_dir)
        if not path.exists():
            raise FileNotFoundError(f"Missing file for '{key}': {path}")
        return _read_text(path).strip()
    return ""


def _clip_text(text: str, limit: int) -> str:
    payload = str(text or "")
    clean_limit = max(256, int(limit))
    if len(payload) <= clean_limit:
        return payload
    suffix = "\n\n[TRUNCATED]"
    head = payload[: max(0, clean_limit - len(suffix))]
    return head + suffix


def _build_judge_prompt(
    judge_system_prompt: str,
    *,
    user_prompt: str,
    answer_a: str,
    answer_b: str,
) -> str:
    user_block = (
        "Nutzeraufgabe:\n"
        f"{user_prompt}\n\n"
        "Antwort A:\n"
        "<A>\n"
        f"{answer_a}\n"
        "</A>\n\n"
        "Antwort B:\n"
        "<B>\n"
        f"{answer_b}\n"
        "</B>\n\n"
        "Waehle den besseren Kandidaten und gib jetzt nur das JSON aus."
    )
    return (
        "<|system|>\n"
        f"{judge_system_prompt}\n"
        "<|user|>\n"
        f"{user_block}\n"
        "<|assistant|>\n"
    )


def _load_llm_manager(
    *,
    args: argparse.Namespace,
    log_bridge: EvalLoggerBridge,
    logger: logging.Logger,
) -> LLMManager:
    model_path = pathlib.Path(str(args.llm_model or "")).expanduser().resolve()
    if not str(args.llm_model or "").strip():
        raise ValueError("--llm-model is required for judge evaluation")
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


def _load_judge_prompt(
    *,
    args: argparse.Namespace,
    logger: logging.Logger,
) -> tuple[str, dict[str, str]]:
    file_arg = str(args.judge_prompt_file or "").strip()
    if file_arg:
        path = pathlib.Path(file_arg).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Judge prompt file not found: {path}")
        text = _read_text(path).strip()
        if text:
            logger.info("Judge prompt loaded from file: %s", path)
            return text, {"source": "file", "path": str(path), "key": ""}

    key = str(args.judge_prompt_key or "").strip() or "judge_pairwise_system"
    prompts_json_arg = str(args.prompts_json or "").strip()
    default_path = (_PROJECT_ROOT / "prompts" / "defaults.json").resolve()
    candidate_paths: list[pathlib.Path] = []
    if prompts_json_arg:
        candidate_paths.append(pathlib.Path(prompts_json_arg).expanduser().resolve())
    if default_path not in candidate_paths:
        candidate_paths.append(default_path)

    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            data = _load_json(path)
            value = str(data.get(key, "") or "").strip()
            if value:
                logger.info(
                    "Judge prompt loaded from json: %s (key=%s)",
                    path,
                    key,
                )
                return value, {"source": "json", "path": str(path), "key": key}
        except Exception as exc:
            logger.warning(
                "Judge prompt json could not be read (%s): %s",
                path,
                exc,
            )

    logger.info("Judge prompt fallback: built-in default")
    return DEFAULT_JUDGE_PROMPT, {"source": "builtin", "path": "", "key": key}


def _llm_generate(
    llm: LLMManager,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float,
    top_p: float,
    repeat_penalty: float,
    seed: int,
) -> str:
    model = llm.worker._model
    kwargs: dict[str, Any] = {
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "top_p": float(top_p),
        "repeat_penalty": float(repeat_penalty),
        "stop": ["<|"],
        "stream": False,
    }
    if int(seed) >= 0:
        kwargs["seed"] = int(seed)
    try:
        result = model(prompt, **kwargs)
    except TypeError as exc:
        # Compatibility fallback for bindings without per-call seed argument.
        if "seed" not in str(exc):
            raise
        kwargs.pop("seed", None)
        result = model(prompt, **kwargs)
    return str(result["choices"][0].get("text", "") or "")


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(raw[idx:])
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _parse_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return None
    if conf > 1.0 and conf <= 100.0:
        conf = conf / 100.0
    return max(0.0, min(1.0, conf))


def _extract_winner_from_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    stripped = raw.strip().upper()
    if stripped in {"A", "B"}:
        return stripped

    patterns = (
        r"\b(?:winner|choice|auswahl|entscheidung|selected|pick)\s*[:=-]?\s*([AB])\b",
        r"\b(?:antwort|answer|option|kandidat|candidate)\s*([AB])\s*(?:ist|is|wins|gewinnt|better|besser)\b",
        r"\b([AB])\s*(?:ist|is)\s*(?:besser|better)\b",
    )
    upper = raw.upper()
    for pattern in patterns:
        match = re.search(pattern, upper, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).upper()
        if candidate in {"A", "B"}:
            return candidate
    return ""


def _parse_judge_output(raw_output: str) -> JudgeDecision:
    raw = str(raw_output or "").strip()
    obj = _extract_json_object(raw)
    if isinstance(obj, dict):
        winner = _normalise_winner(
            obj.get("winner")
            or obj.get("choice")
            or obj.get("selected")
            or obj.get("pick")
            or ""
        )
        reason = str(
            obj.get("reason")
            or obj.get("rationale")
            or obj.get("why")
            or ""
        ).strip()
        confidence = _parse_confidence(
            obj.get("confidence")
            or obj.get("score")
            or obj.get("probability")
            or obj.get("certainty")
        )
        if winner:
            return JudgeDecision(
                winner=winner,
                confidence=confidence,
                reason=reason,
                parsed=True,
                parse_mode="json",
            )

    winner = _extract_winner_from_text(raw)
    if winner:
        return JudgeDecision(
            winner=winner,
            confidence=None,
            reason="",
            parsed=True,
            parse_mode="regex",
        )

    return JudgeDecision(
        winner="",
        confidence=None,
        reason="",
        parsed=False,
        parse_mode="unparsed",
    )


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

    prompt_text = _extract_case_text(
        raw,
        value_keys=("prompt", "query", "instruction"),
        path_keys=("prompt_path", "query_path", "instruction_path"),
        suite_dir=suite_dir,
    )
    if not prompt_text:
        raise ValueError(f"Case '{case_id}' missing prompt")

    answer_a = _extract_case_text(
        raw,
        value_keys=("answer_a", "answer_winner", "candidate_a", "result_a", "a"),
        path_keys=("answer_a_path", "candidate_a_path", "result_a_path", "a_path"),
        suite_dir=suite_dir,
    )
    answer_b = _extract_case_text(
        raw,
        value_keys=("answer_b", "answer_loser", "candidate_b", "result_b", "b"),
        path_keys=("answer_b_path", "candidate_b_path", "result_b_path", "b_path"),
        suite_dir=suite_dir,
    )
    if not answer_a or not answer_b:
        raise ValueError(f"Case '{case_id}' requires both answer_a and answer_b")

    expected = _normalise_winner(
        raw.get("winner")
        or raw.get("correct")
        or raw.get("expected")
        or raw.get("label")
        or ("A" if (raw.get("answer_winner") is not None and raw.get("answer_loser") is not None) else "")
        or ""
    )
    if expected not in {"A", "B"}:
        raise ValueError(f"Case '{case_id}' has invalid winner (expected A/B)")

    labels = _normalise_labels(raw.get("labels"))

    prompt_max_chars = _safe_int(
        raw.get("prompt_max_chars", defaults.get("prompt_max_chars", 8000)),
        8000,
    )
    answer_max_chars = _safe_int(
        raw.get("answer_max_chars", defaults.get("answer_max_chars", 12000)),
        12000,
    )

    if "prompt_max_chars" in cli:
        prompt_max_chars = _safe_int(cli["prompt_max_chars"], prompt_max_chars)
    if "answer_max_chars" in cli:
        answer_max_chars = _safe_int(cli["answer_max_chars"], answer_max_chars)

    return CaseSpec(
        case_id=case_id,
        labels=labels,
        prompt_text=prompt_text,
        answer_a=answer_a,
        answer_b=answer_b,
        expected_winner=expected,
        prompt_max_chars=max(256, prompt_max_chars),
        answer_max_chars=max(256, answer_max_chars),
    )


def _evaluate_case(
    case: CaseSpec,
    *,
    llm: LLMManager,
    judge_prompt: str,
    args: argparse.Namespace,
    logger: logging.Logger,
    artifacts_dir: pathlib.Path | None,
) -> CaseResult:
    clipped_prompt = _clip_text(case.prompt_text, case.prompt_max_chars)
    clipped_a = _clip_text(case.answer_a, case.answer_max_chars)
    clipped_b = _clip_text(case.answer_b, case.answer_max_chars)

    llm_prompt = _build_judge_prompt(
        judge_prompt,
        user_prompt=clipped_prompt,
        answer_a=clipped_a,
        answer_b=clipped_b,
    )

    t0 = time.perf_counter()
    raw_output = _llm_generate(
        llm,
        llm_prompt,
        max_tokens=args.judge_max_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        repeat_penalty=args.repeat_penalty,
        seed=args.seed,
    )
    duration_ms = (time.perf_counter() - t0) * 1000.0

    decision = _parse_judge_output(raw_output)
    predicted = decision.winner
    correct = predicted == case.expected_winner and bool(predicted)

    fail_reasons: list[str] = []
    if not decision.parsed:
        fail_reasons.append("parse_failed")
    if decision.parsed and not correct:
        fail_reasons.append(
            f"wrong_winner(pred={predicted or '?'} exp={case.expected_winner})"
        )

    if artifacts_dir is not None:
        payload = {
            "case": dataclasses.asdict(case),
            "decision": dataclasses.asdict(decision),
            "metrics": {
                "correct": correct,
                "duration_ms": duration_ms,
            },
            "raw_output": raw_output,
            "llm_prompt": llm_prompt,
        }
        _write_json(artifacts_dir / f"{case.case_id}.json", payload)
        _write_text(artifacts_dir / f"{case.case_id}.prompt.txt", llm_prompt)
        _write_text(artifacts_dir / f"{case.case_id}.raw.txt", raw_output)

    logger.info(
        "[%s] correct=%s expected=%s predicted=%s parse=%s mode=%s conf=%s",
        case.case_id,
        correct,
        case.expected_winner,
        predicted or "?",
        decision.parsed,
        decision.parse_mode,
        (
            f"{decision.confidence:.3f}"
            if isinstance(decision.confidence, float)
            else "-"
        ),
    )

    return CaseResult(
        case_id=case.case_id,
        labels=case.labels,
        expected_winner=case.expected_winner,
        predicted_winner=predicted,
        correct=correct,
        parsed=decision.parsed,
        parse_mode=decision.parse_mode,
        confidence=decision.confidence,
        duration_ms=duration_ms,
        prompt_chars=len(clipped_prompt),
        answer_a_chars=len(clipped_a),
        answer_b_chars=len(clipped_b),
        fail_reasons=fail_reasons,
        reason=decision.reason,
        raw_preview=raw_output[:240].replace("\n", " ").strip(),
    )


def _write_cases_csv(path: pathlib.Path, rows: list[CaseResult]) -> None:
    cols = [
        "case_id",
        "labels",
        "expected_winner",
        "predicted_winner",
        "correct",
        "parsed",
        "parse_mode",
        "confidence",
        "duration_ms",
        "prompt_chars",
        "answer_a_chars",
        "answer_b_chars",
        "reason",
        "raw_preview",
        "fail_reasons",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            rec = dataclasses.asdict(row)
            rec["labels"] = ",".join(row.labels)
            rec["confidence"] = (
                f"{row.confidence:.4f}"
                if isinstance(row.confidence, float)
                else ""
            )
            rec["fail_reasons"] = " | ".join(row.fail_reasons)
            writer.writerow({k: rec.get(k, "") for k in cols})


def _summarize(
    rows: list[CaseResult],
    *,
    threshold_accuracy: float,
) -> dict[str, Any]:
    if not rows:
        return {
            "cases": 0,
            "correct": 0,
            "incorrect": 0,
            "accuracy": 0.0,
            "parsed_rate": 0.0,
            "avg_confidence": 0.0,
            "avg_duration_ms": 0.0,
            "threshold_accuracy": threshold_accuracy,
            "passed": False,
        }

    total = len(rows)
    correct = sum(1 for row in rows if row.correct)
    parsed = sum(1 for row in rows if row.parsed)
    confidences = [
        row.confidence
        for row in rows
        if isinstance(row.confidence, float)
    ]
    accuracy = correct / total
    summary = {
        "cases": total,
        "correct": correct,
        "incorrect": total - correct,
        "accuracy": accuracy,
        "parsed_rate": parsed / total,
        "avg_confidence": statistics.fmean(confidences) if confidences else 0.0,
        "avg_duration_ms": statistics.fmean(row.duration_ms for row in rows),
        "threshold_accuracy": threshold_accuracy,
        "passed": accuracy >= threshold_accuracy,
    }
    return summary


def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    suite_path = pathlib.Path(args.suite).expanduser().resolve()
    if not suite_path.exists():
        raise FileNotFoundError(f"Suite file not found: {suite_path}")
    suite_dir = suite_path.parent

    output_dir = pathlib.Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_name = str(args.run_name or "").strip() or datetime.now().strftime(
        "judge_%Y%m%d_%H%M%S"
    )
    logger = setup_logger(output_dir, run_name, args.log_level)
    log_bridge = EvalLoggerBridge(logger)

    llm = _load_llm_manager(args=args, log_bridge=log_bridge, logger=logger)
    judge_prompt, judge_prompt_meta = _load_judge_prompt(args=args, logger=logger)

    suite = _load_json(suite_path)
    defaults_block = suite.get("defaults") if isinstance(suite.get("defaults"), dict) else {}
    defaults = {
        "threshold_accuracy": _safe_float(
            defaults_block.get("threshold_accuracy", 0.8),
            0.8,
        ),
        "prompt_max_chars": _safe_int(defaults_block.get("prompt_max_chars", 8000), 8000),
        "answer_max_chars": _safe_int(defaults_block.get("answer_max_chars", 12000), 12000),
    }

    cli_overrides: dict[str, Any] = {}
    for item in args.set or []:
        key, value = _parse_kv_override(item)
        cli_overrides[key] = value
    if args.prompt_max_chars > 0:
        cli_overrides["prompt_max_chars"] = int(args.prompt_max_chars)
    if args.answer_max_chars > 0:
        cli_overrides["answer_max_chars"] = int(args.answer_max_chars)

    threshold_accuracy = defaults["threshold_accuracy"]
    if "threshold_accuracy" in cli_overrides:
        threshold_accuracy = _safe_float(
            cli_overrides["threshold_accuracy"],
            threshold_accuracy,
        )
    if args.threshold_accuracy >= 0.0:
        threshold_accuracy = float(args.threshold_accuracy)
    threshold_accuracy = max(0.0, min(1.0, threshold_accuracy))

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
        "Loaded %d/%d judge cases from %s",
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
            judge_prompt=judge_prompt,
            args=args,
            logger=logger,
            artifacts_dir=artifacts_dir,
        )
        rows.append(row)
    elapsed = time.perf_counter() - started
    summary = _summarize(rows, threshold_accuracy=threshold_accuracy)

    payload = {
        "run_name": run_name,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "suite": str(suite_path),
        "evaluation_type": "judge_pairwise",
        "config": {
            "llm_model": str(args.llm_model),
            "llm_n_ctx": int(args.llm_n_ctx),
            "llm_gpu_layers": int(args.llm_gpu_layers),
            "llm_threads": int(args.llm_threads),
            "judge_prompt": judge_prompt_meta,
            "judge_prompt_preview": judge_prompt[:400],
            "judge_max_tokens": int(args.judge_max_tokens),
            "temperature": float(args.temperature),
            "top_p": float(args.top_p),
            "repeat_penalty": float(args.repeat_penalty),
            "seed": int(args.seed),
            "threshold_accuracy": threshold_accuracy,
            "settings_overrides": cli_overrides,
        },
        "summary": {
            **summary,
            "elapsed_sec": elapsed,
        },
        "cases": [dataclasses.asdict(row) for row in rows],
    }

    _write_json(output_dir / f"{run_name}.summary.json", payload)
    _write_cases_csv(output_dir / f"{run_name}.cases.csv", rows)
    with open(output_dir / f"{run_name}.debug.jsonl", "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dataclasses.asdict(row), ensure_ascii=False) + "\n")

    logger.info(
        "Done | cases=%d correct=%d accuracy=%.3f threshold=%.3f pass=%s elapsed=%.2fs",
        payload["summary"]["cases"],
        payload["summary"]["correct"],
        payload["summary"]["accuracy"],
        payload["summary"]["threshold_accuracy"],
        payload["summary"]["passed"],
        elapsed,
    )
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pairwise LLM judge eval runner")
    parser.add_argument("--suite", required=True, help="Path to judge suite JSON")
    parser.add_argument(
        "--output-dir",
        default="runs/judge_eval",
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

    parser.add_argument(
        "--prompts-json",
        default="",
        help="Optional JSON containing judge prompt key",
    )
    parser.add_argument(
        "--judge-prompt-key",
        default="judge_pairwise_system",
        help="Prompt key in prompts JSON",
    )
    parser.add_argument(
        "--judge-prompt-file",
        default="",
        help="Optional plain-text prompt file (overrides JSON key lookup)",
    )
    parser.add_argument("--judge-max-tokens", type=int, default=192)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--repeat-penalty", type=float, default=1.05)
    parser.add_argument(
        "--seed",
        type=int,
        default=-1,
        help="Per-call seed if supported by llama-cpp (-1 disables)",
    )

    parser.add_argument(
        "--prompt-max-chars",
        type=int,
        default=0,
        help="Override max chars for prompt text per case",
    )
    parser.add_argument(
        "--answer-max-chars",
        type=int,
        default=0,
        help="Override max chars per answer text",
    )
    parser.add_argument(
        "--threshold-accuracy",
        type=float,
        default=-1.0,
        help="Override minimum run accuracy required to pass",
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
