"""TF-IDF utilities and in-memory index."""
from __future__ import annotations

import math
import re
from collections import Counter
from math import log

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
