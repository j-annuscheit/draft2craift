"""Normalization helpers for canvas selection mapping."""
from __future__ import annotations

import re


def normalize_selection_text(text: str) -> str:
    """Normalize Qt and OS newline differences for selection text."""
    return (text or "").replace("\u2029", "\n").replace("\r\n", "\n")


def normalize_markdown_line(line: str) -> str:
    text = (line or "").replace("\xa0", " ").strip()
    if not text:
        return ""
    if re.match(r"^`{3,}.*$", text):
        return ""
    if re.match(r"^[-*_]{3,}\s*$", text):
        return ""
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = re.sub(r"^\s*(?:[-*+]|[•◦▪●]|\d+[.)])\s+", "", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"\\([^\s])", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize_for_match(text: str) -> list[str]:
    """
    Tokenize normalized text for robust HTML->Markdown span mapping.

    This intentionally ignores trailing punctuation differences
    (e.g. "Markdown" vs. "Markdown.").
    """
    source = str(text or "").strip()
    if not source:
        return []
    pattern = r"\w+(?:[+./-]\w+)*"
    return [
        token.casefold()
        for token in re.findall(pattern, source, flags=re.UNICODE)
        if token
    ]
