"""Utilities for canvas-selection rewrite extraction and validation."""
from __future__ import annotations

import re


def clean_rewrite_block(raw: str) -> str:
    """Normalize a rewrite block and strip optional wrapper tags."""
    text = (raw or "").strip()
    if not text:
        return ""

    match = re.search(
        r"<\s*revised_text\s*>\s*([\s\S]*?)\s*<\s*/\s*revised_text\s*>",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        text = (match.group(1) or "").strip()
    else:
        lines = text.splitlines()
        if lines and re.fullmatch(
            r"\s*<\s*revised_text\s*>\s*", lines[0], flags=re.IGNORECASE
        ):
            lines = lines[1:]
        if lines and re.fullmatch(
            r"\s*<\s*/\s*revised_text\s*>\s*", lines[-1], flags=re.IGNORECASE
        ):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    folded = text.casefold()
    if folded in {"<revised_text>", "</revised_text>", "..."}:
        return ""
    if not text:
        return ""
    return text


def _extract_legacy_rewrite(response: str) -> str:
    """
    Backward-compatible extraction for responses without CANVAS_REWRITE wrappers.

    Accepts common legacy patterns like:
    - section headers ("Überarbeiteter Text ...") + fenced code block
    - first fenced block in the response
    """
    text = (response or "").strip()
    if not text:
        return ""

    patterns = (
        r"(?:^|\n)#{2,4}\s*Überarbeiteter Text[^\n]*\n+```[^\n]*\n([\s\S]*?)\n```",
        r"(?:^|\n)#{2,4}\s*Revised Text[^\n]*\n+```[^\n]*\n([\s\S]*?)\n```",
        r"```[^\n]*\n([\s\S]*?)\n```",
    )
    candidates: list[str] = []
    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        for match in matches:
            cleaned = clean_rewrite_block(match)
            if cleaned:
                candidates.append(cleaned)
        if candidates:
            break

    if not candidates:
        return ""
    candidates.sort(key=len, reverse=True)
    return candidates[0]


def extract_canvas_rewrite(response: str, open_tag: str, close_tag: str) -> str:
    """Extract the best rewrite block between open/close tags."""
    pattern = re.escape(open_tag) + r"\s*([\s\S]*?)\s*" + re.escape(close_tag)
    blocks = re.findall(pattern, response or "", flags=re.DOTALL)
    if not blocks:
        return _extract_legacy_rewrite(response)

    cleaned = [clean_rewrite_block(block) for block in blocks]
    cleaned = [value for value in cleaned if value]
    if not cleaned:
        return ""

    cleaned.sort(key=len, reverse=True)
    return cleaned[0]
