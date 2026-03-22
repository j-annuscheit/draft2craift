"""Result-finalization helpers for :mod:`studio.controllers.llm_tasks`."""
from __future__ import annotations

from datetime import datetime

from shared.domain.graph_codec import extract_graph_spec
from shared.domain.graph_validation import GraphValidationLimits, validate_graph_spec
from shared.services.highlights.store import get_highlight_store


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _format_duration_seconds(value: object) -> str:
    seconds = max(0.0, _float(value, 0.0) / 1000.0)
    if seconds >= 10.0:
        return f"{seconds:.1f} s"
    return f"{seconds:.2f} s"


def _count_phrase(count: int, singular: str, plural: str | None = None) -> str:
    amount = max(0, int(count))
    plural_text = str(plural or f"{singular}e")
    label = singular if amount == 1 else plural_text
    return f"{amount} {label}"


def _tool_call_count(metrics: dict, tool_name: str) -> int:
    tool_calls = dict(metrics.get("tool_calls", {}) or {})
    if tool_name in tool_calls:
        return _int(tool_calls.get(tool_name, 0), 0)
    return _int(tool_calls.get(f"{tool_name}#cache_miss", 0), 0)


def _normalize_map_result_detail_level(value: object) -> str:
    text = str(value or "").strip().casefold()
    if text in {"compact", "standard", "detailed"}:
        return text
    return "auto"


def _resolve_map_result_detail_level(self) -> str:
    raw = "auto"
    getter = getattr(self, "_get_agentic_settings", None)
    if callable(getter):
        try:
            settings = getter()
            raw = str(getattr(settings, "map_result_detail_level", "auto") or "auto")
        except Exception:
            raw = "auto"
    level = _normalize_map_result_detail_level(raw)
    if level != "auto":
        return level
    user_mode = ""
    user_mode_getter = getattr(self, "_get_user_mode", None)
    if callable(user_mode_getter):
        try:
            user_mode = str(user_mode_getter() or "").strip().casefold()
        except Exception:
            user_mode = ""
    if user_mode == "simple":
        return "compact"
    if user_mode == "expert":
        return "detailed"
    return "standard"


def _derive_map_meta(markdown: str, meta: dict) -> dict:
    summary = dict(meta or {})
    spec = extract_graph_spec(str(markdown or ""))
    if spec is None:
        return summary

    report = validate_graph_spec(
        spec,
        limits=GraphValidationLimits(
            min_nodes=0,
            max_nodes=10_000,
            max_edges=20_000,
            max_depth=1_000,
            require_single_root=False,
            allow_cycles=True,
            max_isolated_nodes=10_000,
            require_connected=False,
            min_word_letters=1,
        ),
    )
    stats = dict(report.stats or {})
    summary["kind"] = str(summary.get("kind", spec.kind) or spec.kind or "")
    summary["title"] = str(summary.get("title", spec.title) or spec.title or "")
    for key in ("nodes", "edges", "roots", "isolated_nodes", "components", "max_depth"):
        summary[key] = _int(stats.get(key, summary.get(key, 0)), _int(summary.get(key, 0), 0))
    if not str(summary.get("trace_path", "") or "").strip():
        metrics = dict(summary.get("metrics", {}) or {})
        trace_path = str(metrics.get("trace_path", "") or "").strip()
        if trace_path:
            summary["trace_path"] = trace_path

    root_label = ""
    primary_children: list[str] = []
    if spec.roots:
        root_id = str(spec.roots[0] or "").strip()
        root_node = dict(spec.nodes or {}).get(root_id)
        if root_node is not None:
            root_label = str(getattr(root_node, "label", "") or "").strip()
            child_ids = list(getattr(root_node, "children", []) or [])
            if len(child_ids) == 1:
                first_child = dict(spec.nodes or {}).get(str(child_ids[0] or "").strip())
                grand_children = list(getattr(first_child, "children", []) or []) if first_child else []
                if len(grand_children) >= 2:
                    child_ids = grand_children
            for child_id in child_ids[:5]:
                node = dict(spec.nodes or {}).get(str(child_id or "").strip())
                label = str(getattr(node, "label", "") or "").strip()
                if label:
                    primary_children.append(label)
    sample_labels: list[str] = []
    for node in list(dict(spec.nodes or {}).values())[:5]:
        label = str(getattr(node, "label", "") or "").strip()
        if label:
            sample_labels.append(label)
    if root_label:
        summary["root_label"] = root_label
    if primary_children:
        summary["primary_children"] = list(primary_children)
    if sample_labels:
        summary["sample_labels"] = list(sample_labels)
    return summary


def _format_map_completion_info(
    *,
    label: str,
    markdown: str,
    meta: dict,
    query: str,
    detail_level: str,
) -> tuple[str, dict]:
    summary = _derive_map_meta(markdown, meta)
    nodes = max(0, _int(summary.get("nodes", 0), 0))
    edges = max(0, _int(summary.get("edges", 0), 0))
    depth = max(0, _int(summary.get("max_depth", 0), 0))
    components = max(0, _int(summary.get("components", 0), 0))
    roots = max(0, _int(summary.get("roots", 0), 0))
    isolated_nodes = max(0, _int(summary.get("isolated_nodes", 0), 0))
    cleanup = dict(summary.get("cleanup", {}) or {})
    candidate_review = dict(summary.get("candidate_review", {}) or {})
    metrics = dict(summary.get("metrics", {}) or {})
    coverage_ratio = max(0.0, min(1.0, _float(summary.get("coverage_ratio", 0.0), 0.0)))
    steps = max(0, _int(metrics.get("steps", 0), 0))
    llm_calls = max(0, _tool_call_count(metrics, "llm.generate"))
    elapsed = _format_duration_seconds(metrics.get("elapsed_ms", 0.0))
    branch_labels = list(summary.get("primary_children", []) or [])
    sample_labels = list(summary.get("sample_labels", []) or [])

    first_line = f"{_count_phrase(nodes, 'Knoten', 'Knoten')}, {_count_phrase(edges, 'Verbindung', 'Verbindungen')}"
    if depth > 0:
        first_line += f", Tiefe {depth}"
    lines = [first_line]

    if detail_level in {"standard", "detailed"}:
        focus = str(query or "").strip()
        if focus:
            lines.append(f"Fokus: {focus}")
        structure_bits: list[str] = []
        if components > 0:
            structure_bits.append(_count_phrase(components, "Komponente", "Komponenten"))
        if roots > 0:
            structure_bits.append(_count_phrase(roots, "Wurzel", "Wurzeln"))
        if isolated_nodes > 0:
            structure_bits.append(f"{_count_phrase(isolated_nodes, 'isolierter Knoten', 'isolierte Knoten')}")
        if structure_bits:
            lines.append(f"Struktur: {', '.join(structure_bits)}.")
        if coverage_ratio > 0.0:
            lines.append(f"Abdeckung: {int(round(coverage_ratio * 100.0))}%.")
        label_list = branch_labels or sample_labels
        if label_list:
            prefix = "Hauptaeste" if branch_labels else "Beispielknoten"
            lines.append(f"{prefix}: {', '.join(label_list[:4])}.")
        runtime_bits: list[str] = []
        if llm_calls > 0:
            runtime_bits.append(f"{llm_calls} LLM-Aufrufe")
        if steps > 0:
            runtime_bits.append(f"{steps} Schritte")
        if runtime_bits:
            lines.append(f"Lauf: {', '.join(runtime_bits)}, {elapsed}.")

    if detail_level == "detailed":
        root_label = str(summary.get("root_label", "") or "").strip()
        if root_label:
            lines.append(f"Wurzel: {root_label}")
        cleanup_bits: list[str] = []
        removed_nodes = _int(cleanup.get("removed_nodes", 0), 0)
        renamed_nodes = _int(cleanup.get("renamed_nodes", 0), 0)
        merged_nodes = _int(cleanup.get("merged_nodes", 0), 0)
        if removed_nodes > 0:
            cleanup_bits.append(f"{removed_nodes} entfernt")
        if renamed_nodes > 0:
            cleanup_bits.append(f"{renamed_nodes} normalisiert")
        if merged_nodes > 0:
            cleanup_bits.append(f"{merged_nodes} zusammengefuehrt")
        if cleanup_bits:
            lines.append(f"Cleanup: {', '.join(cleanup_bits)}.")
        loop_bits: list[str] = []
        closure_round = _int(summary.get("graph_closure_round", 0), 0)
        refine_round = _int(summary.get("refine_round", 0), 0)
        expand_round = _int(summary.get("expand_round", 0), 0)
        expansion_round = _int(summary.get("expansion_round", 0), 0)
        gap_round = _int(summary.get("gap_round", 0), 0)
        if closure_round > 0:
            loop_bits.append(f"Closure {closure_round}")
        if refine_round > 0:
            loop_bits.append(f"Refine {refine_round}")
        if expand_round > 0:
            loop_bits.append(f"Expand {expand_round}")
        if expansion_round > 0:
            loop_bits.append(f"Expansion {expansion_round}")
        if gap_round > 0:
            loop_bits.append(f"Gap {gap_round}")
        if loop_bits:
            lines.append(f"Schleifen: {', '.join(loop_bits)}.")
        review_reason = str(candidate_review.get("reason", "") or "").strip()
        if review_reason:
            accepted = bool(candidate_review.get("accepted", False))
            action = "uebernommen" if accepted else "verworfen"
            lines.append(f"Stabilisierung: letzter Kandidat {action} ({review_reason}).")
        profile_id = str(summary.get("profile_id", "") or "").strip()
        workflow_id = str(summary.get("workflow_id", "") or "").strip()
        if profile_id or workflow_id:
            parts = []
            if profile_id:
                parts.append(f"Profil {profile_id}")
            if workflow_id:
                parts.append(f"Workflow {workflow_id}")
            lines.append("Agentic: " + " | ".join(parts) + ".")
        trace_path = str(summary.get("trace_path", "") or "").strip()
        if trace_path:
            lines.append(f"Trace: {trace_path}")

    return "\n".join(line for line in lines if str(line or "").strip()), summary


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
    detail_level = _resolve_map_result_detail_level(self)
    info_text, enriched_meta = _format_map_completion_info(
        label=label,
        markdown=markdown,
        meta=meta,
        query=query,
        detail_level=detail_level,
    )
    self._set_status_feedback_payload(
        {
            "mindmap": {
                "query": query,
                "mode": mode,
                "markdown": markdown[:12000],
            },
            "context_preview": context_text[:4000],
            "meta": enriched_meta,
        }
    )
    self._glossary_feedback_bar.activate("mindmap")
    nodes = _int(enriched_meta.get("nodes", 0), 0)
    edges = _int(enriched_meta.get("edges", 0), 0)
    depth = _int(enriched_meta.get("max_depth", 0), 0)
    status_text = (
        f"{label} erstellt: "
        f"{_count_phrase(nodes, 'Knoten', 'Knoten')}, "
        f"{_count_phrase(edges, 'Verbindung', 'Verbindungen')}."
    )
    if depth > 0:
        status_text = status_text[:-1] + f", Tiefe {depth}."
    self._show_status(
        status_text,
        5000,
    )
    self._autosave_schedule_fn(350)
    return (True, info_text)
