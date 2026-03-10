"""Persistent text-highlight store for HTML preview overlays."""
from __future__ import annotations

from pathlib import Path
import threading
import uuid

from .store_common import default_store_path, normalize_scope, normalize_tab, normalize_text, utc_now
from .store_matching import build_anchor
from .store_models import HighlightMatch
from .store_ops import (
    build_glossary_rows,
    list_glossary_entries_from_records,
    list_jump_targets_from_records,
    rename_tab_records,
    resolve_highlight_by_id_from_records,
    resolve_matches_from_records,
    sync_anchor_records_for_text,
)
from .store_records import (
    default_data,
    is_glossary_record,
    normalize_color,
    normalize_settings,
)
from .store_storage import load_store_data, save_store_data


class HighlightStore:
    """JSON-backed store for tab-scoped highlight rules."""

    def __init__(self, path: Path | None = None):
        self._path = Path(path or default_store_path())
        self._lock = threading.RLock()
        self._data: dict = default_data()
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
        src = normalize_text(full_text)
        s = max(0, min(int(start), len(src)))
        e = max(0, min(int(end), len(src)))
        if e < s:
            s, e = e, s

        exact, prefix, suffix = build_anchor(src, s, e)
        if not exact.strip():
            return ""

        with self._lock:
            self._load_if_needed()
            now = utc_now()
            highlight_id = f"hl_{uuid.uuid4().hex[:12]}"
            record = {
                "id": highlight_id,
                "panel_scope": normalize_scope(panel_scope),
                "tab_scope": "all" if apply_all_tabs else "tabs",
                "tabs": [] if apply_all_tabs else [normalize_tab(tab_name)],
                "color": normalize_color(color),
                "hover_text": "",
                "jump_to": "",
                "kind": "user",
                "match_mode": "anchor",
                "anchor": {
                    "exact": exact,
                    "prefix": prefix,
                    "suffix": suffix,
                },
                "created_at": now,
                "updated_at": now,
            }
            self._highlights().append(record)
            self._save_unlocked()
            return highlight_id

    def is_glossary_enabled(self) -> bool:
        with self._lock:
            self._load_if_needed()
            settings = normalize_settings(self._data.get("settings"))
            return bool(settings.get("glossary_enabled", True))

    def set_glossary_enabled(self, enabled: bool) -> bool:
        with self._lock:
            self._load_if_needed()
            settings = normalize_settings(self._data.get("settings"))
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
        clean_tabs = [
            normalize_tab(item)
            for item in list(tabs or [])
            if normalize_tab(item)
        ]
        if not apply_all_tabs and not clean_tabs:
            return 0

        rows = build_glossary_rows(
            entries,
            panel_scope=panel_scope,
            apply_all_tabs=apply_all_tabs,
            tabs=clean_tabs,
        )

        with self._lock:
            self._load_if_needed()
            kept = [
                row for row in self._highlights()
                if not is_glossary_record(row)
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
            return list_glossary_entries_from_records(self._highlights())

    def resolve_matches(
        self,
        *,
        panel_scope: str,
        tab_name: str,
        full_text: str,
    ) -> list[HighlightMatch]:
        with self._lock:
            self._load_if_needed()
            glossary_enabled = self.is_glossary_enabled()
            return resolve_matches_from_records(
                self._highlights(),
                panel_scope=panel_scope,
                tab_name=tab_name,
                full_text=full_text,
                glossary_enabled=glossary_enabled,
            )

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
        with self._lock:
            self._load_if_needed()
            kept, changed = sync_anchor_records_for_text(
                self._highlights(),
                panel_scope=panel_scope,
                tab_name=tab_name,
                full_text=full_text,
            )
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
        with self._lock:
            self._load_if_needed()
            changed = rename_tab_records(
                self._highlights(),
                panel_scope=panel_scope,
                old_name=old_name,
                new_name=new_name,
            )
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
            if is_glossary_record(record):
                return False
        return self._update_field(
            highlight_id=highlight_id,
            field="color",
            value=normalize_color(color),
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
            return list_jump_targets_from_records(self._highlights())

    def resolve_highlight_by_id(
        self,
        *,
        highlight_id: str,
        panel_scope: str,
        tab_name: str,
        full_text: str,
    ) -> HighlightMatch | None:
        """Resolve one highlight span by ID in current view text."""
        with self._lock:
            self._load_if_needed()
            return resolve_highlight_by_id_from_records(
                self._highlights(),
                highlight_id=highlight_id,
                panel_scope=panel_scope,
                tab_name=tab_name,
                full_text=full_text,
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
            record["updated_at"] = utc_now()
            self._save_unlocked()
            return True

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
        self._data = load_store_data(self._path)

    def _save_unlocked(self):
        self._data["settings"] = normalize_settings(self._data.get("settings"))
        save_store_data(self._path, self._data)

    def _find_record_unlocked(self, highlight_id: str) -> dict | None:
        target = str(highlight_id or "").strip()
        if not target:
            return None
        for record in self._highlights():
            if str(record.get("id", "") or "").strip() == target:
                return record
        return None


_STORE_SINGLETON: HighlightStore | None = None


def get_highlight_store() -> HighlightStore:
    """Return process-wide highlight store singleton."""
    global _STORE_SINGLETON
    if _STORE_SINGLETON is None:
        _STORE_SINGLETON = HighlightStore()
    return _STORE_SINGLETON


__all__ = ["HighlightMatch", "HighlightStore", "get_highlight_store"]
