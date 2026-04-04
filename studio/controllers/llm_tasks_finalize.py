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


def _build_map_diagnostic_report(
    *,
    label: str,
    markdown: str,
    meta: dict,
    query: str,
    context_text: str,
) -> str:
    summary = dict(meta or {})
    metrics = dict(summary.get("metrics", {}) or {})
    tool_calls = dict(summary.get("tool_calls", metrics.get("tool_calls", {})) or {})
    retrieval_strategy = str(summary.get("retrieval_strategy", metrics.get("retrieval_strategy", "")) or "").strip()
    retrieval_policy = dict(summary.get("retrieval_policy", {}) or {})
    agent_budget_controlled = bool(
        summary.get("agent_budget_controlled", metrics.get("agent_budget_controlled", False))
    )
    trace_rows = list(summary.get("trace_steps", []) or [])
    retrieval_steps = list(summary.get("retrieval_agent_steps", []) or [])
    draft_progress = list(summary.get("draft_progress", []) or [])
    snippets = [str(x or "") for x in list(summary.get("rag_snippets_preview", []) or [])]
    fact_issues = [str(x or "") for x in list(summary.get("fact_issues_list", []) or [])]
    structure_validation = dict(summary.get("structure_validation", {}) or {})
    structure_stats = dict(structure_validation.get("stats", {}) or {})
    structure_issues = list(structure_validation.get("issues", []) or [])
    grounding_validation = dict(summary.get("grounding_validation", {}) or {})
    grounding_issues = [str(x or "") for x in list(summary.get("grounding_issues", []) or [])]
    required_main_nodes = [
        str(x or "")
        for x in list(summary.get("required_main_nodes", metrics.get("required_main_nodes", [])) or [])
        if str(x or "").strip()
    ]
    missing_required_main_nodes = [
        str(x or "")
        for x in list(
            summary.get(
                "missing_required_main_nodes",
                grounding_validation.get("missing_required_main_nodes", metrics.get("missing_required_main_nodes", [])),
            )
            or []
        )
        if str(x or "").strip()
    ]
    draft_markdown_raw = str(summary.get("draft_markdown_raw", "") or "")
    draft_logging_enabled = bool(summary.get("log_draft_markdown", metrics.get("log_draft_markdown", False)))
    if draft_markdown_raw and not draft_logging_enabled:
        draft_logging_enabled = True
    run_artifact_path = str(summary.get("run_artifact_path", "") or "").strip()
    trace_path = str(summary.get("trace_path", "") or "").strip()
    workflow_id = str(summary.get("workflow_id", "") or "").strip()
    profile_id = str(summary.get("profile_id", "") or "").strip()
    errors = [str(x or "") for x in list(summary.get("errors", []) or [])]

    lines: list[str] = [
        f"# {label} Diagnose-Report",
        "",
        "## Laufkontext",
        f"- Zeit: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Workflow: {workflow_id or '-'}",
        f"- Profil: {profile_id or '-'}",
        f"- Retrieval-Strategie: {retrieval_strategy or '-'}",
        f"- Dauer: {_format_duration_seconds(metrics.get('elapsed_ms', 0.0))}",
        f"- Schritte: {_int(metrics.get('steps', 0), 0)}",
        f"- Rohentwurf-Logging: {'aktiv' if draft_logging_enabled else 'aus'}",
    ]
    if retrieval_strategy == "agent":
        if agent_budget_controlled:
            lines.append("- Agent-Steuerung: Budget-basiert")
    if run_artifact_path:
        lines.append(f"- Laufartefakt: `{run_artifact_path}`")
    if trace_path:
        lines.append(f"- Trace-Pfad: `{trace_path}`")

    lines.extend(["", "## Fokusfrage", f"- {str(query or '').strip() or '(leer)'}", ""])

    lines.append("## Tool-Aufrufe")
    if tool_calls:
        for name, count in sorted(tool_calls.items(), key=lambda kv: str(kv[0])):
            lines.append(f"- `{name}`: {_int(count, 0)}")
    else:
        lines.append("- Keine Tool-Aufrufe protokolliert.")

    lines.extend(["", "## Retrieval-Agent Schritte"])
    if retrieval_steps:
        lines.append("| # | Aktion | Tool | Treffer | Grund/Fehler |")
        lines.append("|---|---|---|---:|---|")
        for row in retrieval_steps[:40]:
            item = dict(row or {})
            iteration = _int(item.get("iteration", 0), 0)
            action = str(item.get("action", "") or "").strip() or "-"
            tool = str(item.get("tool", "") or "").strip() or "-"
            hits = _int(item.get("hits", 0), 0)
            reason = str(item.get("reason", "") or item.get("error", "") or "").strip()
            raw = str(item.get("raw", "") or "").strip()
            if raw:
                if reason:
                    reason = f"{reason} | raw={raw}"
                else:
                    reason = f"raw={raw}"
            reason = reason.replace("\n", " ").replace("|", "/")
            if len(reason) > 120:
                reason = reason[:117].rstrip() + "..."
            lines.append(f"| {iteration} | {action} | {tool} | {hits} | {reason or '-'} |")
        if len(retrieval_steps) > 40:
            lines.append(f"- Weitere {len(retrieval_steps) - 40} Schritte im Laufartefakt.")
    else:
        lines.append("- Keine Retrieval-Agent-Schritte vorhanden.")

    lines.extend(["", "## Retrieval-Snippets"])
    if snippets:
        for idx, row in enumerate(snippets[:12], 1):
            snippet = str(row or "").strip().replace("\n", " ")
            if len(snippet) > 260:
                snippet = snippet[:257].rstrip() + "..."
            lines.append(f"{idx}. {snippet}")
    else:
        lines.append("- Keine Snippets protokolliert.")

    lines.extend(["", "## Faktentreue"])
    if fact_issues:
        lines.append(f"- Probleme gefunden: {len(fact_issues)}")
        for row in fact_issues[:12]:
            lines.append(f"  - {row}")
    else:
        lines.append("- Keine Faktentreue-Probleme protokolliert.")

    lines.extend(["", "## Schritt-Trace"])
    if trace_rows:
        for row in trace_rows[:48]:
            item = dict(row or {})
            step_id = str(item.get("step_id", "") or "").strip() or "step"
            status = str(item.get("status", "") or "").strip() or "n/a"
            duration_ms = _float(item.get("duration_ms", 0.0), 0.0)
            reason = str(item.get("reason", "") or "").strip()
            output_preview = str(item.get("output", "") or "").replace("\n", " ")
            if len(output_preview) > 180:
                output_preview = output_preview[:177].rstrip() + "..."
            base = f"- `{step_id}` | status={status} | {duration_ms:.1f} ms"
            if reason:
                base += f" | reason={reason}"
            lines.append(base)
            if output_preview:
                lines.append(f"  - output: {output_preview}")
    else:
        lines.append("- Kein Schritt-Trace vorhanden.")

    lines.extend(["", "## Map-Aufbau"])
    if draft_progress:
        for row in draft_progress[:24]:
            item = dict(row or {})
            phase = str(item.get("phase", "") or "phase").strip()
            round_idx = _int(item.get("round", 0), 0)
            accepted = bool(item.get("accepted", False))
            node_count = _int(item.get("node_count", item.get("merged_nodes", 0)), 0)
            score = _float(item.get("score", item.get("score_before", 0.0)), 0.0)
            focus = str(item.get("focus", "") or "").strip()
            focus_part = f" | focus={focus}" if focus else ""
            lines.append(
                f"- Runde {round_idx} | {phase} | {'uebernommen' if accepted else 'verworfen'} | "
                f"Knoten={node_count} | Score={score:.2f}{focus_part}"
            )
        if len(draft_progress) > 24:
            lines.append(f"- Weitere {len(draft_progress) - 24} Aufbau-Schritte im Laufartefakt.")
    else:
        lines.append("- Kein inkrementeller Aufbau protokolliert.")

    lines.extend(["", "## Retrieval-Policy"])
    if retrieval_policy:
        allowed_tools = list(retrieval_policy.get("allowed_tools", []) or [])
        lines.append("- Erlaubte Tools: " + (", ".join(str(x or "") for x in allowed_tools) if allowed_tools else "-"))
        lines.append(f"- Budget total: {_float(retrieval_policy.get('budget_total', 0.0), 0.0):.2f}")
        lines.append(f"- Budget verbleibend: {_float(retrieval_policy.get('budget_remaining', 0.0), 0.0):.2f}")
        lines.append(
            f"- Max no-hit Serie: {_int(retrieval_policy.get('max_consecutive_nohit', 0), 0)}"
        )
        tool_costs = dict(retrieval_policy.get("tool_costs", {}) or {})
        if tool_costs:
            lines.append(
                "- Tool-Kosten: "
                + ", ".join(
                    f"{str(name)}={_float(value, 0.0):.2f}"
                    for name, value in sorted(tool_costs.items(), key=lambda kv: str(kv[0]))
                )
            )
        duplicate_hits = _int(retrieval_policy.get("duplicate_hits", 0), 0)
        if duplicate_hits > 0:
            lines.append(f"- Duplikat-Treffer: {duplicate_hits}")
        per_tool_nohit = dict(retrieval_policy.get("per_tool_nohit", {}) or {})
        if per_tool_nohit:
            lines.append(
                "- No-Hit je Tool: "
                + ", ".join(
                    f"{str(name)}={_int(value, 0)}"
                    for name, value in sorted(per_tool_nohit.items(), key=lambda kv: str(kv[0]))
                )
            )
        per_tool_stale = dict(retrieval_policy.get("per_tool_stale", {}) or {})
        if per_tool_stale:
            lines.append(
                "- Stale je Tool: "
                + ", ".join(
                    f"{str(name)}={_int(value, 0)}"
                    for name, value in sorted(per_tool_stale.items(), key=lambda kv: str(kv[0]))
                )
            )
        policy_call_counts = dict(retrieval_policy.get("policy_call_counts", {}) or {})
        if policy_call_counts:
            lines.append(
                "- Policy-Planrufe: "
                + ", ".join(
                    f"{str(name)}={_int(value, 0)}"
                    for name, value in sorted(policy_call_counts.items(), key=lambda kv: str(kv[0]))
                )
            )
    else:
        lines.append("- Keine Retrieval-Policy protokolliert.")

    lines.extend(["", "## Halluzinations-Indikatoren"])
    indicators: list[str] = []
    if retrieval_strategy in {"rag", "agent"} and not snippets:
        indicators.append("Retrieval aktiviert, aber keine Snippets gefunden.")
    if retrieval_strategy == "agent" and not retrieval_steps:
        indicators.append("Agent-Strategie aktiv, aber keine Agent-Schritte aufgezeichnet.")
    if bool(fact_issues):
        indicators.append("Faktentreue-Prüfung hat strittige Aussagen markiert.")
    if errors:
        indicators.append("Workflow meldete Fehler.")
    if structure_validation and not bool(structure_validation.get("ok", False)):
        indicators.append("Strukturvalidierung fehlgeschlagen (Ausgabe ist kein valider MindMap/Graph-Block).")
    if missing_required_main_nodes:
        indicators.append("Pflicht-Hauptknoten fehlen in der finalen Struktur.")
    if not indicators:
        indicators.append("Keine offensichtlichen Indikatoren gefunden.")
    for row in indicators:
        lines.append(f"- {row}")

    lines.extend(["", "## Strukturvalidierung"])
    if structure_validation:
        lines.append(f"- Ok: {'ja' if bool(structure_validation.get('ok', False)) else 'nein'}")
        expected_kind = str(structure_validation.get("expected_kind", "") or "").strip()
        actual_kind = str(structure_validation.get("kind", "") or "").strip()
        if expected_kind:
            lines.append(f"- Erwarteter Typ: {expected_kind}")
        if actual_kind:
            lines.append(f"- Erkannter Typ: {actual_kind}")
        if structure_stats:
            nodes = _int(structure_stats.get("nodes", 0), 0)
            edges = _int(structure_stats.get("edges", 0), 0)
            components = _int(structure_stats.get("components", 0), 0)
            depth = _int(structure_stats.get("max_depth", 0), 0)
            lines.append(
                f"- Stats: Knoten={nodes}, Verbindungen={edges}, Komponenten={components}, Tiefe={depth}"
            )
        if structure_issues:
            lines.append("- Probleme:")
            for issue in structure_issues[:12]:
                item = dict(issue or {})
                code = str(item.get("code", "") or "").strip()
                message = str(item.get("message", "") or "").strip()
                if code and message:
                    lines.append(f"  - [{code}] {message}")
                elif message:
                    lines.append(f"  - {message}")
    else:
        lines.append("- Keine Strukturvalidierungsdaten vorhanden.")

    lines.extend(["", "## Grounding-Validierung"])
    if grounding_validation or grounding_issues or required_main_nodes:
        overlap_ratio = _float(grounding_validation.get("overlap_ratio", 0.0), 0.0)
        anchor_hits = list(grounding_validation.get("anchor_hits", []) or [])
        lines.append(f"- Overlap ratio: {overlap_ratio:.5f}")
        lines.append(f"- Anchor hits: {len(anchor_hits)}")
        if required_main_nodes:
            lines.append("- Pflicht-Hauptknoten: " + ", ".join(required_main_nodes[:12]))
        if missing_required_main_nodes:
            lines.append("- Fehlende Pflicht-Hauptknoten: " + ", ".join(missing_required_main_nodes[:12]))
        if grounding_issues:
            lines.append("- Probleme:")
            for issue in grounding_issues[:12]:
                lines.append(f"  - {str(issue or '').strip()}")
        else:
            lines.append("- Keine Grounding-Probleme protokolliert.")
    else:
        lines.append("- Keine Grounding-Daten vorhanden.")

    preview_markdown = str(markdown or "")
    if not preview_markdown.strip():
        preview_markdown = str(draft_markdown_raw or "")

    lines.extend(
        [
            "",
            "## Kontext-Vorschau",
            "```text",
            str(context_text or "")[:2500],
            "```",
            "",
            "## Ergebnis-Vorschau",
            "```text",
            str(preview_markdown or "")[:2500],
            "```",
        ]
    )
    return "\n".join(lines)


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
        kind = str(meta.get("kind", mode) or mode).strip().casefold()
        variant = str(meta.get("variant", mode) or mode).strip().casefold()
        if variant == "chunkmap" or mode.strip().casefold() == "chunkmap":
            label = "Chunk-MindMap"
        elif kind == "graph":
            label = "Graph"
        else:
            label = "MindMap"
        diagnostic_markdown = _build_map_diagnostic_report(
            label=label,
            markdown="",
            meta=dict(meta or {}),
            query=query,
            context_text=context_text,
        )
        diag_title = f"{label} Diagnose {datetime.now().strftime('%H:%M')}"
        self._canvas.tabs.add_tab(title=diag_title, content=diagnostic_markdown, read_only=True)
        self._set_status_feedback_payload(
            {
                "mindmap": {
                    "query": query,
                    "mode": mode,
                    "markdown": "",
                    "diagnostic_report": diagnostic_markdown[:12000],
                },
                "context_preview": context_text[:4000],
                "meta": {
                    **dict(meta or {}),
                    "diagnostic_tab_title": diag_title,
                    "diagnostic_report": diagnostic_markdown[:12000],
                },
            }
        )
        if reason == "context_too_large" and detail:
            return False, detail
        if detail:
            return (
                False,
                "Es konnte keine Struktur erzeugt werden.\n"
                f"Detail: {detail}\nDiagnose-Tab: {diag_title}",
            )
        return (
            False,
            "Es konnte keine Struktur erzeugt werden.\n"
            f"Grund: {reason or 'unbekannt'}\nDiagnose-Tab: {diag_title}",
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
    diagnostic_markdown = _build_map_diagnostic_report(
        label=label,
        markdown=markdown,
        meta=enriched_meta,
        query=query,
        context_text=context_text,
    )
    diag_title = f"{label} Diagnose {datetime.now().strftime('%H:%M')}"
    self._canvas.tabs.add_tab(title=diag_title, content=diagnostic_markdown, read_only=True)
    enriched_meta["diagnostic_report"] = diagnostic_markdown[:12000]
    enriched_meta["diagnostic_tab_title"] = diag_title
    self._set_status_feedback_payload(
        {
            "mindmap": {
                "query": query,
                "mode": mode,
                "markdown": markdown[:12000],
                "diagnostic_report": diagnostic_markdown[:12000],
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
    extra_line = f"Diagnose-Tab: {diag_title}"
    if str(enriched_meta.get("run_artifact_path", "") or "").strip():
        extra_line += f" | Laufartefakt: {enriched_meta.get('run_artifact_path')}"
    return (True, "\n".join([info_text, extra_line]).strip())
