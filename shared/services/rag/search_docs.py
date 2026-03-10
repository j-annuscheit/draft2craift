"""Document-level aggregation of chunk search hits."""
from __future__ import annotations

import re
from typing import Any


def merge_overlap_texts(blocks: list[str]) -> str:
    clean = [block.strip() for block in blocks if block and block.strip()]
    if not clean:
        return ""

    merged = clean[0]
    for nxt in clean[1:]:
        if nxt in merged:
            continue
        if merged in nxt:
            merged = nxt
            continue
        max_overlap = min(len(merged), len(nxt), 500)
        overlap = 0
        for n in range(max_overlap, 39, -1):
            if merged[-n:] == nxt[:n]:
                overlap = n
                break
        if overlap > 0:
            merged = merged + nxt[overlap:]
        else:
            merged = merged.rstrip() + "\n\n" + nxt.lstrip()
    return merged


def dedupe_adjacent_paragraphs(text: str) -> str:
    parts = [part.strip() for part in re.split(r"\n{2,}", text or "") if part.strip()]
    if not parts:
        return ""

    out: list[str] = []
    prev_norm = ""
    for part in parts:
        norm = re.sub(r"\s+", " ", part).strip().lower()
        if norm and norm == prev_norm:
            continue
        out.append(part)
        prev_norm = norm
    return "\n\n".join(out)


def to_doc_results(
    chunk_hits: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    doc_map: dict[str, list[dict[str, Any]]] = {}
    for hit in chunk_hits:
        doc_map.setdefault(hit["doc"], []).append(hit)

    doc_results: list[dict[str, Any]] = []
    doc_merges_debug: list[dict[str, Any]] = []

    for doc_name, hits in doc_map.items():
        hits.sort(
            key=lambda hit: (
                hit["span"][0] if hit["span"] is not None else 10**12,
                hit["chunk_idx"] if hit["chunk_idx"] is not None else 10**9,
                -float(hit["score"]),
            )
        )

        clusters: list[dict[str, Any]] = []
        merge_span_gap = 240
        for hit in hits:
            idx = hit["chunk_idx"]
            span = hit["span"]
            can_merge = False
            if clusters:
                prev = clusters[-1]
                if span is not None and prev["max_span"] is not None:
                    can_merge = span[0] <= prev["max_span"] + merge_span_gap
                elif idx is not None and prev["max_idx"] is not None and idx <= prev["max_idx"] + 1:
                    can_merge = True

            if can_merge:
                current = clusters[-1]
                current["hits"].append(hit)
                if idx is not None:
                    if current["min_idx"] is None:
                        current["min_idx"] = idx
                    current["max_idx"] = idx if current["max_idx"] is None else max(current["max_idx"], idx)
                if span is not None:
                    if current["min_span"] is None:
                        current["min_span"] = span[0]
                    if current["max_span"] is None:
                        current["max_span"] = span[1]
                    else:
                        current["max_span"] = max(current["max_span"], span[1])
            else:
                clusters.append(
                    {
                        "hits": [hit],
                        "min_idx": idx,
                        "max_idx": idx,
                        "min_span": span[0] if span is not None else None,
                        "max_span": span[1] if span is not None else None,
                    }
                )

        merged_blocks: list[dict[str, Any]] = []
        block_texts: list[str] = []
        for cluster in clusters:
            cluster_hits = cluster["hits"]
            text = merge_overlap_texts([hit["excerpt"] for hit in cluster_hits])
            text = dedupe_adjacent_paragraphs(text)
            if not text:
                continue

            methods = sorted({method for hit in cluster_hits for method in hit["methods"]})
            keys = [hit["key"] for hit in cluster_hits]
            indexes = [hit["chunk_idx"] for hit in cluster_hits if hit["chunk_idx"] is not None]
            spans = [hit["span"] for hit in cluster_hits if hit["span"] is not None]
            merged_blocks.append(
                {
                    "chunk_keys": keys,
                    "chunk_indexes": indexes,
                    "methods": methods,
                    "text_length": len(text),
                    "span_start": min(span[0] for span in spans) if spans else None,
                    "span_end": max(span[1] for span in spans) if spans else None,
                }
            )
            block_texts.append(text)

        if not block_texts:
            continue

        merged_excerpt = dedupe_adjacent_paragraphs("\n\n[...]\n\n".join(block_texts))
        max_score = max(float(hit["score"]) for hit in hits)
        coverage_bonus = min(0.40, 0.08 * (len(hits) - 1))
        methods = sorted({method for hit in hits for method in hit["methods"]})
        method_bonus = min(0.15, 0.05 * max(0, len(methods) - 1))
        cluster_bonus = min(0.15, 0.05 * max(0, len(merged_blocks) - 1))
        doc_score = max_score + coverage_bonus + method_bonus + cluster_bonus

        chunk_keys = [hit["key"] for hit in hits]
        chunk_indexes = [hit["chunk_idx"] for hit in hits if hit["chunk_idx"] is not None]
        rerank_classes = [
            str(hit.get("llm_rerank_class", "")).strip().lower()
            for hit in hits
            if str(hit.get("llm_rerank_class", "")).strip()
        ]
        rerank_scores = [
            float(hit.get("llm_rerank_score"))
            for hit in hits
            if isinstance(hit.get("llm_rerank_score"), (int, float))
        ]
        rerank_reasons = sorted(
            {
                str(hit.get("llm_rerank_reason", "")).strip()
                for hit in hits
                if str(hit.get("llm_rerank_reason", "")).strip()
            }
        )

        doc_results.append(
            {
                "name": doc_name,
                "score": float(doc_score),
                "excerpt": merged_excerpt,
                "meta": {
                    "hit_count": len(hits),
                    "methods": methods,
                    "chunk_keys": chunk_keys,
                    "chunk_indexes": chunk_indexes,
                    "cluster_count": len(merged_blocks),
                    "merged_clusters": merged_blocks,
                    "llm_rerank_class": (
                        "sinnvoll"
                        if any(cls == "sinnvoll" for cls in rerank_classes)
                        else (rerank_classes[0] if rerank_classes else "")
                    ),
                    "llm_rerank_score": (sum(rerank_scores) / len(rerank_scores) if rerank_scores else None),
                    "llm_rerank_keep": (
                        any(cls == "sinnvoll" for cls in rerank_classes)
                        if rerank_classes
                        else bool(rerank_scores)
                    ),
                    "llm_rerank_reason": rerank_reasons[0] if rerank_reasons else "",
                },
            }
        )

        doc_merges_debug.append(
            {
                "doc": doc_name,
                "score": float(doc_score),
                "hit_count": len(hits),
                "methods": methods,
                "chunk_keys": chunk_keys,
                "chunk_indexes": chunk_indexes,
                "merged_clusters": merged_blocks,
            }
        )

    doc_results.sort(key=lambda item: float(item["score"]), reverse=True)
    return doc_results, doc_merges_debug
