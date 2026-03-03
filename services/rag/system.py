"""
RAG System
==========
Configurable two-tier retrieval pipeline.

Backends
--------
1. TF-IDF  – always available, zero extra dependencies.
2. sentence-transformers – optional, loaded via try_load_sentence_transformers().

Both backends can be active simultaneously; their results are merged using
Reciprocal Rank Fusion (RRF).

Chunking strategies
-------------------
sliding_window (default)
    Overlapping paragraph-aware chunks.

section
    One chunk per Markdown heading section (heading → next same-or-higher heading).

recursive
    Hierarchical: H1 → H2 → sliding-window leaf chunks.
    Stores parent section text for extended context retrieval.

Optional features (all in RAGConfig)
--------------------------------------
use_tfidf               use TF-IDF backend (always available).
use_st                  use sentence-transformers backend (optional).
use_regex_search        use literal term backend (substring matching).
include_headings        prepend "H1 › H2 › …" breadcrumb to every indexed chunk.
include_filename        prepend filename to indexed chunk prefix.
chunking_strategy       "sliding_window" | "section" | "recursive"
use_hyde                rewrite short queries with an LLM before search.
hyde_tfidf_mode         "keywords" | "passage"
hyde_st_mode            "passage" | "multi_passage"
hyde_use_doc_context    prepend global TOC to HyDE prompt
extended_context        expand retrieved excerpts ±N chars in source document.
selection_mode          "top_k" | "threshold" | "top_k_threshold"
literal_use_llm_terms   ask LLM for additional literal search terms.
llm_rerank_enabled      let LLM re-rank/filter retrieved document hits.
"""
from __future__ import annotations

import math
import os
import queue as _queue
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal


_SEP = "\x00"   # separates doc-name from chunk index in internal keys


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class RAGConfig:
    # ── Backends (at least one must be True) ──────────────────────────────────
    use_tfidf: bool = True
    use_st: bool = False            # True once sentence-transformers is active

    # ── Chunking ──────────────────────────────────────────────────────────────
    chunk_size: int = 800           # target chars per chunk
    chunk_overlap: int = 150        # overlap between consecutive chunks (chars)
    chunking_strategy: str = "sliding_window"  # "sliding_window" | "section" | "recursive"

    # ── Structural features ───────────────────────────────────────────────────
    include_headings: bool = True   # prepend heading breadcrumb to indexed text
    include_filename: bool = True   # prepend filename to indexed chunk prefix

    # ── HyDE (Query Expansion) ────────────────────────────────────────────────
    use_hyde: bool = True
    hyde_min_words: int = 5         # expand if word count <= this value
    hyde_tfidf_mode: str = "keywords"   # "keywords" | "passage"
    hyde_st_mode: str = "passage"       # "passage" | "multi_passage"
    hyde_st_hypotheses: int = 3
    hyde_use_doc_context: bool = False  # prepend TOC to HyDE prompt

    # ── Extended Context (Parent Document Retrieval) ───────────────────────────
    extended_context: bool = False
    extended_context_before: int = 500  # chars before chunk in source doc
    extended_context_after: int = 500   # chars after chunk in source doc

    # ── Result selection ──────────────────────────────────────────────────────
    selection_mode: str = "top_k"   # "top_k" | "threshold" | "top_k_threshold"
    top_k: int = 5
    score_threshold: float = 0.15

    # ── Regex / literal search ────────────────────────────────────────────────
    use_regex_search: bool = True
    regex_max_results: int = 3
    literal_use_llm_terms: bool = False
    literal_llm_max_terms: int = 8

    # ── LLM document reranking ────────────────────────────────────────────────
    llm_rerank_enabled: bool = False
    llm_rerank_min_score: float = 0.45
    llm_rerank_max_candidates: int = 10

    # ── Sentence-transformers ─────────────────────────────────────────────────
    st_model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"

    # ── Threading ─────────────────────────────────────────────────────────────
    st_n_threads: int = 0   # CPU threads for ST/torch; 0 = all cores


# ── Excerpt helpers ───────────────────────────────────────────────────────────

def _excerpt(content: str, tokens: list[str], window: int = 400) -> str:
    """Extract a relevant passage from *content* centred on the first token match."""
    if not content.strip():
        return ""

    low = content.lower()
    pos: int | None = None
    for tok in tokens:
        p = low.find(tok)
        if p != -1:
            pos = p
            break

    if pos is None:
        snippet = re.sub(r"\n{3,}", "\n\n", content[:window]).strip()
        if not snippet:
            snippet = content.strip()[:window]
        return snippet + ("…" if len(content) > window else "")

    half  = window // 2
    start = max(0, pos - half)
    end   = min(len(content), pos + half)
    if start == 0:
        end = min(len(content), window)
    if end == len(content):
        start = max(0, len(content) - window)

    snippet = re.sub(r"\n{3,}", "\n\n", content[start:end]).strip()
    if not snippet:
        snippet = content.strip()[:window]
        return snippet + ("…" if len(content) > window else "")

    return ("…" if start > 0 else "") + snippet + ("…" if end < len(content) else "")


def _excerpt_at(content: str, match_start: int, window: int = 400) -> str:
    """Extract a passage centred on *match_start*."""
    half  = window // 2
    start = max(0, match_start - half)
    end   = min(len(content), match_start + half)
    if start == 0:
        end = min(len(content), window)
    if end == len(content):
        start = max(0, len(content) - window)

    snippet = re.sub(r"\n{3,}", "\n\n", content[start:end]).strip()
    if not snippet:
        snippet = content.strip()[:window]
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(content) else "")


# ── TF-IDF ────────────────────────────────────────────────────────────────────

class TFIDFIndex:
    """Lightweight in-memory TF-IDF retrieval engine."""

    def __init__(self):
        self._docs:  dict[str, str]               = {}
        self._tfidf: dict[str, dict[str, float]]  = {}
        self._idf:   dict[str, float]             = {}

    def add_document(self, key: str, content: str):
        self._docs[key] = content
        self._rebuild()

    def add_documents_batch(self, docs: dict[str, str]):
        """Add many documents at once and rebuild only once."""
        self._docs.update(docs)
        self._rebuild()

    def remove_document(self, key: str):
        self._docs.pop(key, None)
        self._rebuild()

    def clear(self):
        self._docs.clear()
        self._tfidf.clear()
        self._idf.clear()

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[^\W\d_]{2,}", text.lower())

    def _rebuild(self):
        if not self._docs:
            self._tfidf.clear()
            self._idf.clear()
            return

        n = len(self._docs)
        doc_tokens: dict[str, list[str]] = {
            key: self._tokenize(content)
            for key, content in self._docs.items()
        }

        vocab: set[str] = set()
        for tokens in doc_tokens.values():
            vocab.update(tokens)

        # Smoothed IDF (sklearn variant)
        self._idf = {
            word: math.log(
                (n + 1) / (1 + sum(1 for t in doc_tokens.values() if word in t))
            ) + 1.0
            for word in vocab
        }

        self._tfidf = {}
        for key, tokens in doc_tokens.items():
            total = max(len(tokens), 1)
            tf = Counter(tokens)
            self._tfidf[key] = {
                w: (c / total) * self._idf.get(w, 0.0)
                for w, c in tf.items()
            }

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float, str]]:
        """Return ``[(key, score, excerpt), …]`` sorted by relevance."""
        q_tokens = self._tokenize(query)
        if not q_tokens or not self._tfidf:
            return []

        scores = {
            key: sum(tfidf.get(w, 0.0) for w in q_tokens)
            for key, tfidf in self._tfidf.items()
        }
        ranked = sorted(
            ((k, s) for k, s in scores.items() if s > 0),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        return [
            (key, score, _excerpt(self._docs[key], q_tokens))
            for key, score in ranked
        ]


# ── RAG System ────────────────────────────────────────────────────────────────

class RAGSystem(QObject):
    """
    Configurable document indexing and retrieval.

    Quick start
    -----------
    1. Adjust ``config`` (RAGConfig) as desired.
    2. Call ``index_content(name, content)`` for each document.
    3. Call ``search(query)`` → ``[{name, score, excerpt, meta}, …]``.
    4. Optionally inject query expanders via ``set_tfidf_query_expander`` and
       ``set_st_query_expander`` for LLM-assisted HyDE query rewriting.
    """

    results_ready   = Signal(list)
    backend_changed = Signal(str)
    rag_settings_requested = Signal()

    def __init__(
        self,
        config: RAGConfig | None = None,
        query_expander: Callable[[str], str] | None = None,
        logger: Any = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.config          = config or RAGConfig()
        self._log            = logger

        self._index          = TFIDFIndex()
        self._indexed:       set[str]        = set()
        # raw chunk text (no heading prefix) → used for excerpts
        self._content_cache: dict[str, str]  = {}
        # text submitted to TF-IDF / ST (may include heading/filename prefix)
        self._indexed_text:  dict[str, str]  = {}
        self._chunk_to_doc:  dict[str, str]  = {}

        # Full document content for extended context retrieval
        self._doc_full_content: dict[str, str] = {}
        # chunk_key → parent section text (populated by recursive chunking)
        self._chunk_parents: dict[str, str]    = {}
        # Cached global TOC string
        self._global_toc: str = ""

        self._st_model:      Any             = None
        self._st_embeddings: dict[str, Any]  = {}

        # Query expanders
        # Legacy: set_query_expander → sets _tfidf_query_expander
        self._tfidf_query_expander: Callable | None = query_expander
        self._st_query_expander:    Callable | None = None
        self._literal_query_expander: Callable | None = None
        self._rag_reranker: Callable | None = None

        # Protects all mutable state against concurrent access from RAGWorker
        self._lock = threading.Lock()

    # ── Backend management ────────────────────────────────────────────────────

    def try_load_sentence_transformers(
        self, model_name: str | None = None
    ) -> bool:
        name = model_name or self.config.st_model_name
        if self._log:
            self._log.info("ST", f"Loading model: {name}")
        try:
            n_threads = self.config.st_n_threads
            if n_threads > 0:
                try:
                    import torch  # type: ignore
                    torch.set_num_threads(n_threads)
                    if self._log:
                        self._log.info("ST", f"Torch threads set to {n_threads}")
                except ImportError:
                    pass
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._st_model = SentenceTransformer(name)
            self.config.use_st = True
            if self._log:
                self._log.info("ST", f"Model loaded: {name}  |  rebuilding embeddings…")
            self._rebuild_st_embeddings()
            self.backend_changed.emit(self.current_backend())
            return True
        except Exception as exc:
            if self._log:
                self._log.error("ST", f"Load failed: {exc}")
            self._st_model = None
            self.backend_changed.emit(self.current_backend())
            return False

    def set_query_expander(self, fn: Callable[[str], str] | None):
        """Deprecated: use set_tfidf_query_expander / set_st_query_expander."""
        self._tfidf_query_expander = fn

    def set_tfidf_query_expander(self, fn: Callable[[str], str] | None):
        """Set the expander used for TF-IDF HyDE (keyword list generator)."""
        self._tfidf_query_expander = fn

    def set_st_query_expander(self, fn: Callable | None):
        """Set the expander used for ST HyDE (passage generator).

        The callable must accept ``(query: str, n_hypotheses: int)`` and return
        a ``list[str]``.
        """
        self._st_query_expander = fn

    def set_literal_query_expander(self, fn: Callable | None):
        """Set optional expander for literal backend term generation."""
        self._literal_query_expander = fn

    def set_rag_reranker(self, fn: Callable | None):
        """Set optional LLM reranker for document-level result filtering."""
        self._rag_reranker = fn

    def current_backend(self) -> str:
        parts = []
        if self.config.use_tfidf:
            parts.append("tfidf")
        if self.config.use_st and self._st_model is not None:
            parts.append("st")
        if self.config.use_regex_search:
            parts.append("literal")
        return "+".join(parts) or "none"

    # ── Indexing ──────────────────────────────────────────────────────────────

    def index_content(self, name: str, content: str) -> bool:
        t0 = time.perf_counter()
        try:
            # Store full content for extended context retrieval
            self._doc_full_content[name] = content

            chunks = self._build_chunks(content, name)

            # ── Pass 1: collect valid chunks ───────────────────────────────
            batch: dict[str, tuple[str, str]] = {}
            new_parents: dict[str, str] = {}
            for i, chunk in enumerate(chunks):
                raw_text     = chunk["raw_text"]
                indexed_text = chunk["text"]
                if raw_text.strip():
                    ckey = f"{name}{_SEP}{i}"
                    batch[ckey] = (raw_text, indexed_text)
                    if "_parent_text" in chunk:
                        new_parents[ckey] = chunk["_parent_text"]

            if not batch:
                # Rebuild TOC even if no chunks (e.g. blank doc registered)
                self._global_toc = self._build_global_toc()
                return True

            # ── Pass 2: single TF-IDF rebuild for all chunks at once ───────
            self._index.add_documents_batch(
                {k: v[1] for k, v in batch.items()}
            )

            # ── Pass 3: update caches ──────────────────────────────────────
            for ckey, (raw_text, indexed_text) in batch.items():
                self._indexed.add(ckey)
                self._content_cache[ckey] = raw_text
                self._indexed_text[ckey]  = indexed_text
                self._chunk_to_doc[ckey]  = name
            self._chunk_parents.update(new_parents)

            # ── Pass 4: batch ST embedding ─────────────────────────────────
            if self.config.use_st and self._st_model:
                self._embed_documents_batch(
                    {k: v[1] for k, v in batch.items()}
                )

            # ── Pass 5: rebuild global TOC ─────────────────────────────────
            self._global_toc = self._build_global_toc()

            if self._log:
                dt       = (time.perf_counter() - t0) * 1000
                strategy = self.config.chunking_strategy
                self._log.info(
                    "RAG",
                    f"Indexed '{name}'"
                    f"  |  {len(batch)} chunks  |  {len(content)} chars"
                    f"  |  {strategy}  |  {dt:.1f}ms",
                )
            return True
        except Exception as exc:
            if self._log:
                self._log.error("RAG", f"Index failed for '{name}': {exc}")
            return False

    def index_file(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            return self.index_content(path, content)
        except Exception:
            return False

    def remove_file(self, name: str):
        to_remove = [
            k for k in list(self._indexed)
            if k == name or k.startswith(f"{name}{_SEP}")
        ]
        for k in to_remove:
            self._index.remove_document(k)
            self._indexed.discard(k)
            self._content_cache.pop(k, None)
            self._indexed_text.pop(k, None)
            self._chunk_to_doc.pop(k, None)
            self._st_embeddings.pop(k, None)
            self._chunk_parents.pop(k, None)
        self._doc_full_content.pop(name, None)
        self._global_toc = self._build_global_toc()

    def clear(self):
        self._index.clear()
        self._indexed.clear()
        self._content_cache.clear()
        self._indexed_text.clear()
        self._chunk_to_doc.clear()
        self._st_embeddings.clear()
        self._doc_full_content.clear()
        self._chunk_parents.clear()
        self._global_toc = ""

    def dump_state(self) -> dict:
        """Return a pickle-serialisable snapshot of all RAG internal state."""
        with self._lock:
            return {
                "tfidf_docs":       dict(self._index._docs),
                "tfidf_scores":     dict(self._index._tfidf),
                "tfidf_idf":        dict(self._index._idf),
                "indexed":          list(self._indexed),
                "content_cache":    dict(self._content_cache),
                "indexed_text":     dict(self._indexed_text),
                "chunk_to_doc":     dict(self._chunk_to_doc),
                "doc_full_content": dict(self._doc_full_content),
                "chunk_parents":    dict(self._chunk_parents),
                "global_toc":       self._global_toc,
                "has_st_embeddings": bool(self._st_embeddings),
            }

    def load_state(self, state: dict):
        """Restore all RAG internal state from a snapshot (thread-safe)."""
        with self._lock:
            self._index._docs   = state.get("tfidf_docs", {})
            self._index._tfidf  = state.get("tfidf_scores", {})
            self._index._idf    = state.get("tfidf_idf", {})
            self._indexed       = set(state.get("indexed", []))
            self._content_cache = state.get("content_cache", {})
            self._indexed_text  = state.get("indexed_text", {})
            self._chunk_to_doc  = state.get("chunk_to_doc", {})
            self._doc_full_content = state.get("doc_full_content", {})
            self._chunk_parents = state.get("chunk_parents", {})
            self._global_toc    = state.get("global_toc", "")

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int | None = None,
        with_debug: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Return document-level merged hits sorted by relevance.

        *top_k* overrides ``config.top_k`` when provided.
        If *with_debug* is True, also return a debug structure explaining
        backend hits, fusion, and cross-chunk merges per document.
        """
        t0              = time.perf_counter()
        cfg             = self.config
        effective_top_k = top_k if top_k is not None else cfg.top_k
        fetch_k         = max(effective_top_k * 4, 30)
        trace_by_key: dict[str, dict[str, Any]] = {}
        span_cache: dict[str, tuple[int, int] | None] = {}

        def _trace_hit(bucket: str, ranked: list[tuple[str, float, str]]):
            for rank, (key, score, _excerpt) in enumerate(ranked, 1):
                tr = trace_by_key.setdefault(
                    key,
                    {"tfidf": None, "st": None, "regex": None},
                )
                prev = tr.get(bucket)
                if prev is None or rank < int(prev["rank"]):
                    tr[bucket] = {"rank": rank, "score": float(score)}

        def _chunk_index(key: str) -> int | None:
            if _SEP not in key:
                return None
            try:
                return int(key.rsplit(_SEP, 1)[1])
            except Exception:
                return None

        def _get_span(key: str) -> tuple[int, int] | None:
            if key not in span_cache:
                span_cache[key] = self._chunk_span(key)
            return span_cache[key]

        def _merge_overlap_texts(blocks: list[str]) -> str:
            clean = [b.strip() for b in blocks if b and b.strip()]
            if not clean:
                return ""
            merged = clean[0]
            for nxt in clean[1:]:
                if nxt in merged:
                    continue
                if merged in nxt:
                    merged = nxt
                    continue
                max_ov = min(len(merged), len(nxt), 500)
                overlap = 0
                for n in range(max_ov, 39, -1):
                    if merged[-n:] == nxt[:n]:
                        overlap = n
                        break
                if overlap > 0:
                    merged = merged + nxt[overlap:]
                else:
                    merged = merged.rstrip() + "\n\n" + nxt.lstrip()
            return merged

        def _dedupe_adjacent_paragraphs(text: str) -> str:
            parts = [p.strip() for p in re.split(r"\n{2,}", text or "") if p.strip()]
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

        # 1. HyDE expansion
        tfidf_query = query
        st_queries  = [query]
        should_expand = cfg.use_hyde and len(query.split()) <= cfg.hyde_min_words

        if should_expand:
            if cfg.use_tfidf and self._tfidf_query_expander:
                tfidf_query = self._safe_expand_tfidf(query)
            if cfg.use_st and self._st_model and self._st_query_expander:
                st_queries = self._safe_expand_st(query)

        # 2. Retrieval
        tfidf_raw: list[tuple[str, float, str]] = []
        st_raw:    list[tuple[str, float, str]] = []

        if cfg.use_tfidf:
            tfidf_raw = self._index.search(tfidf_query, fetch_k)
            _trace_hit("tfidf", tfidf_raw)

        if cfg.use_st and self._st_model:
            for q in st_queries:
                st_batch = self._st_search(q, fetch_k)
                st_raw.extend(st_batch)
                _trace_hit("st", st_batch)
            if len(st_queries) > 1:
                st_raw = _deduplicate_and_rerank(st_raw)

        # 3. Merge (RRF if both backends active)
        if tfidf_raw and st_raw:
            raw = _rrf_merge(tfidf_raw, st_raw)
            if self._log:
                self._log.debug(
                    "RAG",
                    f"RRF merge: {len(tfidf_raw)} TF-IDF + {len(st_raw)} ST"
                    f" → {len(raw)} merged",
                )
        elif st_raw:
            raw = st_raw
        else:
            raw = tfidf_raw

        # 4. Apply selection criteria on an expanded candidate set.
        # We merge chunks to document-level later, therefore we keep more
        # chunk candidates than final top_k docs.
        candidate_top_k = max(effective_top_k * 4, 20)
        raw = raw[:candidate_top_k]

        # 5. Regex / literal direct search
        regex_hits: list[tuple[str, float, str]] = []
        literal_terms: list[str] = [query.strip()] if (cfg.use_regex_search and query.strip()) else []
        literal_llm_terms: list[str] = []
        warnings: list[str] = []
        if cfg.use_regex_search and query.strip():
            if cfg.literal_use_llm_terms:
                if not self._literal_query_expander:
                    warnings.append(
                        "Literal LLM terms enabled, but no LLM expander is configured. "
                        "Continuing without LLM term expansion."
                    )
                else:
                    literal_llm_terms, literal_meta = self._safe_expand_literal_terms(query)
                    if not bool(literal_meta.get("used", bool(literal_llm_terms))):
                        reason = str(literal_meta.get("reason", "unknown"))
                        warnings.append(
                            "Literal LLM term expansion requested but not used "
                            f"(reason: {reason}). Continuing with base query terms."
                        )
                literal_terms.extend(literal_llm_terms)
            regex_hits = self._regex_search(literal_terms)
            _trace_hit("regex", regex_hits)

        # 6. Merge (unique regex hits prepended to semantic results)
        merged = _merge(regex_hits, raw, candidate_top_k + cfg.regex_max_results)
        # Result selection must apply to all backends (TF-IDF/ST/regex).
        merged = self._apply_selection(merged, candidate_top_k + cfg.regex_max_results)

        # 7. Build chunk-level hit list with full chunk text and method trace
        chunk_hits: list[dict[str, Any]] = []
        for key, score, fallback_excerpt in merged:
            doc_name = self._chunk_to_doc.get(key, key)
            excerpt = self._content_cache.get(key, "").strip() or fallback_excerpt.strip()
            if not excerpt:
                continue

            excerpt = self._paragraph_excerpt(key, excerpt)
            if cfg.extended_context:
                excerpt = self._extended_excerpt(key, excerpt)
            elif key in self._chunk_parents:
                excerpt = self._chunk_parents[key]

            trace = trace_by_key.get(key, {})
            methods = [
                bucket for bucket in ("tfidf", "st", "regex")
                if trace.get(bucket) is not None
            ]
            chunk_hits.append({
                "key": key,
                "doc": doc_name,
                "chunk_idx": _chunk_index(key),
                "score": float(score),
                "excerpt": excerpt,
                "methods": methods,
                "trace": trace,
                "span": _get_span(key),
            })

        # 8. Optional LLM rerank/filter on chunk-level hits (every text passage)
        chunk_rerank_debug: dict[str, Any] = {
            "enabled": bool(cfg.llm_rerank_enabled),
            "applied": False,
            "kept": len(chunk_hits),
            "before": len(chunk_hits),
            "threshold": float(cfg.llm_rerank_min_score),
            "mode": "per_hit_all",
        }
        if cfg.llm_rerank_enabled and chunk_hits:
            rerank_candidates = list(chunk_hits)
            reranked, rerank_meta = self._safe_rerank_items(
                query,
                rerank_candidates,
                len(rerank_candidates),
            )
            if isinstance(rerank_meta, dict):
                chunk_rerank_debug.update(rerank_meta)

            if reranked is None:
                chunk_hits = rerank_candidates
            else:
                by_key: dict[str, dict[str, Any]] = {
                    str(h.get("key", "")): h
                    for h in rerank_candidates
                    if isinstance(h, dict)
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

        # 9. Group and merge chunk hits per document
        doc_map: dict[str, list[dict[str, Any]]] = {}
        for hit in chunk_hits:
            doc_map.setdefault(hit["doc"], []).append(hit)

        doc_results: list[dict[str, Any]] = []
        doc_merges_debug: list[dict[str, Any]] = []

        for doc_name, hits in doc_map.items():
            hits.sort(
                key=lambda h: (
                    h["span"][0] if h["span"] is not None else 10**12,
                    h["chunk_idx"] if h["chunk_idx"] is not None else 10**9,
                    -float(h["score"]),
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
                    elif (
                        idx is not None
                        and prev["max_idx"] is not None
                        and idx <= prev["max_idx"] + 1
                    ):
                        can_merge = True

                if can_merge:
                    c = clusters[-1]
                    c["hits"].append(hit)
                    if idx is not None:
                        if c["min_idx"] is None:
                            c["min_idx"] = idx
                        c["max_idx"] = idx if c["max_idx"] is None else max(c["max_idx"], idx)
                    if span is not None:
                        if c["min_span"] is None:
                            c["min_span"] = span[0]
                        if c["max_span"] is None:
                            c["max_span"] = span[1]
                        else:
                            c["max_span"] = max(c["max_span"], span[1])
                else:
                    clusters.append({
                        "hits": [hit],
                        "min_idx": idx,
                        "max_idx": idx,
                        "min_span": span[0] if span is not None else None,
                        "max_span": span[1] if span is not None else None,
                    })

            merged_blocks: list[dict[str, Any]] = []
            block_texts: list[str] = []
            for c in clusters:
                c_hits = c["hits"]
                c_text = _merge_overlap_texts([h["excerpt"] for h in c_hits])
                c_text = _dedupe_adjacent_paragraphs(c_text)
                if not c_text:
                    continue
                c_methods = sorted({m for h in c_hits for m in h["methods"]})
                c_keys = [h["key"] for h in c_hits]
                c_idxs = [h["chunk_idx"] for h in c_hits if h["chunk_idx"] is not None]
                c_spans = [h["span"] for h in c_hits if h["span"] is not None]
                merged_blocks.append({
                    "chunk_keys": c_keys,
                    "chunk_indexes": c_idxs,
                    "methods": c_methods,
                    "text_length": len(c_text),
                    "span_start": min(s[0] for s in c_spans) if c_spans else None,
                    "span_end": max(s[1] for s in c_spans) if c_spans else None,
                })
                block_texts.append(c_text)

            if not block_texts:
                continue

            merged_excerpt = ("\n\n[...]\n\n").join(block_texts)
            merged_excerpt = _dedupe_adjacent_paragraphs(merged_excerpt)
            max_score = max(float(h["score"]) for h in hits)
            coverage_bonus = min(0.40, 0.08 * (len(hits) - 1))
            doc_methods = sorted({m for h in hits for m in h["methods"]})
            method_bonus = min(0.15, 0.05 * max(0, len(doc_methods) - 1))
            cluster_bonus = min(0.15, 0.05 * max(0, len(merged_blocks) - 1))
            doc_score = max_score + coverage_bonus + method_bonus + cluster_bonus
            chunk_keys = [h["key"] for h in hits]
            chunk_indexes = [h["chunk_idx"] for h in hits if h["chunk_idx"] is not None]
            rerank_classes = [
                str(h.get("llm_rerank_class", "")).strip().lower()
                for h in hits
                if str(h.get("llm_rerank_class", "")).strip()
            ]
            rerank_scores = [
                float(h.get("llm_rerank_score"))
                for h in hits
                if isinstance(h.get("llm_rerank_score"), (int, float))
            ]
            rerank_reasons = sorted({
                str(h.get("llm_rerank_reason", "")).strip()
                for h in hits
                if str(h.get("llm_rerank_reason", "")).strip()
            })

            doc_results.append({
                "name": doc_name,
                "score": float(doc_score),
                "excerpt": merged_excerpt,
                "meta": {
                    "hit_count": len(hits),
                    "methods": doc_methods,
                    "chunk_keys": chunk_keys,
                    "chunk_indexes": chunk_indexes,
                    "cluster_count": len(merged_blocks),
                    "merged_clusters": merged_blocks,
                    "llm_rerank_class": (
                        "sinnvoll" if any(c == "sinnvoll" for c in rerank_classes)
                        else (rerank_classes[0] if rerank_classes else "")
                    ),
                    "llm_rerank_score": (
                        sum(rerank_scores) / len(rerank_scores)
                        if rerank_scores else None
                    ),
                    "llm_rerank_keep": (
                        any(c == "sinnvoll" for c in rerank_classes)
                        if rerank_classes else bool(rerank_scores)
                    ),
                    "llm_rerank_reason": rerank_reasons[0] if rerank_reasons else "",
                },
            })

            doc_merges_debug.append({
                "doc": doc_name,
                "score": float(doc_score),
                "hit_count": len(hits),
                "methods": doc_methods,
                "chunk_keys": chunk_keys,
                "chunk_indexes": chunk_indexes,
                "merged_clusters": merged_blocks,
            })

        doc_results.sort(key=lambda x: float(x["score"]), reverse=True)
        doc_results = self._apply_doc_selection(doc_results, effective_top_k)

        debug_info: dict[str, Any] = {
            "query": query,
            "effective_top_k": effective_top_k,
            "candidate_top_k": candidate_top_k,
            "fetch_k": fetch_k,
            "selection_mode": cfg.selection_mode,
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
                    "key": h["key"],
                    "doc": h["doc"],
                    "chunk_idx": h["chunk_idx"],
                    "span_start": h["span"][0] if h["span"] is not None else None,
                    "span_end": h["span"][1] if h["span"] is not None else None,
                    "score": round(float(h["score"]), 6),
                    "methods": h["methods"],
                    "llm_rerank_class": h.get("llm_rerank_class", ""),
                    "llm_rerank_keep": h.get("llm_rerank_keep", None),
                    "llm_rerank_reason": h.get("llm_rerank_reason", ""),
                    "trace": h["trace"],
                }
                for h in chunk_hits
            ],
            "doc_merges": doc_merges_debug,
        }

        if self._log:
            dt      = (time.perf_counter() - t0) * 1000
            backend = self.current_backend()
            notes: list[str] = []
            if tfidf_query != query and cfg.use_tfidf:
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
            extra = ("  " + "  ".join(notes)) if notes else ""
            self._log.info(
                "RAG",
                f"Search '{query}'"
                f"  |  {backend}  mode={cfg.selection_mode}"
                f"  |  chunks={len(chunk_hits)}  docs={len(doc_results)}"
                f"  |  {dt:.1f}ms"
                + extra,
            )

        if with_debug:
            return doc_results, debug_info
        return doc_results

    # ── Chunking ──────────────────────────────────────────────────────────────

    def _build_chunks(self, content: str, doc_name: str = "") -> list[dict]:
        segments = _parse_segments(content)
        if not segments:
            return []

        # Split any segment larger than chunk_size
        split: list[dict] = []
        for seg in segments:
            if len(seg["text"]) > self.config.chunk_size:
                split.extend(_split_segment(seg, self.config.chunk_size))
            else:
                split.append(seg)
        segments = split

        if self._log:
            self._log.debug(
                "RAG",
                f"Parsed {len(segments)} segments"
                f"  |  chunk_size={self.config.chunk_size}"
                f"  |  strategy={self.config.chunking_strategy}",
            )

        strategy = self.config.chunking_strategy
        if strategy == "section":
            return self._chunk_by_section(segments, doc_name)
        elif strategy == "recursive":
            return self._chunk_recursive(segments, doc_name)
        else:  # "sliding_window" (default)
            return self._chunk_sliding_window(segments, doc_name)

    def _chunk_sliding_window(self, segments: list[dict], doc_name: str = "") -> list[dict]:
        cfg    = self.config
        chunks: list[dict] = []
        i = 0

        while i < len(segments):
            window: list[dict] = []
            total_chars = 0
            j = i

            while j < len(segments):
                seg     = segments[j]
                seg_len = len(seg["text"])
                if window and total_chars + seg_len + 2 > cfg.chunk_size:
                    break
                window.append(seg)
                total_chars += seg_len + 2
                j += 1

            if not window:
                i += 1
                continue

            chunks.append(_make_chunk_dict(window, cfg, doc_name))

            if cfg.chunk_overlap > 0 and len(window) > 1:
                overlap_chars = 0
                keep          = 0
                for seg in reversed(window):
                    overlap_chars += len(seg["text"]) + 2
                    keep          += 1
                    if overlap_chars >= cfg.chunk_overlap:
                        break
                advance = max(1, len(window) - keep)
                i += advance
            else:
                i = j

        return chunks

    def _chunk_by_section(self, segments: list[dict], doc_name: str = "") -> list[dict]:
        """One chunk per Markdown heading section."""
        sections: list[list[dict]] = []
        current:  list[dict]       = []
        section_level              = 0

        for seg in segments:
            if seg["is_heading"]:
                lvl = seg["h_level"]
                if current and lvl <= section_level:
                    sections.append(current)
                    current       = [seg]
                    section_level = lvl
                elif not current:
                    current       = [seg]
                    section_level = lvl
                else:
                    current.append(seg)
            else:
                if not current:
                    current = [seg]
                else:
                    current.append(seg)

        if current:
            sections.append(current)

        return [_make_chunk_dict(s, self.config, doc_name) for s in sections]

    def _chunk_recursive(self, segments: list[dict], doc_name: str = "") -> list[dict]:
        """Hierarchical chunking: H1 → H2 → sliding-window leaf chunks.

        Each leaf chunk stores ``_parent_text`` = the full H2 (or H1, or whole
        document) section text, used by extended-context retrieval.
        """

        def _group_by_level(segs: list[dict], level: int) -> list[list[dict]]:
            """Group segments by heading of the given level."""
            groups: list[list[dict]] = []
            current: list[dict] = []
            for seg in segs:
                if seg["is_heading"] and seg["h_level"] == level:
                    if current:
                        groups.append(current)
                    current = [seg]
                else:
                    current.append(seg)
            if current:
                groups.append(current)
            return groups if groups else [segs]

        all_chunks: list[dict] = []

        for h1_segs in _group_by_level(segments, 1):
            for h2_segs in _group_by_level(h1_segs, 2):
                parent_text = "\n\n".join(s["text"] for s in h2_segs)
                leaf_chunks = self._chunk_sliding_window(h2_segs, doc_name)
                for chunk in leaf_chunks:
                    chunk["_parent_text"] = parent_text
                    all_chunks.append(chunk)

        return all_chunks

    # ── Sentence-transformers internals ───────────────────────────────────────

    def _embed_document(self, key: str, text: str):
        """Encode a single chunk.  Prefer ``_embed_documents_batch`` for bulk work."""
        try:
            emb = self._st_model.encode(text[:4096], convert_to_tensor=True)
            self._st_embeddings[key] = emb
        except Exception:
            pass

    def _embed_documents_batch(self, chunks: dict[str, str]):
        """Batch-encode many chunks in a single model forward pass."""
        if not chunks:
            return
        keys  = list(chunks.keys())
        texts = [chunks[k][:4096] for k in keys]
        try:
            embeddings = self._st_model.encode(
                texts,
                convert_to_tensor=True,
                show_progress_bar=False,
                batch_size=32,
            )
            for key, emb in zip(keys, embeddings):
                self._st_embeddings[key] = emb
            if self._log:
                self._log.debug(
                    "ST",
                    f"Batch encoded {len(keys)} chunks  |  batch_size=32",
                )
        except Exception as exc:
            if self._log:
                self._log.error("ST", f"Batch encode failed, falling back to one-by-one: {exc}")
            for key, text in chunks.items():
                self._embed_document(key, text)

    def _rebuild_st_embeddings(self):
        n = len(self._indexed)
        if self._log:
            self._log.info("ST", f"Rebuilding embeddings  |  {n} chunks…")
        t0 = time.perf_counter()
        self._st_embeddings.clear()

        chunks: dict[str, str] = {}
        for key in list(self._indexed):
            text = self._indexed_text.get(key) or self._content_cache.get(key, "")
            if text.strip():
                chunks[key] = text

        self._embed_documents_batch(chunks)

        if self._log:
            dt = time.perf_counter() - t0
            self._log.info(
                "ST",
                f"Embeddings ready  |  {len(self._st_embeddings)} chunks  |  {dt:.2f}s",
            )

    def _st_search(self, query: str, top_k: int) -> list[tuple[str, float, str]]:
        """Semantic search using batched cosine-similarity matrix op."""
        t0 = time.perf_counter()
        try:
            import torch  # type: ignore
            from sentence_transformers import util  # type: ignore

            if not self._st_embeddings:
                return []

            q_emb  = self._st_model.encode(query, convert_to_tensor=True)
            tokens = TFIDFIndex._tokenize(query)

            keys       = list(self._st_embeddings.keys())
            emb_matrix = torch.stack([self._st_embeddings[k] for k in keys])
            scores     = util.cos_sim(q_emb, emb_matrix)[0].tolist()

            ranked = sorted(
                zip(keys, scores), key=lambda x: x[1], reverse=True
            )[:top_k]

            results = [
                (key, score, _excerpt(self._content_cache.get(key, ""), tokens))
                for key, score in ranked
            ]

            if self._log:
                dt = (time.perf_counter() - t0) * 1000
                self._log.debug(
                    "ST",
                    f"Matrix cosine search  |  {len(keys)} embeddings"
                    f"  |  top {len(results)} returned  |  {dt:.1f}ms",
                )
            return results
        except Exception as exc:
            if self._log:
                self._log.error("ST", f"ST search failed, falling back to TF-IDF: {exc}")
            return self._index.search(query, top_k)

    # ── Selection ─────────────────────────────────────────────────────────────

    def _apply_selection(
        self,
        raw: list[tuple[str, float, str]],
        top_k: int,
    ) -> list[tuple[str, float, str]]:
        mode      = self.config.selection_mode
        threshold = self.config.score_threshold

        if mode == "threshold":
            return [r for r in raw if r[1] >= threshold]
        elif mode == "top_k_threshold":
            return [r for r in raw if r[1] >= threshold][:top_k]
        else:   # "top_k" (default)
            return raw[:top_k]

    def _apply_doc_selection(
        self,
        docs: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Apply result-selection policy on final document results."""
        mode      = self.config.selection_mode
        threshold = self.config.score_threshold

        if mode == "threshold":
            return [d for d in docs if float(d.get("score", 0.0)) >= threshold]
        elif mode == "top_k_threshold":
            return [
                d for d in docs
                if float(d.get("score", 0.0)) >= threshold
            ][:top_k]
        else:   # "top_k" (default)
            return docs[:top_k]

    # ── Regex / literal search ────────────────────────────────────────────────

    def _regex_search(self, terms: list[str]) -> list[tuple[str, float, str]]:
        clean_terms = self._normalise_literal_terms(terms)
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
        for key, content in self._content_cache.items():
            body = content.strip()
            if not body:
                continue

            match_count = 0
            first_pos = len(body)
            for _term, pat in patterns:
                m = pat.search(body)
                if m:
                    match_count += 1
                    first_pos = min(first_pos, m.start())

            if match_count <= 0:
                continue

            score = 1.5 + min(0.6, 0.1 * (match_count - 1))
            scored.append((key, score, body, match_count, first_pos))

        scored.sort(key=lambda x: (-x[3], -x[1], x[4]))
        result = [
            (key, score, excerpt)
            for key, score, excerpt, _cnt, _pos in scored[: self.config.regex_max_results]
        ]
        if self._log and result:
            docs = [self._chunk_to_doc.get(k, k) for k, _, _ in result]
            self._log.debug(
                "RAG",
                f"Literal terms '{', '.join(clean_terms[:6])}'"
                f"  |  {len(result)} hits in: {', '.join(set(docs))}",
            )
        return result

    # ── HyDE / Query expansion ────────────────────────────────────────────────

    @staticmethod
    def _normalise_literal_terms(terms: list[str]) -> list[str]:
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

    def _safe_expand_literal_terms(self, query: str) -> tuple[list[str], dict[str, Any]]:
        """Run literal-term expansion via LLM callback."""
        cfg = self.config
        limit = max(1, int(cfg.literal_llm_max_terms))
        try:
            result = self._literal_query_expander(query, limit)  # type: ignore[misc]
            meta: dict[str, Any] = {}
            if (
                isinstance(result, tuple)
                and len(result) == 2
                and isinstance(result[1], dict)
            ):
                raw_result = result[0]
                meta = dict(result[1])
            else:
                raw_result = result

            if isinstance(raw_result, str):
                raw_terms = [
                    t.strip()
                    for t in re.split(r"[,\n;]+", raw_result)
                    if t.strip()
                ]
            else:
                raw_terms = [str(t).strip() for t in (raw_result or []) if str(t).strip()]
            terms = self._normalise_literal_terms(raw_terms)[:limit]
            if self._log and terms:
                self._log.info(
                    "LLM",
                    f"Literal terms: '{query}'  ->  {', '.join(terms[:8])}",
                )
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

    def _safe_rerank_items(
        self,
        query: str,
        items: list[dict[str, Any]],
        top_k: int,
    ) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
        """Run optional LLM reranking/filtering on item-level search hits."""
        cfg = self.config
        if not self._rag_reranker:
            return None, {
                "enabled": True,
                "applied": False,
                "reason": "no_reranker",
            }
        try:
            result = self._rag_reranker(
                query,
                items,
                top_k,
                float(cfg.llm_rerank_min_score),
            )
            rerank_meta: dict[str, Any] = {}
            if (
                isinstance(result, tuple)
                and len(result) == 2
                and isinstance(result[1], dict)
            ):
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

            clean: list[dict[str, Any]] = [
                d for d in reranked_docs
                if isinstance(d, dict)
            ]
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

    def _safe_expand_tfidf(self, query: str) -> str:
        """Run TF-IDF HyDE: return keyword list (or original query on failure)."""
        cfg = self.config
        try:
            input_q = query
            if cfg.hyde_use_doc_context and self._global_toc:
                input_q = f"[Dokumentstruktur:\n{self._global_toc}]\n\n{query}"
            result   = self._tfidf_query_expander(input_q)  # type: ignore[misc]
            expanded = result.strip() if result else ""
            if self._log and expanded and expanded != query:
                self._log.info(
                    "LLM",
                    f"HyDE TF-IDF keywords: '{query}'  ->  '{expanded[:80]}'",
                )
            return expanded if expanded else query
        except Exception as exc:
            if self._log:
                self._log.error("LLM", f"HyDE TF-IDF expansion error: {exc}")
            return query

    def _safe_expand_st(self, query: str) -> list[str]:
        """Run ST HyDE: return list of 1..N hypothetical passages."""
        cfg = self.config
        n   = cfg.hyde_st_hypotheses if cfg.hyde_st_mode == "multi_passage" else 1
        try:
            input_q = query
            if cfg.hyde_use_doc_context and self._global_toc:
                input_q = f"[Dokumentstruktur:\n{self._global_toc}]\n\n{query}"
            result = self._st_query_expander(input_q, n)  # type: ignore[misc]
            if isinstance(result, str):
                result = [result]
            passages = [p.strip() for p in result if p.strip()]
            if self._log and passages and passages != [query]:
                self._log.info(
                    "ST",
                    f"HyDE ST passages x{len(passages)}: '{query}'",
                )
            return passages if passages else [query]
        except Exception as exc:
            if self._log:
                self._log.error("ST", f"HyDE ST expansion error: {exc}")
            return [query]

    # ── Extended context ──────────────────────────────────────────────────────

    def _chunk_span(self, key: str) -> tuple[int, int] | None:
        """Return ``(start, end)`` of a chunk inside its source document."""
        doc_name = self._chunk_to_doc.get(key, "")
        full = self._doc_full_content.get(doc_name, "")
        chunk = self._content_cache.get(key, "")
        if not full or not chunk:
            return None

        pos = full.find(chunk)
        if pos != -1:
            return (pos, pos + len(chunk))

        # Fallback: use a short anchor when exact chunk lookup fails.
        anchor = chunk.strip()[:200]
        if not anchor:
            return None
        pos = full.find(anchor)
        if pos == -1:
            return None
        return (pos, min(len(full), pos + len(anchor)))

    def _paragraph_excerpt(self, key: str, fallback: str) -> str:
        """Return full paragraph block containing the chunk span."""
        doc_name = self._chunk_to_doc.get(key, "")
        full = self._doc_full_content.get(doc_name, "")
        span = self._chunk_span(key)
        if not full or span is None:
            return fallback

        start, end = span
        para_start = full.rfind("\n\n", 0, start)
        para_start = 0 if para_start == -1 else para_start + 2
        para_end = full.find("\n\n", end)
        para_end = len(full) if para_end == -1 else para_end

        excerpt = re.sub(r"\n{3,}", "\n\n", full[para_start:para_end]).strip()
        return excerpt or fallback

    def _extended_excerpt(self, key: str, fallback: str) -> str:
        """Expand the chunk excerpt by ±N chars in the source document."""
        cfg      = self.config
        doc_name = self._chunk_to_doc.get(key, "")
        full     = self._doc_full_content.get(doc_name, "")
        if not full:
            return fallback

        span = self._chunk_span(key)
        if span is None:
            return fallback

        start = max(0, span[0] - cfg.extended_context_before)
        end   = min(len(full), span[1] + cfg.extended_context_after)
        excerpt = re.sub(r"\n{3,}", "\n\n", full[start:end]).strip()
        return (
            ("…" if start > 0 else "")
            + excerpt
            + ("…" if end < len(full) else "")
        )

    # ── Global TOC ────────────────────────────────────────────────────────────

    def _build_global_toc(self) -> str:
        """Build a compact heading TOC from all indexed documents (max 800 chars)."""
        MAX   = 800
        lines: list[str] = []

        for doc_name, content in self._doc_full_content.items():
            basename = os.path.basename(doc_name)
            headings = re.findall(r"^(#{1,3})\s+(.+)", content, re.MULTILINE)
            if not headings:
                continue
            parts = [f"[{basename}]"]
            for hashes, title in headings[:8]:
                lvl    = len(hashes)
                indent = "  " * (lvl - 1)
                parts.append(f"{indent}{title.strip()}")
            lines.append("\n".join(parts))

        result = "\n\n".join(lines)
        if len(result) > MAX:
            result = result[:MAX] + "…"
        return result


# ── Module-level helpers ──────────────────────────────────────────────────────

def _parse_segments(content: str) -> list[dict]:
    """Split *content* into paragraphs, tracking Markdown heading hierarchy."""
    heading_stack: list[tuple[int, str]] = []
    segments: list[dict] = []

    for raw in re.split(r"\n{2,}", content):
        para = raw.strip()
        if not para:
            continue
        m = re.match(r'^(#{1,6})\s+(.+)', para)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            heading_stack = [(l, t) for l, t in heading_stack if l < level]
            heading_stack.append((level, title))
            is_heading = True
        else:
            is_heading = False

        segments.append({
            "text":      para,
            "breadcrumb": [t for _, t in heading_stack],
            "is_heading": is_heading,
            "h_level":    len(m.group(1)) if m else 0,
        })

    return segments


def _split_segment(seg: dict, max_chars: int) -> list[dict]:
    """Break a segment wider than *max_chars* into smaller pieces."""
    def _hard_split(text: str, limit: int) -> list[str]:
        parts: list[str] = []
        while len(text) > limit:
            cut = text.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            parts.append(text[:cut].strip())
            text = text[cut:].strip()
        if text:
            parts.append(text)
        return parts

    text  = seg["text"]
    lines = text.split("\n")

    groups: list[str] = []
    buf: list[str]    = []
    buf_len           = 0

    for line in lines:
        line_len = len(line)
        if line_len > max_chars:
            if buf:
                groups.append("\n".join(buf))
                buf, buf_len = [], 0
            groups.extend(_hard_split(line, max_chars))
        elif buf and buf_len + line_len + 1 > max_chars:
            groups.append("\n".join(buf))
            buf, buf_len = [line], line_len
        else:
            buf.append(line)
            buf_len += line_len + 1

    if buf:
        groups.append("\n".join(buf))

    return [
        {**seg, "text": g}
        for g in groups
        if g.strip()
    ] or [seg]


def _make_chunk_dict(segs: list[dict], cfg: RAGConfig, doc_name: str = "") -> dict:
    raw_text   = "\n\n".join(s["text"] for s in segs)
    breadcrumb = segs[-1]["breadcrumb"]

    if cfg.include_filename and doc_name:
        basename     = os.path.basename(doc_name)
        prefix_parts = [basename]
        if cfg.include_headings and breadcrumb:
            prefix_parts.extend(breadcrumb)
        indexed_text = f"[{' › '.join(prefix_parts)}]\n\n{raw_text}"
    elif cfg.include_headings and breadcrumb:
        prefix       = " › ".join(breadcrumb)
        indexed_text = f"[{prefix}]\n\n{raw_text}"
    else:
        indexed_text = raw_text

    return {
        "text":      indexed_text,
        "raw_text":  raw_text,
        "breadcrumb": breadcrumb,
    }


def _rrf_merge(
    a: list[tuple[str, float, str]],
    b: list[tuple[str, float, str]],
    k: int = 60,
) -> list[tuple[str, float, str]]:
    """Reciprocal Rank Fusion of two ranked lists."""
    scores:   dict[str, float] = {}
    excerpts: dict[str, str]   = {}

    for rank, (key, _score, excerpt) in enumerate(a):
        scores[key]   = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        excerpts[key] = excerpt

    for rank, (key, _score, excerpt) in enumerate(b):
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        if key not in excerpts:
            excerpts[key] = excerpt

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [(key, score, excerpts[key]) for key, score in ranked]


def _deduplicate_and_rerank(
    results: list[tuple[str, float, str]],
) -> list[tuple[str, float, str]]:
    """Keep highest score per key, re-sort descending."""
    best: dict[str, tuple[float, str]] = {}
    for key, score, excerpt in results:
        if key not in best or score > best[key][0]:
            best[key] = (score, excerpt)
    return sorted(
        [(key, score, excerpt) for key, (score, excerpt) in best.items()],
        key=lambda x: x[1],
        reverse=True,
    )


def _merge(
    regex: list[tuple[str, float, str]],
    semantic: list[tuple[str, float, str]],
    max_total: int,
) -> list[tuple[str, float, str]]:
    """Prepend unique regex hits before semantic results, capped at *max_total*."""
    seen         = {k for k, _, _ in semantic}
    unique_regex = [(k, s, e) for k, s, e in regex if k not in seen]
    return (unique_regex + semantic)[:max_total]


# ── Background worker ─────────────────────────────────────────────────────────

class RAGWorker(QThread):
    """
    Background QThread for non-blocking RAG operations.

    All heavy work (indexing, search, ST model loading) is serialised through
    an internal task queue so the UI thread is never blocked.

    Signals
    -------
    search_complete(query, results, debug_info)
    index_complete(n_docs)
    st_loaded(success)
    status_changed(message)
    """

    search_complete = Signal(str, list, dict)
    index_complete  = Signal(int)
    st_loaded       = Signal(bool)
    status_changed  = Signal(str)

    def __init__(self, rag: RAGSystem, parent: QObject | None = None):
        super().__init__(parent)
        self._rag   = rag
        self._queue: _queue.Queue = _queue.Queue()

    def enqueue_search(self, query: str):
        self._drain("search")
        self._queue.put(("search", query))
        if not self.isRunning():
            self.start()

    def enqueue_index(self, entries: list[tuple[str, str]]):
        self._drain("index")
        self._queue.put(("index", list(entries)))
        if not self.isRunning():
            self.start()

    def enqueue_load_st(self, model_name: str | None = None):
        self._queue.put(("load_st", model_name))
        if not self.isRunning():
            self.start()

    def stop_and_wait(self, timeout_ms: int = 5000):
        self._queue.put(("stop", None))
        self.wait(timeout_ms)

    def _drain(self, task_type: str):
        kept: list = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
            except _queue.Empty:
                break
            if item[0] != task_type:
                kept.append(item)
        for item in kept:
            self._queue.put(item)

    def run(self):
        while True:
            try:
                task, data = self._queue.get(timeout=0.5)
            except _queue.Empty:
                return

            if task == "stop":
                return

            elif task == "search":
                self.status_changed.emit("Searching…")
                with self._rag._lock:
                    results, debug_info = self._rag.search(data, with_debug=True)
                self.search_complete.emit(data, results, debug_info)
                self.status_changed.emit("")

            elif task == "index":
                n = len(data)
                self.status_changed.emit(
                    f"Indexing {n} file{'s' if n != 1 else ''}…"
                )
                with self._rag._lock:
                    self._rag.clear()
                    count = sum(
                        1 for name, content in data
                        if self._rag.index_content(name, content)
                    )
                self.index_complete.emit(count)
                self.status_changed.emit("")

            elif task == "load_st":
                self.status_changed.emit("Loading sentence-transformers model…")
                with self._rag._lock:
                    ok = self._rag.try_load_sentence_transformers(data)
                self.st_loaded.emit(ok)
                self.status_changed.emit("")
