"""HyDE/query-expansion task methods for ``LLMManager``."""
from __future__ import annotations

import json
import re
from typing import Any

_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*]+|\d+[\.\)])\s*")
_FENCED_REGEX_BLOCK_RE = re.compile(r"```(?:regex|json|text)?\s*([\s\S]*?)```", flags=re.IGNORECASE)
_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")


def _unwrap_matching_quotes(value: str) -> str:
    text = str(value or "").strip()
    if len(text) < 2:
        return text
    if text[0] == text[-1] and text[0] in "\"'`":
        return text[1:-1].strip()
    return text


def _extract_regex_candidates(raw_text: str) -> list[str]:
    text = str(raw_text or "").strip()
    if not text:
        return []
    fenced = _FENCED_REGEX_BLOCK_RE.search(text)
    candidate = str(fenced.group(1) if fenced else text).strip()
    if not candidate:
        return []

    array_match = _JSON_ARRAY_RE.search(candidate)
    if array_match:
        try:
            payload = json.loads(array_match.group(0))
            if isinstance(payload, list):
                out = [str(item).strip() for item in payload if str(item).strip()]
                if out:
                    return out
        except Exception:
            pass

    return [str(line).strip() for line in candidate.splitlines() if str(line).strip()]


def expand_query_tfidf_sync(self, query: str) -> str:
    """HyDE keyword expansion for the TF-IDF backend.

    Generates a comma-separated list of domain keywords / synonyms.
    TF-IDF matches these terms against the indexed vocabulary, dramatically
    improving recall for short or abstract queries.

    Call only while the worker is idle (not generating).
    """
    if not self.is_model_loaded():
        return query
    if self.worker.isRunning():
        if self._log:
            self._log.debug("LLM", f"HyDE (TF-IDF) skipped – model busy: '{query}'")
        return query
    cache_key = str(query or "")
    cached = self._query_cache_get("tfidf", cache_key)
    if cached is not self._QUERY_CACHE_MISS:
        return str(cached or query)
    user_block = self._render_prompt_template(
        "hyde_tfidf_user",
        {"query": query},
    )
    prompt = (
        "<|system|>\n"
        f"{self._prompts['hyde_tfidf_system']}\n"
        "<|user|>\n"
        f"{user_block}\n"
        "<|assistant|>\n"
    )
    try:
        raw_text = self._generate_backend_text(
            prompt,
            max_tokens=80,
            temperature=0.2,
            top_p=0.9,
            repeat_penalty=1.0,
            stop_tokens=["<|"],
        )
        self._log_llm_io("HyDE-TFIDF", prompt, raw_text)
        keywords = raw_text.strip()
        if self._log:
            if keywords:
                self._log.info(
                    "LLM",
                    f"HyDE (TF-IDF keywords): '{query}'  ->  '{keywords[:100]}'",
                )
            else:
                self._log.debug("LLM", f"HyDE (TF-IDF) no output for: '{query}'")
        result_text = keywords if keywords else query
        self._query_cache_set("tfidf", cache_key, result_text)
        return result_text
    except Exception as exc:
        self._log_llm_io("HyDE-TFIDF", prompt, error=str(exc))
        if self._log:
            self._log.error("LLM", f"HyDE TF-IDF expansion failed: {exc}")
        return query

def expand_query_st_sync(self, query: str, n_hypotheses: int = 1) -> list[str]:
    """HyDE passage expansion for the sentence-transformers backend.

    Generates 1 or *n_hypotheses* short hypothetical passages whose vectors
    closely match real document chunks for cosine-similarity retrieval.

    Returns a ``list[str]`` (always at least ``[query]`` as fallback).
    Call only while the worker is idle (not generating).
    """
    if not self.is_model_loaded():
        return [query]
    if self.worker.isRunning():
        if self._log:
            self._log.debug("LLM", f"HyDE (ST) skipped – model busy: '{query}'")
        return [query]
    cache_key = (str(query or ""), int(n_hypotheses or 1))
    cached = self._query_cache_get("st", cache_key)
    if cached is not self._QUERY_CACHE_MISS:
        return list(cached or [query])
    if n_hypotheses <= 1:
        user_block = self._render_prompt_template(
            "hyde_st_single_user",
            {"query": query},
        )
        prompt = (
            "<|system|>\n"
            f"{self._prompts['hyde_st_single_system']}\n"
            "<|user|>\n"
            f"{user_block}\n"
            "<|assistant|>\n"
        )
        try:
            raw_text = self._generate_backend_text(
                prompt,
                max_tokens=120,
                temperature=0.3,
                top_p=0.9,
                repeat_penalty=1.0,
                stop_tokens=["<|"],
            )
            self._log_llm_io("HyDE-ST-single", prompt, raw_text)
            passage = raw_text.strip()
            if self._log and passage and passage != query:
                self._log.info(
                    "LLM",
                    f"HyDE (ST passage): '{query}'  ->  '{passage[:80]}…'",
                )
            result_passages = [passage] if passage else [query]
            self._query_cache_set("st", cache_key, list(result_passages))
            return result_passages
        except Exception as exc:
            self._log_llm_io("HyDE-ST-single", prompt, error=str(exc))
            if self._log:
                self._log.error("LLM", f"HyDE ST expansion failed: {exc}")
            return [query]
    else:
        user_block = self._render_prompt_template(
            "hyde_st_multi_user",
            {"query": query, "n_hypotheses": str(n_hypotheses)},
        )
        prompt = (
            "<|system|>\n"
            f"{self._prompts['hyde_st_multi_system']}\n"
            "<|user|>\n"
            f"{user_block}\n"
            "<|assistant|>\n"
        )
        try:
            raw_text = self._generate_backend_text(
                prompt,
                max_tokens=120 * n_hypotheses,
                temperature=0.5,
                top_p=0.9,
                repeat_penalty=1.0,
                stop_tokens=["<|"],
            )
            self._log_llm_io("HyDE-ST-multi", prompt, raw_text)
            text     = raw_text.strip()
            passages = [p.strip() for p in text.split("---") if p.strip()]
            if not passages:
                passages = [query]
            if self._log:
                self._log.info(
                    "LLM",
                    f"HyDE (ST multi-passage x{len(passages)}): '{query}'",
                )
            self._query_cache_set("st", cache_key, list(passages))
            return passages
        except Exception as exc:
            self._log_llm_io("HyDE-ST-multi", prompt, error=str(exc))
            if self._log:
                self._log.error("LLM", f"HyDE ST multi-passage expansion failed: {exc}")
            return [query]

def expand_query_literal_terms_sync(
    self,
    query: str,
    max_terms: int = 8,
) -> list[str] | tuple[list[str], dict[str, Any]]:
    """Generate regex patterns for the regex RAG backend."""
    if not self.is_model_loaded():
        return [], {
            "applied": False,
            "used": False,
            "reason": "model_not_loaded",
        }
    if self.worker.isRunning():
        if self._log:
            self._log.debug("LLM", f"Regex expansion skipped – model busy: '{query}'")
        return [], {
            "applied": False,
            "used": False,
            "reason": "model_busy",
        }

    limit = max(1, int(max_terms))
    cache_key = (str(query or ""), int(limit))
    cached = self._query_cache_get("literal", cache_key)
    if cached is not self._QUERY_CACHE_MISS:
        terms_cached, meta_cached = cached
        return list(terms_cached or []), dict(meta_cached or {})
    user_block = self._render_prompt_template(
        "literal_terms_user",
        {"query": query, "max_terms": str(limit)},
    )
    prompt = (
        "<|system|>\n"
        f"{self._prompts['literal_terms_system']}\n"
        "<|user|>\n"
        f"{user_block}\n"
        "<|assistant|>\n"
    )
    try:
        raw_full = self._generate_backend_text(
            prompt,
            max_tokens=max(80, limit * 18),
            temperature=0.2,
            top_p=0.9,
            repeat_penalty=1.0,
            stop_tokens=["<|"],
        )
        self._log_llm_io("Literal-Terms", prompt, raw_full)
        raw = raw_full.strip()
        if not raw:
            result = (
                [],
                {
                    "applied": True,
                    "used": False,
                    "reason": "empty",
                },
            )
            self._query_cache_set("literal", cache_key, result)
            return result

        patterns: list[str] = []
        seen: set[str] = set()
        for token in _extract_regex_candidates(raw):
            pattern = str(token).strip()
            pattern = _LIST_PREFIX_RE.sub("", pattern).strip()
            pattern = re.sub(r"^\s*regex\s*:\s*", "", pattern, flags=re.IGNORECASE).strip()
            pattern = _unwrap_matching_quotes(pattern)
            if not pattern:
                continue
            if len(pattern) > 240:
                continue
            key = pattern.casefold()
            if key in seen:
                continue
            seen.add(key)
            patterns.append(pattern)
            if len(patterns) >= limit:
                break

        if self._log:
            if patterns:
                self._log.info(
                    "LLM",
                    f"Regex patterns: '{query}' -> {', '.join(patterns[:8])}",
                )
            else:
                self._log.debug("LLM", f"Regex patterns empty for: '{query}'")
        result = (
            patterns,
            {
                "applied": True,
                "used": bool(patterns),
                "reason": "ok" if patterns else "empty",
            },
        )
        self._query_cache_set("literal", cache_key, result)
        return result
    except Exception as exc:
        self._log_llm_io("Literal-Terms", prompt, error=str(exc))
        if self._log:
            self._log.error("LLM", f"Regex pattern expansion failed: {exc}")
        return [], {
            "applied": False,
            "used": False,
            "reason": "exception",
            "error": str(exc),
        }
