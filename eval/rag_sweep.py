#!/usr/bin/env python3
"""
RAG parameter sweep runner.

Runs multiple `rag_eval.run_suite(...)` evaluations over a JSON-defined
parameter grid and aggregates all results.

Usage
-----
python -m eval.rag_sweep \
  --suite tests/rag_suite.json \
  --grid tests/rag_sweep.json \
  --output-dir runs/rag_sweep \
  --run-prefix sweep_baseline
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import logging
import os
import pathlib
import sys
import time
from datetime import datetime
from typing import Any

# Ensure project root is importable when script is launched from any cwd.
_THIS_FILE = pathlib.Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from eval.rag_eval import run_suite


LLM_KEYS = {"llm_model", "llm_n_ctx", "llm_gpu_layers", "llm_threads"}


def setup_logger(output_dir: pathlib.Path, run_prefix: str, level: str) -> logging.Logger:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"rag_sweep.{run_prefix}")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(output_dir / f"{run_prefix}.sweep.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)
    return logger


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in: {path}")
    return data


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _build_combinations(parameters: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    if not parameters:
        return [{}]

    keys = list(parameters.keys())
    value_lists = [_as_list(parameters[k]) for k in keys]
    for i, vals in enumerate(value_lists):
        if not vals:
            raise ValueError(f"Parameter '{keys[i]}' has an empty value list")

    mode = mode.strip().lower()
    if mode == "zip":
        size = len(value_lists[0])
        if any(len(v) != size for v in value_lists):
            raise ValueError("combination_mode='zip' requires equal-length value lists")
        return [dict(zip(keys, row)) for row in zip(*value_lists)]
    if mode != "product":
        raise ValueError("combination_mode must be 'product' or 'zip'")
    return [dict(zip(keys, row)) for row in itertools.product(*value_lists)]


def _split_overrides(combo: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg: dict[str, Any] = {}
    llm: dict[str, Any] = {}
    for k, v in combo.items():
        if k in LLM_KEYS:
            llm[k] = v
        else:
            cfg[k] = v
    return cfg, llm


def _lookup_metric(run_payload: dict[str, Any], metric_path: str) -> float | None:
    path = metric_path.strip()
    if not path:
        return None
    if path.startswith("summary."):
        path = path[len("summary.") :]
    node: Any = run_payload.get("summary", {})
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    if isinstance(node, (int, float)):
        return float(node)
    return None


def _write_json(path: pathlib.Path, data: Any):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _write_csv(path: pathlib.Path, rows: list[dict[str, Any]]):
    cols = [
        "run_name",
        "status",
        "metric",
        "metric_value",
        "cases",
        "micro_f1",
        "macro_f1",
        "map",
        "mrr",
        "ndcg",
        "hit_at_k",
        "contains_recall",
        "elapsed_sec",
        "error",
        "config_overrides",
        "llm_overrides",
    ]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["config_overrides"] = json.dumps(out.get("config_overrides", {}), ensure_ascii=False)
            out["llm_overrides"] = json.dumps(out.get("llm_overrides", {}), ensure_ascii=False)
            writer.writerow({k: out.get(k, "") for k in cols})


def run_sweep(args: argparse.Namespace) -> dict[str, Any]:
    suite_path = pathlib.Path(args.suite).expanduser().resolve()
    if not suite_path.exists():
        raise FileNotFoundError(f"Suite file not found: {suite_path}")
    grid_path = pathlib.Path(args.grid).expanduser().resolve()
    if not grid_path.exists():
        raise FileNotFoundError(f"Grid file not found: {grid_path}")

    output_dir = pathlib.Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logger(output_dir, args.run_prefix, args.log_level)

    grid = _load_json(grid_path)
    base_config = grid.get("base_config") or {}
    if not isinstance(base_config, dict):
        raise ValueError("grid.base_config must be an object")
    parameters = grid.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ValueError("grid.parameters must be an object")
    combination_mode = str(grid.get("combination_mode", "product"))
    file_max_runs = int(grid.get("max_runs", 0) or 0)

    combos = _build_combinations(parameters, combination_mode)
    cli_max_runs = int(args.max_runs or 0)
    max_runs = min(
        [x for x in (len(combos), file_max_runs, cli_max_runs) if x > 0] or [len(combos)]
    )
    combos = combos[:max_runs]

    logger.info(
        "Loaded sweep grid with %d combinations (mode=%s, executing=%d)",
        len(_build_combinations(parameters, combination_mode)),
        combination_mode,
        len(combos),
    )
    logger.info("Ranking metric: %s (%s)", args.metric, "ascending" if args.ascending else "descending")

    rows: list[dict[str, Any]] = []
    best_row: dict[str, Any] | None = None
    started = time.perf_counter()

    for idx, combo in enumerate(combos, 1):
        cfg_override, llm_override = _split_overrides(combo)
        full_cfg = dict(base_config)
        full_cfg.update(cfg_override)

        run_name = f"{args.run_prefix}_{idx:03d}"
        llm_model = str(llm_override.get("llm_model", args.llm_model)).strip() or None
        llm_n_ctx = int(llm_override.get("llm_n_ctx", args.llm_n_ctx))
        llm_gpu_layers = int(llm_override.get("llm_gpu_layers", args.llm_gpu_layers))
        llm_threads = int(llm_override.get("llm_threads", args.llm_threads))

        logger.info(
            "[%d/%d] %s | cfg=%s | llm=%s",
            idx,
            len(combos),
            run_name,
            json.dumps(full_cfg, ensure_ascii=False),
            json.dumps(
                {
                    "llm_model": llm_model or "",
                    "llm_n_ctx": llm_n_ctx,
                    "llm_gpu_layers": llm_gpu_layers,
                    "llm_threads": llm_threads,
                },
                ensure_ascii=False,
            ),
        )

        t0 = time.perf_counter()
        row: dict[str, Any] = {
            "run_name": run_name,
            "status": "ok",
            "metric": args.metric,
            "metric_value": None,
            "cases": 0,
            "micro_f1": 0.0,
            "macro_f1": 0.0,
            "map": 0.0,
            "mrr": 0.0,
            "ndcg": 0.0,
            "hit_at_k": 0.0,
            "contains_recall": None,
            "elapsed_sec": 0.0,
            "error": "",
            "config_overrides": full_cfg,
            "llm_overrides": {
                "llm_model": llm_model or "",
                "llm_n_ctx": llm_n_ctx,
                "llm_gpu_layers": llm_gpu_layers,
                "llm_threads": llm_threads,
            },
        }
        try:
            payload = run_suite(
                suite_path=suite_path,
                output_dir=output_dir,
                run_name=run_name,
                config_overrides=full_cfg,
                cli_top_k=None,
                llm_model=llm_model,
                llm_n_ctx=llm_n_ctx,
                llm_gpu_layers=llm_gpu_layers,
                llm_threads=llm_threads,
                log_level=args.log_level,
            )
            summary = payload.get("summary", {})
            micro = summary.get("micro", {}) if isinstance(summary, dict) else {}
            macro = summary.get("macro", {}) if isinstance(summary, dict) else {}
            metric_value = _lookup_metric(payload, args.metric)
            row.update(
                {
                    "metric_value": metric_value,
                    "cases": int(summary.get("cases", 0)) if isinstance(summary, dict) else 0,
                    "micro_f1": float(micro.get("f1", 0.0)) if isinstance(micro, dict) else 0.0,
                    "macro_f1": float(macro.get("f1", 0.0)) if isinstance(macro, dict) else 0.0,
                    "map": float(macro.get("map", 0.0)) if isinstance(macro, dict) else 0.0,
                    "mrr": float(macro.get("mrr", 0.0)) if isinstance(macro, dict) else 0.0,
                    "ndcg": float(macro.get("ndcg", 0.0)) if isinstance(macro, dict) else 0.0,
                    "hit_at_k": float(macro.get("hit_at_k", 0.0)) if isinstance(macro, dict) else 0.0,
                    "contains_recall": (
                        float(macro.get("contains_recall"))
                        if isinstance(macro, dict) and isinstance(macro.get("contains_recall"), (int, float))
                        else None
                    ),
                }
            )
        except Exception as exc:
            row["status"] = "error"
            row["error"] = str(exc)
            logger.exception("Run %s failed: %s", run_name, exc)
            if args.fail_fast:
                row["elapsed_sec"] = time.perf_counter() - t0
                rows.append(row)
                break
        row["elapsed_sec"] = time.perf_counter() - t0
        rows.append(row)

        if row["status"] == "ok" and isinstance(row.get("metric_value"), (int, float)):
            if best_row is None:
                best_row = row
            else:
                lhs = float(row["metric_value"])
                rhs = float(best_row["metric_value"])
                if (lhs < rhs and args.ascending) or (lhs > rhs and not args.ascending):
                    best_row = row

        logger.info(
            "Finished %s in %.2fs | status=%s | %s=%s",
            run_name,
            row["elapsed_sec"],
            row["status"],
            args.metric,
            row["metric_value"],
        )

    elapsed = time.perf_counter() - started
    ok_runs = [r for r in rows if r.get("status") == "ok"]
    err_runs = [r for r in rows if r.get("status") == "error"]
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "suite": str(suite_path),
        "grid": str(grid_path),
        "output_dir": str(output_dir),
        "run_prefix": args.run_prefix,
        "metric": args.metric,
        "ascending": bool(args.ascending),
        "total_runs": len(rows),
        "ok_runs": len(ok_runs),
        "error_runs": len(err_runs),
        "elapsed_sec": elapsed,
        "best_run": best_row,
        "runs": rows,
    }

    _write_json(output_dir / f"{args.run_prefix}.sweep.json", payload)
    _write_csv(output_dir / f"{args.run_prefix}.sweep.csv", rows)
    logger.info(
        "Sweep finished in %.2fs | ok=%d error=%d | summary=%s",
        elapsed,
        len(ok_runs),
        len(err_runs),
        output_dir / f"{args.run_prefix}.sweep.json",
    )
    if best_row:
        logger.info("Best run: %s (%s=%s)", best_row["run_name"], args.metric, best_row["metric_value"])
    return payload


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run RAG parameter sweeps")
    p.add_argument("--suite", required=True, help="Path to RAG suite JSON")
    p.add_argument("--grid", required=True, help="Path to sweep JSON")
    p.add_argument("--output-dir", default="runs/rag_sweep", help="Output directory")
    p.add_argument("--run-prefix", default="sweep", help="Prefix for run names and sweep files")
    p.add_argument("--metric", default="macro.f1", help="Metric path used to select best run")
    p.add_argument("--ascending", action="store_true", help="Select best run by minimum metric value")
    p.add_argument("--max-runs", type=int, default=0, help="Optional cap for number of combinations")
    p.add_argument("--fail-fast", action="store_true", help="Stop at first failed run")

    p.add_argument("--llm-model", default="", help="Default GGUF model path (can be overridden in grid)")
    p.add_argument("--llm-n-ctx", type=int, default=4096, help="Default LLM context")
    p.add_argument("--llm-gpu-layers", type=int, default=0, help="Default LLM GPU layers")
    p.add_argument("--llm-threads", type=int, default=0, help="Default LLM threads")

    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_sweep(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
