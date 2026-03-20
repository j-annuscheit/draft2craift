"""Lexical retrieval utilities and in-memory indexes (TF-IDF / BM25)."""
from __future__ import annotations

import math
import re
from collections import Counter
from math import log
from typing import Any

from shared.services.rag.excerpt import excerpt


def tokenize(text: str) -> list[str]:
    return [token for token in str(text or "").lower().split() if token]


def compute_idf(documents: list[str]) -> dict[str, float]:
    if not documents:
        return {}
    docs_tokens = [set(tokenize(doc)) for doc in documents]
    total = float(len(documents))
    idf: dict[str, float] = {}
    for token_set in docs_tokens:
        for token in token_set:
            idf[token] = idf.get(token, 0.0) + 1.0
    return {token: log((1.0 + total) / (1.0 + count)) + 1.0 for token, count in idf.items()}


def tfidf_score(query: str, document: str, idf: dict[str, float]) -> float:
    query_tokens = tokenize(query)
    if not query_tokens:
        return 0.0
    doc_counts = Counter(tokenize(document))
    doc_len = max(sum(doc_counts.values()), 1)
    score = 0.0
    for token in query_tokens:
        tf = doc_counts.get(token, 0) / doc_len
        score += tf * idf.get(token, 0.0)
    return score


class TFIDFIndex:
    """Lightweight in-memory TF-IDF retrieval engine."""

    def __init__(self):
        self._docs: dict[str, str] = {}
        self._tfidf: dict[str, dict[str, float]] = {}
        self._idf: dict[str, float] = {}

    def add_document(self, key: str, content: str) -> None:
        self._docs[key] = content
        self._rebuild()

    def add_documents_batch(self, docs: dict[str, str]) -> None:
        self._docs.update(docs)
        self._rebuild()

    def remove_document(self, key: str) -> None:
        self._docs.pop(key, None)
        self._rebuild()

    def clear(self) -> None:
        self._docs.clear()
        self._tfidf.clear()
        self._idf.clear()

    @staticmethod
    def tokenize(text: str) -> list[str]:
        return re.findall(r"[^\W\d_]{2,}", str(text or "").lower())

    def _rebuild(self) -> None:
        if not self._docs:
            self._tfidf.clear()
            self._idf.clear()
            return

        doc_tokens = {key: self.tokenize(content) for key, content in self._docs.items()}
        vocab: set[str] = set()
        for tokens in doc_tokens.values():
            vocab.update(tokens)

        n_docs = len(self._docs)
        self._idf = {
            word: math.log((n_docs + 1) / (1 + sum(1 for tokens in doc_tokens.values() if word in tokens))) + 1.0
            for word in vocab
        }

        self._tfidf = {}
        for key, tokens in doc_tokens.items():
            total = max(len(tokens), 1)
            tf = Counter(tokens)
            self._tfidf[key] = {
                word: (count / total) * self._idf.get(word, 0.0)
                for word, count in tf.items()
            }

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float, str]]:
        q_tokens = self.tokenize(query)
        if not q_tokens or not self._tfidf:
            return []

        scores = {
            key: sum(tfidf.get(word, 0.0) for word in q_tokens)
            for key, tfidf in self._tfidf.items()
        }
        ranked = sorted(
            ((key, score) for key, score in scores.items() if score > 0),
            key=lambda item: item[1],
            reverse=True,
        )[:top_k]

        return [(key, score, excerpt(self._docs[key], q_tokens)) for key, score in ranked]

    def dump_state(self) -> dict[str, Any]:
        return {
            "type": "tfidf",
            "docs": dict(self._docs),
            "tfidf": dict(self._tfidf),
            "idf": dict(self._idf),
        }

    def load_state(self, state: dict[str, Any]) -> None:
        self._docs = dict(state["docs"])
        self._tfidf = dict(state["tfidf"])
        self._idf = dict(state["idf"])


class BM25Index:
    """In-memory BM25 lexical retrieval engine."""

    def __init__(self, *, k1: float = 1.2, b: float = 0.75):
        self._docs: dict[str, str] = {}
        self._doc_term_freq: dict[str, Counter[str]] = {}
        self._doc_len: dict[str, int] = {}
        self._doc_freq: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._avgdl: float = 0.0
        self._k1 = float(k1)
        self._b = float(b)

    @property
    def k1(self) -> float:
        return self._k1

    @property
    def b(self) -> float:
        return self._b

    def set_params(self, *, k1: float, b: float) -> None:
        self._k1 = float(k1)
        self._b = float(b)

    def add_document(self, key: str, content: str) -> None:
        self._docs[key] = content
        self._rebuild()

    def add_documents_batch(self, docs: dict[str, str]) -> None:
        self._docs.update(docs)
        self._rebuild()

    def remove_document(self, key: str) -> None:
        self._docs.pop(key, None)
        self._rebuild()

    def clear(self) -> None:
        self._docs.clear()
        self._doc_term_freq.clear()
        self._doc_len.clear()
        self._doc_freq.clear()
        self._idf.clear()
        self._avgdl = 0.0

    @staticmethod
    def tokenize(text: str) -> list[str]:
        return TFIDFIndex.tokenize(text)

    def _rebuild(self) -> None:
        if not self._docs:
            self.clear()
            return

        self._doc_term_freq.clear()
        self._doc_len.clear()
        self._doc_freq.clear()
        self._idf.clear()

        for key, content in self._docs.items():
            tokens = self.tokenize(content)
            tf = Counter(tokens)
            self._doc_term_freq[key] = tf
            self._doc_len[key] = len(tokens)
            for term in tf.keys():
                self._doc_freq[term] = self._doc_freq.get(term, 0) + 1

        n_docs = len(self._docs)
        total_len = sum(self._doc_len.values())
        self._avgdl = (float(total_len) / float(n_docs)) if n_docs > 0 else 0.0

        for term, df in self._doc_freq.items():
            # Robertson/Sparck Jones style IDF; always positive with +1 inside log.
            self._idf[term] = math.log(1.0 + ((n_docs - df + 0.5) / (df + 0.5)))

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float, str]]:
        q_tokens = self.tokenize(query)
        if not q_tokens or not self._docs or self._avgdl <= 0.0:
            return []

        q_counts = Counter(q_tokens)
        scores: dict[str, float] = {}
        for key, tf in self._doc_term_freq.items():
            dl = max(1, int(self._doc_len.get(key, 0)))
            score = 0.0
            norm = (1.0 - self._b) + self._b * (float(dl) / self._avgdl)
            for term, qtf in q_counts.items():
                f = float(tf.get(term, 0))
                if f <= 0.0:
                    continue
                denom = f + self._k1 * norm
                if denom <= 0.0:
                    continue
                term_score = self._idf.get(term, 0.0) * ((f * (self._k1 + 1.0)) / denom)
                score += float(qtf) * term_score
            if score > 0.0:
                scores[key] = score

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
        return [(key, score, excerpt(self._docs[key], q_tokens)) for key, score in ranked]

    def dump_state(self) -> dict[str, Any]:
        return {
            "type": "bm25",
            "docs": dict(self._docs),
            "k1": float(self._k1),
            "b": float(self._b),
        }

    def load_state(self, state: dict[str, Any]) -> None:
        self._docs = dict(state["docs"])
        self._k1 = float(state["k1"])
        self._b = float(state["b"])
        self._rebuild()
