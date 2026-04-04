"""Local-first RAG orchestration based on library-first components.

This module keeps a stable public API for the UI/worker layer while moving
the retrieval stack toward:

- LlamaIndex + LanceDB (vector stage, when optional deps are installed)
- configurable lexical and literal stages (for fast local fallbacks)
- stage-based selection/rerank/context logic for easy experimentation
- plugin hooks for extension without hard-forking core code
"""
from __future__ import annotations

import importlib
import hashlib
import os
import re
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from shared.services.rag.chunking import build_chunks
from shared.services.rag.config import RAGConfig

_SEP = "\x00"
_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)
_REGEX_FLAGS = re.IGNORECASE | re.MULTILINE
_MAX_EXCERPT_LEN = 8_000
_HF_OFFLINE_ENV_DEFAULTS = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
}


def _ensure_hf_offline_env() -> None:
    for key, value in _HF_OFFLINE_ENV_DEFAULTS.items():
        if not str(os.environ.get(key, "") or "").strip():
            os.environ[key] = value


def _resolve_local_hf_model_ref(model_name: str) -> str:
    raw = str(model_name or "").strip()
    if not raw:
        return ""
    path = Path(raw).expanduser()
    if path.exists():
        return str(path)

    hub_root = str(os.environ.get("HF_HUB_CACHE", "") or "").strip()
    if not hub_root:
        hub_root = str((Path.home() / ".cache" / "huggingface" / "hub"))
    repo_dir = Path(hub_root).expanduser() / f"models--{raw.replace('/', '--')}"
    snapshots_dir = repo_dir / "snapshots"
    if not snapshots_dir.is_dir():
        return raw
    candidates = [entry for entry in snapshots_dir.iterdir() if entry.is_dir()]
    if not candidates:
        return raw
    candidates.sort(key=lambda entry: float(entry.stat().st_mtime), reverse=True)
    return str(candidates[0])


@dataclass(slots=True)
class _ChunkRecord:
    chunk_id: str
    doc_name: str
    chunk_index: int
    text: str
    raw_text: str
    breadcrumb: list[str] = field(default_factory=list)
    start: int = 0
    end: int = 0


@dataclass(slots=True)
class _SearchHit:
    chunk: _ChunkRecord
    score: float
    methods: set[str] = field(default_factory=set)
    match_start: int = -1
    match_end: int = -1
    llm_rerank_class: str = ""
    llm_rerank_score: float | None = None
    llm_rerank_keep: bool | None = None
    llm_rerank_reason: str = ""


@dataclass(slots=True)
class _SectionRecord:
    section_id: str
    doc_name: str
    breadcrumb: list[str]
    path: str
    summary: str
    chunk_ids: list[str]


@dataclass(slots=True)
class _SectionRoutingResult:
    enabled: bool = False
    mode: str = "hybrid"
    strict_filter: bool = False
    score_boost: float = 0.0
    selected_section_ids: set[str] = field(default_factory=set)
    selected_scores: dict[str, float] = field(default_factory=dict)
    query_expansions: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)


class RAGSystem(QObject):
    """Thread-safe RAG facade used by the GUI and project persistence layer."""

    results_ready = Signal(list)
    backend_changed = Signal(str)
    rag_settings_requested = Signal()

    def __init__(
        self,
        config: RAGConfig | None = None,
        query_expander: Callable[[str], str] | None = None,
        logger: Any = None,
        plugin_manager: Any = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._log = logger
        self._plugin_manager = plugin_manager
        self._config = config or RAGConfig()
        self._lock = threading.RLock()

        # Compatibility callbacks from the legacy pipeline.
        self._query_expander: Callable[[str], str] | None = query_expander
        self._tfidf_query_expander: Callable[[str], str] | None = None
        self._st_query_expander: Callable[..., Any] | None = None
        self._literal_query_expander: Callable[..., Any] | None = None
        self._rag_reranker: Callable[..., Any] | None = None

        # Canonical in-memory corpus state.
        self._documents: dict[str, str] = {}
        self._chunks: list[_ChunkRecord] = []
        self._chunks_by_id: dict[str, _ChunkRecord] = {}
        self._chunks_by_doc: dict[str, list[_ChunkRecord]] = {}
        self._sections: list[_SectionRecord] = []
        self._sections_by_id: dict[str, _SectionRecord] = {}
        self._section_by_chunk_id: dict[str, str] = {}

        # Vector backend state (optional dependencies).
        self._vector_stack = self._load_vector_stack()
        self._vector_index: Any = None
        self._vector_backend_available = False
        self._vector_backend_error = ""
        self._vector_embedding_provider = ""
        self._lancedb_dir: Path | None = None
        self._require_vector_backend = True

    # ------------------------------------------------------------------
    # Public config / compatibility surface
    # ------------------------------------------------------------------
    @property
    def config(self) -> RAGConfig:
        with self._lock:
            return self._config

    @config.setter
    def config(self, value: RAGConfig) -> None:
        with self._lock:
            self._config = value if isinstance(value, RAGConfig) else RAGConfig()
            self._rebuild_index()
            backend = self.current_backend()
        self.backend_changed.emit(backend)

    @property
    def _st_model(self) -> Any:
        """Legacy compatibility attribute (sentence-transformers removed)."""
        return None

    @_st_model.setter
    def _st_model(self, value: Any) -> None:
        _ = value

    @property
    def _st_embeddings(self) -> dict[str, Any]:
        """Legacy compatibility attribute (sentence-transformers removed)."""
        return {}

    @_st_embeddings.setter
    def _st_embeddings(self, value: dict[str, Any]) -> None:
        _ = value

    @property
    def st_model_loaded(self) -> bool:
        return False

    def try_load_sentence_transformers(self, model_name: str | None = None) -> bool:
        """Kept for API compatibility; ST runtime is intentionally removed."""
        if self._log:
            self._log.info(
                "RAG",
                "Sentence-Transformers runtime is deprecated in v2; no model is loaded.",
            )
        _ = model_name
        self.backend_changed.emit(self.current_backend())
        return False

    def set_query_expander(self, fn: Callable[[str], str] | None) -> None:
        self._query_expander = fn

    def set_tfidf_query_expander(self, fn: Callable[[str], str] | None) -> None:
        self._tfidf_query_expander = fn

    def set_st_query_expander(self, fn: Callable[..., Any] | None) -> None:
        self._st_query_expander = fn

    def set_literal_query_expander(self, fn: Callable[..., Any] | None) -> None:
        self._literal_query_expander = fn

    def set_rag_reranker(self, fn: Callable[..., Any] | None) -> None:
        self._rag_reranker = fn

    def current_backend(self) -> str:
        if self._vector_backend_available:
            return "llamaindex+lancedb"
        return "llamaindex+lancedb-unavailable"

    @property
    def require_vector_backend(self) -> bool:
        return True

    def set_require_vector_backend(self, required: bool) -> None:
        _ = required
        self._require_vector_backend = True

    # ------------------------------------------------------------------
    # Indexing lifecycle
    # ------------------------------------------------------------------
    def index_file(self, path: str) -> bool:
        file_path = Path(str(path or ""))
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return False
        return self.index_content(file_path.name or str(path or ""), content)

    def index_content(self, name: str, content: str) -> bool:
        doc_name = str(name or "").strip()
        if not doc_name:
            return False
        with self._lock:
            self._documents[doc_name] = str(content or "")
            self._rebuild_index()
        return True

    def sync_index(self, entries: list[tuple[str, str]]) -> tuple[int, int, int]:
        """Incrementally align index with provided documents.

        Returns:
            (indexed_count, skipped_count, removed_count)
        """
        target: dict[str, str] = {}
        skipped = 0
        for raw_name, raw_content in list(entries or []):
            name = str(raw_name or "").strip()
            if not name:
                continue
            target[name] = str(raw_content or "")

        with self._lock:
            removed_names = set(self._documents.keys()) - set(target.keys())
            removed = len(removed_names)

            indexed = 0
            for name, content in target.items():
                if self._documents.get(name) == content:
                    skipped += 1
                    continue
                indexed += 1

            self._documents = dict(target)
            self._rebuild_index()
            return indexed, skipped, removed

    def remove_file(self, name: str) -> None:
        key = str(name or "").strip()
        if not key:
            return
        with self._lock:
            if key not in self._documents:
                return
            self._documents.pop(key, None)
            self._rebuild_index()

    def clear(self) -> None:
        with self._lock:
            self._documents.clear()
            self._chunks.clear()
            self._chunks_by_id.clear()
            self._chunks_by_doc.clear()
            self._sections.clear()
            self._sections_by_id.clear()
            self._section_by_chunk_id.clear()
            self._teardown_vector_backend()

    def dump_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": 2,
                "backend": self.current_backend(),
                "documents": dict(self._documents),
                # Compatibility key expected by older project/test code.
                "has_st_embeddings": False,
                "vector_backend_available": bool(self._vector_backend_available),
                "vector_backend_error": str(self._vector_backend_error or ""),
            }

    def load_state(self, state: dict[str, Any]) -> None:
        raw = dict(state or {}) if isinstance(state, dict) else {}
        docs = self._extract_documents_from_state(raw)
        with self._lock:
            self._documents = docs
            self._rebuild_index()

    def _extract_documents_from_state(self, state: dict[str, Any]) -> dict[str, str]:
        docs: dict[str, str] = {}

        raw_docs = state.get("documents")
        if isinstance(raw_docs, dict):
            for name, content in raw_docs.items():
                key = str(name or "").strip()
                if not key:
                    continue
                docs[key] = str(content or "")
            if docs:
                return docs

        # Backward compatibility for older project snapshots.
        old_docs = state.get("doc_full_content")
        if isinstance(old_docs, dict):
            for name, content in old_docs.items():
                key = str(name or "").strip()
                if not key:
                    continue
                docs[key] = str(content or "")
            if docs:
                return docs

        legacy_entries = state.get("entries")
        if isinstance(legacy_entries, list):
            for row in legacy_entries:
                if not isinstance(row, (tuple, list)) or len(row) < 2:
                    continue
                key = str(row[0] or "").strip()
                if not key:
                    continue
                docs[key] = str(row[1] or "")

        return docs

    def _build_chunks(self, content: str, doc_name: str = "") -> list[dict[str, Any]]:
        with self._lock:
            return build_chunks(str(content or ""), self._config.chunking, str(doc_name or ""), self._log)

    # ------------------------------------------------------------------
    # Search pipeline
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        top_k: int | None = None,
        with_debug: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        with self._lock:
            return self._search_locked(query, top_k=top_k, with_debug=with_debug)

    def _search_locked(
        self,
        query: str,
        *,
        top_k: int | None,
        with_debug: bool,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        started = time.perf_counter()
        cfg = self._config
        q = str(query or "").strip()
        warnings: list[str] = []
        effective_top_k = max(1, int(top_k if top_k is not None else cfg.selection.top_k))

        pre_payload = self._run_hook(
            "rag.before_search",
            {
                "query": q,
                "top_k": effective_top_k,
                "config": cfg.to_dict(),
            },
            warnings=warnings,
        )
        if isinstance(pre_payload, dict):
            hook_query = str(pre_payload.get("query", q) or "").strip()
            if hook_query:
                q = hook_query

        if not q:
            debug = self._build_debug_payload(
                query=q,
                effective_top_k=effective_top_k,
                warnings=warnings,
                query_variants=[],
                vector_count=0,
                lexical_count=0,
                regex_count=0,
                merged_count=0,
                routed_count=0,
                selected_count=0,
                results=[],
                regex_debug={},
                rerank_debug={"enabled": bool(cfg.rerank.enabled), "applied": False},
                section_debug={},
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
            )
            return ([], debug) if with_debug else []

        if self._require_vector_backend and not self._vector_backend_available:
            raise RuntimeError(
                "RAG backend unavailable: LlamaIndex/LanceDB + local HuggingFace embeddings "
                "must be available. Install core dependencies and provide a local embedding model."
            )

        query_variants = self._query_variants(q, warnings=warnings)
        routing = self._route_sections(q, query_variants, warnings=warnings)
        if routing.query_expansions:
            query_variants = _dedupe_non_empty(list(query_variants) + list(routing.query_expansions))
        retrieval_k = max(effective_top_k * 4, 20)

        vector_hits, vector_debug = self._vector_search(query_variants, retrieval_k)
        lexical_hits = self._lexical_search(query_variants, retrieval_k) if cfg.backend.use_tfidf else []
        regex_hits, regex_debug = (
            self._regex_search(q, query_variants)
            if cfg.backend.use_regex_search
            else ([], {})
        )

        merged = self._merge_hits(vector_hits, lexical_hits, regex_hits)
        merged_count = len(merged)
        merged = self._apply_section_routing(merged, routing)
        routed_count = len(merged)
        candidates = self._candidate_pool(merged, effective_top_k=effective_top_k)

        rerank_debug: dict[str, Any] = {
            "enabled": bool(cfg.rerank.enabled),
            "applied": False,
            "before": len(candidates),
            "kept": len(candidates),
            "threshold": float(cfg.rerank.min_score),
            "max_candidates": int(cfg.rerank.max_candidates),
        }
        candidates = self._maybe_rerank(q, candidates, warnings=warnings, debug=rerank_debug)

        selected = self._apply_selection_to_hits(
            candidates,
            top_k=effective_top_k,
        )
        results = self._to_doc_results(selected, top_k=effective_top_k)

        post_payload = self._run_hook(
            "rag.after_search",
            {
                "query": q,
                "results": [dict(row) for row in results],
            },
            warnings=warnings,
        )
        if isinstance(post_payload, dict):
            maybe_results = post_payload.get("results")
            if isinstance(maybe_results, list):
                normalized: list[dict[str, Any]] = []
                for row in maybe_results:
                    if isinstance(row, dict):
                        normalized.append(dict(row))
                if normalized:
                    results = normalized

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        debug = self._build_debug_payload(
            query=q,
            effective_top_k=effective_top_k,
            warnings=warnings,
            query_variants=query_variants,
            vector_count=len(vector_hits),
            lexical_count=len(lexical_hits),
            regex_count=len(regex_hits),
            merged_count=merged_count,
            routed_count=routed_count,
            selected_count=len(selected),
            results=results,
            regex_debug=regex_debug,
            rerank_debug=rerank_debug,
            section_debug=routing.debug,
            elapsed_ms=elapsed_ms,
            vector_debug=vector_debug,
        )
        if with_debug:
            return results, debug
        return results

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------
    def _query_variants(self, query: str, *, warnings: list[str]) -> list[str]:
        variants: list[str] = [str(query or "").strip()]
        if not variants[0]:
            return []

        cfg = self._config
        should_expand = bool(cfg.hyde.use_hyde) and _word_count(query) <= max(1, int(cfg.hyde.min_words))
        if not should_expand:
            return variants

        extra: list[str] = []
        extra.extend(self._expand_with_callback(self._query_expander, query, "query_expander", warnings))
        extra.extend(self._expand_with_callback(self._tfidf_query_expander, query, "tfidf_expander", warnings))
        extra.extend(self._expand_with_callback(self._st_query_expander, query, "st_expander", warnings))

        if cfg.hyde.use_doc_context:
            toc = self._doc_context_hint()
            if toc:
                extra.append(f"{query}\n\nContext:\n{toc}")

        if not extra:
            extra.append(f"{query} background and related details")

        max_extra = max(1, int(cfg.hyde.st_hypotheses))
        variants.extend(extra[:max_extra])
        return _dedupe_non_empty(variants)

    def _route_sections(
        self,
        query: str,
        query_variants: list[str],
        *,
        warnings: list[str],
    ) -> _SectionRoutingResult:
        _ = warnings
        cfg = self._config.routing
        mode = str(cfg.mode or "hybrid").strip().lower()
        if mode not in {"heading", "summary", "hybrid"}:
            mode = "hybrid"

        result = _SectionRoutingResult(
            enabled=bool(cfg.enabled),
            mode=mode,
            strict_filter=bool(cfg.strict_filter),
            score_boost=max(0.0, float(cfg.score_boost)),
        )

        if not result.enabled:
            result.debug = {
                "enabled": False,
                "reason": "disabled",
                "mode": mode,
                "total_sections": len(self._sections),
                "selected_ids": [],
                "candidates": [],
                "query_expansions": [],
            }
            return result

        if not self._sections:
            result.debug = {
                "enabled": True,
                "reason": "no_sections",
                "mode": mode,
                "total_sections": 0,
                "selected_ids": [],
                "candidates": [],
                "query_expansions": [],
            }
            return result

        query_tokens = _tokenize(" ".join([query, *list(query_variants or [])]))
        if not query_tokens:
            result.debug = {
                "enabled": True,
                "reason": "empty_query_tokens",
                "mode": mode,
                "total_sections": len(self._sections),
                "selected_ids": [],
                "candidates": [],
                "query_expansions": [],
            }
            return result

        scored: list[tuple[_SectionRecord, float, float, float, float]] = []
        query_text = str(query or "").strip()
        query_text_cf = query_text.casefold()

        for section in self._sections:
            heading_text = section.path or " ".join(section.breadcrumb)
            summary_text = section.summary

            heading_score = _overlap_score(query_tokens, _tokenize(heading_text))
            summary_score = _overlap_score(query_tokens, _tokenize(summary_text))

            phrase_bonus = 0.0
            if query_text_cf and query_text_cf in str(heading_text or "").casefold():
                phrase_bonus += 0.25
            if query_text_cf and query_text_cf in str(summary_text or "").casefold():
                phrase_bonus += 0.15

            if mode == "heading":
                base_score = heading_score
            elif mode == "summary":
                base_score = summary_score
            else:
                base_score = (0.60 * heading_score) + (0.40 * summary_score)

            final_score = base_score + phrase_bonus
            if final_score <= 0.0:
                continue

            scored.append((section, final_score, heading_score, summary_score, phrase_bonus))

        scored.sort(key=lambda row: row[1], reverse=True)

        top_k = max(1, int(cfg.top_k))
        min_score = max(0.0, float(cfg.min_score))
        selected_rows = [row for row in scored[:top_k] if row[1] >= min_score]

        result.selected_section_ids = {row[0].section_id for row in selected_rows}
        result.selected_scores = {row[0].section_id: float(row[1]) for row in selected_rows}

        if bool(cfg.expand_query) and selected_rows:
            max_sections = max(1, int(cfg.expand_query_max_sections))
            expansions: list[str] = []
            for section, _score, _hs, _ss, _pb in selected_rows[:max_sections]:
                focus_path = str(section.path or section.doc_name).strip()
                focus_summary = str(section.summary or "").strip()
                if not focus_path and not focus_summary:
                    continue
                if focus_summary:
                    expansions.append(f"{query}\n\nFocus section: {focus_path}\n{focus_summary}")
                else:
                    expansions.append(f"{query}\n\nFocus section: {focus_path}")
            result.query_expansions = _dedupe_non_empty(expansions)

        preview: list[dict[str, Any]] = []
        for section, score, heading_score, summary_score, phrase_bonus in scored[:10]:
            preview.append(
                {
                    "section_id": section.section_id,
                    "doc_name": section.doc_name,
                    "path": section.path,
                    "score": float(score),
                    "heading_score": float(heading_score),
                    "summary_score": float(summary_score),
                    "phrase_bonus": float(phrase_bonus),
                    "chunk_count": len(section.chunk_ids),
                }
            )

        result.debug = {
            "enabled": True,
            "mode": mode,
            "top_k": top_k,
            "min_score": float(min_score),
            "strict_filter": bool(result.strict_filter),
            "score_boost": float(result.score_boost),
            "total_sections": len(self._sections),
            "selected_count": len(result.selected_section_ids),
            "selected_ids": sorted(result.selected_section_ids),
            "candidates": preview,
            "query_expansions": list(result.query_expansions),
        }
        return result

    def _apply_section_routing(
        self,
        hits: list[_SearchHit],
        routing: _SectionRoutingResult,
    ) -> list[_SearchHit]:
        if not hits:
            return []
        if not routing.enabled:
            return list(hits)

        selected = set(routing.selected_section_ids or set())
        strict = bool(routing.strict_filter)
        score_boost = max(0.0, float(routing.score_boost))
        selected_scores = dict(routing.selected_scores or {})

        out: list[_SearchHit] = []
        for hit in hits:
            section_id = self._section_by_chunk_id.get(hit.chunk.chunk_id, "")
            if strict:
                if not selected:
                    continue
                if section_id not in selected:
                    continue
            if section_id and section_id in selected_scores and score_boost > 0.0:
                hit.score = float(hit.score) + (score_boost * float(selected_scores[section_id]))
                hit.methods.add("section")
            out.append(hit)

        out.sort(key=lambda row: float(row.score), reverse=True)
        return out

    def _vector_search(self, query_variants: list[str], top_k: int) -> tuple[list[_SearchHit], dict[str, Any]]:
        debug: dict[str, Any] = {
            "available": bool(self._vector_backend_available),
            "error": str(self._vector_backend_error or ""),
            "raw_hits": 0,
        }
        if not self._vector_backend_available or self._vector_index is None:
            return [], debug

        try:
            retriever = self._vector_index.as_retriever(similarity_top_k=max(1, int(top_k)))
        except Exception as exc:
            self._vector_backend_available = False
            self._vector_backend_error = f"retriever_init_failed: {type(exc).__name__}: {exc}"
            debug["available"] = False
            debug["error"] = self._vector_backend_error
            return [], debug

        out: list[_SearchHit] = []
        for variant in query_variants:
            if not variant:
                continue
            try:
                rows = list(retriever.retrieve(variant) or [])
            except Exception:
                continue
            debug["raw_hits"] = int(debug.get("raw_hits", 0)) + len(rows)
            for row in rows:
                hit = self._vector_row_to_hit(row, method="vector")
                if hit is not None:
                    out.append(hit)

        out.sort(key=lambda item: float(item.score), reverse=True)
        return out[: max(1, int(top_k))], debug

    def _vector_row_to_hit(self, row: Any, *, method: str) -> _SearchHit | None:
        score = _to_float(getattr(row, "score", 0.0))
        node = getattr(row, "node", row)
        metadata = getattr(node, "metadata", None)
        meta = dict(metadata) if isinstance(metadata, dict) else {}

        chunk_id = str(meta.get("chunk_id", "") or "").strip()
        if chunk_id and chunk_id in self._chunks_by_id:
            chunk = self._chunks_by_id[chunk_id]
            return _SearchHit(chunk=chunk, score=score, methods={method})

        doc_name = str(meta.get("doc_name", "") or "").strip()
        chunk_index = _to_int(meta.get("chunk_index", -1), default=-1)
        if doc_name and chunk_index >= 0:
            key = f"{doc_name}{_SEP}{chunk_index}"
            chunk = self._chunks_by_id.get(key)
            if chunk is not None:
                return _SearchHit(chunk=chunk, score=score, methods={method})

        text = _node_text(node)
        if not text.strip():
            return None
        synthetic = _ChunkRecord(
            chunk_id=f"synthetic{_SEP}{abs(hash(text))}",
            doc_name=doc_name or "Unknown",
            chunk_index=max(0, chunk_index),
            text=text,
            raw_text=text,
            breadcrumb=[],
            start=0,
            end=len(text),
        )
        return _SearchHit(chunk=synthetic, score=score, methods={method})

    def _lexical_search(self, query_variants: list[str], top_k: int) -> list[_SearchHit]:
        out: list[_SearchHit] = []
        lexical_mode = str(self._config.backend.lexical_mode or "tfidf").strip().lower()
        bm25_k1 = float(self._config.backend.bm25_k1)
        bm25_b = float(self._config.backend.bm25_b)

        avg_len = 1.0
        if self._chunks:
            avg_len = sum(max(1, len(_tokenize(chunk.raw_text))) for chunk in self._chunks) / max(1, len(self._chunks))

        for chunk in self._chunks:
            text = str(chunk.raw_text or chunk.text or "")
            if not text.strip():
                continue
            best = 0.0
            text_lower = text.casefold()
            text_tokens = _tokenize(text)
            for variant in query_variants:
                q_tokens = _tokenize(variant)
                if not q_tokens:
                    continue
                overlap = len(q_tokens & text_tokens)
                if overlap <= 0 and str(variant).casefold() not in text_lower:
                    continue
                score = overlap / max(1.0, float(len(q_tokens)))
                if str(variant).casefold() in text_lower:
                    score += 0.25
                if lexical_mode == "bm25":
                    doc_len = max(1.0, float(len(text_tokens)))
                    norm = 1.0 - bm25_b + bm25_b * (doc_len / max(1.0, avg_len))
                    score *= (bm25_k1 + 1.0) / max(0.01, bm25_k1 * norm + overlap)
                best = max(best, score)
            if best > 0.0:
                out.append(_SearchHit(chunk=chunk, score=best, methods={"lexical"}))

        out.sort(key=lambda item: float(item.score), reverse=True)
        return out[: max(1, int(top_k))]

    def _regex_search(self, query: str, query_variants: list[str]) -> tuple[list[_SearchHit], dict[str, Any]]:
        cfg = self._config
        patterns: list[str] = [str(query or "").strip()]
        debug: dict[str, Any] = {
            "input_patterns": [],
            "compiled_patterns": [],
            "invalid_patterns": [],
            "literal_fallback_patterns": [],
        }
        warnings: list[str] = []

        if cfg.literal.use_llm_terms:
            expanded = self._expand_literal_patterns(query, query_variants, warnings=warnings)
            max_terms = max(1, int(cfg.literal.max_llm_terms))
            patterns.extend(expanded[:max_terms])

        patterns = _dedupe_non_empty(patterns)
        debug["input_patterns"] = list(patterns)

        compiled: list[tuple[str, Any]] = []
        for pattern in patterns:
            try:
                compiled.append((pattern, re.compile(pattern, _REGEX_FLAGS)))
                debug["compiled_patterns"].append(pattern)
            except re.error as exc:
                escaped = re.escape(pattern)
                try:
                    compiled.append((pattern, re.compile(escaped, _REGEX_FLAGS)))
                    debug["compiled_patterns"].append(pattern)
                    debug["literal_fallback_patterns"].append(pattern)
                    debug["invalid_patterns"].append(
                        {"pattern": pattern, "error": str(exc), "fallback_used": True}
                    )
                except re.error:
                    debug["invalid_patterns"].append(
                        {"pattern": pattern, "error": str(exc), "fallback_used": False}
                    )

        if not compiled:
            return [], debug

        scored: list[tuple[_SearchHit, int]] = []
        for chunk in self._chunks:
            body = str(chunk.raw_text or chunk.text or "")
            if not body.strip():
                continue
            matched = 0
            first_start = -1
            first_end = -1
            for _pattern_text, regex in compiled:
                match = regex.search(body)
                if match is None:
                    continue
                matched += 1
                if first_start < 0 or match.start() < first_start:
                    first_start = int(match.start())
                    first_end = int(match.end())
            if matched <= 0:
                continue
            score = 1.2 + min(0.8, 0.1 * max(0, matched - 1))
            hit = _SearchHit(
                chunk=chunk,
                score=score,
                methods={"regex"},
                match_start=first_start,
                match_end=first_end,
            )
            scored.append((hit, matched))

        scored.sort(key=lambda item: (-item[1], -float(item[0].score)))
        max_results = max(0, int(cfg.literal.max_results))
        if max_results <= 0:
            return [], debug
        return [row[0] for row in scored[:max_results]], debug

    def _expand_literal_patterns(
        self,
        query: str,
        query_variants: list[str],
        *,
        warnings: list[str],
    ) -> list[str]:
        out: list[str] = []
        out.extend(self._expand_with_callback(self._literal_query_expander, query, "literal_expander", warnings))
        out.extend(query_variants[1:])

        payload = self._run_hook(
            "rag.literal_patterns",
            {
                "query": query,
                "patterns": list(out),
            },
            warnings=warnings,
        )
        if isinstance(payload, dict):
            hook_patterns = payload.get("patterns")
            if isinstance(hook_patterns, list):
                out = [str(item or "") for item in hook_patterns]
        return _dedupe_non_empty(out)

    def _merge_hits(self, *groups: list[_SearchHit]) -> list[_SearchHit]:
        merged: dict[str, _SearchHit] = {}
        for group in groups:
            for item in list(group or []):
                key = str(item.chunk.chunk_id or "")
                if not key:
                    continue
                existing = merged.get(key)
                if existing is None:
                    merged[key] = _SearchHit(
                        chunk=item.chunk,
                        score=float(item.score),
                        methods=set(item.methods),
                        match_start=int(item.match_start),
                        match_end=int(item.match_end),
                    )
                    continue
                existing.score = max(float(existing.score), float(item.score))
                existing.methods.update(item.methods)
                if existing.match_start < 0 and item.match_start >= 0:
                    existing.match_start = int(item.match_start)
                    existing.match_end = int(item.match_end)
                elif item.match_start >= 0 and 0 <= item.match_start < existing.match_start:
                    existing.match_start = int(item.match_start)
                    existing.match_end = int(item.match_end)

        out = list(merged.values())
        for item in out:
            # Slight bonus for cross-stage agreement.
            item.score += 0.05 * max(0, len(item.methods) - 1)
        out.sort(key=lambda hit: float(hit.score), reverse=True)
        return out

    def _candidate_pool(self, merged: list[_SearchHit], *, effective_top_k: int) -> list[_SearchHit]:
        mode = str(self._config.selection.mode or "top_k").strip().lower()
        threshold = float(self._config.selection.score_threshold)
        hard_cap = max(effective_top_k * 6, 24)
        trimmed = list(merged[:hard_cap])
        if mode == "threshold":
            return [row for row in trimmed if float(row.score) >= threshold]
        if mode == "top_k_threshold":
            return [row for row in trimmed if float(row.score) >= threshold]
        return trimmed

    def _maybe_rerank(
        self,
        query: str,
        candidates: list[_SearchHit],
        *,
        warnings: list[str],
        debug: dict[str, Any],
    ) -> list[_SearchHit]:
        cfg = self._config
        if not cfg.rerank.enabled or not candidates:
            return candidates

        max_candidates = max(1, int(cfg.rerank.max_candidates))
        pool = list(candidates[:max_candidates])
        debug["applied"] = True

        query_tokens = _tokenize(query)
        for item in pool:
            excerpt = self._excerpt_for_hit(item)
            text_tokens = _tokenize(excerpt or item.chunk.raw_text)
            overlap = len(query_tokens & text_tokens)
            rerank_score = overlap / max(1.0, float(len(query_tokens)))
            keep = bool(rerank_score >= float(cfg.rerank.min_score))
            item.llm_rerank_score = rerank_score
            item.llm_rerank_keep = keep
            item.llm_rerank_class = "sinnvoll" if keep else "nicht_sinnvoll"
            item.llm_rerank_reason = "token_overlap_heuristic"
            item.score = (0.72 * float(item.score)) + (0.28 * float(rerank_score))

        # Optional external reranker callback.
        if callable(self._rag_reranker):
            payload_hits = [self._hit_payload(row) for row in pool]
            callback_rows = self._safe_call_reranker(
                self._rag_reranker,
                query=query,
                hits=payload_hits,
                max_candidates=max_candidates,
                min_score=float(cfg.rerank.min_score),
                warnings=warnings,
            )
            self._apply_external_rerank(pool, callback_rows)

        hook_payload = self._run_hook(
            "rag.rerank",
            {
                "query": query,
                "hits": [self._hit_payload(row) for row in pool],
                "max_candidates": max_candidates,
                "min_score": float(cfg.rerank.min_score),
            },
            warnings=warnings,
        )
        if isinstance(hook_payload, dict):
            self._apply_external_rerank(pool, hook_payload.get("hits"))

        filtered = [row for row in pool if bool(row.llm_rerank_keep)]
        debug["kept"] = len(filtered)
        if not filtered:
            debug["reason"] = "all_filtered"
            return []
        filtered.sort(key=lambda row: float(row.score), reverse=True)
        return filtered

    def _apply_selection_to_hits(self, rows: list[_SearchHit], *, top_k: int) -> list[_SearchHit]:
        mode = str(self._config.selection.mode or "top_k").strip().lower()
        threshold = float(self._config.selection.score_threshold)
        if mode == "threshold":
            out = [row for row in rows if float(row.score) >= threshold]
            out.sort(key=lambda row: float(row.score), reverse=True)
            return out
        if mode == "top_k_threshold":
            out = [row for row in rows if float(row.score) >= threshold]
            out.sort(key=lambda row: float(row.score), reverse=True)
            return out[: max(1, int(top_k))]
        sorted_rows = list(rows)
        sorted_rows.sort(key=lambda row: float(row.score), reverse=True)
        return sorted_rows[: max(1, int(top_k))]

    def _to_doc_results(self, rows: list[_SearchHit], *, top_k: int) -> list[dict[str, Any]]:
        grouped: dict[str, list[_SearchHit]] = {}
        for row in rows:
            grouped.setdefault(row.chunk.doc_name, []).append(row)

        docs: list[dict[str, Any]] = []
        for doc_name, hits in grouped.items():
            hits.sort(key=lambda item: float(item.score), reverse=True)
            methods = sorted({method for row in hits for method in row.methods})
            chunk_indexes = sorted({int(row.chunk.chunk_index) for row in hits})
            max_clusters = max(6, min(12, int(max(1, top_k)) * 3))
            max_excerpts = max(2, min(4, int(max(1, top_k))))

            merged_clusters: list[dict[str, Any]] = []
            for row in hits[:max_clusters]:
                merged_clusters.append(
                    {
                        "chunk_indexes": [int(row.chunk.chunk_index)],
                        "methods": sorted(row.methods),
                    }
                )

            excerpts: list[str] = []
            for row in hits:
                ex = self._excerpt_for_hit(row)
                if not ex:
                    continue
                if ex in excerpts:
                    continue
                excerpts.append(ex)
                if len(excerpts) >= max_excerpts:
                    break

            excerpt = "\n\n...\n\n".join(excerpts).strip()
            if not excerpt:
                excerpt = hits[0].chunk.raw_text.strip() or hits[0].chunk.text.strip()

            score = float(hits[0].score)
            if len(hits) > 1:
                score += min(0.2, 0.03 * (len(hits) - 1))

            meta: dict[str, Any] = {
                "methods": methods,
                "hit_count": len(hits),
                "chunk_indexes": chunk_indexes,
                "merged_clusters": merged_clusters,
                "excerpt_count": len(excerpts),
            }
            section_paths = sorted(
                {
                    self._sections_by_id[section_id].path
                    for section_id in (
                        self._section_by_chunk_id.get(row.chunk.chunk_id, "")
                        for row in hits
                    )
                    if section_id and section_id in self._sections_by_id
                }
            )
            if section_paths:
                meta["section_paths"] = section_paths
            rerank_scores = [float(row.llm_rerank_score) for row in hits if row.llm_rerank_score is not None]
            if rerank_scores:
                keep_any = any(bool(row.llm_rerank_keep) for row in hits if row.llm_rerank_keep is not None)
                meta["llm_rerank_score"] = max(rerank_scores)
                meta["llm_rerank_keep"] = bool(keep_any)
                meta["llm_rerank_class"] = "sinnvoll" if keep_any else "nicht_sinnvoll"
                meta["llm_rerank_reason"] = "aggregated"

            docs.append(
                {
                    "name": doc_name,
                    "score": score,
                    "excerpt": excerpt,
                    "meta": meta,
                }
            )

        docs.sort(key=lambda row: float(row.get("score", 0.0)), reverse=True)
        return self._apply_selection_to_docs(docs, top_k=top_k)

    def _apply_selection_to_docs(self, rows: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
        mode = str(self._config.selection.mode or "top_k").strip().lower()
        threshold = float(self._config.selection.score_threshold)
        if mode == "threshold":
            return [row for row in rows if _to_float(row.get("score")) >= threshold]
        if mode == "top_k_threshold":
            filtered = [row for row in rows if _to_float(row.get("score")) >= threshold]
            return filtered[: max(1, int(top_k))]
        return rows[: max(1, int(top_k))]

    # ------------------------------------------------------------------
    # Debug / hook helpers
    # ------------------------------------------------------------------
    def _build_debug_payload(
        self,
        *,
        query: str,
        effective_top_k: int,
        warnings: list[str],
        query_variants: list[str],
        vector_count: int,
        lexical_count: int,
        regex_count: int,
        merged_count: int,
        routed_count: int,
        selected_count: int,
        results: list[dict[str, Any]],
        regex_debug: dict[str, Any],
        rerank_debug: dict[str, Any],
        section_debug: dict[str, Any],
        elapsed_ms: float,
        vector_debug: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "backend": self.current_backend(),
            "vector_backend_available": bool(self._vector_backend_available),
            "vector_backend_error": str(self._vector_backend_error or ""),
            "vector_embedding_provider": str(self._vector_embedding_provider or ""),
            "doc_count": len(self._documents),
            "chunk_count": len(self._chunks),
            "query": query,
            "query_variants": list(query_variants),
            "selection_mode": str(self._config.selection.mode),
            "effective_top_k": int(effective_top_k),
            "counts": {
                "vector_hits": int(vector_count),
                "lexical_hits": int(lexical_count),
                "regex_hits": int(regex_count),
                "merged_hits": int(merged_count),
                "routed_hits": int(routed_count),
                "selected_hits": int(selected_count),
                "doc_results": len(results),
            },
            "regex": dict(regex_debug or {}),
            "rerank": dict(rerank_debug or {}),
            "section_routing": dict(section_debug or {}),
            "vector": dict(vector_debug or {}),
            "warnings": _dedupe_non_empty(warnings),
            "elapsed_ms": float(elapsed_ms),
        }

    def _run_hook(
        self,
        hook_name: str,
        payload: dict[str, Any],
        *,
        warnings: list[str],
    ) -> dict[str, Any]:
        manager = self._plugin_manager
        if manager is None:
            return dict(payload or {})
        run_hook = getattr(manager, "run_hook", None)
        if not callable(run_hook):
            return dict(payload or {})
        try:
            out = run_hook(str(hook_name or ""), dict(payload or {}))
            if isinstance(out, dict):
                return out
        except Exception as exc:
            warnings.append(f"Plugin hook failed ({hook_name}): {exc}")
        return dict(payload or {})

    def _expand_with_callback(
        self,
        fn: Callable[..., Any] | None,
        query: str,
        label: str,
        warnings: list[str],
    ) -> list[str]:
        if not callable(fn):
            return []
        try:
            try:
                value = fn(query)
            except TypeError:
                value = fn(query, self._doc_context_hint())
        except Exception as exc:
            warnings.append(f"{label} failed: {exc}")
            return []
        return _normalize_expander_output(value)

    def _safe_call_reranker(
        self,
        fn: Callable[..., Any],
        *,
        query: str,
        hits: list[dict[str, Any]],
        max_candidates: int,
        min_score: float,
        warnings: list[str],
    ) -> Any:
        try:
            return fn(
                query=query,
                hits=hits,
                max_candidates=max_candidates,
                min_score=min_score,
            )
        except TypeError:
            try:
                return fn(query, hits)
            except Exception as exc:
                warnings.append(f"rag_reranker failed: {exc}")
                return None
        except Exception as exc:
            warnings.append(f"rag_reranker failed: {exc}")
            return None

    def _apply_external_rerank(self, pool: list[_SearchHit], payload: Any) -> None:
        if not isinstance(payload, list):
            return
        by_id = {row.chunk.chunk_id: row for row in pool}
        for item in payload:
            if not isinstance(item, dict):
                continue
            chunk_id = str(item.get("chunk_id", "") or item.get("key", "")).strip()
            target = by_id.get(chunk_id)
            if target is None:
                continue
            if "score" in item:
                target.score = _to_float(item.get("score"), default=target.score)
            if "llm_rerank_score" in item:
                target.llm_rerank_score = _to_float(item.get("llm_rerank_score"), default=0.0)
            if "llm_rerank_class" in item:
                target.llm_rerank_class = str(item.get("llm_rerank_class", "") or "")
            if "llm_rerank_keep" in item:
                target.llm_rerank_keep = bool(item.get("llm_rerank_keep"))
            if "llm_rerank_reason" in item:
                target.llm_rerank_reason = str(item.get("llm_rerank_reason", "") or "")

    def _hit_payload(self, hit: _SearchHit) -> dict[str, Any]:
        section_id = self._section_by_chunk_id.get(hit.chunk.chunk_id, "")
        section_path = ""
        if section_id and section_id in self._sections_by_id:
            section_path = str(self._sections_by_id[section_id].path or "")
        return {
            "chunk_id": hit.chunk.chunk_id,
            "doc_name": hit.chunk.doc_name,
            "chunk_index": int(hit.chunk.chunk_index),
            "score": float(hit.score),
            "methods": sorted(hit.methods),
            "excerpt": self._excerpt_for_hit(hit),
            "section_id": section_id,
            "section_path": section_path,
            "llm_rerank_class": str(hit.llm_rerank_class or ""),
            "llm_rerank_score": (
                float(hit.llm_rerank_score) if hit.llm_rerank_score is not None else None
            ),
            "llm_rerank_keep": hit.llm_rerank_keep,
            "llm_rerank_reason": str(hit.llm_rerank_reason or ""),
        }

    # ------------------------------------------------------------------
    # Chunk/index backend internals
    # ------------------------------------------------------------------
    def _rebuild_index(self) -> None:
        self._rebuild_chunks()
        self._rebuild_vector_backend()

    def _rebuild_chunks(self) -> None:
        self._chunks.clear()
        self._chunks_by_id.clear()
        self._chunks_by_doc.clear()
        self._sections.clear()
        self._sections_by_id.clear()
        self._section_by_chunk_id.clear()

        for doc_name, body in sorted(self._documents.items()):
            text = str(body or "")
            built = build_chunks(text, self._config.chunking, doc_name, self._log)
            cursor = 0
            per_doc: list[_ChunkRecord] = []

            for chunk_index, payload in enumerate(built):
                indexed_text = str(payload.get("text", "") or "")
                raw_text = str(payload.get("raw_text", "") or indexed_text)
                if not raw_text.strip():
                    continue
                start, end = _find_span(text, raw_text, start_hint=cursor)
                cursor = max(cursor, end)
                chunk_id = f"{doc_name}{_SEP}{chunk_index}"
                record = _ChunkRecord(
                    chunk_id=chunk_id,
                    doc_name=doc_name,
                    chunk_index=chunk_index,
                    text=indexed_text or raw_text,
                    raw_text=raw_text,
                    breadcrumb=[str(x) for x in list(payload.get("breadcrumb", []) or []) if str(x).strip()],
                    start=max(0, int(start)),
                    end=max(0, int(end)),
                )
                self._chunks.append(record)
                self._chunks_by_id[chunk_id] = record
                per_doc.append(record)

            self._chunks_by_doc[doc_name] = per_doc
        self._rebuild_sections()

    def _rebuild_sections(self) -> None:
        cfg = self._config.routing
        max_summary_chars = max(120, int(cfg.max_summary_chars))
        summary_sentences = max(1, int(cfg.summary_sentences))

        for doc_name, chunks in self._chunks_by_doc.items():
            by_path: dict[tuple[str, ...], list[_ChunkRecord]] = {}
            for chunk in chunks:
                path_key = tuple(chunk.breadcrumb) if chunk.breadcrumb else ("(document root)",)
                by_path.setdefault(path_key, []).append(chunk)

            for path_key, section_chunks in by_path.items():
                path = " > ".join([str(item or "").strip() for item in path_key if str(item or "").strip()])
                if not path:
                    path = "(document root)"
                section_id = self._make_section_id(doc_name, path)
                joined = "\n\n".join(
                    str(chunk.raw_text or chunk.text or "")
                    for chunk in section_chunks
                    if str(chunk.raw_text or chunk.text or "").strip()
                )
                summary = _summarize_text(joined, max_chars=max_summary_chars, max_sentences=summary_sentences)
                record = _SectionRecord(
                    section_id=section_id,
                    doc_name=doc_name,
                    breadcrumb=[str(item) for item in path_key if str(item).strip()],
                    path=path,
                    summary=summary,
                    chunk_ids=[row.chunk_id for row in section_chunks],
                )
                self._sections.append(record)
                self._sections_by_id[record.section_id] = record
                for chunk in section_chunks:
                    self._section_by_chunk_id[chunk.chunk_id] = record.section_id

    def _make_section_id(self, doc_name: str, path: str) -> str:
        key = f"{doc_name}\n{path}"
        digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()[:20]
        return f"section:{digest}"

    def _rebuild_vector_backend(self) -> None:
        self._teardown_vector_backend()
        if not self._chunks:
            self._vector_backend_available = False
            self._vector_backend_error = "no_chunks"
            self._vector_embedding_provider = ""
            return

        if not bool(self._vector_stack.get("ready")):
            self._vector_backend_available = False
            self._vector_backend_error = str(self._vector_stack.get("error", "vector_stack_unavailable"))
            self._vector_embedding_provider = ""
            return

        Document = self._vector_stack["Document"]
        StorageContext = self._vector_stack["StorageContext"]
        VectorStoreIndex = self._vector_stack["VectorStoreIndex"]
        LanceDBVectorStore = self._vector_stack["LanceDBVectorStore"]
        embed_model, embedding_provider, embedding_error = self._resolve_embedding_model()
        if embed_model is None:
            self._vector_backend_available = False
            self._vector_backend_error = str(embedding_error or "embedding_unavailable")
            self._vector_embedding_provider = ""
            return

        docs: list[Any] = []
        for chunk in self._chunks:
            docs.append(
                Document(
                    text=str(chunk.text or chunk.raw_text),
                    metadata={
                        "chunk_id": chunk.chunk_id,
                        "doc_name": chunk.doc_name,
                        "chunk_index": int(chunk.chunk_index),
                        "start": int(chunk.start),
                        "end": int(chunk.end),
                        "breadcrumb": " > ".join(chunk.breadcrumb),
                    },
                )
            )

        db_root = Path(tempfile.mkdtemp(prefix="d2c_rag_lancedb_"))
        try:
            vector_store = LanceDBVectorStore(uri=str(db_root), table_name="rag_chunks")
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            build_kwargs: dict[str, Any] = {
                "storage_context": storage_context,
                "embed_model": embed_model,
            }
            try:
                index = VectorStoreIndex.from_documents(docs, show_progress=False, **build_kwargs)
            except TypeError:
                index = VectorStoreIndex.from_documents(docs, **build_kwargs)
            self._vector_index = index
            self._vector_backend_available = True
            self._vector_backend_error = ""
            self._vector_embedding_provider = str(embedding_provider or "")
            self._lancedb_dir = db_root
        except Exception as exc:
            self._vector_index = None
            self._vector_backend_available = False
            self._vector_backend_error = f"{type(exc).__name__}: {exc}"
            self._vector_embedding_provider = ""
            shutil.rmtree(db_root, ignore_errors=True)
            self._lancedb_dir = None

    def _teardown_vector_backend(self) -> None:
        self._vector_index = None
        self._vector_embedding_provider = ""
        if self._lancedb_dir is not None:
            shutil.rmtree(self._lancedb_dir, ignore_errors=True)
            self._lancedb_dir = None

    def _load_vector_stack(self) -> dict[str, Any]:
        stack: dict[str, Any] = {"ready": False}
        try:
            core = importlib.import_module("llama_index.core")
            storage_mod = importlib.import_module("llama_index.core.storage.storage_context")
            lancedb_mod = importlib.import_module("llama_index.vector_stores.lancedb")
            stack["Document"] = getattr(core, "Document")
            stack["VectorStoreIndex"] = getattr(core, "VectorStoreIndex")
            stack["StorageContext"] = getattr(storage_mod, "StorageContext")
            stack["LanceDBVectorStore"] = getattr(lancedb_mod, "LanceDBVectorStore")
            stack["ready"] = True
            return stack
        except Exception as exc:
            stack["error"] = f"{type(exc).__name__}: {exc}"
            return stack

    def _resolve_embedding_model(self) -> tuple[Any, str, str]:
        _ensure_hf_offline_env()
        model_name = str(self._config.backend.st_model_name or "").strip()
        if not model_name:
            model_name = "sentence-transformers/all-MiniLM-L6-v2"
        model_ref = _resolve_local_hf_model_ref(model_name)
        candidates = (
            ("llama_index.embeddings.huggingface", "HuggingFaceEmbedding"),
            ("llama_index.embeddings.huggingface.base", "HuggingFaceEmbedding"),
        )
        last_error = ""
        for module_name, class_name in candidates:
            try:
                module = importlib.import_module(module_name)
                cls = getattr(module, class_name)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                continue

            kwargs: dict[str, Any] = {"model_name": model_ref}
            cache_dir = str(os.getenv("D2C_EMBEDDING_CACHE_DIR", "") or "").strip()
            if cache_dir:
                kwargs["cache_folder"] = cache_dir
            device = str(os.getenv("D2C_EMBEDDING_DEVICE", "cpu") or "cpu").strip().lower()
            if not device:
                device = "cpu"
            kwargs["device"] = device
            kwargs["local_files_only"] = True
            kwargs["trust_remote_code"] = False
            kwargs["show_progress_bar"] = False
            kwargs["model_kwargs"] = {"local_files_only": True}

            try:
                model = cls(**kwargs)
                provider = f"huggingface:{model_name}"
                if str(model_ref or "").strip() and str(model_ref) != str(model_name):
                    provider = f"{provider} [local:{model_ref}]"
                return model, provider, ""
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"

        error = (
            "HuggingFace embedding model unavailable. "
            "Install `llama-index-embeddings-huggingface` and provide a local embedding model cache. "
            f"Last error: {last_error or 'unknown'}"
        )
        return None, "", error


    def _doc_context_hint(self) -> str:
        lines: list[str] = []
        for idx, name in enumerate(sorted(self._documents.keys())):
            if idx >= 20:
                lines.append("...")
                break
            headings = [
                " > ".join(chunk.breadcrumb)
                for chunk in self._chunks_by_doc.get(name, [])
                if chunk.breadcrumb
            ]
            label = name
            if headings:
                label += f" ({headings[0]})"
            lines.append(f"- {label}")
        return "\n".join(lines)

    def _excerpt_for_hit(self, hit: _SearchHit) -> str:
        cfg = self._config
        chunk = hit.chunk
        base = str(chunk.raw_text or chunk.text or "")
        if not cfg.context.enabled:
            return base[:_MAX_EXCERPT_LEN].strip()

        full = self._documents.get(chunk.doc_name, "")
        if not full:
            return base[:_MAX_EXCERPT_LEN].strip()

        left_anchor = int(chunk.start)
        right_anchor = int(chunk.end)
        if hit.match_start >= 0:
            left_anchor = int(chunk.start + hit.match_start)
            if hit.match_end >= hit.match_start:
                right_anchor = int(chunk.start + hit.match_end)

        before = max(0, int(cfg.context.before_chars))
        after = max(0, int(cfg.context.after_chars))
        left = max(0, left_anchor - before)
        right = min(len(full), max(left + 1, right_anchor + after))
        excerpt = str(full[left:right]).strip()
        if not excerpt:
            excerpt = base
        return excerpt[:_MAX_EXCERPT_LEN].strip()


# ----------------------------------------------------------------------
# Utility helpers
# ----------------------------------------------------------------------
def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in _WORD_RE.findall(str(text or "").casefold())
        if len(token) >= 2
    }


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(str(text or "")))


def _overlap_score(query_tokens: set[str], text_tokens: set[str]) -> float:
    if not query_tokens or not text_tokens:
        return 0.0
    overlap = len(query_tokens & text_tokens)
    return float(overlap) / max(1.0, float(len(query_tokens)))


def _to_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _dedupe_non_empty(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _summarize_text(text: str, *, max_chars: int, max_sentences: int) -> str:
    body = str(text or "").strip()
    if not body:
        return ""
    limited = body[: max(120, int(max_chars))].strip()
    parts = re.split(r"(?<=[\.\!\?\n])\s+", limited)
    out: list[str] = []
    for part in parts:
        sentence = str(part or "").strip()
        if not sentence:
            continue
        out.append(sentence)
        if len(out) >= max(1, int(max_sentences)):
            break
    if not out:
        return limited
    joined = " ".join(out).strip()
    return joined[: max(120, int(max_chars))].strip()


def _normalize_expander_output(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _dedupe_non_empty([value])
    if isinstance(value, (tuple, list, set)):
        return _dedupe_non_empty([str(item or "") for item in value])
    if isinstance(value, dict):
        out: list[str] = []
        for key in ("query", "queries", "terms", "patterns", "text"):
            field = value.get(key)
            if isinstance(field, str):
                out.append(field)
            elif isinstance(field, (tuple, list, set)):
                out.extend([str(item or "") for item in field])
        return _dedupe_non_empty(out)
    return []


def _node_text(node: Any) -> str:
    for attr_name in ("get_content", "text"):
        attr = getattr(node, attr_name, None)
        if callable(attr):
            try:
                value = attr()
                if str(value or "").strip():
                    return str(value)
            except Exception:
                continue
        elif attr is not None:
            text = str(attr or "")
            if text.strip():
                return text
    return ""


def _find_span(body: str, snippet: str, *, start_hint: int = 0) -> tuple[int, int]:
    text = str(body or "")
    chunk = str(snippet or "")
    if not text or not chunk:
        return 0, 0

    hint = max(0, int(start_hint))
    pos = text.find(chunk, hint)
    if pos < 0 and hint > 0:
        pos = text.find(chunk)

    if pos >= 0:
        return pos, pos + len(chunk)

    anchor = chunk.strip()
    if anchor:
        anchor = anchor[: min(220, len(anchor))]
        pos = text.find(anchor, hint)
        if pos < 0 and hint > 0:
            pos = text.find(anchor)
        if pos >= 0:
            return pos, min(len(text), pos + len(anchor))

    start = min(max(0, hint), len(text))
    end = min(len(text), start + len(chunk))
    return start, end
