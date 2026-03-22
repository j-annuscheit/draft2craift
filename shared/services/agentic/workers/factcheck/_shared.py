"""Shared helpers for factcheck workers.

The helpers stay local to the factcheck package so the worker modules remain
small and easy to reason about.
"""
from __future__ import annotations

import re

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def split_claims(text: str) -> list[str]:
    out: list[str] = []
    for sent in _SENT_SPLIT_RE.split(str(text or "")):
        item = " ".join(str(sent or "").split()).strip()
        if len(item) < 8:
            continue
        if item and item not in out:
            out.append(item)
    return out
