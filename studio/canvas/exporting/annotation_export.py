"""Annotation export helpers for markdown/html split-view panels."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import html

from shared.services.highlights.store import get_highlight_store
from shared.services.highlights.store_records import normalize_color


_DEFAULT_COLOR_LABELS = {
    "#F9E2AF": "Gelb",
    "#A6E3A1": "Grün",
    "#89B4FA": "Blau",
    "#F38BA8": "Rot",
    "#CBA6F7": "Lila",
    "#FAB387": "Orange",
    "#94E2D5": "Glossar",
}
_DEFAULT_COLOR_CSS = {
    "#F9E2AF": "lemonchiffon",
    "#A6E3A1": "palegreen",
    "#89B4FA": "lightskyblue",
    "#F38BA8": "lightpink",
    "#CBA6F7": "thistle",
    "#FAB387": "peachpuff",
    "#94E2D5": "paleturquoise",
}

_SORT_CHRONOLOGICAL = "chronological"
_SORT_GROUPED_BY_COLOR = "grouped_by_color"


@dataclass(frozen=True, slots=True)
class AnnotationExportEntry:
    """One resolved highlight occurrence for export rendering."""

    highlight_id: str
    kind: str
    color: str
    text: str
    comment: str
    created_at: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class AnnotationExportData:
    """Resolved entries plus option metadata for dialog construction."""

    entries: tuple[AnnotationExportEntry, ...]
    color_counts: tuple[tuple[str, int], ...]
    glossary_count: int

    @property
    def has_entries(self) -> bool:
        return bool(self.entries)


@dataclass(frozen=True, slots=True)
class AnnotationExportOptions:
    """User-selected export options."""

    include_colors: tuple[str, ...]
    include_glossary: bool = True
    include_comments: bool = False
    sort_mode: str = _SORT_CHRONOLOGICAL
    keep_markers: bool = True

    @classmethod
    def normalize(cls, raw: AnnotationExportOptions) -> AnnotationExportOptions:
        selected: list[str] = []
        for color in raw.include_colors:
            normalized = normalize_color(color)
            if normalized not in selected:
                selected.append(normalized)
        mode = str(raw.sort_mode or "").strip().lower()
        if mode not in {_SORT_CHRONOLOGICAL, _SORT_GROUPED_BY_COLOR}:
            mode = _SORT_CHRONOLOGICAL
        return cls(
            include_colors=tuple(selected),
            include_glossary=bool(raw.include_glossary),
            include_comments=bool(raw.include_comments),
            sort_mode=mode,
            keep_markers=bool(raw.keep_markers),
        )


def color_display_name(color: str) -> str:
    """Return a human-friendly color name for a normalized hex value."""
    normalized = normalize_color(color)
    mapped = _DEFAULT_COLOR_LABELS.get(normalized)
    if mapped:
        return mapped
    return "Benutzerfarbe"


def collect_annotation_export_data(
    *,
    panel_scope: str,
    tab_name: str,
    source_text: str,
) -> AnnotationExportData:
    """Resolve annotation occurrences for one panel/tab text snapshot."""
    scope = str(panel_scope or "").strip().lower() or "generic"
    title = str(tab_name or "").strip()
    text = str(source_text or "").replace("\r\n", "\n")

    store = get_highlight_store()
    matches = store.resolve_matches(
        panel_scope=scope,
        tab_name=title,
        full_text=text,
    )
    snapshot = store.snapshot()
    records = list(snapshot.get("highlights", []) or [])
    record_by_id = {
        str(row.get("id", "") or "").strip(): row
        for row in records
        if isinstance(row, dict)
    }

    entries: list[AnnotationExportEntry] = []
    for match in matches:
        start = max(0, min(int(getattr(match, "start", 0)), len(text)))
        end = max(start, min(int(getattr(match, "end", start)), len(text)))
        excerpt = text[start:end]
        if not excerpt.strip():
            continue

        highlight_id = str(getattr(match, "highlight_id", "") or "").strip()
        record = record_by_id.get(highlight_id, {})
        kind = str(getattr(match, "kind", "") or record.get("kind", "user")).strip().lower()
        color = normalize_color(getattr(match, "color", "") or record.get("color", ""))
        comment = str(record.get("hover_text", "") or getattr(match, "hover_text", "") or "").strip()
        created_at = str(record.get("created_at", "") or "").strip()
        if not created_at:
            created_at = str(record.get("updated_at", "") or "").strip()

        entries.append(
            AnnotationExportEntry(
                highlight_id=highlight_id,
                kind=kind if kind in {"user", "glossary"} else "user",
                color=color,
                text=excerpt,
                comment=comment,
                created_at=created_at,
                start=start,
                end=end,
            )
        )

    color_counts_map: "OrderedDict[str, int]" = OrderedDict()
    glossary_count = 0
    for entry in entries:
        if entry.kind == "glossary":
            glossary_count += 1
            continue
        color_counts_map[entry.color] = int(color_counts_map.get(entry.color, 0)) + 1

    color_counts = tuple((color, count) for color, count in color_counts_map.items())
    return AnnotationExportData(
        entries=tuple(entries),
        color_counts=color_counts,
        glossary_count=glossary_count,
    )


def build_annotation_export_markdown(
    *,
    panel_scope: str,
    tab_name: str,
    data: AnnotationExportData,
    options: AnnotationExportOptions,
) -> str:
    """Build markdown content from resolved annotations + export options."""
    normalized = AnnotationExportOptions.normalize(options)
    filtered = _filtered_entries(data.entries, normalized)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    scope = str(panel_scope or "").strip().lower() or "generic"
    title = str(tab_name or "").strip() or "(ohne Titel)"

    lines: list[str] = [
        "# Annotationen Extraktion",
        "",
        f"- Bereich: `{scope}`",
        f"- Reiter: `{title}`",
        f"- Extraktionszeit (UTC): `{now}`",
        "",
    ]

    if not filtered:
        lines.extend(
            [
                "## Ergebnis",
                "",
                "_Keine Annotationen mit den aktuellen Filtern gefunden._",
                "",
            ]
        )
        return "\n".join(lines)

    if normalized.sort_mode == _SORT_GROUPED_BY_COLOR:
        groups = _grouped_by_color(filtered)
        for heading, items in groups:
            lines.append(f"## {heading}")
            lines.append("")
            lines.extend(
                _render_entries(
                    items,
                    include_comments=normalized.include_comments,
                    keep_markers=normalized.keep_markers,
                    include_entry_label=False,
                )
            )
            lines.append("")
        return "\n".join(lines)

    lines.extend(["## Chronologisch", ""])
    lines.extend(
        _render_entries(
            _sort_historically(filtered),
            include_comments=normalized.include_comments,
            keep_markers=normalized.keep_markers,
            include_entry_label=True,
        )
    )
    lines.append("")
    return "\n".join(lines)


def _filtered_entries(
    entries: tuple[AnnotationExportEntry, ...],
    options: AnnotationExportOptions,
) -> list[AnnotationExportEntry]:
    selected_colors = set(options.include_colors)
    out: list[AnnotationExportEntry] = []
    for entry in entries:
        if entry.kind == "glossary":
            if options.include_glossary:
                out.append(entry)
            continue
        if entry.color in selected_colors:
            out.append(entry)
    return _sort_historically(out)


def _sort_historically(entries: list[AnnotationExportEntry]) -> list[AnnotationExportEntry]:
    def _key(item: AnnotationExportEntry) -> tuple[str, int, int, str]:
        created = str(item.created_at or "").strip()
        if not created:
            created = "9999-12-31T23:59:59+00:00"
        return (created, int(item.start), int(item.end), str(item.highlight_id))

    return sorted(entries, key=_key)


def _grouped_by_color(
    entries: list[AnnotationExportEntry],
) -> list[tuple[str, list[AnnotationExportEntry]]]:
    grouped: "OrderedDict[str, list[AnnotationExportEntry]]" = OrderedDict()
    for entry in entries:
        if entry.kind == "glossary":
            key = "glossary"
        else:
            key = entry.color
        grouped.setdefault(key, []).append(entry)

    out: list[tuple[str, list[AnnotationExportEntry]]] = []
    for key, items in grouped.items():
        if key == "glossary":
            heading = "Glossar"
        else:
            heading = f"Farbe: {color_display_name(key)}"
        out.append((heading, _sort_historically(items)))
    return out


def _render_entries(
    entries: list[AnnotationExportEntry],
    *,
    include_comments: bool,
    keep_markers: bool,
    include_entry_label: bool,
) -> list[str]:
    lines: list[str] = []
    for index, entry in enumerate(entries):
        rendered_excerpt = _render_excerpt(entry.text, entry.color, keep_markers)
        if include_entry_label:
            lines.append(f"> **{_entry_label(entry)}**: {rendered_excerpt}")
        else:
            lines.append(f"> {rendered_excerpt}")
        if include_comments and entry.comment:
            comment_label = "Glossar-Kommentar" if entry.kind == "glossary" else "Kommentar"
            lines.append(f"> {comment_label}: {_normalize_inline(entry.comment)}")
        if index < (len(entries) - 1):
            lines.append("")
    return lines


def _entry_label(entry: AnnotationExportEntry) -> str:
    if entry.kind == "glossary":
        return "Glossar"
    return color_display_name(entry.color)


def _render_excerpt(text: str, color: str, keep_markers: bool) -> str:
    excerpt = _normalize_inline(text)
    escaped = html.escape(excerpt)
    if not keep_markers:
        return escaped
    color_name = _color_css_value(color)
    return f"<mark style=\"background-color: {color_name};\">{escaped}</mark>"


def _color_css_value(color: str) -> str:
    normalized = normalize_color(color)
    return str(_DEFAULT_COLOR_CSS.get(normalized, "khaki"))


def _normalize_inline(text: str) -> str:
    value = str(text or "").replace("\r\n", "\n")
    compact = " ".join(value.split())
    return compact.strip()


__all__ = [
    "AnnotationExportData",
    "AnnotationExportEntry",
    "AnnotationExportOptions",
    "build_annotation_export_markdown",
    "collect_annotation_export_data",
    "color_display_name",
]
