"""Excerpt helpers for retrieval output."""
from __future__ import annotations

import re

def excerpt(content: str, tokens: list[str], window: int = 400) -> str:
    """Extract a relevant passage centered on the first token match."""
    body = str(content or "")
    if not body.strip():
        return ""

    low = body.lower()
    pos: int | None = None
    for token in tokens:
        found = low.find(token)
        if found != -1:
            pos = found
            break

    if pos is None:
        snippet = re.sub(r"\n{3,}", "\n\n", body[:window]).strip()
        if not snippet:
            snippet = body.strip()[:window]
        return snippet + ("…" if len(body) > window else "")

    half = window // 2
    start = max(0, pos - half)
    end = min(len(body), pos + half)
    if start == 0:
        end = min(len(body), window)
    if end == len(body):
        start = max(0, len(body) - window)

    snippet = re.sub(r"\n{3,}", "\n\n", body[start:end]).strip()
    if not snippet:
        snippet = body.strip()[:window]
        return snippet + ("…" if len(body) > window else "")

    return ("…" if start > 0 else "") + snippet + ("…" if end < len(body) else "")


def excerpt_at(content: str, match_start: int, window: int = 400) -> str:
    """Extract a passage centered around an absolute character position."""
    body = str(content or "")
    half = window // 2
    start = max(0, int(match_start) - half)
    end = min(len(body), int(match_start) + half)
    if start == 0:
        end = min(len(body), window)
    if end == len(body):
        start = max(0, len(body) - window)

    snippet = re.sub(r"\n{3,}", "\n\n", body[start:end]).strip()
    if not snippet:
        snippet = body.strip()[:window]
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(body) else "")
