"""HyDE/query expansion and optional LLM reranking helpers."""
from __future__ import annotations

import re
from typing import Any, Callable, Protocol


class ExpanderConfig(Protocol):
    hyde: Any
    literal: Any
    rerank: Any


class RAGExpanders:
    """Holds callback-based expanders and exposes guarded execution helpers."""

    def __init__(
        self,
        config: ExpanderConfig,
        logger: Any = None,
        tfidf_query_expander: Callable[[str], str] | None = None,
    ):
        self._config = config
        self._log = logger
        self._tfidf_query_expander: Callable | None = tfidf_query_expander
        self._st_query_expander: Callable | None = None
        self._literal_query_expander: Callable | None = None
        self._rag_reranker: Callable | None = None

    def set_config(self, config: ExpanderConfig) -> None:
        self._config = config

    def set_query_expander(self, fn: Callable[[str], str] | None) -> None:
        """Deprecated alias for TF-IDF query expander."""
        self._tfidf_query_expander = fn

    def set_tfidf_query_expander(self, fn: Callable[[str], str] | None) -> None:
        self._tfidf_query_expander = fn

    def set_st_query_expander(self, fn: Callable | None) -> None:
        self._st_query_expander = fn

    def set_literal_query_expander(self, fn: Callable | None) -> None:
        self._literal_query_expander = fn

    def set_rag_reranker(self, fn: Callable | None) -> None:
        self._rag_reranker = fn

    @property
    def tfidf_query_expander(self) -> Callable | None:
        return self._tfidf_query_expander

    @property
    def st_query_expander(self) -> Callable | None:
        return self._st_query_expander

    @property
    def literal_query_expander(self) -> Callable | None:
        return self._literal_query_expander

    @property
    def rag_reranker(self) -> Callable | None:
        return self._rag_reranker

    @staticmethod
    def normalise_literal_terms(terms: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in terms:
            term = str(raw or "").strip()
            if not term:
                continue
            term = re.sub(r"^\s*(?:[-*\u2022]+|\d+[\.\)])\s*", "", term).strip()
            term = term.strip("\"'`")
            term = re.sub(r"\s+", " ", term)
            if len(term) < 2:
                continue
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(term)
        return out[:24]

    def safe_expand_tfidf(self, query: str, global_toc: str = "") -> str:
        """Run TF-IDF HyDE expansion; return original query on failure."""
        cfg = self._config
        if not self._tfidf_query_expander:
            return query

        try:
            input_query = query
            if cfg.hyde.use_doc_context and global_toc:
                input_query = f"[Dokumentstruktur:\n{global_toc}]\n\n{query}"
            result = self._tfidf_query_expander(input_query)
            expanded = str(result or "").strip()
            if self._log and expanded and expanded != query:
                self._log.info("LLM", f"HyDE TF-IDF keywords: '{query}'  ->  '{expanded[:80]}'")
            return expanded if expanded else query
        except Exception as exc:
            if self._log:
                self._log.error("LLM", f"HyDE TF-IDF expansion error: {exc}")
            return query

    def safe_expand_st(self, query: str, global_toc: str = "") -> list[str]:
        """Run ST HyDE and return one or multiple hypothetical passages."""
        cfg = self._config
        if not self._st_query_expander:
            return [query]

        n_hypotheses = cfg.hyde.st_hypotheses if cfg.hyde.st_mode == "multi_passage" else 1
        try:
            input_query = query
            if cfg.hyde.use_doc_context and global_toc:
                input_query = f"[Dokumentstruktur:\n{global_toc}]\n\n{query}"
            result = self._st_query_expander(input_query, n_hypotheses)
            if isinstance(result, str):
                result = [result]
            passages = [p.strip() for p in result if str(p).strip()]
            if self._log and passages and passages != [query]:
                self._log.info("ST", f"HyDE ST passages x{len(passages)}: '{query}'")
            return passages if passages else [query]
        except Exception as exc:
            if self._log:
                self._log.error("ST", f"HyDE ST expansion error: {exc}")
            return [query]

    def safe_expand_literal_terms(self, query: str) -> tuple[list[str], dict[str, Any]]:
        """Expand literal terms via optional LLM callback."""
        if not self._literal_query_expander:
            return [], {"attempted": False, "used": False, "reason": "no_expander"}

        cfg = self._config
        limit = max(1, int(cfg.literal.max_llm_terms))
        try:
            result = self._literal_query_expander(query, limit)  # type: ignore[misc]
            meta: dict[str, Any] = {}
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
                raw_result = result[0]
                meta = dict(result[1])
            else:
                raw_result = result

            if isinstance(raw_result, str):
                raw_terms = [term.strip() for term in re.split(r"[,\n;]+", raw_result) if term.strip()]
            else:
                raw_terms = [str(term).strip() for term in (raw_result or []) if str(term).strip()]

            terms = self.normalise_literal_terms(raw_terms)[:limit]
            if self._log and terms:
                self._log.info("LLM", f"Literal terms: '{query}'  ->  {', '.join(terms[:8])}")
            return terms, {
                "attempted": True,
                "used": bool(terms),
                "reason": meta.get("reason", ("ok" if terms else "empty")),
                **meta,
            }
        except Exception as exc:
            if self._log:
                self._log.error("LLM", f"Literal term expansion error: {exc}")
            return [], {
                "attempted": True,
                "used": False,
                "reason": "exception",
                "error": str(exc),
            }

    def safe_rerank_items(
        self,
        query: str,
        items: list[dict[str, Any]],
        top_k: int,
    ) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
        """Apply optional LLM reranker with guarded error handling."""
        if not self._rag_reranker:
            return None, {
                "enabled": True,
                "applied": False,
                "reason": "no_reranker",
            }

        cfg = self._config
        try:
            result = self._rag_reranker(
                query,
                items,
                top_k,
                float(cfg.rerank.min_score),
            )
            rerank_meta: dict[str, Any] = {}
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
                reranked_docs = result[0]
                rerank_meta = dict(result[1])
            else:
                reranked_docs = result

            if not isinstance(reranked_docs, list):
                return None, {
                    "enabled": True,
                    "applied": False,
                    "reason": "invalid_reranker_return",
                    **rerank_meta,
                }

            clean = [doc for doc in reranked_docs if isinstance(doc, dict)]
            return clean, {
                "enabled": True,
                "applied": True,
                "reason": "ok",
                "kept": len(clean),
                **rerank_meta,
            }
        except Exception as exc:
            if self._log:
                self._log.error("LLM", f"RAG rerank error: {exc}")
            return None, {
                "enabled": True,
                "applied": False,
                "reason": "exception",
                "error": str(exc),
            }

    def should_expand(self, query: str) -> bool:
        cfg = self._config
        return bool(cfg.hyde.use_hyde and len(str(query or "").split()) <= cfg.hyde.min_words)
