from __future__ import annotations

import re
from typing import Optional

_MD_HEADING = re.compile(r"^#{1,6}\s")
_MD_CODE_FENCE = re.compile(r"^```")

_HF_LEAD_NUM_RE = re.compile(
    r"^\s*(?:\d+(?:\s*[.\-:)]\s*\d+)*\s*[.\-:)]?\s+)+",
    re.IGNORECASE,
)
_HF_PAGE_INLINE_RE = re.compile(
    r"\b(?:seite|page|pag(?:e|ina)|p\.?)\s*\d+(?:\s*(?:/|\\|\||\-|–)\s*\d+)?\b",
    re.IGNORECASE,
)
_HF_PAGE_RATIO_RE = re.compile(r"\b\d+\s*(?:/|\\|\||\-|–)\s*\d+\b")
_HF_STANDALONE_NUM_RE = re.compile(r"\b\d+\b")
_HF_NON_WORD_RE = re.compile(r"[^\w\s<>]", flags=re.UNICODE)


def normalize_heading_for_hf(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text or "").strip().casefold()
    if not normalized:
        return ""
    normalized = _HF_LEAD_NUM_RE.sub("", normalized)
    normalized = _HF_NON_WORD_RE.sub(" ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def extract_heading_terms_for_hf(markdown: str) -> list[str]:
    """Extract normalized markdown heading titles (without leading numbering)."""
    if not markdown:
        return []

    lines = markdown.splitlines()
    first_nonempty = next((i for i, line in enumerate(lines) if line.strip()), 0)
    in_code_fence = False
    terms: list[str] = []

    for index, line in enumerate(lines):
        stripped = line.strip()
        if _MD_CODE_FENCE.match(stripped):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence or not _MD_HEADING.match(line):
            continue

        level = len(line) - len(line.lstrip("#"))
        level = max(1, min(level, 6))
        title = line[level:].strip()
        if not title:
            continue
        if index == first_nonempty and level == 1:
            continue

        normalized = normalize_heading_for_hf(title)
        if len(normalized) >= 3:
            terms.append(normalized)

    seen: set[str] = set()
    output: list[str] = []
    for term in sorted(terms, key=lambda value: (-len(value), value)):
        if term in seen:
            continue
        seen.add(term)
        output.append(term)
    return output


def build_detection_markdown(path: str, pages: Optional[list[int]] = None) -> str:
    """Generate a raw markdown pass used only for heading extraction in H/F detection."""
    try:
        import pymupdf4llm  # type: ignore
    except Exception:
        return ""

    kwargs = {
        "pages": pages,
        "margins": 0,
        "page_chunks": True,
        "show_progress": False,
    }

    try:
        chunks = pymupdf4llm.to_markdown(path, **kwargs)
    except TypeError:
        try:
            chunks = pymupdf4llm.to_markdown(
                path,
                pages=pages,
                margins=0,
                page_chunks=True,
                show_progress=False,
            )
        except Exception:
            return ""
    except Exception:
        return ""

    if isinstance(chunks, str):
        return chunks
    if isinstance(chunks, dict):
        chunks = [chunks]

    parts: list[str] = []
    for chunk in chunks or []:
        if isinstance(chunk, str):
            text = chunk.strip()
        elif isinstance(chunk, dict):
            text = str(chunk.get("text", "")).strip()
        else:
            text = str(chunk).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def canonicalize_hf_candidate(text: str, heading_terms: list[str]) -> tuple[str, bool, bool]:
    """Canonicalize candidate text: page numbers -> <PAGE>, heading names -> <HEADING>."""
    normalized = re.sub(r"\s+", " ", text or "").strip().casefold()
    if not normalized:
        return "", False, False

    normalized = normalized.replace("–", "-").replace("—", "-")

    had_page = bool(_HF_PAGE_INLINE_RE.search(normalized) or _HF_PAGE_RATIO_RE.search(normalized))
    normalized = _HF_PAGE_INLINE_RE.sub(" <PAGE> ", normalized)
    normalized = _HF_PAGE_RATIO_RE.sub(" <PAGE> ", normalized)

    normalized = _HF_NON_WORD_RE.sub(" ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    had_heading = False
    for heading in heading_terms:
        if len(heading) < 4:
            continue
        if heading in normalized:
            normalized = normalized.replace(heading, " <HEADING> ")
            had_heading = True

    normalized = _HF_STANDALONE_NUM_RE.sub(" ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = normalized.replace("<page>", "<PAGE>").replace("<heading>", "<HEADING>")

    if normalized:
        return normalized, had_page, had_heading
    if had_page and had_heading:
        return "<HEADING> <PAGE>", True, True
    if had_page:
        return "<PAGE>", True, False
    if had_heading:
        return "<HEADING>", False, True
    return "", False, False
