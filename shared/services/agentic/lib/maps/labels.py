"""Label helpers for map-shaped workflows."""
from __future__ import annotations

import re
import unicodedata

from shared.services.agentic.graph_closure import label_fingerprint

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
_STOPWORDS = {
    "aber", "als", "also", "am", "an", "and", "auch", "auf", "aus", "bei", "by",
    "das", "dem", "den", "der", "des", "die", "dies", "doch", "ein", "eine", "einer",
    "einem", "einen", "einerseits", "eines", "er", "es", "for", "from", "hat", "haben",
    "ich", "im", "in", "ist", "it", "mit", "nicht", "of", "on", "oder", "sie", "so",
    "the", "to", "und", "von", "was", "we", "wie", "with", "zu", "zum", "zur",
}
_META_LABELS = {
    "children", "nodes", "edges", "label", "labels", "relation", "relations", "source",
    "target", "text", "name", "title", "node", "graph", "mindmap", "format",
}


def ascii_fold(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(ch for ch in raw if not unicodedata.combining(ch))


def word_tokens(text: str, *, min_letters: int = 3) -> list[str]:
    out: list[str] = []
    for token in _WORD_RE.findall(ascii_fold(text)):
        tok = str(token or "").strip()
        if len(tok) < max(1, int(min_letters)):
            continue
        if tok in _STOPWORDS:
            continue
        out.append(tok)
    return out


def contains_word_like_text(text: str, *, min_letters: int = 3) -> bool:
    return bool(word_tokens(text, min_letters=min_letters))


def slug(text: str, *, default: str = "node") -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", ascii_fold(text)).strip("-")
    return clean or str(default or "node")


def clean_label(text: str, *, min_word_letters: int = 3, max_chars: int = 80) -> str:
    value = str(text or "").replace("\\n", " ").replace("\\t", " ").strip()
    value = value.strip("` ").strip("\"'").strip()
    value = value.rstrip(",;:").strip()
    value = re.sub(r"^#{1,6}\s+", "", value)
    value = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return ""
    if ascii_fold(value) in _META_LABELS:
        return ""
    if not contains_word_like_text(value, min_letters=min_word_letters):
        return ""
    return value[: max(1, int(max_chars))].strip()


def labels_equivalent(left: str, right: str) -> bool:
    left_clean = clean_label(left, min_word_letters=1, max_chars=200)
    right_clean = clean_label(right, min_word_letters=1, max_chars=200)
    if not left_clean or not right_clean:
        return False
    if left_clean.casefold() == right_clean.casefold():
        return True
    return tuple(label_fingerprint(left_clean)) == tuple(label_fingerprint(right_clean))


def dedupe_labels(labels: list[str]) -> list[str]:
    out: list[str] = []
    for item in list(labels or []):
        label = clean_label(item)
        if not label:
            continue
        if any(labels_equivalent(label, existing) for existing in out):
            continue
        out.append(label)
    return out


def choose_root_label(*, query: str, title: str, fallback: str = "Mindmap") -> str:
    for candidate in (title, query, fallback):
        label = clean_label(candidate, min_word_letters=2, max_chars=100)
        if label:
            return label
    return "Mindmap"
