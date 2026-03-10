#!/usr/bin/env python3
"""
LLM-vs-LLM compare runner with a separate LLM judge.

Goal
----
- Generate two candidate answers (setting A and setting B) for each prompt.
- Let a dedicated judge LLM pick the better candidate.
- Aggregate preference rates and latency metrics.

Usage
-----
python -m eval.llm_compare_eval \
  --suite eval/examples/llm_compare_suite.example.json \
  --output-dir runs/llm_compare_eval \
  --run-name demo_compare \
  --a-llm-model /path/to/model_a.gguf \
  --b-llm-model /path/to/model_b.gguf \
  --judge-llm-model /path/to/judge.gguf
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

from shared.services.llm.manager import LLMManager  # noqa: E402

DEFAULT_CANDIDATE_SYSTEM_PROMPT = (
    "Du bist ein hilfreicher Assistent. "
    "Beantworte die Aufgabe korrekt, klar und praezise."
)

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
    prompt_max_chars: int


@dataclass
class GenerationConfig:
    max_tokens: int
    temperature: float
    top_p: float
    repeat_penalty: float
    seed: int


@dataclass
class RuntimeLoadConfig:
    model_path: pathlib.Path
    n_ctx: int
    gpu_layers: int
    threads: int


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
    preferred_setting: str
    preferred_label: str
    judge_winner: str
    parsed: bool
    parse_mode: str
    confidence: float | None
    swapped_order: bool
    gen_a_ms: float
    gen_b_ms: float
    judge_ms: float
    total_ms: float
    prompt_chars: int
    answer_a_chars: int
    answer_b_chars: int
    prompt_preview: str
    answer_a_preview: str
    answer_b_preview: str
    reason: str
    raw_preview: str
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
    logger = logging.getLogger(f"llm_compare_eval.{run_name}")
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


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    raw = str(value or "").strip().casefold()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    return default


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in file: {path}")
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


def _clip_text(text: str, limit: int) -> str:
    payload = str(text or "")
    clean_limit = max(256, int(limit))
    if len(payload) <= clean_limit:
        return payload
    suffix = "\n\n[TRUNCATED]"
    head = payload[: max(0, clean_limit - len(suffix))]
    return head + suffix


def _build_candidate_prompt(
    candidate_system_prompt: str,
    *,
    user_prompt: str,
) -> str:
    return (
        "<|system|>\n"
        f"{candidate_system_prompt}\n"
        "<|user|>\n"
        f"{user_prompt}\n"
        "<|assistant|>\n"
    )


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


def _load_prompt_text(
    *,
    file_arg: str,
    key: str,
    prompts_json_arg: str,
    fallback_default_path: pathlib.Path,
    builtin_default: str,
    logger: logging.Logger,
    prompt_name: str,
) -> tuple[str, dict[str, str]]:
    file_arg_clean = str(file_arg or "").strip()
    if file_arg_clean:
        path = pathlib.Path(file_arg_clean).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"{prompt_name} prompt file not found: {path}")
        text = _read_text(path).strip()
        if text:
            logger.info("%s prompt loaded from file: %s", prompt_name, path)
            return text, {"source": "file", "path": str(path), "key": ""}

    key_clean = str(key or "").strip()
    candidate_paths: list[pathlib.Path] = []
    prompts_json_clean = str(prompts_json_arg or "").strip()
    if prompts_json_clean:
        candidate_paths.append(pathlib.Path(prompts_json_clean).expanduser().resolve())
    if fallback_default_path not in candidate_paths:
        candidate_paths.append(fallback_default_path)

    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            data = _load_json(path)
            value = str(data.get(key_clean, "") or "").strip()
            if value:
                logger.info(
                    "%s prompt loaded from json: %s (key=%s)",
                    prompt_name,
                    path,
                    key_clean,
                )
                return value, {"source": "json", "path": str(path), "key": key_clean}
        except Exception as exc:
            logger.warning(
                "%s prompt json could not be read (%s): %s",
                prompt_name,
                path,
                exc,
            )

    logger.info("%s prompt fallback: built-in default", prompt_name)
    return builtin_default, {"source": "builtin", "path": "", "key": key_clean}


def _load_llm_cached(
    *,
    cfg: RuntimeLoadConfig,
    cache: dict[tuple[str, int, int, int], LLMManager],
    logger: logging.Logger,
    log_bridge: EvalLoggerBridge,
    role_name: str,
) -> LLMManager:
    if not str(cfg.model_path):
        raise ValueError(f"{role_name}: model path is empty")
    if not cfg.model_path.exists():
        raise FileNotFoundError(f"{role_name}: model not found: {cfg.model_path}")

    try:
        from llama_cpp import Llama
    except Exception as exc:
        raise RuntimeError(
            "llama-cpp-python is required for --*-llm-model"
        ) from exc

    n_threads = int(cfg.threads) if int(cfg.threads) > 0 else (os.cpu_count() or 4)
    key = (
        str(cfg.model_path),
        int(cfg.n_ctx),
        int(cfg.gpu_layers),
        int(n_threads),
    )
    cached = cache.get(key)
    if cached is not None:
        logger.info(
            "Reusing LLM for %s: %s | n_ctx=%s gpu_layers=%s threads=%s",
            role_name,
            cfg.model_path,
            cfg.n_ctx,
            cfg.gpu_layers,
            n_threads,
        )
        return cached

    logger.info(
        "Loading LLM for %s: %s | n_ctx=%s gpu_layers=%s threads=%s",
        role_name,
        cfg.model_path,
        cfg.n_ctx,
        cfg.gpu_layers,
        n_threads,
    )
    t0 = time.perf_counter()
    model = Llama(
        model_path=str(cfg.model_path),
        n_ctx=int(cfg.n_ctx),
        n_gpu_layers=int(cfg.gpu_layers),
        n_threads=int(n_threads),
        verbose=False,
    )
    logger.info("LLM loaded for %s in %.2fs", role_name, time.perf_counter() - t0)

    llm = LLMManager(logger=log_bridge)
    llm.worker._model = model
    llm.worker._load_params = {
        "n_ctx": int(cfg.n_ctx),
        "n_gpu_layers": int(cfg.gpu_layers),
        "n_threads": int(n_threads),
    }
    cache[key] = llm
    return llm


def _llm_generate(
    llm: LLMManager,
    prompt: str,
    *,
    cfg: GenerationConfig,
) -> str:
    model = llm.worker._model
    kwargs: dict[str, Any] = {
        "max_tokens": int(cfg.max_tokens),
        "temperature": float(cfg.temperature),
        "top_p": float(cfg.top_p),
        "repeat_penalty": float(cfg.repeat_penalty),
        "stop": ["<|"],
        "stream": False,
    }
    if int(cfg.seed) >= 0:
        kwargs["seed"] = int(cfg.seed)
    try:
        result = model(prompt, **kwargs)
    except TypeError as exc:
        # Compatibility fallback for bindings without per-call seed argument.
        if "seed" not in str(exc):
            raise
        kwargs.pop("seed", None)
        result = model(prompt, **kwargs)
    return str(result["choices"][0].get("text", "") or "")


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
    cli_overrides: dict[str, Any],
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

    labels = _normalise_labels(raw.get("labels"))

    prompt_max_chars = _safe_int(
        raw.get("prompt_max_chars", defaults.get("prompt_max_chars", 8000)),
        8000,
    )
    if "prompt_max_chars" in cli_overrides:
        prompt_max_chars = _safe_int(cli_overrides["prompt_max_chars"], prompt_max_chars)

    return CaseSpec(
        case_id=case_id,
        labels=labels,
        prompt_text=prompt_text,
        prompt_max_chars=max(256, int(prompt_max_chars)),
    )


def _evaluate_case(
    case: CaseSpec,
    *,
    case_index: int,
    candidate_a_llm: LLMManager,
    candidate_b_llm: LLMManager,
    judge_llm: LLMManager,
    candidate_cfg_a: GenerationConfig,
    candidate_cfg_b: GenerationConfig,
    judge_cfg: GenerationConfig,
    candidate_system_prompt: str,
    judge_system_prompt: str,
    candidate_label_a: str,
    candidate_label_b: str,
    swap_order: bool,
    logger: logging.Logger,
    artifacts_dir: pathlib.Path | None,
) -> CaseResult:
    clipped_prompt = _clip_text(case.prompt_text, case.prompt_max_chars)
    candidate_prompt = _build_candidate_prompt(
        candidate_system_prompt,
        user_prompt=clipped_prompt,
    )

    total_start = time.perf_counter()

    t0 = time.perf_counter()
    answer_a = _llm_generate(candidate_a_llm, candidate_prompt, cfg=candidate_cfg_a)
    gen_a_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    answer_b = _llm_generate(candidate_b_llm, candidate_prompt, cfg=candidate_cfg_b)
    gen_b_ms = (time.perf_counter() - t0) * 1000.0

    swapped = bool(swap_order and ((case_index % 2) == 1))
    if swapped:
        judge_answer_a = answer_b
        judge_answer_b = answer_a
    else:
        judge_answer_a = answer_a
        judge_answer_b = answer_b

    judge_prompt = _build_judge_prompt(
        judge_system_prompt,
        user_prompt=clipped_prompt,
        answer_a=judge_answer_a,
        answer_b=judge_answer_b,
    )

    t0 = time.perf_counter()
    judge_raw = _llm_generate(judge_llm, judge_prompt, cfg=judge_cfg)
    judge_ms = (time.perf_counter() - t0) * 1000.0

    decision = _parse_judge_output(judge_raw)

    preferred_setting = ""
    preferred_label = ""
    if decision.parsed and decision.winner in {"A", "B"}:
        if swapped:
            preferred_setting = "b" if decision.winner == "A" else "a"
        else:
            preferred_setting = "a" if decision.winner == "A" else "b"
        preferred_label = candidate_label_a if preferred_setting == "a" else candidate_label_b

    fail_reasons: list[str] = []
    if not decision.parsed:
        fail_reasons.append("parse_failed")
    if not preferred_setting:
        fail_reasons.append("undecided")

    total_ms = (time.perf_counter() - total_start) * 1000.0

    if artifacts_dir is not None:
        payload = {
            "case": dataclasses.asdict(case),
            "swapped_order": swapped,
            "candidate_prompt": candidate_prompt,
            "candidate_answer_a": answer_a,
            "candidate_answer_b": answer_b,
            "judge_prompt": judge_prompt,
            "judge_raw": judge_raw,
            "judge_decision": dataclasses.asdict(decision),
            "preferred_setting": preferred_setting,
            "preferred_label": preferred_label,
            "timings_ms": {
                "gen_a": gen_a_ms,
                "gen_b": gen_b_ms,
                "judge": judge_ms,
                "total": total_ms,
            },
        }
        _write_json(artifacts_dir / f"{case.case_id}.json", payload)
        _write_text(artifacts_dir / f"{case.case_id}.candidate.prompt.txt", candidate_prompt)
        _write_text(artifacts_dir / f"{case.case_id}.candidate_a.raw.txt", answer_a)
        _write_text(artifacts_dir / f"{case.case_id}.candidate_b.raw.txt", answer_b)
        _write_text(artifacts_dir / f"{case.case_id}.judge.prompt.txt", judge_prompt)
        _write_text(artifacts_dir / f"{case.case_id}.judge.raw.txt", judge_raw)

    logger.info(
        "[%s] preferred=%s judge=%s parsed=%s mode=%s conf=%s swapped=%s genA=%.1fms genB=%.1fms judge=%.1fms",
        case.case_id,
        preferred_setting or "-",
        decision.winner or "-",
        decision.parsed,
        decision.parse_mode,
        (
            f"{decision.confidence:.3f}"
            if isinstance(decision.confidence, float)
            else "-"
        ),
        swapped,
        gen_a_ms,
        gen_b_ms,
        judge_ms,
    )

    return CaseResult(
        case_id=case.case_id,
        labels=case.labels,
        preferred_setting=preferred_setting,
        preferred_label=preferred_label,
        judge_winner=decision.winner,
        parsed=decision.parsed,
        parse_mode=decision.parse_mode,
        confidence=decision.confidence,
        swapped_order=swapped,
        gen_a_ms=gen_a_ms,
        gen_b_ms=gen_b_ms,
        judge_ms=judge_ms,
        total_ms=total_ms,
        prompt_chars=len(clipped_prompt),
        answer_a_chars=len(answer_a),
        answer_b_chars=len(answer_b),
        prompt_preview=clipped_prompt[:220].replace("\n", " ").strip(),
        answer_a_preview=answer_a[:220].replace("\n", " ").strip(),
        answer_b_preview=answer_b[:220].replace("\n", " ").strip(),
        reason=decision.reason,
        raw_preview=judge_raw[:240].replace("\n", " ").strip(),
        fail_reasons=fail_reasons,
    )


def _write_cases_csv(path: pathlib.Path, rows: list[CaseResult]) -> None:
    cols = [
        "case_id",
        "labels",
        "preferred_setting",
        "preferred_label",
        "judge_winner",
        "parsed",
        "parse_mode",
        "confidence",
        "swapped_order",
        "gen_a_ms",
        "gen_b_ms",
        "judge_ms",
        "total_ms",
        "prompt_chars",
        "answer_a_chars",
        "answer_b_chars",
        "prompt_preview",
        "answer_a_preview",
        "answer_b_preview",
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
    threshold_win_gap: float,
) -> dict[str, Any]:
    if not rows:
        return {
            "cases": 0,
            "preferred_a": 0,
            "preferred_b": 0,
            "undecided": 0,
            "parsed": 0,
            "unparsed": 0,
            "preference_a_rate": 0.0,
            "preference_b_rate": 0.0,
            "parsed_rate": 0.0,
            "undecided_rate": 0.0,
            "avg_confidence": 0.0,
            "avg_gen_a_ms": 0.0,
            "avg_gen_b_ms": 0.0,
            "avg_judge_ms": 0.0,
            "avg_total_ms": 0.0,
            "winner": "tie",
            "win_gap": 0.0,
            "threshold_win_gap": threshold_win_gap,
            "passed": False,
        }

    total = len(rows)
    preferred_a = sum(1 for row in rows if row.preferred_setting == "a")
    preferred_b = sum(1 for row in rows if row.preferred_setting == "b")
    undecided = total - preferred_a - preferred_b
    parsed = sum(1 for row in rows if row.parsed)
    unparsed = total - parsed
    confidences = [row.confidence for row in rows if isinstance(row.confidence, float)]

    pref_a_rate = preferred_a / total
    pref_b_rate = preferred_b / total
    win_gap = pref_a_rate - pref_b_rate
    if win_gap > 0.0:
        winner = "A"
    elif win_gap < 0.0:
        winner = "B"
    else:
        winner = "tie"

    summary = {
        "cases": total,
        "preferred_a": preferred_a,
        "preferred_b": preferred_b,
        "undecided": undecided,
        "parsed": parsed,
        "unparsed": unparsed,
        "preference_a_rate": pref_a_rate,
        "preference_b_rate": pref_b_rate,
        "parsed_rate": parsed / total,
        "undecided_rate": undecided / total,
        "avg_confidence": statistics.fmean(confidences) if confidences else 0.0,
        "avg_gen_a_ms": statistics.fmean(row.gen_a_ms for row in rows),
        "avg_gen_b_ms": statistics.fmean(row.gen_b_ms for row in rows),
        "avg_judge_ms": statistics.fmean(row.judge_ms for row in rows),
        "avg_total_ms": statistics.fmean(row.total_ms for row in rows),
        "winner": winner,
        "win_gap": win_gap,
        "threshold_win_gap": threshold_win_gap,
        "passed": abs(win_gap) > threshold_win_gap,
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
        "llm_compare_%Y%m%d_%H%M%S"
    )
    logger = setup_logger(output_dir, run_name, args.log_level)
    log_bridge = EvalLoggerBridge(logger)

    suite = _load_json(suite_path)
    defaults_block = suite.get("defaults") if isinstance(suite.get("defaults"), dict) else {}
    defaults = {
        "prompt_max_chars": _safe_int(defaults_block.get("prompt_max_chars", 8000), 8000),
        "threshold_win_gap": _safe_float(defaults_block.get("threshold_win_gap", 0.0), 0.0),
    }

    cli_overrides: dict[str, Any] = {}
    for item in args.set or []:
        key, value = _parse_kv_override(item)
        cli_overrides[key] = value
    if args.prompt_max_chars > 0:
        cli_overrides["prompt_max_chars"] = int(args.prompt_max_chars)

    threshold_win_gap = defaults["threshold_win_gap"]
    if "threshold_win_gap" in cli_overrides:
        threshold_win_gap = _safe_float(cli_overrides["threshold_win_gap"], threshold_win_gap)
    if args.threshold_win_gap >= 0.0:
        threshold_win_gap = float(args.threshold_win_gap)
    threshold_win_gap = max(0.0, min(1.0, threshold_win_gap))

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
                cli_overrides=cli_overrides,
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

    candidate_prompt, candidate_prompt_meta = _load_prompt_text(
        file_arg=args.candidate_prompt_file,
        key=args.candidate_prompt_key,
        prompts_json_arg=args.prompts_json,
        fallback_default_path=(_PROJECT_ROOT / "data" / "prompts" / "defaults.json").resolve(),
        builtin_default=DEFAULT_CANDIDATE_SYSTEM_PROMPT,
        logger=logger,
        prompt_name="Candidate",
    )
    judge_prompt, judge_prompt_meta = _load_prompt_text(
        file_arg=args.judge_prompt_file,
        key=args.judge_prompt_key,
        prompts_json_arg=args.prompts_json,
        fallback_default_path=(_PROJECT_ROOT / "data" / "prompts" / "defaults.json").resolve(),
        builtin_default=DEFAULT_JUDGE_PROMPT,
        logger=logger,
        prompt_name="Judge",
    )

    cache: dict[tuple[str, int, int, int], LLMManager] = {}
    candidate_a_model = pathlib.Path(str(args.a_llm_model or "")).expanduser().resolve()
    candidate_b_model = pathlib.Path(str(args.b_llm_model or "")).expanduser().resolve()
    judge_model = pathlib.Path(str(args.judge_llm_model or "")).expanduser().resolve()
    if not str(args.a_llm_model or "").strip():
        raise ValueError("--a-llm-model is required")
    if not str(args.b_llm_model or "").strip():
        raise ValueError("--b-llm-model is required")
    if not str(args.judge_llm_model or "").strip():
        raise ValueError("--judge-llm-model is required")

    candidate_a_llm = _load_llm_cached(
        cfg=RuntimeLoadConfig(
            model_path=candidate_a_model,
            n_ctx=int(args.a_llm_n_ctx),
            gpu_layers=int(args.a_llm_gpu_layers),
            threads=int(args.a_llm_threads),
        ),
        cache=cache,
        logger=logger,
        log_bridge=log_bridge,
        role_name="candidate_a",
    )
    candidate_b_llm = _load_llm_cached(
        cfg=RuntimeLoadConfig(
            model_path=candidate_b_model,
            n_ctx=int(args.b_llm_n_ctx),
            gpu_layers=int(args.b_llm_gpu_layers),
            threads=int(args.b_llm_threads),
        ),
        cache=cache,
        logger=logger,
        log_bridge=log_bridge,
        role_name="candidate_b",
    )
    judge_llm = _load_llm_cached(
        cfg=RuntimeLoadConfig(
            model_path=judge_model,
            n_ctx=int(args.judge_llm_n_ctx),
            gpu_layers=int(args.judge_llm_gpu_layers),
            threads=int(args.judge_llm_threads),
        ),
        cache=cache,
        logger=logger,
        log_bridge=log_bridge,
        role_name="judge",
    )

    candidate_cfg_a = GenerationConfig(
        max_tokens=int(args.a_max_tokens),
        temperature=float(args.a_temperature),
        top_p=float(args.a_top_p),
        repeat_penalty=float(args.a_repeat_penalty),
        seed=int(args.a_seed),
    )
    candidate_cfg_b = GenerationConfig(
        max_tokens=int(args.b_max_tokens),
        temperature=float(args.b_temperature),
        top_p=float(args.b_top_p),
        repeat_penalty=float(args.b_repeat_penalty),
        seed=int(args.b_seed),
    )
    judge_cfg = GenerationConfig(
        max_tokens=int(args.judge_max_tokens),
        temperature=float(args.judge_temperature),
        top_p=float(args.judge_top_p),
        repeat_penalty=float(args.judge_repeat_penalty),
        seed=int(args.judge_seed),
    )

    logger.info(
        "Loaded %d/%d compare cases from %s | swap_order=%s",
        len(selected_cases),
        len(all_cases),
        suite_path,
        bool(args.swap_order),
    )

    artifacts_dir = (
        output_dir / f"{run_name}.artifacts" if args.write_artifacts else None
    )
    candidate_label_a = str(args.a_label or "A").strip() or "A"
    candidate_label_b = str(args.b_label or "B").strip() or "B"

    rows: list[CaseResult] = []
    started = time.perf_counter()
    for idx, case in enumerate(selected_cases):
        row = _evaluate_case(
            case,
            case_index=idx,
            candidate_a_llm=candidate_a_llm,
            candidate_b_llm=candidate_b_llm,
            judge_llm=judge_llm,
            candidate_cfg_a=candidate_cfg_a,
            candidate_cfg_b=candidate_cfg_b,
            judge_cfg=judge_cfg,
            candidate_system_prompt=candidate_prompt,
            judge_system_prompt=judge_prompt,
            candidate_label_a=candidate_label_a,
            candidate_label_b=candidate_label_b,
            swap_order=bool(args.swap_order),
            logger=logger,
            artifacts_dir=artifacts_dir,
        )
        rows.append(row)
    elapsed = time.perf_counter() - started
    summary = _summarize(rows, threshold_win_gap=threshold_win_gap)

    payload = {
        "run_name": run_name,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "suite": str(suite_path),
        "evaluation_type": "llm_compare_judge",
        "config": {
            "candidate_a": {
                "label": candidate_label_a,
                "llm_model": str(candidate_a_model),
                "llm_n_ctx": int(args.a_llm_n_ctx),
                "llm_gpu_layers": int(args.a_llm_gpu_layers),
                "llm_threads": int(args.a_llm_threads),
                "max_tokens": int(args.a_max_tokens),
                "temperature": float(args.a_temperature),
                "top_p": float(args.a_top_p),
                "repeat_penalty": float(args.a_repeat_penalty),
                "seed": int(args.a_seed),
            },
            "candidate_b": {
                "label": candidate_label_b,
                "llm_model": str(candidate_b_model),
                "llm_n_ctx": int(args.b_llm_n_ctx),
                "llm_gpu_layers": int(args.b_llm_gpu_layers),
                "llm_threads": int(args.b_llm_threads),
                "max_tokens": int(args.b_max_tokens),
                "temperature": float(args.b_temperature),
                "top_p": float(args.b_top_p),
                "repeat_penalty": float(args.b_repeat_penalty),
                "seed": int(args.b_seed),
            },
            "judge": {
                "llm_model": str(judge_model),
                "llm_n_ctx": int(args.judge_llm_n_ctx),
                "llm_gpu_layers": int(args.judge_llm_gpu_layers),
                "llm_threads": int(args.judge_llm_threads),
                "max_tokens": int(args.judge_max_tokens),
                "temperature": float(args.judge_temperature),
                "top_p": float(args.judge_top_p),
                "repeat_penalty": float(args.judge_repeat_penalty),
                "seed": int(args.judge_seed),
                "prompt": judge_prompt_meta,
                "prompt_preview": judge_prompt[:400],
            },
            "prompts": {
                "candidate_system": candidate_prompt_meta,
                "candidate_system_preview": candidate_prompt[:400],
            },
            "swap_order": bool(args.swap_order),
            "threshold_win_gap": threshold_win_gap,
            "settings_overrides": cli_overrides,
        },
        "summary": {
            **summary,
            "elapsed_sec": elapsed,
            "winner_label": (
                candidate_label_a
                if summary.get("winner") == "A"
                else candidate_label_b
                if summary.get("winner") == "B"
                else "tie"
            ),
        },
        "cases": [dataclasses.asdict(row) for row in rows],
    }

    _write_json(output_dir / f"{run_name}.summary.json", payload)
    _write_cases_csv(output_dir / f"{run_name}.cases.csv", rows)
    with open(output_dir / f"{run_name}.debug.jsonl", "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dataclasses.asdict(row), ensure_ascii=False) + "\n")

    logger.info(
        "Done | cases=%d prefA=%d prefB=%d undecided=%d win_gap=%.3f winner=%s elapsed=%.2fs",
        payload["summary"]["cases"],
        payload["summary"]["preferred_a"],
        payload["summary"]["preferred_b"],
        payload["summary"]["undecided"],
        payload["summary"]["win_gap"],
        payload["summary"]["winner"],
        elapsed,
    )
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare two LLM settings with a third LLM as judge"
    )
    parser.add_argument("--suite", required=True, help="Path to compare suite JSON")
    parser.add_argument(
        "--output-dir",
        default="runs/llm_compare_eval",
        help="Directory for run artifacts",
    )
    parser.add_argument("--run-name", default="", help="Optional run name")
    parser.add_argument("--labels", default="", help="Optional comma-separated labels filter")
    parser.add_argument("--max-cases", type=int, default=0)

    parser.add_argument("--a-label", default="A", help="Display label for candidate setting A")
    parser.add_argument(
        "--a-llm-model",
        default="",
        help="GGUF model path for candidate setting A (required)",
    )
    parser.add_argument("--a-llm-n-ctx", type=int, default=4096)
    parser.add_argument("--a-llm-gpu-layers", type=int, default=0)
    parser.add_argument("--a-llm-threads", type=int, default=0)
    parser.add_argument("--a-max-tokens", type=int, default=512)
    parser.add_argument("--a-temperature", type=float, default=0.20)
    parser.add_argument("--a-top-p", type=float, default=0.95)
    parser.add_argument("--a-repeat-penalty", type=float, default=1.05)
    parser.add_argument("--a-seed", type=int, default=-1)

    parser.add_argument("--b-label", default="B", help="Display label for candidate setting B")
    parser.add_argument(
        "--b-llm-model",
        default="",
        help="GGUF model path for candidate setting B (required)",
    )
    parser.add_argument("--b-llm-n-ctx", type=int, default=4096)
    parser.add_argument("--b-llm-gpu-layers", type=int, default=0)
    parser.add_argument("--b-llm-threads", type=int, default=0)
    parser.add_argument("--b-max-tokens", type=int, default=512)
    parser.add_argument("--b-temperature", type=float, default=0.20)
    parser.add_argument("--b-top-p", type=float, default=0.95)
    parser.add_argument("--b-repeat-penalty", type=float, default=1.05)
    parser.add_argument("--b-seed", type=int, default=-1)

    parser.add_argument(
        "--judge-llm-model",
        default="",
        help="GGUF model path for judge setting (required)",
    )
    parser.add_argument("--judge-llm-n-ctx", type=int, default=4096)
    parser.add_argument("--judge-llm-gpu-layers", type=int, default=0)
    parser.add_argument("--judge-llm-threads", type=int, default=0)
    parser.add_argument("--judge-max-tokens", type=int, default=192)
    parser.add_argument("--judge-temperature", type=float, default=0.0)
    parser.add_argument("--judge-top-p", type=float, default=1.0)
    parser.add_argument("--judge-repeat-penalty", type=float, default=1.05)
    parser.add_argument("--judge-seed", type=int, default=-1)

    parser.add_argument(
        "--prompts-json",
        default="",
        help="Optional JSON containing prompt keys",
    )
    parser.add_argument(
        "--candidate-prompt-key",
        default="llm_compare_candidate_system",
        help="Prompt key used for candidate generation system prompt",
    )
    parser.add_argument(
        "--candidate-prompt-file",
        default="",
        help="Optional plain-text prompt file for candidate generation (overrides key lookup)",
    )
    parser.add_argument(
        "--judge-prompt-key",
        default="judge_pairwise_system",
        help="Prompt key used for judge system prompt",
    )
    parser.add_argument(
        "--judge-prompt-file",
        default="",
        help="Optional plain-text prompt file for judge (overrides key lookup)",
    )

    parser.add_argument(
        "--prompt-max-chars",
        type=int,
        default=0,
        help="Override max chars for prompt text per case",
    )
    parser.add_argument(
        "--threshold-win-gap",
        type=float,
        default=-1.0,
        help="Minimum absolute preference gap for passed=true",
    )
    parser.add_argument(
        "--swap-order",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Alternate answer order A/B in judge prompt to reduce position bias",
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
