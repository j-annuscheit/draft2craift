"""Source preparation helpers for map workflows."""
from __future__ import annotations

import re
from typing import Any

from .labels import clean_label, word_tokens

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MD_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<label>.+?)\s*$")
_NUM_HEADING_RE = re.compile(r"^(?P<num>\d+(?:\.\d+){0,4})\s+(?P<label>.+?)\s*$")


def normalize_context(text: str) -> dict[str, Any]:
    raw = str(text or "")
    removed_control_chars = len(_CONTROL_RE.findall(raw))
    normalized = _CONTROL_RE.sub("", raw)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
    collapsed_spaces = sum(1 for line in lines if "  " in line)
    normalized = "\n".join(lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return {
        "context_text": raw,
        "normalized_text": normalized,
        "context_chars": len(raw),
        "normalized_chars": len(normalized),
        "cleanup": {
            "removed_control_chars": removed_control_chars,
            "collapsed_spaces": collapsed_spaces,
        },
    }


def segment_context(text: str, *, max_segment_chars: int = 700) -> dict[str, Any]:
    normalized = str(text or "").strip()
    blocks = [block.strip() for block in re.split(r"\n\s*\n", normalized) if block.strip()]
    segments: list[dict[str, Any]] = []
    idx = 1
    for block in blocks:
        chunk = str(block)
        while len(chunk) > max_segment_chars:
            cut = chunk[:max_segment_chars]
            split_at = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(", "))
            if split_at < max_segment_chars // 2:
                split_at = max_segment_chars
            piece = chunk[:split_at].strip()
            if piece:
                segments.append({"segment_id": f"seg-{idx:03d}", "text": piece})
                idx += 1
            chunk = chunk[split_at:].strip()
        if chunk:
            segments.append({"segment_id": f"seg-{idx:03d}", "text": chunk})
            idx += 1
    return {"segments": segments, "segment_count": len(segments)}


def extract_outline(*, normalized_text: str, segments: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [str(line or "").rstrip() for line in str(normalized_text or "").splitlines()]
    title = ""
    sections: list[dict[str, Any]] = []
    for line in lines:
        clean = clean_label(line, min_word_letters=2, max_chars=120)
        if clean:
            title = clean
            break
    for idx, line in enumerate(lines, 1):
        stripped = str(line or "").strip()
        if not stripped:
            continue
        level = 0
        label = ""
        md = _MD_HEADING_RE.match(stripped)
        if md is not None:
            level = len(str(md.group("marks") or "#"))
            label = clean_label(md.group("label"), min_word_letters=2, max_chars=90)
        else:
            numbered = _NUM_HEADING_RE.match(stripped)
            if numbered is not None:
                level = str(numbered.group("num") or "1").count(".") + 1
                label = clean_label(numbered.group("label"), min_word_letters=2, max_chars=90)
            elif len(stripped) <= 80 and stripped == stripped.title() and not stripped.endswith((".", ":", ";")):
                level = 1
                label = clean_label(stripped, min_word_letters=2, max_chars=90)
        if not label:
            continue
        sections.append(
            {
                "section_id": f"sec-{idx:03d}",
                "label": label,
                "level": max(1, int(level or 1)),
            }
        )
    if not sections:
        for idx, segment in enumerate(list(segments or [])[:6], 1):
            label = clean_label(str(segment.get("text", "") or "").split(".", 1)[0], min_word_letters=2, max_chars=72)
            if not label:
                continue
            sections.append({"section_id": f"sec-fallback-{idx:02d}", "label": label, "level": 1})
    return {"title": title, "sections": sections}


def score_focus_sections(
    *,
    query: str,
    segments: list[dict[str, Any]],
    outline: dict[str, Any],
    max_sections: int = 6,
    max_segments: int = 10,
) -> dict[str, Any]:
    query_terms = set(word_tokens(query, min_letters=3))
    scored_sections: list[tuple[int, str]] = []
    for section in list(outline.get("sections", []) or []):
        label = str(section.get("label", "") or "")
        overlap = len(query_terms & set(word_tokens(label, min_letters=3)))
        scored_sections.append((overlap, str(section.get("section_id", "") or "")))
    scored_sections.sort(key=lambda item: (-item[0], item[1]))
    top_sections = [item[1] for item in scored_sections[:max_sections] if item[1]]

    scored_segments: list[tuple[int, str]] = []
    for segment in list(segments or []):
        seg_id = str(segment.get("segment_id", "") or "")
        text = str(segment.get("text", "") or "")
        score = len(query_terms & set(word_tokens(text, min_letters=3)))
        if score <= 0 and not query_terms:
            score = 1
        scored_segments.append((score, seg_id))
    scored_segments.sort(key=lambda item: (-item[0], item[1]))
    top_segments = [item[1] for item in scored_segments[:max_segments] if item[1] and item[0] > 0]
    return {
        "query": str(query or "").strip(),
        "query_terms": sorted(query_terms),
        "top_sections": top_sections,
        "top_segments": top_segments,
    }
