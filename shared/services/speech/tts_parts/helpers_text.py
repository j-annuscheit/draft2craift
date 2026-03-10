"""Text normalization and chunking helpers for TTS."""
from __future__ import annotations

import re

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKDOWN_PREFIX_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)"
)
_TRAILING_PUNCT_RE = re.compile(r"[.!?;:]\Z")
_WHITESPACE_RE = re.compile(r"\s+")
_SPEECH_SPLIT_RE = re.compile(r"\n{2,}|(?<=[.!?;:])\s+")

def _build_speech_jobs(
    text: str,
    *,
    pause_ms: int,
    backend: str,
    pause_triggers: str = "",
) -> list[tuple[str, int]]:
    # Keep exactly one queue job to avoid playback restarts that can clip
    # leading words on some audio setups.
    _ = (pause_ms, backend, pause_triggers)
    normalized = _normalize_text_for_tts(text)
    if not normalized:
        return []
    merged = " ".join(_split_text_units(normalized)).strip()
    if not merged:
        return []
    return [(merged, 0)]

def _parse_pause_triggers(raw: str) -> list[str]:
    text = str(raw or "").replace("\r", "")
    if not text.strip():
        return []

    pieces = text.split("|") if "|" in text else text.splitlines()
    parsed: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        token = str(piece or "")
        if not token:
            continue
        if token.strip() == "":
            continue

        # Preserve spaced hyphen trigger intentionally as " - ".
        if token.strip() == "-" and (" " in token):
            token = " - "
        else:
            token = token.strip()
        if not token:
            continue
        if token in seen:
            continue
        seen.add(token)
        parsed.append(token)

    parsed.sort(key=len, reverse=True)
    return parsed

def _split_for_trigger_pauses(text: str, triggers: list[str]) -> list[str]:
    return _split_unit_on_pause_triggers(text, triggers)

def _split_unit_on_pause_triggers(
    unit: str,
    triggers: list[str],
) -> list[str]:
    text = str(unit or "").strip()
    if not text:
        return []
    if not triggers:
        return [text]

    chunks: list[str] = []
    cursor = 0
    limit = len(text)
    while cursor < limit:
        hit_index = -1
        hit_token = ""
        for token in triggers:
            idx = text.find(token, cursor)
            if idx < 0:
                continue
            if (
                hit_index < 0
                or idx < hit_index
                or (idx == hit_index and len(token) > len(hit_token))
            ):
                hit_index = idx
                hit_token = token

        if hit_index < 0:
            tail = text[cursor:].strip()
            if tail:
                chunks.append(tail)
            break

        end = hit_index + len(hit_token)
        part = text[cursor:end].strip()
        if part:
            chunks.append(part)
        cursor = end

    return chunks or [text]

def _normalize_text_for_tts(text: str) -> str:
    raw = (
        str(text or "")
        .replace("\u2029", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    if not raw.strip():
        return ""

    lines: list[str] = []
    in_code_block = False
    for line in raw.split("\n"):
        clean = line.strip()
        if clean.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if not clean:
            lines.append("")
            continue

        clean = _MARKDOWN_LINK_RE.sub(r"\1", clean)
        clean = _MARKDOWN_PREFIX_RE.sub("", clean).strip()
        clean = clean.replace("`", "")
        clean = clean.replace("*", " ")
        clean = clean.replace("_", " ")
        clean = clean.strip("|")
        clean = clean.replace("|", ", ")
        clean = _WHITESPACE_RE.sub(" ", clean).strip()
        if not clean:
            continue
        if not _TRAILING_PUNCT_RE.search(clean):
            clean = f"{clean}."
        lines.append(clean)

    text_out = "\n".join(lines).strip()
    if not text_out:
        return ""
    return re.sub(r"\n{3,}", "\n\n", text_out)

def _split_text_units(text: str) -> list[str]:
    units: list[str] = []
    for part in _SPEECH_SPLIT_RE.split(text):
        clean = _WHITESPACE_RE.sub(" ", str(part or "")).strip(" ,")
        if not clean:
            continue
        if not _TRAILING_PUNCT_RE.search(clean):
            clean = f"{clean}."
        units.append(clean)
    return units

def _merge_units(
    units: list[str],
    *,
    target_chars: int,
    hard_max_chars: int,
) -> list[str]:
    chunks: list[str] = []
    current = ""
    for unit in units:
        for piece in _split_long_unit(unit, max_chars=hard_max_chars):
            if not current:
                current = piece
                continue
            proposed = f"{current} {piece}"
            if len(proposed) <= target_chars:
                current = proposed
            else:
                chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks

def _split_long_unit(unit: str, *, max_chars: int) -> list[str]:
    clean = str(unit or "").strip()
    if not clean:
        return []
    if len(clean) <= max_chars:
        return [clean]

    chunks: list[str] = []
    current = ""
    for fragment in re.split(r"(?<=,)\s+", clean):
        frag = str(fragment or "").strip()
        if not frag:
            continue
        if len(frag) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_words(frag, max_chars=max_chars))
            continue
        if not current:
            current = frag
            continue
        proposed = f"{current} {frag}"
        if len(proposed) <= max_chars:
            current = proposed
        else:
            chunks.append(current)
            current = frag

    if current:
        chunks.append(current)
    return chunks or _split_words(clean, max_chars=max_chars)

def _split_words(text: str, *, max_chars: int) -> list[str]:
    words = str(text or "").split()
    if not words:
        return []

    chunks: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
            continue
        proposed = f"{current} {word}"
        if len(proposed) <= max_chars:
            current = proposed
        else:
            chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks

__all__ = [
    "_build_speech_jobs",
    "_parse_pause_triggers",
    "_split_for_trigger_pauses",
    "_split_unit_on_pause_triggers",
    "_normalize_text_for_tts",
    "_split_text_units",
    "_merge_units",
    "_split_long_unit",
    "_split_words",
]
