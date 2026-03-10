"""Source normalization, chunking and evidence snippet helpers."""
from __future__ import annotations

import os
import re

from .text_ops import normalize_match_text_plain

def norm_source_name(name: str) -> str:
    value = os.path.basename(str(name or "").strip())
    value = re.sub(r"\s+", " ", value).strip().casefold()
    return value

def source_text_for_label(label: str, sources: list[tuple[str, str]]) -> str:
    want = norm_source_name(label)
    if not want:
        return ""
    for name, text in sources:
        got = norm_source_name(name)
        if not got:
            continue
        if got == want or got in want or want in got:
            return str(text or "")
    return ""

def _fact_token_set(text: str) -> set[str]:
    return {
        tok
        for tok in normalize_match_text_plain(text).split()
        if len(tok) >= 4
    }

def chunk_source_text(
    text: str,
    *,
    chunk_size: int = 900,
    chunk_overlap: int = 160,
) -> list[str]:
    src = str(text or "").replace("\r\n", "\n").strip()
    if not src:
        return []

    blocks = [b.strip() for b in re.split(r"\n{2,}", src) if b.strip()]
    if not blocks:
        blocks = [src]

    chunks: list[str] = []
    i = 0
    while i < len(blocks):
        window: list[str] = []
        total = 0
        j = i
        while j < len(blocks):
            block = blocks[j]
            block_len = len(block)
            if window and total + block_len + 2 > chunk_size:
                break
            if block_len > chunk_size and not window:
                start = 0
                while start < block_len:
                    end = min(block_len, start + chunk_size)
                    piece = block[start:end].strip()
                    if piece:
                        chunks.append(piece)
                    if end >= block_len:
                        break
                    start = max(start + 1, end - max(0, chunk_overlap))
                j += 1
                total = 0
                window = []
                break
            window.append(block)
            total += block_len + 2
            j += 1

        if window:
            chunks.append("\n\n".join(window))
            if chunk_overlap > 0 and len(window) > 1:
                overlap_chars = 0
                keep = 0
                for block in reversed(window):
                    overlap_chars += len(block) + 2
                    keep += 1
                    if overlap_chars >= chunk_overlap:
                        break
                i += max(1, len(window) - keep)
            else:
                i = j
        elif j <= i:
            i += 1
        else:
            i = j

    return chunks

def build_source_chunks(
    sources: list[tuple[str, str]],
    *,
    chunk_size: int = 900,
    chunk_overlap: int = 160,
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name, text in sources:
        clean_name = str(name or "").strip() or "Quelle"
        for chunk in chunk_source_text(
            str(text or ""),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ):
            clean_chunk = str(chunk or "").strip()
            if clean_chunk:
                out.append((clean_name, clean_chunk))
    return out

def select_evidence_snippet(fact: str, chunk: str, *, max_chars: int = 220) -> str:
    text = str(chunk or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    fact_tokens = _fact_token_set(fact)
    best = ""
    best_score = 0.0
    candidates = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", text)
        if part.strip()
    ]
    for cand in candidates:
        cand_tokens = _fact_token_set(cand)
        if not cand_tokens or not fact_tokens:
            continue
        score = len(cand_tokens & fact_tokens) / max(1, len(fact_tokens))
        if score > best_score:
            best = cand
            best_score = score

    if best and best_score >= 0.20:
        snippet = best
    else:
        low_text = text.casefold()
        pos = -1
        for tok in sorted(fact_tokens, key=len, reverse=True):
            pos = low_text.find(tok)
            if pos >= 0:
                break
        if pos < 0:
            snippet = text[:max_chars]
        else:
            half = max_chars // 2
            start = max(0, pos - half)
            end = min(len(text), pos + half)
            if start == 0:
                end = min(len(text), max_chars)
            if end >= len(text):
                start = max(0, len(text) - max_chars)
            snippet = text[start:end]
            if start > 0:
                snippet = "…" + snippet
            if end < len(text):
                snippet = snippet + "…"

    snippet = re.sub(r"\s+", " ", snippet).strip()
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars].rstrip() + " …"
    return snippet or ""

__all__ = [
    "norm_source_name",
    "source_text_for_label",
    "_fact_token_set",
    "chunk_source_text",
    "build_source_chunks",
    "select_evidence_snippet",
]
