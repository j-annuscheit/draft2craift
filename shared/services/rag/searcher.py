"""Search pipeline: retrieval, fusion, selection, and debug assembly."""
from __future__ import annotations

import re
import time
from typing import Any

from shared.services.rag.search_docs import to_doc_results
from shared.services.rag.search_fusion import (
    deduplicate_and_rerank,
    merge_regex_first,
    rrf_merge,
)

# Retrieval oversampling for better recall before fusion and filtering.
_RETRIEVAL_OVERSAMPLE_FACTOR = 4
_RETRIEVAL_MIN_FETCH_K = 30

# Candidate pool after fusion; kept larger than final top_k for selection/rerank.
_CANDIDATE_OVERSAMPLE_FACTOR = 4
_CANDIDATE_MIN_TOP_K = 20

# Literal direct-match scoring heuristic.
# Base boost for one literal hit plus capped bonus per additional matched term.
_LITERAL_DIRECT_BASE_SCORE = 1.5
_LITERAL_DIRECT_BONUS_CAP = 0.6
_LITERAL_DIRECT_BONUS_PER_EXTRA_MATCH = 0.1


class RAGSearcher:
    """Coordinates retrieval across TF-IDF/ST/literal and builds document hits."""

    def __init__(self, config: Any, indexer: Any, expanders: Any, logger: Any = None):
        self.config = config
        self._indexer = indexer
        self._expanders = expanders
        self._log = logger

    def set_config(self, config: Any) -> None:
        self.config = config

    def search(
        self,
        query: str,
        top_k: int | None = None,
        with_debug: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        t0 = time.perf_counter()
        cfg = self.config
        effective_top_k = top_k if top_k is not None else cfg.selection.top_k
        fetch_k = max(
            effective_top_k * _RETRIEVAL_OVERSAMPLE_FACTOR,
            _RETRIEVAL_MIN_FETCH_K,
        )
        trace_by_key: dict[str, dict[str, Any]] = {}
        span_cache: dict[str, tuple[int, int] | None] = {}

        def trace_hit(bucket: str, ranked: list[tuple[str, float, str]]) -> None:
            for rank, (key, score, _ex) in enumerate(ranked, 1):
                trace = trace_by_key.setdefault(key, {"tfidf": None, "st": None, "regex": None})
                prev = trace.get(bucket)
                if prev is None or rank < int(prev["rank"]):
                    trace[bucket] = {"rank": rank, "score": float(score)}

        def chunk_index(key: str) -> int | None:
            if "\x00" not in key:
                return None
            try:
                return int(key.rsplit("\x00", 1)[1])
            except (ValueError, IndexError):
                return None

        def get_span(key: str) -> tuple[int, int] | None:
            if key not in span_cache:
                span_cache[key] = self._indexer.chunk_span(key)
            return span_cache[key]

        tfidf_query = query
        st_queries = [query]
        should_expand = self._expanders.should_expand(query)

        if should_expand:
            if cfg.backend.use_tfidf and self._expanders.tfidf_query_expander:
                tfidf_query = self._expanders.safe_expand_tfidf(query, self._indexer.global_toc)
            if cfg.backend.use_st and self._indexer.st_model and self._expanders.st_query_expander:
                st_queries = self._expanders.safe_expand_st(query, self._indexer.global_toc)

        tfidf_raw: list[tuple[str, float, str]] = []
        st_raw: list[tuple[str, float, str]] = []

        if cfg.backend.use_tfidf:
            tfidf_raw = self._indexer.index.search(tfidf_query, fetch_k)
            trace_hit("tfidf", tfidf_raw)

        if cfg.backend.use_st and self._indexer.st_model:
            for st_query in st_queries:
                batch = self._indexer.st_search(st_query, fetch_k)
                st_raw.extend(batch)
                trace_hit("st", batch)
            if len(st_queries) > 1:
                st_raw = deduplicate_and_rerank(st_raw)

        if tfidf_raw and st_raw:
            raw = rrf_merge(tfidf_raw, st_raw)
            if self._log:
                self._log.debug(
                    "RAG",
                    f"RRF merge: {len(tfidf_raw)} TF-IDF + {len(st_raw)} ST -> {len(raw)} merged",
                )
        elif st_raw:
            raw = st_raw
        else:
            raw = tfidf_raw

        candidate_top_k = max(
            effective_top_k * _CANDIDATE_OVERSAMPLE_FACTOR,
            _CANDIDATE_MIN_TOP_K,
        )
        raw = raw[:candidate_top_k]

        regex_hits: list[tuple[str, float, str]] = []
        literal_terms = [query.strip()] if (cfg.backend.use_regex_search and query.strip()) else []
        literal_llm_terms: list[str] = []
        warnings: list[str] = []

        if cfg.backend.use_regex_search and query.strip():
            if cfg.literal.use_llm_terms:
                if not self._expanders.literal_query_expander:
                    warnings.append(
                        "Literal LLM terms enabled, but no LLM expander is configured. Continuing without LLM term expansion."
                    )
                else:
                    literal_llm_terms, literal_meta = self._expanders.safe_expand_literal_terms(query)
                    if not bool(literal_meta.get("used", bool(literal_llm_terms))):
                        reason = str(literal_meta.get("reason", "unknown"))
                        warnings.append(
                            "Literal LLM term expansion requested but not used "
                            f"(reason: {reason}). Continuing with base query terms."
                        )
                literal_terms.extend(literal_llm_terms)

            regex_hits = self._regex_search(literal_terms)
            trace_hit("regex", regex_hits)

        merged = merge_regex_first(regex_hits, raw, candidate_top_k + cfg.literal.max_results)
        merged = self._apply_selection(merged, candidate_top_k + cfg.literal.max_results)

        chunk_hits: list[dict[str, Any]] = []
        for key, score, fallback_excerpt in merged:
            doc_name = self._indexer.chunk_to_doc.get(key, key)
            ex = self._indexer.content_cache.get(key, "").strip() or fallback_excerpt.strip()
            if not ex:
                continue

            ex = self._indexer.paragraph_excerpt(key, ex)
            if cfg.context.enabled:
                ex = self._indexer.extended_excerpt(key, ex)
            elif key in self._indexer.chunk_parents:
                ex = self._indexer.chunk_parents[key]

            trace = trace_by_key.get(key, {})
            methods = [bucket for bucket in ("tfidf", "st", "regex") if trace.get(bucket) is not None]
            chunk_hits.append(
                {
                    "key": key,
                    "doc": doc_name,
                    "chunk_idx": chunk_index(key),
                    "score": float(score),
                    "excerpt": ex,
                    "methods": methods,
                    "trace": trace,
                    "span": get_span(key),
                }
            )

        chunk_rerank_debug: dict[str, Any] = {
            "enabled": bool(cfg.rerank.enabled),
            "applied": False,
            "kept": len(chunk_hits),
            "before": len(chunk_hits),
            "threshold": float(cfg.rerank.min_score),
            "mode": "per_hit_all",
        }
        if cfg.rerank.enabled and chunk_hits:
            rerank_candidates = list(chunk_hits)
            reranked, rerank_meta = self._expanders.safe_rerank_items(query, rerank_candidates, len(rerank_candidates))
            if isinstance(rerank_meta, dict):
                chunk_rerank_debug.update(rerank_meta)

            if reranked is None:
                chunk_hits = rerank_candidates
            else:
                by_key = {
                    str(hit.get("key", "")): hit
                    for hit in rerank_candidates
                    if isinstance(hit, dict)
                }
                selected: list[dict[str, Any]] = []
                for item in reranked:
                    if not isinstance(item, dict):
                        continue
                    key = str(item.get("key", ""))
                    base = by_key.get(key)
                    if base is None:
                        continue
                    merged_hit = dict(base)
                    meta = item.get("meta", {}) if isinstance(item.get("meta"), dict) else {}
                    if "llm_rerank_class" in meta:
                        merged_hit["llm_rerank_class"] = str(meta.get("llm_rerank_class", ""))
                    if "llm_rerank_score" in meta:
                        merged_hit["llm_rerank_score"] = float(meta.get("llm_rerank_score", 0.0))
                    if "llm_rerank_keep" in meta:
                        merged_hit["llm_rerank_keep"] = bool(meta.get("llm_rerank_keep"))
                    if "llm_rerank_reason" in meta:
                        merged_hit["llm_rerank_reason"] = str(meta.get("llm_rerank_reason", ""))
                    selected.append(merged_hit)
                chunk_hits = selected
            chunk_rerank_debug["before"] = len(rerank_candidates)
            chunk_rerank_debug["kept"] = len(chunk_hits)
            if not bool(chunk_rerank_debug.get("applied", False)):
                reason = str(chunk_rerank_debug.get("reason", "unknown"))
                warnings.append(
                    "LLM reranking requested but could not be applied "
                    f"(reason: {reason}). Continuing without LLM reranking."
                )

        doc_results, doc_merges_debug = to_doc_results(chunk_hits)
        doc_results = self._apply_doc_selection(doc_results, effective_top_k)

        debug_info: dict[str, Any] = {
            "query": query,
            "effective_top_k": effective_top_k,
            "candidate_top_k": candidate_top_k,
            "fetch_k": fetch_k,
            "selection_mode": cfg.selection.mode,
            "should_expand": should_expand,
            "tfidf_query": tfidf_query,
            "st_queries": st_queries,
            "literal_terms": literal_terms,
            "literal_llm_terms": literal_llm_terms,
            "rerank": chunk_rerank_debug,
            "warnings": warnings,
            "counts": {
                "tfidf_raw": len(tfidf_raw),
                "st_raw": len(st_raw),
                "regex_hits": len(regex_hits),
                "fused_chunk_hits": len(chunk_hits),
                "doc_results": len(doc_results),
            },
            "chunk_hits": [
                {
                    "key": hit["key"],
                    "doc": hit["doc"],
                    "chunk_idx": hit["chunk_idx"],
                    "span_start": hit["span"][0] if hit["span"] is not None else None,
                    "span_end": hit["span"][1] if hit["span"] is not None else None,
                    "score": round(float(hit["score"]), 6),
                    "methods": hit["methods"],
                    "llm_rerank_class": hit.get("llm_rerank_class", ""),
                    "llm_rerank_keep": hit.get("llm_rerank_keep", None),
                    "llm_rerank_reason": hit.get("llm_rerank_reason", ""),
                    "trace": hit["trace"],
                }
                for hit in chunk_hits
            ],
            "doc_merges": doc_merges_debug,
        }

        if self._log:
            dt = (time.perf_counter() - t0) * 1000
            notes: list[str] = []
            if tfidf_query != query and cfg.backend.use_tfidf:
                notes.append(f"tfidf_q='{tfidf_query[:60]}'")
            if len(st_queries) > 1:
                notes.append(f"st_passages={len(st_queries)}")
            if literal_llm_terms:
                notes.append(f"literal_terms={len(literal_terms)}")
            if chunk_rerank_debug.get("enabled"):
                notes.append(
                    f"rerank={chunk_rerank_debug.get('kept', len(chunk_hits))}/"
                    f"{chunk_rerank_debug.get('before', len(chunk_hits))}"
                )
            suffix = ("  " + "  ".join(notes)) if notes else ""
            self._log.info(
                "RAG",
                f"Search '{query}'  |  {self._indexer.current_backend()}  mode={cfg.selection.mode}"
                f"  |  chunks={len(chunk_hits)}  docs={len(doc_results)}  |  {dt:.1f}ms"
                + suffix,
            )

        if with_debug:
            return doc_results, debug_info
        return doc_results

    def _regex_search(self, terms: list[str]) -> list[tuple[str, float, str]]:
        clean_terms = self._expanders.normalise_literal_terms(terms)
        if not clean_terms:
            return []

        patterns: list[tuple[str, Any]] = []
        for term in clean_terms:
            try:
                patterns.append((term, re.compile(re.escape(term), re.IGNORECASE)))
            except re.error:
                continue
        if not patterns:
            return []

        scored: list[tuple[str, float, str, int, int]] = []
        for key, content in self._indexer.content_cache.items():
            body = content.strip()
            if not body:
                continue

            match_count = 0
            first_pos = len(body)
            for _term, pattern in patterns:
                match = pattern.search(body)
                if match:
                    match_count += 1
                    first_pos = min(first_pos, match.start())

            if match_count <= 0:
                continue

            score = _LITERAL_DIRECT_BASE_SCORE + min(
                _LITERAL_DIRECT_BONUS_CAP,
                _LITERAL_DIRECT_BONUS_PER_EXTRA_MATCH * (match_count - 1),
            )
            scored.append((key, score, body, match_count, first_pos))

        scored.sort(key=lambda item: (-item[3], -item[1], item[4]))
        result = [
            (key, score, ex)
            for key, score, ex, _count, _pos in scored[: self.config.literal.max_results]
        ]
        if self._log and result:
            docs = [self._indexer.chunk_to_doc.get(key, key) for key, _, _ in result]
            self._log.debug(
                "RAG",
                f"Literal terms '{', '.join(clean_terms[:6])}'  |  {len(result)} hits in: {', '.join(set(docs))}",
            )
        return result

    def _apply_selection(
        self,
        raw: list[tuple[str, float, str]],
        top_k: int,
    ) -> list[tuple[str, float, str]]:
        mode = self.config.selection.mode
        threshold = self.config.selection.score_threshold
        if mode == "threshold":
            return [row for row in raw if row[1] >= threshold]
        if mode == "top_k_threshold":
            return [row for row in raw if row[1] >= threshold][:top_k]
        return raw[:top_k]

    def _apply_doc_selection(self, docs: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        mode = self.config.selection.mode
        threshold = self.config.selection.score_threshold
        if mode == "threshold":
            return [doc for doc in docs if float(doc.get("score", 0.0)) >= threshold]
        if mode == "top_k_threshold":
            return [doc for doc in docs if float(doc.get("score", 0.0)) >= threshold][:top_k]
        return docs[:top_k]
