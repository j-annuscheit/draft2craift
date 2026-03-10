"""Markdown rendering helpers for RAG result output."""
from __future__ import annotations

from typing import Any


def extract_warnings(debug_info: object) -> list[str]:
    """Extract non-empty warning strings from debug payload."""
    if not isinstance(debug_info, dict):
        return []

    warnings: list[str] = []
    for raw in debug_info.get("warnings", []) or []:
        message = str(raw).strip()
        if message:
            warnings.append(message)
    return warnings


def _quote_block(text: str) -> str:
    return (text or "").strip()


def _cluster_label(meta: dict[str, Any]) -> str:
    clusters = meta.get("merged_clusters", []) if isinstance(meta, dict) else []
    if not isinstance(clusters, list) or not clusters:
        return "—"

    labels: list[str] = []
    for idx, cluster in enumerate(clusters[:5], 1):
        if not isinstance(cluster, dict):
            continue

        chunk_indexes = cluster.get("chunk_indexes", [])
        if isinstance(chunk_indexes, list) and chunk_indexes:
            left = chunk_indexes[0]
            right = chunk_indexes[-1]
            span = f"{left}" if left == right else f"{left}-{right}"
        else:
            span = "?"

        methods = cluster.get("methods", [])
        if isinstance(methods, list) and methods:
            method_label = ",".join(str(m) for m in methods[:3])
        else:
            method_label = "—"

        labels.append(f"C{idx}:{span} [{method_label}]")

    if len(clusters) > 5:
        labels.append("…")
    return " | ".join(labels) if labels else "—"


def _format_llm_label(meta: dict[str, Any]) -> str:
    llm_class = str(meta.get("llm_rerank_class", "")).strip().lower()
    llm_score = meta.get("llm_rerank_score")
    llm_keep = bool(meta.get("llm_rerank_keep", False))

    if llm_class:
        if isinstance(llm_score, (int, float)):
            return f"{llm_class} ({float(llm_score):.2f})"
        return llm_class

    if isinstance(llm_score, (int, float)):
        keep_label = "keep" if llm_keep else "drop"
        return f"{float(llm_score):.2f} ({keep_label})"

    return "—"


def _result_metadata(item: dict[str, Any]) -> tuple[str, int, str, str, str]:
    meta = item.get("meta", {}) if isinstance(item.get("meta"), dict) else {}

    methods = ""
    raw_methods = meta.get("methods", [])
    if isinstance(raw_methods, list):
        methods = ", ".join(str(m) for m in raw_methods)

    hit_count = int(meta.get("hit_count", 1)) if meta else 1

    raw_indexes = meta.get("chunk_indexes", []) if meta else []
    if isinstance(raw_indexes, list) and raw_indexes:
        idx_label = ", ".join(str(x) for x in raw_indexes[:8])
        if len(raw_indexes) > 8:
            idx_label += ", …"
    else:
        idx_label = "—"

    cluster_label = _cluster_label(meta)
    llm_label = _format_llm_label(meta)
    return methods, hit_count, idx_label, cluster_label, llm_label


def _render_result_item(index: int, item: object) -> list[str]:
    if isinstance(item, dict):
        name = str(item.get("name", "Unknown"))
        score = float(item.get("score", 0.0))
        excerpt = str(item.get("excerpt", "") or "")
        methods, hit_count, idx_label, cluster_label, llm_label = _result_metadata(item)
    else:
        name, score, excerpt = item
        methods = ""
        hit_count = 1
        idx_label = "—"
        cluster_label = "—"
        llm_label = "—"

    return [
        f"### {index}. {name}",
        f"*Score: {score:.3f}*",
        f"*Merged chunks:* {hit_count}  |  *Methods:* {methods or '—'}",
        f"*Chunk idx:* {idx_label}",
        f"*Merge trace:* {cluster_label}",
        f"*LLM relevance:* {llm_label}",
        _quote_block(str(excerpt)),
        "---",
    ]


def build_results_markdown(query: str, results: list, debug_info: object = None) -> str:
    """Build markdown block for one RAG search result set."""
    warnings = extract_warnings(debug_info)
    lines = [f"## 🔍 {query}"]

    if warnings:
        lines.append("### ⚠ Warnings")
        for message in warnings[:8]:
            lines.append(f"- {message}")
        lines.append("---")

    if results:
        for index, item in enumerate(results, 1):
            lines.extend(_render_result_item(index, item))
    else:
        lines.append("*Keine Treffer.*")
        lines.append("---")

    return "\n\n".join(lines)
