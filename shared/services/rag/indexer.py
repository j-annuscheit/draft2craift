"""Indexing state and retrieval backends for RAG."""
from __future__ import annotations

import os
import re
import time
from typing import Any

from shared.services.rag.chunking import build_chunks
from shared.services.rag.excerpt import excerpt
from shared.services.rag.tfidf import BM25Index, TFIDFIndex

_SEP = "\x00"


class RAGIndexer:
    """Owns indexed content state and backend-specific retrieval primitives."""

    def __init__(self, config: Any, logger: Any = None):
        self.config = config
        self._log = logger
        self._index: TFIDFIndex | BM25Index = self._create_lexical_index()
        self._indexed: set[str] = set()
        self._content_cache: dict[str, str] = {}
        self._indexed_text: dict[str, str] = {}
        self._chunk_to_doc: dict[str, str] = {}
        self._doc_full_content: dict[str, str] = {}
        self._chunk_parents: dict[str, str] = {}
        self._global_toc: str = ""
        self._st_model: Any = None
        self._st_embeddings: dict[str, Any] = {}

    @property
    def index(self) -> TFIDFIndex | BM25Index:
        return self._index

    @property
    def indexed(self) -> set[str]:
        return self._indexed

    @property
    def content_cache(self) -> dict[str, str]:
        return self._content_cache

    @property
    def indexed_text(self) -> dict[str, str]:
        return self._indexed_text

    @property
    def chunk_to_doc(self) -> dict[str, str]:
        return self._chunk_to_doc

    @property
    def doc_full_content(self) -> dict[str, str]:
        return self._doc_full_content

    @property
    def chunk_parents(self) -> dict[str, str]:
        return self._chunk_parents

    @property
    def global_toc(self) -> str:
        return self._global_toc

    @property
    def st_model(self) -> Any:
        return self._st_model

    @st_model.setter
    def st_model(self, value: Any) -> None:
        self._st_model = value

    @property
    def st_embeddings(self) -> dict[str, Any]:
        return self._st_embeddings

    @st_embeddings.setter
    def st_embeddings(self, value: dict[str, Any]) -> None:
        self._st_embeddings = dict(value or {})

    def set_config(self, config: Any) -> None:
        self.config = config
        self._sync_lexical_index_from_config()

    @staticmethod
    def _normalise_lexical_mode(value: object) -> str:
        mode = str(value or "").strip().lower()
        if mode in {"tfidf", "bm25"}:
            return mode
        return "tfidf"

    def lexical_mode(self) -> str:
        backend = getattr(self.config, "backend", None)
        mode = getattr(backend, "lexical_mode", "tfidf")
        return self._normalise_lexical_mode(mode)

    def _create_lexical_index(self) -> TFIDFIndex | BM25Index:
        mode = self.lexical_mode()
        if mode == "bm25":
            backend = getattr(self.config, "backend", None)
            k1 = float(getattr(backend, "bm25_k1", 1.2))
            b = float(getattr(backend, "bm25_b", 0.75))
            return BM25Index(k1=k1, b=b)
        return TFIDFIndex()

    def _rebuild_lexical_index(self) -> None:
        docs = {
            key: text
            for key, text in self._indexed_text.items()
            if str(text or "").strip()
        }
        self._index.clear()
        if docs:
            self._index.add_documents_batch(docs)

    def _sync_lexical_index_from_config(self) -> None:
        mode = self.lexical_mode()
        backend = getattr(self.config, "backend", None)
        if mode == "bm25" and isinstance(self._index, BM25Index):
            self._index.set_params(
                k1=float(getattr(backend, "bm25_k1", 1.2)),
                b=float(getattr(backend, "bm25_b", 0.75)),
            )
            return
        if mode == "tfidf" and isinstance(self._index, TFIDFIndex):
            return
        self._index = self._create_lexical_index()
        self._rebuild_lexical_index()

    def current_backend(self) -> str:
        parts: list[str] = []
        if bool(self.config.backend.use_tfidf):
            parts.append(self.lexical_mode())
        if bool(self.config.backend.use_st and self._st_model is not None):
            parts.append("st")
        if bool(self.config.backend.use_regex_search):
            parts.append("literal")
        return "+".join(parts) or "none"

    def try_load_sentence_transformers(self, model_name: str | None = None) -> bool:
        name = model_name or self.config.backend.st_model_name
        if self._log:
            self._log.info("ST", f"Loading model: {name}")
        try:
            n_threads = int(getattr(self.config.backend, "st_n_threads", 0) or 0)
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
            self.config.backend.use_st = True
            if self._log:
                self._log.info("ST", f"Model loaded: {name}  |  rebuilding embeddings...")
            self.rebuild_st_embeddings()
            return True
        except Exception as exc:
            if self._log:
                self._log.error("ST", f"Load failed: {exc}")
            self._st_model = None
            return False

    def index_content(self, name: str, content: str) -> bool:
        t0 = time.perf_counter()
        try:
            self._doc_full_content[name] = content
            chunks = build_chunks(content, self.config.chunking, name, self._log)

            batch: dict[str, tuple[str, str]] = {}
            parents: dict[str, str] = {}
            for i, chunk in enumerate(chunks):
                raw_text = str(chunk.get("raw_text", ""))
                indexed_text = str(chunk.get("text", ""))
                if not raw_text.strip():
                    continue
                key = f"{name}{_SEP}{i}"
                batch[key] = (raw_text, indexed_text)
                parent_text = chunk.get("_parent_text")
                if isinstance(parent_text, str):
                    parents[key] = parent_text

            if not batch:
                self._global_toc = self.build_global_toc()
                return True

            self._index.add_documents_batch({key: value[1] for key, value in batch.items()})

            for key, (raw_text, indexed_text) in batch.items():
                self._indexed.add(key)
                self._content_cache[key] = raw_text
                self._indexed_text[key] = indexed_text
                self._chunk_to_doc[key] = name
            self._chunk_parents.update(parents)

            if self.config.backend.use_st and self._st_model:
                self.embed_documents_batch({key: value[1] for key, value in batch.items()})

            self._global_toc = self.build_global_toc()
            if self._log:
                dt = (time.perf_counter() - t0) * 1000
                self._log.info(
                    "RAG",
                    f"Indexed '{name}'  |  {len(batch)} chunks  |  {len(content)} chars"
                    f"  |  {self.config.chunking.strategy}  |  {dt:.1f}ms",
                )
            return True
        except Exception as exc:
            if self._log:
                self._log.error("RAG", f"Index failed for '{name}': {exc}")
            return False

    def index_file(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                content = handle.read()
            return self.index_content(path, content)
        except Exception:
            return False

    def sync_index(self, entries: list[tuple[str, str]]) -> tuple[int, int, int]:
        target_map: dict[str, str] = {}
        for name_raw, content_raw in list(entries or []):
            name = str(name_raw or "").strip()
            if not name:
                continue
            target_map[name] = str(content_raw or "")

        target_names = set(target_map.keys())
        existing_names = set(str(name or "") for name in self._doc_full_content.keys())

        removed_count = 0
        for obsolete in sorted(existing_names - target_names):
            if not obsolete:
                continue
            self.remove_file(obsolete)
            removed_count += 1

        indexed_count = 0
        skipped_count = 0
        for name, content in target_map.items():
            previous = self._doc_full_content.get(name)
            if previous is not None and previous == content:
                skipped_count += 1
                continue
            if previous is not None:
                self.remove_file(name)
            if self.index_content(name, content):
                indexed_count += 1

        if self._log:
            self._log.debug(
                "RAG",
                "Incremental sync"
                f"  |  target={len(target_map)}"
                f"  indexed={indexed_count}"
                f"  skipped={skipped_count}"
                f"  removed={removed_count}",
            )
        return indexed_count, skipped_count, removed_count

    def remove_file(self, name: str) -> None:
        to_remove = [
            key
            for key in list(self._indexed)
            if key == name or key.startswith(f"{name}{_SEP}")
        ]
        for key in to_remove:
            self._index.remove_document(key)
            self._indexed.discard(key)
            self._content_cache.pop(key, None)
            self._indexed_text.pop(key, None)
            self._chunk_to_doc.pop(key, None)
            self._st_embeddings.pop(key, None)
            self._chunk_parents.pop(key, None)

        self._doc_full_content.pop(name, None)
        self._global_toc = self.build_global_toc()

    def clear(self) -> None:
        self._index.clear()
        self._indexed.clear()
        self._content_cache.clear()
        self._indexed_text.clear()
        self._chunk_to_doc.clear()
        self._st_embeddings.clear()
        self._doc_full_content.clear()
        self._chunk_parents.clear()
        self._global_toc = ""

    def dump_state(self) -> dict[str, Any]:
        lexical_state = self._index.dump_state()
        return {
            "lexical_mode": self.lexical_mode(),
            "lexical_state": lexical_state,
            "indexed": list(self._indexed),
            "content_cache": dict(self._content_cache),
            "indexed_text": dict(self._indexed_text),
            "chunk_to_doc": dict(self._chunk_to_doc),
            "doc_full_content": dict(self._doc_full_content),
            "chunk_parents": dict(self._chunk_parents),
            "global_toc": self._global_toc,
            "has_st_embeddings": bool(self._st_embeddings),
        }

    def load_state(self, state: dict[str, Any]) -> None:
        mode = self._normalise_lexical_mode(state["lexical_mode"])
        backend = getattr(self.config, "backend", None)
        if backend is not None:
            setattr(backend, "lexical_mode", mode)

        if mode == "bm25":
            self._index = BM25Index(
                k1=float(getattr(backend, "bm25_k1", 1.2)),
                b=float(getattr(backend, "bm25_b", 0.75)),
            )
        else:
            self._index = TFIDFIndex()

        lexical_state = dict(state["lexical_state"])
        self._index.load_state(lexical_state)
        if mode == "bm25" and isinstance(self._index, BM25Index) and backend is not None:
            backend.bm25_k1 = float(self._index.k1)
            backend.bm25_b = float(self._index.b)

        self._indexed = set(state["indexed"])
        self._content_cache = dict(state["content_cache"])
        self._indexed_text = dict(state["indexed_text"])
        self._chunk_to_doc = dict(state["chunk_to_doc"])
        self._doc_full_content = dict(state["doc_full_content"])
        self._chunk_parents = dict(state["chunk_parents"])
        self._global_toc = str(state["global_toc"])

    def embed_documents_batch(self, chunks: dict[str, str]) -> None:
        if not chunks:
            return
        keys = list(chunks.keys())
        texts = [str(chunks[key] or "")[:4096] for key in keys]
        try:
            embeddings = self._st_model.encode(
                texts,
                convert_to_tensor=True,
                show_progress_bar=False,
                batch_size=32,
            )
            for key, emb in zip(keys, embeddings):
                self._st_embeddings[key] = emb
        except Exception:
            for key, text in chunks.items():
                self.embed_document(key, text)

    def embed_document(self, key: str, text: str) -> None:
        try:
            self._st_embeddings[key] = self._st_model.encode(text[:4096], convert_to_tensor=True)
        except Exception:
            return

    def rebuild_st_embeddings(self) -> None:
        self._st_embeddings.clear()
        chunks: dict[str, str] = {}
        for key in list(self._indexed):
            text = self._indexed_text.get(key) or self._content_cache.get(key, "")
            if str(text).strip():
                chunks[key] = text
        self.embed_documents_batch(chunks)

    def st_search(self, query: str, top_k: int) -> list[tuple[str, float, str]]:
        try:
            import torch  # type: ignore
            from sentence_transformers import util  # type: ignore

            if not self._st_embeddings:
                return []

            q_emb = self._st_model.encode(query, convert_to_tensor=True)
            tokens = TFIDFIndex.tokenize(query)
            keys = list(self._st_embeddings.keys())
            emb_matrix = torch.stack([self._st_embeddings[key] for key in keys])
            scores = util.cos_sim(q_emb, emb_matrix)[0].tolist()

            ranked = sorted(zip(keys, scores), key=lambda item: item[1], reverse=True)[:top_k]
            return [
                (key, score, excerpt(self._content_cache.get(key, ""), tokens))
                for key, score in ranked
            ]
        except Exception as exc:
            if self._log:
                self._log.error("ST", f"ST search failed, falling back to lexical search: {exc}")
            return self._index.search(query, top_k)

    def chunk_span(self, key: str) -> tuple[int, int] | None:
        doc_name = self._chunk_to_doc.get(key, "")
        full = self._doc_full_content.get(doc_name, "")
        chunk = self._content_cache.get(key, "")
        if not full or not chunk:
            return None

        pos = full.find(chunk)
        if pos != -1:
            return (pos, pos + len(chunk))

        anchor = chunk.strip()[:200]
        if not anchor:
            return None
        pos = full.find(anchor)
        if pos == -1:
            return None
        return (pos, min(len(full), pos + len(anchor)))

    def paragraph_excerpt(self, key: str, fallback: str) -> str:
        doc_name = self._chunk_to_doc.get(key, "")
        full = self._doc_full_content.get(doc_name, "")
        span = self.chunk_span(key)
        if not full or span is None:
            return fallback

        start, end = span
        para_start = full.rfind("\n\n", 0, start)
        para_start = 0 if para_start == -1 else para_start + 2
        para_end = full.find("\n\n", end)
        para_end = len(full) if para_end == -1 else para_end

        value = re.sub(r"\n{3,}", "\n\n", full[para_start:para_end]).strip()
        return value or fallback

    def extended_excerpt(self, key: str, fallback: str) -> str:
        doc_name = self._chunk_to_doc.get(key, "")
        full = self._doc_full_content.get(doc_name, "")
        if not full:
            return fallback

        span = self.chunk_span(key)
        if span is None:
            return fallback

        start = max(0, span[0] - int(self.config.context.before_chars))
        end = min(len(full), span[1] + int(self.config.context.after_chars))
        value = re.sub(r"\n{3,}", "\n\n", full[start:end]).strip()
        return ("…" if start > 0 else "") + value + ("…" if end < len(full) else "")

    def build_global_toc(self) -> str:
        max_chars = 800
        lines: list[str] = []
        for doc_name, content in self._doc_full_content.items():
            basename = os.path.basename(doc_name)
            headings = re.findall(r"^(#{1,3})\s+(.+)", content, re.MULTILINE)
            if not headings:
                continue
            parts = [f"[{basename}]"]
            for hashes, title in headings[:8]:
                indent = "  " * (len(hashes) - 1)
                parts.append(f"{indent}{title.strip()}")
            lines.append("\n".join(parts))

        result = "\n\n".join(lines)
        if len(result) > max_chars:
            result = result[:max_chars] + "…"
        return result
