"""Core text normalization and candidate heuristics for fact-checking."""
from __future__ import annotations

import html
import re

def normalize_match_text(text: str) -> str:
    value = html.unescape(str(text or ""))
    value = re.sub(r"(?is)<\s*/?\s*br\s*/?\s*>", " ", value)
    value = value.casefold()
    value = value.replace("\u00ad", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value

def normalize_match_text_plain(text: str) -> str:
    value = normalize_match_text(text)
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value

def clean_factcheck_cell(text: str) -> str:
    value = html.unescape(str(text or ""))
    value = re.sub(r"(?is)<\s*/?\s*br\s*/?\s*>", " ", value)
    value = re.sub(r"(?is)<[^>]+>", " ", value)
    value = value.strip()
    value = re.sub(r"^`+|`+$", "", value)
    value = value.strip(" \"'„“‚‘’”«»")
    value = re.sub(r"\s+", " ", value).strip()
    return value

def contains_text(haystack: str, needle: str) -> bool:
    hay = normalize_match_text(haystack)
    nee = normalize_match_text(needle)
    if len(nee) >= 6 and nee in hay:
        return True
    hay_plain = normalize_match_text_plain(haystack)
    nee_plain = normalize_match_text_plain(needle)
    return len(nee_plain) >= 6 and nee_plain in hay_plain

def token_overlap(a: str, b: str) -> float:
    left = {word for word in normalize_match_text_plain(a).split() if len(word) >= 4}
    right = {word for word in normalize_match_text_plain(b).split() if len(word) >= 4}
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, min(len(left), len(right)))

def evidence_in_source_texts(
    evidence: str,
    source_texts: list[str],
) -> tuple[bool, float]:
    snippet = clean_factcheck_cell(evidence)
    if not snippet or not source_texts:
        return False, 0.0

    best_score = 0.0
    for src in source_texts:
        source_text = str(src or "")
        if not source_text:
            continue
        if contains_text(source_text, snippet):
            return True, 1.0
        score = token_overlap(source_text, snippet)
        if score > best_score:
            best_score = score

    fuzzy_threshold = 0.62 if len(snippet) >= 80 else 0.70
    return best_score >= fuzzy_threshold, best_score

def split_sentences_for_facts(text: str) -> list[str]:
    if not text:
        return []

    prepared = html.unescape(str(text or ""))
    prepared = re.sub(r"(?is)<\s*/?\s*br\s*/?\s*>", "\n", prepared)
    lines = prepared.replace("\r", "\n").splitlines()
    blocks: list[str] = []
    current: list[str] = []

    def flush_current():
        if current:
            block = re.sub(r"\s+", " ", " ".join(current)).strip()
            if block:
                blocks.append(block)
            current.clear()

    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            flush_current()
            continue
        if line.startswith("#") or line.startswith("|"):
            flush_current()
            continue
        if re.match(r"^(?:[-*•]+|\d+[\.\)])\s+\S", line):
            flush_current()
            bullet = re.sub(r"^(?:[-*•]+|\d+[\.\)])\s*", "", line).strip()
            if bullet:
                blocks.append(bullet)
            continue
        current.append(line)
    flush_current()

    out: list[str] = []
    sentence_split = re.compile(r"(?<=[.!?])\s+")
    for block in blocks:
        for part in sentence_split.split(block):
            sentence = part.strip(" \t-")
            if sentence:
                out.append(sentence)
    return out

def _line_facts_for_target_text(text: str) -> list[str]:
    """Build robust, order-preserving line-based fact candidates."""
    out: list[str] = []
    if not text:
        return out

    prepared = html.unescape(str(text or ""))
    prepared = re.sub(r"(?is)<\s*/?\s*br\s*/?\s*>", "\n", prepared)
    for raw_line in prepared.replace("\r", "\n").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if line.startswith("#"):
            continue

        # Ignore markdown table rows entirely to avoid layout artifacts as "facts".
        if line.startswith("|") and line.endswith("|"):
            continue

        is_bullet = bool(re.match(r"^(?:[-*•]+|\d+[\.\)])\s+\S", line))
        line = re.sub(r"^(?:[-*•]+|\d+[\.\)])\s*", "", line).strip()
        if not line:
            continue

        if len(line) < 2:
            continue
        if not is_bullet and not re.search(r"[.!?…]\s*$", line):
            # Normal line fallback only if it already looks like a complete sentence.
            continue
        out.append(line)

    return out

def suggest_fact_limit(target_text: str) -> int:
    sentences = [
        sentence
        for sentence in split_sentences_for_facts(target_text)
        if len(sentence) >= 12
    ]
    bullet_count = len(
        re.findall(r"(?m)^\s*(?:[-*•]+|\d+[\.\)])\s+\S+", target_text or "")
    )
    base = len(sentences) + bullet_count
    if base <= 0:
        words = len(re.findall(r"\w+", target_text or "", flags=re.UNICODE))
        if words <= 0:
            return 24
        base = max(24, words // 6)
    limit = int(base * 1.15) + 4
    return max(24, min(180, limit))

def is_fact_from_target_text(fact: str, target_text: str) -> bool:
    if not fact or not target_text:
        return False
    if contains_text(target_text, fact):
        return True

    fact_tokens = [
        word for word in normalize_match_text_plain(fact).split()
        if len(word) >= 4
    ]
    if len(fact_tokens) < 2:
        return False

    target_tokens = {
        word for word in normalize_match_text_plain(target_text).split()
        if len(word) >= 4
    }
    if not target_tokens:
        return False

    matched = sum(1 for token in fact_tokens if token in target_tokens)
    ratio = matched / max(1, len(fact_tokens))

    if len(fact_tokens) <= 4:
        return matched >= 2 and ratio >= 0.60
    if matched >= 3 and ratio >= 0.52:
        return True
    if matched >= 5 and ratio >= 0.42:
        return True
    return False

def heuristic_fact_candidates_from_text(text: str) -> list[str]:
    out: list[str] = []
    if not text:
        return out

    seen: set[str] = set()

    def add_candidate(candidate: str):
        clean = clean_factcheck_cell(candidate)
        if len(clean) < 6:
            return
        key = normalize_match_text_plain(clean)
        if len(key) < 5 or key in seen:
            return
        seen.add(key)
        out.append(clean)

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^(?:[-*•]+|\d+[\.\)])\s+\S", stripped):
            bullet = re.sub(r"^(?:[-*•]+|\d+[\.\)])\s*", "", stripped).strip()
            if bullet:
                add_candidate(bullet)

    for sentence in split_sentences_for_facts(text):
        sent = re.sub(r"\s+", " ", sentence).strip()
        if not sent:
            continue
        if len(sent) <= 220:
            add_candidate(sent)
            continue

        parts = re.split(r"\s*;\s+|\s+(?:und|oder|sowie|wobei)\s+", sent)
        added = False
        for part in parts:
            clean = part.strip(" ,-\t")
            if len(clean) >= 20:
                add_candidate(clean)
                added = True
        if not added:
            add_candidate(sent)

    return out

__all__ = [
    "normalize_match_text",
    "normalize_match_text_plain",
    "clean_factcheck_cell",
    "contains_text",
    "token_overlap",
    "evidence_in_source_texts",
    "split_sentences_for_facts",
    "_line_facts_for_target_text",
    "suggest_fact_limit",
    "is_fact_from_target_text",
    "heuristic_fact_candidates_from_text",
]
