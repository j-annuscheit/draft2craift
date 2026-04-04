#!/usr/bin/env python3
"""Live local-model evaluation for agentic mindmap generation (AIAYN paper)."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
import os
from pathlib import Path
import sys
import time
from typing import Any

_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared.domain.graph_codec import extract_graph_spec
from shared.services.agentic import AgenticWorkflowService, build_tools
from shared.services.llm.manager import LLMManager
from shared.services.rag.config import RAGConfig
from shared.services.rag.orchestrator import RAGSystem, _resolve_local_hf_model_ref

DEFAULT_MODEL_PATH = Path("/home/be/test_claude/canvas2/models/google_gemma-3-4b-it-qat-Q4_0.gguf")
DEFAULT_SOURCE_MD = Path("/home/be/.local/share/draft2craift/draft2craift/autosave_project/knowledge/doc_0000.md")
_HF_OFFLINE_ENV_DEFAULTS = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
}


def _pick_local_embedding_model() -> str:
    candidates = (
        "sentence-transformers/all-MiniLM-L6-v2",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "paraphrase-multilingual-MiniLM-L12-v2",
    )
    for candidate in candidates:
        resolved = _resolve_local_hf_model_ref(candidate)
        if Path(resolved).exists():
            return str(resolved)
    return str(candidates[0])


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    query: str
    retrieval_strategy: str
    factcheck: bool
    agent_max_iterations: int
    max_nodes: int
    max_refinement_rounds: int
    required_keywords: tuple[str, ...]
    min_keyword_hits: int
    min_root_children: int


def default_scenarios() -> list[Scenario]:
    return [
        Scenario(
            scenario_id="overview_auto",
            query="",
            retrieval_strategy="agent",
            factcheck=True,
            agent_max_iterations=6,
            max_nodes=28,
            max_refinement_rounds=1,
            required_keywords=("transformer", "attention", "encoder", "decoder", "wmt14"),
            min_keyword_hits=4,
            min_root_children=4,
        ),
        Scenario(
            scenario_id="attention_focus",
            query="Wie funktioniert Multi-Head Attention im Encoder und Decoder?",
            retrieval_strategy="agent",
            factcheck=True,
            agent_max_iterations=6,
            max_nodes=28,
            max_refinement_rounds=1,
            required_keywords=("multi-head", "scaled dot-product", "encoder", "decoder", "mask"),
            min_keyword_hits=4,
            min_root_children=3,
        ),
        Scenario(
            scenario_id="results_focus",
            query="Welche BLEU-Ergebnisse und Trainingsaufwaende nennt das Paper?",
            retrieval_strategy="agent",
            factcheck=True,
            agent_max_iterations=6,
            max_nodes=28,
            max_refinement_rounds=1,
            required_keywords=("bleu", "wmt14", "28.4", "41.8", "3.5"),
            min_keyword_hits=4,
            min_root_children=3,
        ),
        Scenario(
            scenario_id="position_focus",
            query="Welche Rolle spielt Positional Encoding im Transformer?",
            retrieval_strategy="rag",
            factcheck=True,
            agent_max_iterations=4,
            max_nodes=24,
            max_refinement_rounds=1,
            required_keywords=("positional", "sinus", "position", "sequence"),
            min_keyword_hits=3,
            min_root_children=3,
        ),
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--source-md", default=str(DEFAULT_SOURCE_MD))
    parser.add_argument("--output-dir", default="runs/agentic_mindmap_live")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--n-ctx", type=int, default=40000)
    parser.add_argument("--n-gpu-layers", type=int, default=99)
    parser.add_argument("--n-threads", type=int, default=0)
    parser.add_argument("--map-max-output-tokens", type=int, default=1200)
    parser.add_argument("--map-temperature", type=float, default=0.2)
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--scenario-id", default="")
    parser.add_argument(
        "--embedding-model",
        default="",
        help="Local HuggingFace embedding model path/name available in local cache.",
    )
    parser.add_argument(
        "--embedding-device",
        default="cpu",
        help="Embedding device passed via D2C_EMBEDDING_DEVICE (cpu/cuda).",
    )
    parser.add_argument("--chunk-size", type=int, default=1400)
    parser.add_argument("--chunk-overlap", type=int, default=120)
    parser.add_argument("--max-source-chars", type=int, default=0)
    parser.add_argument(
        "--allow-failures",
        action="store_true",
        help="Return exit code 0 even when one or more scenarios fail.",
    )
    return parser.parse_args()


def _quality(markdown: str, scenario: Scenario) -> dict[str, Any]:
    spec = extract_graph_spec(str(markdown or ""))
    if spec is None:
        return {"ok": False, "reason": "unparseable_markdown"}
    if str(spec.kind or "").casefold() != "mindmap":
        return {"ok": False, "reason": f"wrong_kind:{spec.kind}"}

    nodes = dict(spec.nodes or {})
    roots = [str(node_id or "").strip() for node_id in list(spec.roots or []) if str(node_id or "").strip()]
    if not roots:
        return {"ok": False, "reason": "missing_root"}
    root = nodes.get(roots[0])
    root_children = list(getattr(root, "children", []) or []) if root is not None else []
    root_label = str(getattr(root, "label", "") or "")
    node_count = len(nodes)

    corpus = " ".join(
        [
            str(getattr(node, "label", "") or "")
            for node in list(nodes.values())
        ]
        + [
            str(getattr(node, "quote", "") or "")
            for node in list(nodes.values())
            if str(getattr(node, "quote", "") or "").strip()
        ]
    ).casefold()
    keyword_hits = [kw for kw in scenario.required_keywords if str(kw).casefold() in corpus]

    issues: list[str] = []
    if node_count < 6:
        issues.append("node_count_too_low")
    if node_count > int(scenario.max_nodes):
        issues.append("node_count_too_high")
    if len(root_children) < int(scenario.min_root_children):
        issues.append("root_children_too_low")
    if len(keyword_hits) < int(scenario.min_keyword_hits):
        issues.append("keyword_coverage_too_low")
    if "softwareentwicklungserfolg" in corpus:
        issues.append("irrelevant_softwareentwicklungserfolg_detected")

    return {
        "ok": not issues,
        "issues": issues,
        "node_count": node_count,
        "root_label": root_label,
        "root_children": len(root_children),
        "keyword_hits": len(keyword_hits),
        "keywords_expected": list(scenario.required_keywords),
        "keywords_found": keyword_hits,
    }


def _run_case(
    *,
    service: AgenticWorkflowService,
    tools: dict[str, Any],
    context_text: str,
    scenario: Scenario,
    map_max_output_tokens: int,
    map_temperature: float,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    run = service.run_mindmap(
        request={
            "query": scenario.query,
            "context_text": context_text,
            "retrieval_strategy": scenario.retrieval_strategy,
            "agent_max_iterations": scenario.agent_max_iterations,
            "factcheck": scenario.factcheck,
            "max_refinement_rounds": scenario.max_refinement_rounds,
            "max_nodes": scenario.max_nodes,
            "map_max_output_tokens": int(map_max_output_tokens),
            "map_temperature": float(map_temperature),
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )
    duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    markdown = str(run.result.get("markdown", "") or "")
    quality = _quality(markdown, scenario)
    return {
        "scenario": asdict(scenario),
        "duration_ms": duration_ms,
        "run_ok": bool(run.ok),
        "errors": list(run.errors or []),
        "metrics": dict(run.metrics or {}),
        "quality": quality,
        "trace_steps": [
            {
                "step_id": str(row.step_id or ""),
                "status": str(row.status or ""),
                "duration_ms": float(row.duration_ms),
                "output": dict(row.output or {}),
            }
            for row in list(run.trace or [])
        ],
        "state_summary": {
            "query_origin": str(dict(run.state or {}).get("query_origin", "")),
            "effective_query": str(dict(run.state or {}).get("effective_query", "")),
            "root_label": str(dict(run.state or {}).get("root_label", "")),
            "primary_children": list(dict(run.state or {}).get("primary_children", []) or []),
            "rag_snippets": len(list(dict(run.state or {}).get("rag_snippets", []) or [])),
            "retrieval_agent_steps": len(list(dict(run.state or {}).get("retrieval_agent_steps", []) or [])),
        },
        "markdown": markdown,
    }


def _write_markdown_summary(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# Agentic MindMap Live Eval")
    lines.append("")
    lines.append(f"- Run: `{payload['run_name']}`")
    lines.append(f"- Model: `{payload['model_path']}`")
    lines.append(f"- Source: `{payload['source_md']}`")
    lines.append(f"- n_ctx: `{payload['n_ctx']}`")
    lines.append(f"- n_gpu_layers: `{payload['n_gpu_layers']}`")
    lines.append(f"- embedding_model: `{payload['embedding_model']}`")
    lines.append(f"- embedding_device: `{payload['embedding_device']}`")
    lines.append(f"- chunk_size: `{payload['chunk_size']}`")
    lines.append(f"- chunk_overlap: `{payload['chunk_overlap']}`")
    lines.append(f"- max_source_chars: `{payload['max_source_chars']}`")
    lines.append(f"- map_max_output_tokens: `{payload['map_max_output_tokens']}`")
    lines.append(f"- map_temperature: `{payload['map_temperature']}`")
    lines.append(f"- Cases: `{payload['summary']['cases']}`")
    lines.append(f"- Passed: `{payload['summary']['passed']}`")
    lines.append(f"- Failed: `{payload['summary']['failed']}`")
    lines.append("")

    for row in list(payload.get("results", [])):
        scenario = dict(row.get("scenario", {}) or {})
        quality = dict(row.get("quality", {}) or {})
        lines.append(f"## {scenario.get('scenario_id', 'unknown')}")
        lines.append(f"- query: `{scenario.get('query', '')}`")
        lines.append(f"- retrieval: `{scenario.get('retrieval_strategy', '')}`")
        lines.append(f"- run_ok: `{row.get('run_ok', False)}`")
        lines.append(f"- quality_ok: `{quality.get('ok', False)}`")
        lines.append(f"- duration_ms: `{row.get('duration_ms', 0)}`")
        lines.append(f"- quality_issues: `{quality.get('issues', [])}`")
        lines.append(f"- keyword_hits: `{quality.get('keyword_hits', 0)}`")
        lines.append(f"- root_label: `{quality.get('root_label', '')}`")
        lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    for key, value in _HF_OFFLINE_ENV_DEFAULTS.items():
        if not str(os.environ.get(key, "") or "").strip():
            os.environ[key] = value

    run_name = str(args.run_name or "").strip() or datetime.now().strftime("mindmap_live_%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir).expanduser().resolve()
    run_dir = output_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    model_path = Path(str(args.model_path or "")).expanduser().resolve()
    source_path = Path(str(args.source_md or "")).expanduser().resolve()
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    if not source_path.exists():
        raise FileNotFoundError(f"Source markdown not found: {source_path}")
    source_text = source_path.read_text(encoding="utf-8", errors="replace")
    if int(args.max_source_chars or 0) > 0:
        source_text = source_text[: max(1000, int(args.max_source_chars))]
    if "Attention Is All You Need" not in source_text:
        raise RuntimeError("Source markdown does not look like arXiv 1706.03762.")

    llm = LLMManager()
    rag = None
    try:
        print(
            f"[{run_name}] loading model: {model_path} | n_ctx={int(args.n_ctx)} "
            f"n_gpu_layers={int(args.n_gpu_layers)}",
            flush=True,
        )
        t_load = time.perf_counter()
        ok, message = llm.worker.load_model(
            str(model_path),
            n_ctx=max(2048, int(args.n_ctx)),
            n_gpu_layers=int(args.n_gpu_layers),
            n_threads=int(args.n_threads),
            backend="llama_cpp",
        )
        if not ok:
            raise RuntimeError(f"LLM load failed: {message}")
        print(
            f"[{run_name}] model ready in {round((time.perf_counter() - t_load) * 1000.0, 1)} ms",
            flush=True,
        )

        rag_cfg = RAGConfig()
        embedding_model = str(args.embedding_model or "").strip() or _pick_local_embedding_model()
        rag_cfg.backend.st_model_name = embedding_model
        rag_cfg.chunking.chunk_size = max(400, int(args.chunk_size))
        rag_cfg.chunking.chunk_overlap = max(
            0,
            min(int(args.chunk_overlap), rag_cfg.chunking.chunk_size - 50),
        )
        embedding_device = str(args.embedding_device or "cpu").strip().lower() or "cpu"
        os.environ["D2C_EMBEDDING_DEVICE"] = embedding_device
        print(
            f"[{run_name}] building RAG index with embedding model: {rag_cfg.backend.st_model_name} "
            f"| device={embedding_device} | chunk_size={rag_cfg.chunking.chunk_size} "
            f"chunk_overlap={rag_cfg.chunking.chunk_overlap}",
            flush=True,
        )
        t_index = time.perf_counter()
        rag = RAGSystem(config=rag_cfg)
        if not rag.index_content(source_path.name, source_text):
            raise RuntimeError("RAG indexing failed.")
        rag_state = dict(rag.dump_state() or {})
        if not bool(rag_state.get("vector_backend_available", False)):
            raise RuntimeError(
                "RAG backend unavailable after indexing: "
                f"{rag_state.get('vector_backend_error', 'unknown_error')}"
            )
        print(
            f"[{run_name}] RAG index ready in {round((time.perf_counter() - t_index) * 1000.0, 1)} ms",
            flush=True,
        )

        tools = build_tools(
            llm_manager=llm,
            rag_system=rag,
            source_texts=[(source_path.name, source_text)],
        )
        service = AgenticWorkflowService()

        scenarios = default_scenarios()
        scenario_id = str(args.scenario_id or "").strip()
        if scenario_id:
            scenarios = [scenario for scenario in scenarios if scenario.scenario_id == scenario_id]
            if not scenarios:
                raise RuntimeError(f"Unknown scenario_id: {scenario_id}")
        if int(args.max_cases or 0) > 0:
            scenarios = scenarios[: int(args.max_cases)]

        results: list[dict[str, Any]] = []
        for scenario in scenarios:
            print(
                f"[{run_name}] case start: {scenario.scenario_id} | retrieval={scenario.retrieval_strategy} "
                f"factcheck={scenario.factcheck}",
                flush=True,
            )
            case_t0 = time.perf_counter()
            case_result = _run_case(
                service=service,
                tools=tools,
                context_text=source_text,
                scenario=scenario,
                map_max_output_tokens=max(256, int(args.map_max_output_tokens)),
                map_temperature=max(0.0, min(1.2, float(args.map_temperature))),
            )
            case_dt = round((time.perf_counter() - case_t0) * 1000.0, 1)
            quality_ok = bool(dict(case_result.get("quality", {}) or {}).get("ok", False))
            print(
                f"[{run_name}] case done: {scenario.scenario_id} | run_ok={bool(case_result.get('run_ok', False))} "
                f"quality_ok={quality_ok} | {case_dt} ms",
                flush=True,
            )
            results.append(
                case_result
            )

        failed = 0
        for row in results:
            quality_ok = bool(dict(row.get("quality", {}) or {}).get("ok", False))
            if (not bool(row.get("run_ok", False))) or (not quality_ok):
                failed += 1

        payload = {
            "run_name": run_name,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "model_path": str(model_path),
            "source_md": str(source_path),
            "n_ctx": int(args.n_ctx),
            "n_gpu_layers": int(args.n_gpu_layers),
            "n_threads": int(args.n_threads),
            "embedding_device": str(args.embedding_device),
            "embedding_model": str(embedding_model),
            "chunk_size": int(args.chunk_size),
            "chunk_overlap": int(args.chunk_overlap),
            "max_source_chars": int(args.max_source_chars),
            "map_max_output_tokens": int(args.map_max_output_tokens),
            "map_temperature": float(args.map_temperature),
            "summary": {
                "cases": len(results),
                "passed": len(results) - failed,
                "failed": failed,
            },
            "results": results,
        }

        json_path = run_dir / "report.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_markdown_summary(run_dir / "report.md", payload)
        print(json.dumps(payload["summary"], ensure_ascii=False))
        print(f"report: {json_path}")

        if failed > 0 and not bool(args.allow_failures):
            return 1
        return 0
    finally:
        try:
            llm.shutdown()
        except Exception:
            pass
        if rag is not None:
            try:
                rag.clear()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
