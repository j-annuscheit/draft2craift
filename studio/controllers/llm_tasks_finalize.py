"""Result-finalization helpers for :mod:`studio.controllers.llm_tasks`."""
from __future__ import annotations

from datetime import datetime

from shared.services.highlights.store import get_highlight_store


def _finalize_glossary(
    self,
    *,
    entries: list[dict],
    meta: dict,
    context_text: str,
) -> tuple[bool, str]:
    reason = str(meta.get("reason", "") or "")
    if not entries:
        detail = str(meta.get("error", "") or "").strip()
        if reason == "context_too_large" and detail:
            return False, detail
        if reason in {"empty", "parse_failed"}:
            retried = bool(meta.get("retried", False))
            parse_mode = str(meta.get("parse", "") or "").strip() or "n/a"
            return (
                False,
                "Es konnten keine Glossar-Einträge erzeugt werden.\n"
                "Die Modellausgabe war leer oder nicht als Glossar parsebar.\n"
                f"Retry ausgeführt: {'ja' if retried else 'nein'} | Parse-Modus: {parse_mode}",
            )
        return (
            False,
            "Es konnten keine Glossar-Einträge erzeugt werden.\n"
            f"Grund: {reason or 'unbekannt'}",
        )

    count = get_highlight_store().replace_glossary_entries(
        entries=entries,
        panel_scope="*",
        apply_all_tabs=True,
    )
    self._set_status_feedback_payload(
        {
            "glossary": {
                "count": count,
                "entries": entries[:64],
            },
            "context_preview": context_text[:4000],
            "meta": meta,
        }
    )
    self._glossary_feedback_bar.activate("glossary")
    self._refresh_preview_overlays()
    overlays_on = get_highlight_store().is_glossary_enabled()
    self._show_status(
        (
            f"Glossar aktualisiert: {count} Begriffe."
            if overlays_on
            else f"Glossar aktualisiert: {count} Begriffe (Overlay aktuell AUS)."
        ),
        4500,
    )
    self._autosave_schedule_fn(350)
    return True, f"{count} Begriffe"


def _finalize_mindmap(
    self,
    *,
    markdown: str,
    meta: dict,
    context_text: str,
    query: str,
    mode: str,
) -> tuple[bool, str]:
    reason = str(meta.get("reason", "") or "")
    if not str(markdown or "").strip():
        detail = str(meta.get("error", "") or "").strip()
        if reason == "context_too_large" and detail:
            return False, detail
        return (
            False,
            "Es konnte keine Struktur erzeugt werden.\n"
            f"Grund: {reason or 'unbekannt'}",
        )

    kind = str(meta.get("kind", mode) or mode).strip().casefold()
    variant = str(meta.get("variant", mode) or mode).strip().casefold()
    if variant == "chunkmap" or mode.strip().casefold() == "chunkmap":
        label = "Chunk-MindMap"
    elif kind == "graph":
        label = "Graph"
    else:
        label = "MindMap"
    title = f"{label} {datetime.now().strftime('%H:%M')}"
    self._canvas.tabs.add_tab(title=title, content=markdown, read_only=False)
    self._set_status_feedback_payload(
        {
            "mindmap": {
                "query": query,
                "mode": mode,
                "markdown": markdown[:12000],
            },
            "context_preview": context_text[:4000],
            "meta": meta,
        }
    )
    self._glossary_feedback_bar.activate("mindmap")
    self._show_status(
        (
            f"{label} erstellt: {int(meta.get('nodes', 0) or 0)} Knoten, "
            f"{int(meta.get('edges', 0) or 0)} Verbindungen."
        ),
        5000,
    )
    self._autosave_schedule_fn(350)
    return (
        True,
        f"{label}: {int(meta.get('nodes', 0) or 0)} Knoten, "
        f"{int(meta.get('edges', 0) or 0)} Verbindungen",
    )

