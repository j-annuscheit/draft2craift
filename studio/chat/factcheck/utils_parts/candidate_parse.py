"""LLM-response parsing and fact candidate extraction helpers."""
from __future__ import annotations

import html
import json
import re

from .text_ops import (
    _line_facts_for_target_text,
    clean_factcheck_cell,
    contains_text,
    heuristic_fact_candidates_from_text,
    normalize_match_text_plain,
    split_sentences_for_facts,
    suggest_fact_limit,
)

def _extract_json_payload(raw: str) -> object | None:
    text = html.unescape(str(raw or "")).strip()
    if not text:
        return None

    # Prefer fenced JSON block if present.
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidate = fenced.group(1).strip() if fenced else text

    try:
        return json.loads(candidate)
    except Exception:
        pass

    # Try to recover the first JSON array/object from mixed text.
    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        match = re.search(pattern, candidate)
        if not match:
            continue
        chunk = match.group(0)
        try:
            return json.loads(chunk)
        except Exception:
            continue
    return None

def _collect_llm_fact_strings(data: object) -> list[str]:
    out: list[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                for key in ("fact", "claim", "text", "sentence"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        out.append(value)
                        break
        return out

    if isinstance(data, dict):
        for key in ("facts", "claims", "items", "data", "sentences"):
            value = data.get(key)
            if isinstance(value, list):
                out.extend(_collect_llm_fact_strings(value))
                if out:
                    return out
    return out

def _looks_like_fact_fragment(text: str) -> bool:
    value = clean_factcheck_cell(text)
    if not value:
        return True
    low = value.casefold()
    if re.fullmatch(r"[-–—_=~*#.`:;/\\|+\s]+", value):
        return True
    if re.fullmatch(r"(?:col|column)\s*\d+", low):
        return True
    if re.fullmatch(r"item\s*\d+", low):
        return True
    if low in {"beispiele:", "example:", "happy writing.", "view.", "context."}:
        return True

    alpha_words = re.findall(r"[^\W\d_]{2,}", value, flags=re.UNICODE)
    if len(alpha_words) <= 1 and len(value) <= 24:
        return True
    if len(value) < 10 and len(alpha_words) < 2:
        return True
    if value.endswith(":"):
        return True
    return False

def _normalize_fact_list(candidates: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        clean = clean_factcheck_cell(candidate)
        if _looks_like_fact_fragment(clean):
            continue
        key = normalize_match_text_plain(clean)
        if len(key) < 4 or key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out

def parse_fact_candidates(response: str, target_text: str) -> list[str]:
    parsed = _extract_json_payload(response)
    llm_candidates = _normalize_fact_list(_collect_llm_fact_strings(parsed))
    if llm_candidates:
        return llm_candidates

    sentence_facts = [
        clean_factcheck_cell(sentence)
        for sentence in split_sentences_for_facts(target_text)
        if len(clean_factcheck_cell(sentence)) >= 2
    ]
    line_facts = [
        clean_factcheck_cell(line)
        for line in _line_facts_for_target_text(target_text)
        if len(clean_factcheck_cell(line)) >= 2
    ]

    # Fact = sentence. Sentence splitting is the primary strategy.
    # The line fallback only adds additional bullet/full lines
    # that are not already covered by sentence splitting.
    if sentence_facts:
        merged = list(sentence_facts)
        for candidate in line_facts:
            is_duplicate = False
            for existing in merged:
                if contains_text(existing, candidate) or contains_text(candidate, existing):
                    is_duplicate = True
                    break
            if not is_duplicate:
                merged.append(candidate)
        return _normalize_fact_list(merged)
    if line_facts:
        return _normalize_fact_list(line_facts)

    # Fallback for highly unstructured text.
    out: list[str] = []
    max_facts = suggest_fact_limit(target_text)
    for candidate in heuristic_fact_candidates_from_text(target_text):
        clean = clean_factcheck_cell(candidate)
        if len(clean) < 2:
            continue
        out.append(clean)
        if len(out) >= max_facts:
            break

    return _normalize_fact_list(out)

__all__ = [
    "_extract_json_payload",
    "_collect_llm_fact_strings",
    "_looks_like_fact_fragment",
    "_normalize_fact_list",
    "parse_fact_candidates",
]
