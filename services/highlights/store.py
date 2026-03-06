"""Persistent text-highlight store for HTML preview overlays."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import uuid


_ANCHOR_CONTEXT_CHARS = 48
_STORE_VERSION = 2
_DEFAULT_GLOSSARY_COLOR = "#94E2D5"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\u2029", "\n")


def _normalize_scope(value: str) -> str:
    clean = str(value or "").strip().lower()
    return clean or "generic"


def _normalize_tab(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("🔒 "):
        text = text[2:].strip()
    return text


def _default_store_path() -> Path:
    raw = str(os.getenv("DRAFT2CRAIFT_HIGHLIGHTS_JSON", "")).strip()
    if raw:
        return Path(raw).expanduser()
    return (Path.cwd() / "highlights.json").resolve()


@dataclass(slots=True)
class HighlightMatch:
    """Resolved highlight span in plain preview text."""

    highlight_id: str
    start: int
    end: int
    color: str
    hover_text: str
    jump_to: str
    kind: str = "user"


class HighlightStore:
    """JSON-backed store for tab-scoped highlight rules."""

    def __init__(self, path: Path | None = None):
        self._path = Path(path or _default_store_path())
        self._lock = threading.RLock()
        self._data: dict = _default_data()
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_from_selection(
        self,
        *,
        panel_scope: str,
        tab_name: str,
        full_text: str,
        start: int,
        end: int,
        color: str,
        apply_all_tabs: bool,
    ) -> str:
        src = _normalize_text(full_text)
        s = max(0, min(int(start), len(src)))
        e = max(0, min(int(end), len(src)))
        if e < s:
            s, e = e, s

        exact, prefix, suffix = _build_anchor(src, s, e)
        if not exact.strip():
            return ""

        with self._lock:
            self._load_if_needed()
            highlight_id = f"hl_{uuid.uuid4().hex[:12]}"
            record = {
                "id": highlight_id,
                "panel_scope": _normalize_scope(panel_scope),
                "tab_scope": "all" if apply_all_tabs else "tabs",
                "tabs": [] if apply_all_tabs else [_normalize_tab(tab_name)],
                "color": _normalize_color(color),
                "hover_text": "",
                "jump_to": "",
                "kind": "user",
                "match_mode": "anchor",
                "anchor": {
                    "exact": exact,
                    "prefix": prefix,
                    "suffix": suffix,
                },
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            }
            self._highlights().append(record)
            self._save_unlocked()
            return highlight_id

    def is_glossary_enabled(self) -> bool:
        with self._lock:
            self._load_if_needed()
            settings = _normalize_settings(self._data.get("settings"))
            return bool(settings.get("glossary_enabled", True))

    def set_glossary_enabled(self, enabled: bool) -> bool:
        with self._lock:
            self._load_if_needed()
            settings = _normalize_settings(self._data.get("settings"))
            target = bool(enabled)
            if bool(settings.get("glossary_enabled", True)) == target:
                return False
            settings["glossary_enabled"] = target
            self._data["settings"] = settings
            self._save_unlocked()
            return True

    def replace_glossary_entries(
        self,
        *,
        entries: list[dict],
        panel_scope: str = "*",
        apply_all_tabs: bool = True,
        tabs: list[str] | None = None,
    ) -> int:
        clean_scope = str(panel_scope or "*").strip().lower() or "*"
        tab_scope = "all" if apply_all_tabs else "tabs"
        clean_tabs = (
            []
            if apply_all_tabs
            else [
                _normalize_tab(item)
                for item in list(tabs or [])
                if _normalize_tab(item)
            ]
        )
        if tab_scope == "tabs" and not clean_tabs:
            return 0

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
                rows.append(
                    {
                        "id": f"gls_{uuid.uuid4().hex[:12]}",
                        "panel_scope": clean_scope,
                        "tab_scope": tab_scope,
                        "tabs": list(clean_tabs),
                        "color": _DEFAULT_GLOSSARY_COLOR,
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
                        "created_at": _utc_now(),
                        "updated_at": _utc_now(),
                    }
                )

        with self._lock:
            self._load_if_needed()
            kept = [
                row for row in self._highlights()
                if not _is_glossary_record(row)
            ]
            kept.extend(rows)
            self._data["highlights"] = kept
            self._save_unlocked()
            return len(rows)

    def list_glossary_entries(self) -> list[dict]:
        """
        Return current glossary entries as a simple editable list.

        Each entry has the shape:
        ``{"term": str, "definition": str}``
        """
        with self._lock:
            self._load_if_needed()
            out: list[dict] = []
            seen: set[str] = set()
            for record in self._highlights():
                if not _is_glossary_record(record):
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

    def resolve_matches(
        self,
        *,
        panel_scope: str,
        tab_name: str,
        full_text: str,
    ) -> list[HighlightMatch]:
        src = _normalize_text(full_text)
        scope = _normalize_scope(panel_scope)
        tab = _normalize_tab(tab_name)

        with self._lock:
            self._load_if_needed()
            glossary_enabled = self.is_glossary_enabled()
            out: list[HighlightMatch] = []
            for record in self._highlights():
                if not _record_applies(record, scope, tab):
                    continue
                kind = _record_kind(record)
                if kind == "glossary" and not glossary_enabled:
                    continue
                match_mode = _match_mode(record)
                if match_mode == "term_all":
                    anchor = record.get("anchor", {})
                    term = str(anchor.get("exact", "") or "")
                    spans = _find_term_spans(
                        src,
                        term=term,
                        case_sensitive=bool(record.get("case_sensitive", False)),
                        whole_word=bool(record.get("whole_word", True)),
                    )
                    for start, end in spans:
                        out.append(
                            HighlightMatch(
                                highlight_id=str(record.get("id", "") or ""),
                                start=start,
                                end=end,
                                color=_normalize_color(record.get("color", "")),
                                hover_text=str(record.get("hover_text", "") or ""),
                                jump_to=str(record.get("jump_to", "") or ""),
                                kind=kind,
                            )
                        )
                    continue

                anchor = record.get("anchor", {})
                span = _find_anchor_span(
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
                out.append(
                    HighlightMatch(
                        highlight_id=str(record.get("id", "") or ""),
                        start=start,
                        end=end,
                        color=_normalize_color(record.get("color", "")),
                        hover_text=str(record.get("hover_text", "") or ""),
                        jump_to=str(record.get("jump_to", "") or ""),
                        kind=kind,
                    )
                )
            return out

    def sync_for_text(
        self,
        *,
        panel_scope: str,
        tab_name: str,
        full_text: str,
    ) -> bool:
        """
        Sync anchors for one tab after text edits.

        - If prefix/suffix still localize a changed span, anchor.exact is updated.
        - If a localized span becomes empty, the highlight is removed.
        """
        src = _normalize_text(full_text)
        scope = _normalize_scope(panel_scope)
        tab = _normalize_tab(tab_name)

        with self._lock:
            self._load_if_needed()
            changed = False
            items = self._highlights()
            kept: list[dict] = []
            for record in items:
                if not _record_applies(record, scope, tab):
                    kept.append(record)
                    continue
                if _match_mode(record) != "anchor":
                    kept.append(record)
                    continue

                anchor = record.get("anchor", {})
                exact = str(anchor.get("exact", "") or "")
                prefix = str(anchor.get("prefix", "") or "")
                suffix = str(anchor.get("suffix", "") or "")
                span = _find_anchor_span(src, exact, prefix, suffix)
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

                new_exact, new_prefix, new_suffix = _build_anchor(src, start, end)
                new_anchor = {
                    "exact": new_exact,
                    "prefix": new_prefix,
                    "suffix": new_suffix,
                }
                if new_anchor != anchor:
                    record["anchor"] = new_anchor
                    record["updated_at"] = _utc_now()
                    changed = True
                kept.append(record)

            if changed:
                self._data["highlights"] = kept
                self._save_unlocked()
            return changed

    def rename_tab(
        self,
        *,
        panel_scope: str,
        old_name: str,
        new_name: str,
    ) -> bool:
        scope = _normalize_scope(panel_scope)
        old = _normalize_tab(old_name)
        new = _normalize_tab(new_name)
        if not old or not new or old == new:
            return False

        with self._lock:
            self._load_if_needed()
            changed = False
            for record in self._highlights():
                if _normalize_scope(record.get("panel_scope", "")) != scope:
                    continue
                if str(record.get("tab_scope", "") or "tabs") != "tabs":
                    continue
                tabs = [
                    _normalize_tab(item)
                    for item in list(record.get("tabs", []) or [])
                    if _normalize_tab(item)
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
                    record["updated_at"] = _utc_now()
                    changed = True
            if changed:
                self._save_unlocked()
            return changed

    def set_hover_text(self, highlight_id: str, text: str) -> bool:
        return self._update_field(
            highlight_id=highlight_id,
            field="hover_text",
            value=str(text or "").strip(),
        )

    def set_jump_target(self, highlight_id: str, value: str) -> bool:
        return self._update_field(
            highlight_id=highlight_id,
            field="jump_to",
            value=str(value or "").strip(),
        )

    def set_color(self, highlight_id: str, color: str) -> bool:
        with self._lock:
            self._load_if_needed()
            record = self._find_record_unlocked(highlight_id)
            if record is None:
                return False
            if _is_glossary_record(record):
                return False
        return self._update_field(
            highlight_id=highlight_id,
            field="color",
            value=_normalize_color(color),
        )

    def get_highlight(self, highlight_id: str) -> dict | None:
        """Return one stored highlight as plain dict copy."""
        target = str(highlight_id or "").strip()
        if not target:
            return None
        with self._lock:
            self._load_if_needed()
            record = self._find_record_unlocked(target)
            if record is None:
                return None
            return dict(record)

    def list_jump_targets(self) -> list[dict]:
        """Return metadata for jump-target picker UIs."""
        with self._lock:
            self._load_if_needed()
            out: list[dict] = []
            for record in self._highlights():
                if _is_glossary_record(record):
                    continue
                anchor = record.get("anchor", {})
                exact = str(anchor.get("exact", "") or "")
                exact = " ".join(exact.split())
                if len(exact) > 40:
                    exact = f"{exact[:37]}..."
                out.append(
                    {
                        "id": str(record.get("id", "") or ""),
                        "kind": _record_kind(record),
                        "panel_scope": _normalize_scope(
                            record.get("panel_scope", "")
                        ),
                        "tab_scope": str(record.get("tab_scope", "") or "tabs"),
                        "tabs": [
                            _normalize_tab(item)
                            for item in list(record.get("tabs", []) or [])
                            if _normalize_tab(item)
                        ],
                        "exact_preview": exact,
                    }
                )
            out.sort(key=lambda item: str(item.get("id", "")))
            return out

    def resolve_highlight_by_id(
        self,
        *,
        highlight_id: str,
        panel_scope: str,
        tab_name: str,
        full_text: str,
    ) -> HighlightMatch | None:
        """Resolve one highlight span by ID in current view text."""
        target = str(highlight_id or "").strip()
        if not target:
            return None
        src = _normalize_text(full_text)
        scope = _normalize_scope(panel_scope)
        tab = _normalize_tab(tab_name)
        with self._lock:
            self._load_if_needed()
            record = self._find_record_unlocked(target)
            if record is None:
                return None
            if not _record_applies(record, scope, tab):
                return None
            kind = _record_kind(record)
            mode = _match_mode(record)
            if mode == "term_all":
                anchor = record.get("anchor", {})
                term = str(anchor.get("exact", "") or "")
                spans = _find_term_spans(
                    src,
                    term=term,
                    case_sensitive=bool(record.get("case_sensitive", False)),
                    whole_word=bool(record.get("whole_word", True)),
                )
                if not spans:
                    return None
                start, end = spans[0]
                return HighlightMatch(
                    highlight_id=str(record.get("id", "") or ""),
                    start=start,
                    end=end,
                    color=_normalize_color(record.get("color", "")),
                    hover_text=str(record.get("hover_text", "") or ""),
                    jump_to=str(record.get("jump_to", "") or ""),
                    kind=kind,
                )
            anchor = record.get("anchor", {})
            span = _find_anchor_span(
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
            return HighlightMatch(
                highlight_id=str(record.get("id", "") or ""),
                start=start,
                end=end,
                color=_normalize_color(record.get("color", "")),
                hover_text=str(record.get("hover_text", "") or ""),
                jump_to=str(record.get("jump_to", "") or ""),
                kind=kind,
            )

    def delete(self, highlight_id: str) -> bool:
        target = str(highlight_id or "").strip()
        if not target:
            return False
        with self._lock:
            self._load_if_needed()
            src = self._highlights()
            kept = [
                row for row in src
                if str(row.get("id", "") or "").strip() != target
            ]
            if len(kept) == len(src):
                return False
            self._data["highlights"] = kept
            self._save_unlocked()
            return True

    # ------------------------------------------------------------------
    # Internal storage helpers
    # ------------------------------------------------------------------

    def _update_field(
        self,
        *,
        highlight_id: str,
        field: str,
        value: str,
    ) -> bool:
        target = str(highlight_id or "").strip()
        if not target:
            return False
        with self._lock:
            self._load_if_needed()
            record = self._find_record_unlocked(target)
            if record is None:
                return False
            if str(record.get(field, "") or "") == value:
                return False
            record[field] = value
            record["updated_at"] = _utc_now()
            self._save_unlocked()
            return True
        return False

    def _highlights(self) -> list[dict]:
        value = self._data.get("highlights")
        if isinstance(value, list):
            return value
        self._data["highlights"] = []
        return self._data["highlights"]

    def _load_if_needed(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            if not self._path.exists():
                return
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            highlights = raw.get("highlights")
            if not isinstance(highlights, list):
                highlights = []
            settings = _normalize_settings(raw.get("settings"))
            self._data = {
                "version": int(raw.get("version", _STORE_VERSION)),
                "highlights": [row for row in highlights if isinstance(row, dict)],
                "settings": settings,
            }
        except Exception:
            self._data = _default_data()

    def _save_unlocked(self):
        payload = dict(self._data)
        payload["version"] = _STORE_VERSION
        payload["settings"] = _normalize_settings(payload.get("settings"))
        payload["updated_at"] = _utc_now()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def _find_record_unlocked(self, highlight_id: str) -> dict | None:
        target = str(highlight_id or "").strip()
        if not target:
            return None
        for record in self._highlights():
            if str(record.get("id", "") or "").strip() == target:
                return record
        return None


def _normalize_color(color: object) -> str:
    text = str(color or "").strip()
    if not text:
        return "#F9E2AF"
    if not text.startswith("#"):
        return "#F9E2AF"
    if len(text) == 4:
        # #RGB -> #RRGGBB
        r = text[1]
        g = text[2]
        b = text[3]
        return f"#{r}{r}{g}{g}{b}{b}".upper()
    if len(text) != 7:
        return "#F9E2AF"
    return text.upper()


def _default_data() -> dict:
    return {
        "version": _STORE_VERSION,
        "highlights": [],
        "settings": {"glossary_enabled": True},
    }


def _normalize_settings(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {"glossary_enabled": True}
    return {
        "glossary_enabled": bool(raw.get("glossary_enabled", True)),
    }


def _record_kind(record: dict) -> str:
    clean = str(record.get("kind", "user") or "").strip().lower()
    if clean in {"user", "glossary"}:
        return clean
    return "user"


def _is_glossary_record(record: dict) -> bool:
    return _record_kind(record) == "glossary"


def _match_mode(record: dict) -> str:
    mode = str(record.get("match_mode", "anchor") or "").strip().lower()
    if mode in {"anchor", "term_all"}:
        return mode
    return "anchor"


def _record_applies(record: dict, panel_scope: str, tab_name: str) -> bool:
    rec_scope = _normalize_scope(record.get("panel_scope", ""))
    if rec_scope not in {panel_scope, "*"}:
        return False

    tab_scope = str(record.get("tab_scope", "") or "tabs").strip().lower()
    if tab_scope == "all":
        return True

    tabs = [
        _normalize_tab(item)
        for item in list(record.get("tabs", []) or [])
        if _normalize_tab(item)
    ]
    if not tabs:
        return False
    return _normalize_tab(tab_name) in tabs


def _find_term_spans(
    text: str,
    *,
    term: str,
    case_sensitive: bool,
    whole_word: bool,
) -> list[tuple[int, int]]:
    src = _normalize_text(text)
    needle = str(term or "")
    if not src or not needle.strip():
        return []
    escaped = re.escape(needle)
    if whole_word:
        pattern = rf"(?<!\w){escaped}(?!\w)"
    else:
        pattern = escaped
    flags = 0 if case_sensitive else re.IGNORECASE
    spans: list[tuple[int, int]] = []
    for match in re.finditer(pattern, src, flags):
        spans.append((int(match.start()), int(match.end())))
    return spans


def _build_anchor(text: str, start: int, end: int) -> tuple[str, str, str]:
    src = _normalize_text(text)
    s = max(0, min(int(start), len(src)))
    e = max(0, min(int(end), len(src)))
    if e < s:
        s, e = e, s
    prefix_start = max(0, s - _ANCHOR_CONTEXT_CHARS)
    suffix_end = min(len(src), e + _ANCHOR_CONTEXT_CHARS)
    return (
        src[s:e],
        src[prefix_start:s],
        src[e:suffix_end],
    )


def _find_anchor_span(
    text: str,
    exact: str,
    prefix: str,
    suffix: str,
) -> tuple[int, int, str | None] | None:
    src = _normalize_text(text)
    needle = _normalize_text(exact)
    pre = _normalize_text(prefix)
    suf = _normalize_text(suffix)
    if not src:
        return None

    direct = _find_exact_spans(src, needle)
    if direct:
        best = _pick_best_span(src, direct, pre, suf)
        return (best[0], best[1], None)

    inferred = _infer_span_from_context(src, pre, suf)
    if inferred is None:
        return None
    start, end = inferred
    return (start, end, src[start:end])


def _find_exact_spans(text: str, needle: str) -> list[tuple[int, int]]:
    if not needle:
        return []
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        idx = text.find(needle, pos)
        if idx < 0:
            break
        spans.append((idx, idx + len(needle)))
        pos = idx + 1
    return spans


def _pick_best_span(
    text: str,
    spans: list[tuple[int, int]],
    prefix: str,
    suffix: str,
) -> tuple[int, int]:
    if len(spans) == 1:
        return spans[0]

    best_span = spans[0]
    best_score = -1
    for start, end in spans:
        left = text[max(0, start - len(prefix)):start] if prefix else ""
        right = text[end:min(len(text), end + len(suffix))] if suffix else ""
        score = 0
        if prefix:
            score += _common_suffix_len(left, prefix)
        if suffix:
            score += _common_prefix_len(right, suffix)
        if score > best_score:
            best_score = score
            best_span = (start, end)
    return best_span


def _infer_span_from_context(
    text: str,
    prefix: str,
    suffix: str,
) -> tuple[int, int] | None:
    if not prefix and not suffix:
        return None

    pre_hits = _find_context_hits(text, prefix, tail=True)
    suf_hits = _find_context_hits(text, suffix, tail=False)
    if not pre_hits and not suf_hits:
        return None

    if pre_hits and not suf_hits:
        return None
    if suf_hits and not pre_hits:
        return None

    best: tuple[int, int] | None = None
    best_gap = 10**9
    for start in pre_hits:
        for end in suf_hits:
            if end < start:
                continue
            gap = end - start
            if gap < best_gap:
                best_gap = gap
                best = (start, end)
            break
    return best


def _find_context_hits(text: str, context: str, *, tail: bool) -> list[int]:
    src = str(text or "")
    raw = str(context or "")
    if not raw:
        return []

    sizes: list[int] = []
    full_len = len(raw)
    for size in (full_len, 32, 24, 16, 12, 8):
        if size <= 0:
            continue
        if size > full_len:
            continue
        if size not in sizes:
            sizes.append(size)

    hits: list[int] = []
    for size in sizes:
        piece = raw[-size:] if tail else raw[:size]
        if not piece:
            continue
        pos = 0
        local_hits: list[int] = []
        while True:
            idx = src.find(piece, pos)
            if idx < 0:
                break
            if tail:
                local_hits.append(idx + len(piece))
            else:
                local_hits.append(idx)
            pos = idx + 1
        if local_hits:
            hits = local_hits
            break
    return hits


def _common_suffix_len(left: str, right: str) -> int:
    a = str(left or "")
    b = str(right or "")
    n = min(len(a), len(b))
    count = 0
    for i in range(1, n + 1):
        if a[-i] != b[-i]:
            break
        count += 1
    return count


def _common_prefix_len(left: str, right: str) -> int:
    a = str(left or "")
    b = str(right or "")
    n = min(len(a), len(b))
    count = 0
    for i in range(n):
        if a[i] != b[i]:
            break
        count += 1
    return count


_STORE_SINGLETON: HighlightStore | None = None


def get_highlight_store() -> HighlightStore:
    """Return process-wide highlight store singleton."""
    global _STORE_SINGLETON
    if _STORE_SINGLETON is None:
        _STORE_SINGLETON = HighlightStore()
    return _STORE_SINGLETON
