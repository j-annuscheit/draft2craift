"""Parsing helpers for small LLM node-proposal payloads."""
from __future__ import annotations

import json
import re
from typing import Any

from shared.domain.graph_codec import extract_graph_spec

from .labels import clean_label, labels_equivalent

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(?P<body>\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(?P<label>.+?)\s*$")
_LABEL_LINE_RE = re.compile(r"^\s*(?:label|name|text)\s*:\s*(?P<label>.+?)\s*$", re.IGNORECASE)
_QUOTED_RE = re.compile(r"\"([^\"\n]{3,120})\"|'([^'\n]{3,120})'")


def parse_map_markdown(markdown: str):
    return extract_graph_spec(str(markdown or ""))


def parse_child_suggestions(
    raw_text: str,
    *,
    valid_segment_ids: set[str] | None = None,
    min_word_letters: int = 3,
    max_children: int = 6,
    relaxed: bool = False,
) -> dict[str, Any]:
    parsed = parse_node_suggestions(
        raw_text,
        valid_segment_ids=valid_segment_ids,
        min_word_letters=min_word_letters,
        max_nodes=max_children,
        top_keys=("children", "nodes", "items"),
        relaxed=relaxed,
    )
    return {
        "children": list(parsed.get("nodes", []) or []),
        "reason": str(parsed.get("reason", "invalid_response_format") or "invalid_response_format"),
    }


def parse_node_suggestions(
    raw_text: str,
    *,
    valid_segment_ids: set[str] | None = None,
    min_word_letters: int = 3,
    max_nodes: int = 6,
    top_keys: tuple[str, ...] = ("nodes", "children", "items"),
    relaxed: bool = False,
) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {"nodes": [], "reason": "empty_response"}
    valid_ids = set(valid_segment_ids or set())
    nodes: list[dict[str, Any]] = []

    parsed = _try_json(text)
    if isinstance(parsed, dict):
        for key in top_keys:
            rows = parsed.get(str(key))
            if isinstance(rows, list):
                for item in rows:
                    node = _normalize_node(
                        item,
                        valid_segment_ids=valid_ids,
                        min_word_letters=min_word_letters,
                    )
                    if node:
                        nodes.append(node)
                if nodes:
                    break
    elif isinstance(parsed, list):
        for item in parsed:
            node = _normalize_node(
                item,
                valid_segment_ids=valid_ids,
                min_word_letters=min_word_letters,
            )
            if node:
                nodes.append(node)

    if not nodes:
        for line in text.splitlines():
            match = _BULLET_RE.match(line)
            if match is not None:
                label = clean_label(match.group("label"), min_word_letters=min_word_letters)
                if label:
                    nodes.append({"label": label, "evidence_segment_ids": []})
                    continue
            label_match = _LABEL_LINE_RE.match(line)
            if label_match is None:
                continue
            label = clean_label(label_match.group("label"), min_word_letters=min_word_letters)
            if label:
                nodes.append({"label": label, "evidence_segment_ids": []})

    if relaxed and not nodes:
        for label in _quoted_labels(text, min_word_letters=min_word_letters):
            nodes.append({"label": label, "evidence_segment_ids": []})
        if not nodes:
            nodes.extend(_split_inline_labels(text, min_word_letters=min_word_letters))

    deduped: list[dict[str, Any]] = []
    for node in nodes[: max(1, int(max_nodes) * 3)]:
        label = str(node.get("label", "") or "")
        if not label:
            continue
        if any(labels_equivalent(label, str(existing.get("label", "") or "")) for existing in deduped):
            continue
        deduped.append(node)
        if len(deduped) >= max(1, int(max_nodes)):
            break
    return {
        "nodes": deduped,
        "reason": "ok" if deduped else "invalid_response_format",
    }


def _try_json(text: str) -> Any:
    candidates = [str(text or "")]
    match = _JSON_BLOCK_RE.search(str(text or ""))
    if match is not None:
        candidates.insert(0, str(match.group("body") or ""))
    for candidate in candidates:
        body = str(candidate or "").strip()
        if not body:
            continue
        try:
            return json.loads(body)
        except Exception:
            continue
    return None


def _normalize_node(
    item: Any,
    *,
    valid_segment_ids: set[str],
    min_word_letters: int,
) -> dict[str, Any] | None:
    if isinstance(item, str):
        label = clean_label(item, min_word_letters=min_word_letters)
        return {"label": label, "evidence_segment_ids": []} if label else None
    if not isinstance(item, dict):
        return None
    label = clean_label(
        item.get("label") or item.get("name") or item.get("text") or item.get("title"),
        min_word_letters=min_word_letters,
    )
    if not label:
        return None
    evidence_ids: list[str] = []
    raw_ids = item.get("evidence_segment_ids") or item.get("segment_ids") or []
    if isinstance(raw_ids, list):
        for raw in raw_ids:
            seg_id = str(raw or "").strip()
            if not seg_id:
                continue
            if valid_segment_ids and seg_id not in valid_segment_ids:
                continue
            if seg_id not in evidence_ids:
                evidence_ids.append(seg_id)
    reason = str(item.get("reason", "") or "").strip()
    out = {"label": label, "evidence_segment_ids": evidence_ids}
    if reason:
        out["reason"] = reason[:240]
    return out


def _quoted_labels(text: str, *, min_word_letters: int) -> list[str]:
    labels: list[str] = []
    for match in _QUOTED_RE.finditer(str(text or "")):
        raw = str(match.group(1) or match.group(2) or "")
        label = clean_label(raw, min_word_letters=min_word_letters)
        if label:
            labels.append(label)
    return labels


def _split_inline_labels(text: str, *, min_word_letters: int) -> list[dict[str, Any]]:
    cleaned = str(text or "").strip()
    cleaned = cleaned.replace("\n", ", ")
    cleaned = re.sub(r"[{}\[\]()]+", " ", cleaned)
    cleaned = re.sub(r"\b(?:children|nodes|items|label|labels|text|name|title)\b\s*:?", " ", cleaned, flags=re.IGNORECASE)
    out: list[dict[str, Any]] = []
    for chunk in re.split(r"\s*(?:,|;|\||/|\\n)+\s*", cleaned):
        label = clean_label(chunk, min_word_letters=min_word_letters)
        if not label:
            continue
        out.append({"label": label, "evidence_segment_ids": []})
    return out
