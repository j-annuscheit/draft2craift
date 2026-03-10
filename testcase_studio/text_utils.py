"""Text and value helpers for Testcase Studio."""
from __future__ import annotations

from typing import Any


def safe_str(value: Any) -> str:
    return str(value or "").strip()


def truncate(text: str, max_len: int = 96) -> str:
    clean = str(text or "").replace("\n", " ").strip()
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1] + "..."


def coerce_int_list(raw: Any) -> list[int]:
    out: list[int] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        try:
            value = int(item)
        except Exception:
            continue
        if value > 0:
            out.append(value)
    return out


def coerce_labels(raw: Any) -> list[str]:
    tokens: list[str] = []
    if isinstance(raw, str):
        for line in raw.splitlines():
            for part in line.split(","):
                text = part.strip()
                if text:
                    tokens.append(text)
    elif isinstance(raw, list):
        for item in raw:
            text = str(item or "").strip()
            if text:
                tokens.append(text)

    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def case_title(case_payload: dict[str, Any]) -> str:
    for key in (
        "prompt",
        "query",
        "target_markdown",
        "pdf",
        "markdown",
        "markdown_text",
    ):
        value = safe_str(case_payload.get(key))
        if value:
            return truncate(value, 120)
    return "(ohne Titel)"
