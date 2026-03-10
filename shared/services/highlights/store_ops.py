"""High-level operations on normalized highlight records."""
from __future__ import annotations

import uuid

from .store_common import normalize_scope, normalize_tab, normalize_text, utc_now
from .store_matching import build_anchor, find_anchor_span, find_term_spans
from .store_models import HighlightMatch
from .store_records import (
    DEFAULT_GLOSSARY_COLOR,
    is_glossary_record,
    match_mode,
    normalize_color,
    record_applies,
    record_kind,
)


def build_glossary_rows(
    entries: list[dict],
    *,
    panel_scope: str,
    apply_all_tabs: bool,
    tabs: list[str] | None,
) -> list[dict]:
    clean_scope = str(panel_scope or "*").strip().lower() or "*"
    tab_scope = "all" if apply_all_tabs else "tabs"
    clean_tabs = (
        []
        if apply_all_tabs
        else [
            normalize_tab(item)
            for item in list(tabs or [])
            if normalize_tab(item)
        ]
    )
    if tab_scope == "tabs" and not clean_tabs:
        return []

    rows: list[dict] = []
    seen: set[str] = set()
    for row in list(entries or []):
        if not isinstance(row, dict):
            continue
        term = str(row.get("term", "") or "").strip()
        definition = str(row.get("definition", "") or "").strip()
        aliases_raw = row.get("aliases", [])
        aliases: list[str] = []
        if isinstance(aliases_raw, list):
            aliases = [
                str(item or "").strip()
                for item in aliases_raw
                if str(item or "").strip()
            ]

        tokens = [term] + aliases
        for token in tokens:
            cleaned = str(token or "").strip()
            if len(cleaned) < 2:
                continue
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
            now = utc_now()
            rows.append(
                {
                    "id": f"gls_{uuid.uuid4().hex[:12]}",
                    "panel_scope": clean_scope,
                    "tab_scope": tab_scope,
                    "tabs": list(clean_tabs),
                    "color": DEFAULT_GLOSSARY_COLOR,
                    "hover_text": definition,
                    "jump_to": "",
                    "kind": "glossary",
                    "match_mode": "term_all",
                    "case_sensitive": False,
                    "whole_word": True,
                    "anchor": {
                        "exact": cleaned,
                        "prefix": "",
                        "suffix": "",
                    },
                    "created_at": now,
                    "updated_at": now,
                }
            )
    return rows


def list_glossary_entries_from_records(records: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for record in records:
        if not is_glossary_record(record):
            continue
        anchor = record.get("anchor", {})
        term = str(anchor.get("exact", "") or "").strip()
        if len(term) < 2:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "term": term,
                "definition": str(record.get("hover_text", "") or "").strip(),
            }
        )
    out.sort(key=lambda row: str(row.get("term", "")).casefold())
    return out


def resolve_matches_from_records(
    records: list[dict],
    *,
    panel_scope: str,
    tab_name: str,
    full_text: str,
    glossary_enabled: bool,
) -> list[HighlightMatch]:
    src = normalize_text(full_text)
    scope = normalize_scope(panel_scope)
    tab = normalize_tab(tab_name)
    out: list[HighlightMatch] = []

    for record in records:
        if not record_applies(record, scope, tab):
            continue
        kind = record_kind(record)
        if kind == "glossary" and not glossary_enabled:
            continue
        mode = match_mode(record)
        if mode == "term_all":
            anchor = record.get("anchor", {})
            term = str(anchor.get("exact", "") or "")
            spans = find_term_spans(
                src,
                term=term,
                case_sensitive=bool(record.get("case_sensitive", False)),
                whole_word=bool(record.get("whole_word", True)),
            )
            for start, end in spans:
                out.append(_match_from_record(record, kind=kind, start=start, end=end))
            continue

        anchor = record.get("anchor", {})
        span = find_anchor_span(
            src,
            str(anchor.get("exact", "") or ""),
            str(anchor.get("prefix", "") or ""),
            str(anchor.get("suffix", "") or ""),
        )
        if span is None:
            continue
        start, end, _inferred_exact = span
        if end <= start:
            continue
        out.append(_match_from_record(record, kind=kind, start=start, end=end))

    return out


def sync_anchor_records_for_text(
    records: list[dict],
    *,
    panel_scope: str,
    tab_name: str,
    full_text: str,
) -> tuple[list[dict], bool]:
    src = normalize_text(full_text)
    scope = normalize_scope(panel_scope)
    tab = normalize_tab(tab_name)

    changed = False
    kept: list[dict] = []
    for record in records:
        if not record_applies(record, scope, tab):
            kept.append(record)
            continue
        if match_mode(record) != "anchor":
            kept.append(record)
            continue

        anchor = record.get("anchor", {})
        exact = str(anchor.get("exact", "") or "")
        prefix = str(anchor.get("prefix", "") or "")
        suffix = str(anchor.get("suffix", "") or "")
        span = find_anchor_span(src, exact, prefix, suffix)
        if span is None:
            kept.append(record)
            continue

        start, end, inferred_exact = span
        if end <= start:
            changed = True
            continue

        new_exact = inferred_exact if inferred_exact is not None else src[start:end]
        if not str(new_exact or "").strip():
            changed = True
            continue

        new_exact, new_prefix, new_suffix = build_anchor(src, start, end)
        new_anchor = {
            "exact": new_exact,
            "prefix": new_prefix,
            "suffix": new_suffix,
        }
        if new_anchor != anchor:
            record["anchor"] = new_anchor
            record["updated_at"] = utc_now()
            changed = True
        kept.append(record)

    return kept, changed


def rename_tab_records(
    records: list[dict],
    *,
    panel_scope: str,
    old_name: str,
    new_name: str,
) -> bool:
    scope = normalize_scope(panel_scope)
    old = normalize_tab(old_name)
    new = normalize_tab(new_name)
    if not old or not new or old == new:
        return False

    changed = False
    for record in records:
        if normalize_scope(record.get("panel_scope", "")) != scope:
            continue
        if str(record.get("tab_scope", "") or "tabs") != "tabs":
            continue
        tabs = [
            normalize_tab(item)
            for item in list(record.get("tabs", []) or [])
            if normalize_tab(item)
        ]
        if not tabs:
            continue
        replaced = False
        unique: list[str] = []
        for item in tabs:
            value = new if item == old else item
            if value == new and item == old:
                replaced = True
            if value not in unique:
                unique.append(value)
        if replaced and unique:
            record["tabs"] = unique
            record["updated_at"] = utc_now()
            changed = True

    return changed


def list_jump_targets_from_records(records: list[dict]) -> list[dict]:
    out: list[dict] = []
    for record in records:
        if is_glossary_record(record):
            continue
        anchor = record.get("anchor", {})
        exact = str(anchor.get("exact", "") or "")
        exact = " ".join(exact.split())
        if len(exact) > 40:
            exact = f"{exact[:37]}..."
        out.append(
            {
                "id": str(record.get("id", "") or ""),
                "kind": record_kind(record),
                "panel_scope": normalize_scope(record.get("panel_scope", "")),
                "tab_scope": str(record.get("tab_scope", "") or "tabs"),
                "tabs": [
                    normalize_tab(item)
                    for item in list(record.get("tabs", []) or [])
                    if normalize_tab(item)
                ],
                "exact_preview": exact,
            }
        )
    out.sort(key=lambda item: str(item.get("id", "")))
    return out


def resolve_highlight_by_id_from_records(
    records: list[dict],
    *,
    highlight_id: str,
    panel_scope: str,
    tab_name: str,
    full_text: str,
) -> HighlightMatch | None:
    target = str(highlight_id or "").strip()
    if not target:
        return None

    src = normalize_text(full_text)
    scope = normalize_scope(panel_scope)
    tab = normalize_tab(tab_name)

    record = _find_record(records, target)
    if record is None:
        return None
    if not record_applies(record, scope, tab):
        return None
    kind = record_kind(record)
    mode = match_mode(record)

    if mode == "term_all":
        anchor = record.get("anchor", {})
        term = str(anchor.get("exact", "") or "")
        spans = find_term_spans(
            src,
            term=term,
            case_sensitive=bool(record.get("case_sensitive", False)),
            whole_word=bool(record.get("whole_word", True)),
        )
        if not spans:
            return None
        start, end = spans[0]
        return _match_from_record(record, kind=kind, start=start, end=end)

    anchor = record.get("anchor", {})
    span = find_anchor_span(
        src,
        str(anchor.get("exact", "") or ""),
        str(anchor.get("prefix", "") or ""),
        str(anchor.get("suffix", "") or ""),
    )
    if span is None:
        return None
    start, end, _inferred_exact = span
    if end <= start:
        return None
    return _match_from_record(record, kind=kind, start=start, end=end)


def _find_record(records: list[dict], highlight_id: str) -> dict | None:
    target = str(highlight_id or "").strip()
    if not target:
        return None
    for record in records:
        if str(record.get("id", "") or "").strip() == target:
            return record
    return None


def _match_from_record(
    record: dict,
    *,
    kind: str,
    start: int,
    end: int,
) -> HighlightMatch:
    return HighlightMatch(
        highlight_id=str(record.get("id", "") or ""),
        start=int(start),
        end=int(end),
        color=normalize_color(record.get("color", "")),
        hover_text=str(record.get("hover_text", "") or ""),
        jump_to=str(record.get("jump_to", "") or ""),
        kind=kind,
    )


__all__ = [
    "build_glossary_rows",
    "list_glossary_entries_from_records",
    "list_jump_targets_from_records",
    "rename_tab_records",
    "resolve_highlight_by_id_from_records",
    "resolve_matches_from_records",
    "sync_anchor_records_for_text",
]
