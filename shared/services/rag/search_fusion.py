"""Ranking and result list fusion helpers."""
from __future__ import annotations


def rrf_merge(
    a: list[tuple[str, float, str]],
    b: list[tuple[str, float, str]],
    k: int = 60,
) -> list[tuple[str, float, str]]:
    scores: dict[str, float] = {}
    excerpts: dict[str, str] = {}

    for rank, (key, _score, ex) in enumerate(a):
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        excerpts[key] = ex

    for rank, (key, _score, ex) in enumerate(b):
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        if key not in excerpts:
            excerpts[key] = ex

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [(key, score, excerpts[key]) for key, score in ranked]


def deduplicate_and_rerank(results: list[tuple[str, float, str]]) -> list[tuple[str, float, str]]:
    best: dict[str, tuple[float, str]] = {}
    for key, score, ex in results:
        if key not in best or score > best[key][0]:
            best[key] = (score, ex)
    return sorted(
        [(key, score, ex) for key, (score, ex) in best.items()],
        key=lambda item: item[1],
        reverse=True,
    )


def merge_regex_first(
    regex_hits: list[tuple[str, float, str]],
    semantic_hits: list[tuple[str, float, str]],
    max_total: int,
) -> list[tuple[str, float, str]]:
    seen = {key for key, _, _ in semantic_hits}
    unique_regex = [(key, score, ex) for key, score, ex in regex_hits if key not in seen]
    return (unique_regex + semantic_hits)[:max_total]
