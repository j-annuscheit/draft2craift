"""Fact-check parsing, normalization, and validation helpers."""
from __future__ import annotations

from .utils_parts.candidate_parse import (
    _collect_llm_fact_strings,
    _extract_json_payload,
    _looks_like_fact_fragment,
    _normalize_fact_list,
    parse_fact_candidates,
)
from .utils_parts.source_chunks import (
    _fact_token_set,
    build_source_chunks,
    chunk_source_text,
    norm_source_name,
    select_evidence_snippet,
    source_text_for_label,
)
from .utils_parts.text_ops import (
    _line_facts_for_target_text,
    clean_factcheck_cell,
    contains_text,
    evidence_in_source_texts,
    heuristic_fact_candidates_from_text,
    is_fact_from_target_text,
    normalize_match_text,
    normalize_match_text_plain,
    split_sentences_for_facts,
    suggest_fact_limit,
    token_overlap,
)
from .utils_parts.verification import (
    compose_fact_check_markdown,
    fact_status_icon,
    md_escape_cell,
    parse_factcheck_rows,
    parse_single_fact_verification,
    validate_fact_check_response,
)

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
    "_extract_json_payload",
    "_collect_llm_fact_strings",
    "_looks_like_fact_fragment",
    "_normalize_fact_list",
    "parse_fact_candidates",
    "norm_source_name",
    "source_text_for_label",
    "_fact_token_set",
    "chunk_source_text",
    "build_source_chunks",
    "select_evidence_snippet",
    "parse_single_fact_verification",
    "fact_status_icon",
    "md_escape_cell",
    "compose_fact_check_markdown",
    "parse_factcheck_rows",
    "validate_fact_check_response",
]
