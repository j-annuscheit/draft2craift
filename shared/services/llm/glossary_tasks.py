"""Glossary generation helpers for ``LLMManager``."""
from __future__ import annotations

import json
import re
from typing import Any

_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*]+|\d+[\.\)])\s*")
_COMMA_NEWLINE_SEMI_SPLIT_RE = re.compile(r"[,\n;]+")
_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")
_FENCED_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*([\s\S]*?)```",
    flags=re.IGNORECASE,
)


def generate_glossary_sync(
    self,
    context_text: str,
    max_terms: int = 24,
) -> tuple[list[dict[str, object]], dict[str, Any]]:
    """Generate glossary entries from context text via local LLM."""
    context = str(context_text or "").strip()
    if not context:
        return [], {
            "applied": False,
            "reason": "empty_context",
        }
    if not self.is_model_loaded():
        return [], {
            "applied": False,
            "reason": "model_not_loaded",
        }
    if self.worker.isRunning():
        if self._log:
            self._log.debug("LLM", "Glossary generation skipped – model busy.")
        return [], {
            "applied": False,
            "reason": "model_busy",
        }

    limit = max(1, min(64, int(max_terms)))

    def _compact_context(text: str, max_chars: int) -> tuple[str, bool]:
        source = str(text or "")
        cap = max(1200, int(max_chars))
        if len(source) <= cap:
            return source, False
        marker = "\n\n[... Kontext gekürzt ...]\n\n"
        if cap <= (len(marker) + 24):
            return source[:cap], True
        head_len = int(cap * 0.72)
        tail_len = max(0, cap - head_len - len(marker))
        compact = (
            source[:head_len].rstrip()
            + marker
            + source[-tail_len:].lstrip()
        )
        return compact, True

    def _normalize_entries(parsed: Any) -> list[dict[str, object]]:
        if isinstance(parsed, dict):
            for key in ("entries", "glossary", "items", "begriffe"):
                value = parsed.get(key)
                if isinstance(value, list):
                    parsed = value
                    break
            else:
                # Single object fallback.
                parsed = [parsed]

        if not isinstance(parsed, list):
            return []

        out: list[dict[str, object]] = []
        seen: set[str] = set()
        for item in parsed:
            term = ""
            definition = ""
            aliases: list[str] = []
            if isinstance(item, dict):
                term = str(
                    item.get("term")
                    or item.get("begriff")
                    or item.get("keyword")
                    or item.get("title")
                    or ""
                ).strip()
                definition = str(
                    item.get("definition")
                    or item.get("erklaerung")
                    or item.get("erklärung")
                    or item.get("explanation")
                    or item.get("desc")
                    or ""
                ).strip()
                raw_aliases = item.get("aliases", [])
                if isinstance(raw_aliases, list):
                    aliases = [
                        str(alias or "").strip()
                        for alias in raw_aliases
                        if str(alias or "").strip()
                    ]
                elif isinstance(raw_aliases, str):
                    aliases = [
                        token.strip()
                        for token in _COMMA_NEWLINE_SEMI_SPLIT_RE.split(raw_aliases)
                        if token.strip()
                    ]
            elif isinstance(item, str):
                term = str(item or "").strip(" -*\t\"'`")

            if len(term) < 2:
                continue
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "term": term,
                    "definition": definition,
                    "aliases": aliases,
                }
            )
            if len(out) >= limit:
                break
        return out

    def _parse_glossary_output(raw_text: str) -> tuple[list[dict[str, object]], str]:
        raw = str(raw_text or "").strip()
        if not raw:
            return [], "empty"

        candidates: list[str] = [raw]
        for m in _FENCED_JSON_BLOCK_RE.finditer(raw):
            candidate = str(m.group(1) or "").strip()
            if candidate:
                candidates.append(candidate)
        bracket_match = _JSON_ARRAY_RE.search(raw)
        if bracket_match:
            candidates.append(str(bracket_match.group(0) or "").strip())
        object_match = _JSON_OBJECT_RE.search(raw)
        if object_match:
            candidates.append(str(object_match.group(0) or "").strip())

        seen_candidates: set[str] = set()
        for candidate in candidates:
            token = str(candidate or "").strip()
            if not token or token in seen_candidates:
                continue
            seen_candidates.add(token)
            try:
                parsed = json.loads(token)
            except Exception:
                continue
            normalized = _normalize_entries(parsed)
            if normalized:
                return normalized, "json"

        # Minimal text fallback: "- TERM: definition" / "TERM: definition".
        fallback_rows: list[dict[str, object]] = []
        seen_terms: set[str] = set()
        for line in raw.splitlines():
            entry = str(line or "").strip()
            entry = _LIST_PREFIX_RE.sub("", entry).strip()
            if not entry:
                continue
            term = ""
            definition = ""
            if ":" in entry:
                left, right = entry.split(":", 1)
                term = left.strip(" \"'`")
                definition = right.strip()
            else:
                if len(entry.split()) <= 5:
                    term = entry.strip(" \"'`")
            if len(term) < 2:
                continue
            key = term.casefold()
            if key in seen_terms:
                continue
            seen_terms.add(key)
            fallback_rows.append(
                {
                    "term": term,
                    "definition": definition,
                    "aliases": [],
                }
            )
            if len(fallback_rows) >= limit:
                break
        if fallback_rows:
            return fallback_rows, "lines"
        return [], "parse_failed"

    def _call_glossary(
        *,
        call_name: str,
        prompt: str,
        stop_tokens: list[str] | None,
        temperature: float,
        top_p: float,
        repeat_penalty: float,
        max_tokens: int,
    ) -> str:
        kwargs: dict[str, Any] = {
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "top_p": float(top_p),
            "repeat_penalty": float(repeat_penalty),
        }
        raw_full = self._generate_backend_text(
            prompt,
            max_tokens=int(kwargs["max_tokens"]),
            temperature=float(kwargs["temperature"]),
            top_p=float(kwargs["top_p"]),
            repeat_penalty=float(kwargs["repeat_penalty"]),
            stop_tokens=list(stop_tokens or ["<|"]),
        )
        self._log_llm_io(call_name, prompt, raw_full)
        return str(raw_full or "")

    # Compact very long contexts for small models so they still produce output.
    n_ctx = int(self._n_ctx())
    context_char_budget = min(26000, max(7000, int(n_ctx * 2.8)))
    compact_context, was_compacted = _compact_context(context, context_char_budget)

    user_block = self._render_prompt_template(
        "glossary_user",
        {"context": compact_context, "max_terms": str(limit)},
    )
    prompt = (
        "<|system|>\n"
        f"{self._prompts['glossary_system']}\n"
        "<|user|>\n"
        f"{user_block}\n"
        "<|assistant|>\n"
    )
    max_out_tokens = max(220, min(1800, limit * 70))
    window_err = self._check_prompt_window(prompt, max_out_tokens)
    if window_err:
        if self._log:
            self._log.error("LLM", f"Glossary context too large: {window_err}")
        return [], {
            "applied": False,
            "reason": "context_too_large",
            "error": window_err,
        }

    try:
        raw_primary = _call_glossary(
            call_name="Glossary",
            prompt=prompt,
            stop_tokens=["<|"],
            temperature=0.2,
            top_p=0.9,
            repeat_penalty=1.05,
            max_tokens=max_out_tokens,
        )
        primary_entries, primary_parse_reason = _parse_glossary_output(raw_primary)
        if primary_entries:
            return primary_entries, {
                "applied": True,
                "reason": "ok",
                "generated": len(primary_entries),
                "parse": primary_parse_reason,
                "retried": False,
                "context_compacted": was_compacted,
                "context_chars_used": len(compact_context),
            }

        if self._log:
            self._log.warning(
                "LLM",
                "Glossary primary parse empty/failed. Retrying with compact strict prompt.",
            )

        retry_context, retry_compacted = _compact_context(compact_context, 9000)
        retry_prompt = (
            "<|system|>\n"
            "Extrahiere ein Glossar aus dem Kontext.\n"
            "Antworte ausschließlich als gültiges JSON-Array.\n"
            "Jedes Element: {\"term\":\"...\",\"definition\":\"...\",\"aliases\":[\"...\"]}\n"
            "Keine Erklärungen, kein Markdown, kein zusätzlicher Text.\n"
            "<|user|>\n"
            f"Maximal {limit} Einträge.\n"
            "Nur Begriffe aus dem Kontext verwenden.\n"
            "Kontext:\n"
            f"{retry_context}\n"
            "<|assistant|>\n"
        )
        retry_window_err = self._check_prompt_window(retry_prompt, max_out_tokens)
        if retry_window_err:
            return [], {
                "applied": False,
                "reason": "context_too_large_retry",
                "error": retry_window_err,
                "parse": primary_parse_reason,
                "retried": True,
            }

        raw_retry = _call_glossary(
            call_name="Glossary-Retry",
            prompt=retry_prompt,
            stop_tokens=None,
            temperature=0.1,
            top_p=0.85,
            repeat_penalty=1.0,
            max_tokens=max_out_tokens,
        )
        retry_entries, retry_parse_reason = _parse_glossary_output(raw_retry)
        if retry_entries:
            return retry_entries, {
                "applied": True,
                "reason": "ok_retry",
                "generated": len(retry_entries),
                "parse": retry_parse_reason,
                "retried": True,
                "context_compacted": bool(was_compacted or retry_compacted),
                "context_chars_used": len(retry_context),
            }

        final_reason = (
            "empty"
            if (not str(raw_primary or "").strip() and not str(raw_retry or "").strip())
            else "parse_failed"
        )
        return [], {
            "applied": True,
            "reason": final_reason,
            "generated": 0,
            "retried": True,
            "parse": retry_parse_reason or primary_parse_reason,
            "raw_preview": str(raw_retry or raw_primary or "")[:320],
            "context_compacted": bool(was_compacted or retry_compacted),
            "context_chars_used": len(retry_context),
        }
    except Exception as exc:
        self._log_llm_io("Glossary", prompt, error=str(exc))
        if self._log:
            self._log.error("LLM", f"Glossary generation failed: {exc}")
        return [], {
            "applied": False,
            "reason": "exception",
            "error": str(exc),
        }

def expand_query_sync(self, query: str) -> str:
    """Deprecated: generate a single hypothetical passage.

    Use ``expand_query_tfidf_sync`` or ``expand_query_st_sync`` instead.
    """
    passages = self.expand_query_st_sync(query, 1)
    return passages[0] if passages else query
