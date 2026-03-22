"""Internal support helpers for map workers.

This module intentionally contains shared algorithms that would otherwise be
duplicated across many worker files: parsing, repair prompts, structural
validation, grounding heuristics and merge/closure helpers.

The registered workers live in sibling modules within this package.
"""
from __future__ import annotations

import json
import re
from typing import Any

from shared.domain.graph_codec import extract_graph_spec, spec_to_markdown
from shared.domain.graph_spec import GraphSpec
from shared.domain.graph_validation import (
    GraphValidationLimits,
    validate_graph_spec,
)

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.graph_candidate_review import review_graph_candidate
from shared.services.agentic.graph_closure import (
    component_groups,
    component_overview_text,
    connect_components_minimally,
    sanitize_graph_spec,
)
from shared.services.agentic.graph_grounding import evaluate_graph_grounding

_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")
_GENERIC_FENCE_RE = re.compile(
    r"```(?:[A-Za-z0-9_-]+)?[ \t]*\n(?P<body>[\s\S]*?)\n```",
    flags=re.MULTILINE,
)


def resolve_mode_scope(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    mode = str(ctx.request.get("mode", "mindmap") or "mindmap").strip().casefold()
    if mode not in {"mindmap", "graph", "chunkmap"}:
        mode = "mindmap"
    scope = str(ctx.request.get("scope", "selection") or "selection").strip().casefold()
    return StepOutcome(value={"mode": mode, "scope": scope})


def collect_context(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    return StepOutcome(value={"context_text": str(ctx.request.get("context_text", "") or "")})


def plan_focus(ctx, step, projected):  # noqa: ANN001
    """Passes through user query and mode — no LLM call."""
    _ = step, projected
    query = str(ctx.request.get("query", "") or "").strip()
    mode_info = dict(ctx.state.get("map_mode_scope", {}) or {})
    return StepOutcome(value={"query": query, "mode": mode_info.get("mode", "mindmap")})


def _mode_tag(mode: str) -> str:
    return "graph" if str(mode or "").strip().casefold() == "graph" else "mindmap"


def _prompt_text(value: object) -> str:
    return str(value or "").strip()


def _prompt_section(title: str, value: object) -> str:
    return f"{title}:\n{_prompt_text(value)}\n\n"


def _unterminated_fence_body(raw: str) -> str:
    text = str(raw or "")
    if text.count("```") % 2 == 0:
        return ""
    start = text.rfind("```")
    if start < 0:
        return ""
    body = text[start + 3 :]
    if "\n" in body:
        body = body.split("\n", 1)[1]
    return str(body or "").strip()


def _has_structured_hint(raw: str) -> bool:
    text = str(raw or "")
    if "```" in text:
        return True
    if _JSON_OBJECT_RE.search(text) is not None:
        return True
    lowered = text.casefold()
    return "graph-ausgabe" in lowered or "mindmap-ausgabe" in lowered


def _extract_spec_best_effort(markdown: str, *, mode: str) -> GraphSpec | None:
    raw = str(markdown or "").strip()
    if not raw:
        return None
    mode_clean = str(mode or "").strip().casefold()
    tag = _mode_tag(mode_clean)
    structured_candidates: list[str] = []

    for match in _GENERIC_FENCE_RE.finditer(raw):
        body = str(match.group("body") or "").strip()
        if not body:
            continue
        lead = str(body.splitlines()[0] if body.splitlines() else "").strip().casefold()
        if lead.startswith("graph ") or lead.startswith("flowchart "):
            structured_candidates.append(f"```mermaid\n{body}\n```")
        structured_candidates.append(body)
        structured_candidates.append(f"```{tag}\n{body}\n```")

    unterminated_body = _unterminated_fence_body(raw)
    if unterminated_body:
        structured_candidates.append(unterminated_body)
        structured_candidates.append(f"```{tag}\n{unterminated_body}\n```")

    json_match = _JSON_OBJECT_RE.search(raw)
    if json_match is not None:
        obj = str(json_match.group(0) or "").strip()
        if obj:
            structured_candidates.append(f"```{tag}\n{obj}\n```")

    fallback_candidates: list[str] = []
    if not _has_structured_hint(raw):
        fallback_candidates.extend([raw, f"```{tag}\n{raw}\n```"])

    seen: set[str] = set()
    for candidate in [*structured_candidates, *fallback_candidates]:
        key = str(candidate or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        spec = extract_graph_spec(key)
        if spec is None:
            continue
        if mode_clean in {"mindmap", "chunkmap"}:
            spec.kind = "mindmap"
        elif mode_clean == "graph":
            spec.kind = "graph"
        return spec
    return None


def draft_graphspec(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    context_text = str((ctx.state.get("map_context", {}) or {}).get("context_text", "") or "")
    focus = dict(ctx.state.get("map_focus", {}) or {})
    mode = str(focus.get("mode", "mindmap") or "mindmap").strip().casefold()
    tag = _mode_tag(mode)
    structure_check = dict(ctx.state.get("structure_check", {}) or {})
    prev_parse_failed = bool(structure_check.get("parse_failed", False))

    retry_hint = (
        f"HINWEIS: Der vorherige Versuch hat KEINEN gültigen ```{tag}``` Block geliefert. "
        f"Antworte diesmal ZWINGEND mit genau einem ```{tag} ... ``` Block.\n\n"
        if prev_parse_failed else ""
    )
    prompt = (
        retry_hint
        + f"Erzeuge eine strukturierte {mode}-Ausgabe aus dem folgenden Kontext.\n\n"
        "STRENGE GROUNDING-REGELN — diese sind absolut verbindlich:\n"
        f"- Antworte NUR mit einem einzigen ```{tag} ... ``` Block, ohne jede weitere Erklärung.\n"
        "- VERBOTEN: Allgemeines Weltwissen, Wikipedia-Fakten, Schulbuchinhalte, "
        "Begriffe die NICHT im Kontext stehen.\n"
        "- ERLAUBT: Ausschließlich Begriffe, Konzepte, Ergebnisse und Beziehungen die "
        "WORTWÖRTLICH oder SINNGEMÄSS im Kontext belegt sind.\n"
        "- Wenn der Kontext nichts über ein Konzept sagt → gehört es NICHT in die Mindmap.\n"
        "- Die Mindmap muss das TATSÄCHLICHE Dokument widerspiegeln, nicht das Thema im Allgemeinen.\n\n"
        + _prompt_section("Fokus", focus.get("query", ""))
        + _prompt_section("Kontext", context_text)
    ).rstrip()
    try:
        raw_markdown = str(ctx.tools.call("llm.generate", prompt=prompt) or "")
    except Exception as exc:
        return StepOutcome(
            value={
                "markdown": "",
                "mode": mode,
                "reason": "llm_error",
                "error": str(exc),
            },
            meta={
                "context_chars": len(context_text),
                "prompt_chars": len(prompt),
            },
        )

    markdown = str(raw_markdown or "")
    reason = "ok"
    repair_reason = ""
    if not markdown.strip():
        reason = "empty_response"
    else:
        spec = _extract_spec_best_effort(markdown, mode=mode)
        if spec is not None:
            markdown = spec_to_markdown(spec)
            if f"```{tag}" not in str(raw_markdown or ""):
                reason = "normalized_response_format"
        else:
            repaired_spec, repair_reason = _repair_parse_failure_with_llm(
                ctx,
                mode=mode,
                raw_markdown=markdown,
                context_text=context_text,
                query=str(focus.get("query", "") or ""),
            )
            if repaired_spec is not None:
                markdown = spec_to_markdown(repaired_spec)
                reason = str(repair_reason or "repair_applied")
            else:
                markdown = ""
                reason = "invalid_response_format"
    return StepOutcome(
        value={
            "markdown": markdown,
            "mode": mode,
            "reason": reason,
            **({"repair_reason": repair_reason} if repair_reason else {}),
        },
        meta={
            "context_chars": len(context_text),
            "prompt_chars": len(prompt),
        },
    )


def _policy_int(policy: dict[str, Any], key: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = policy.get(key, default)
    try:
        value = int(raw)
    except Exception:
        value = int(default)
    return max(int(min_value), min(int(max_value), int(value)))


def _policy_bool(policy: dict[str, Any], key: str, default: bool) -> bool:
    raw = policy.get(key, default)
    if isinstance(raw, bool):
        return bool(raw)
    text = str(raw or "").strip().casefold()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _cleanup_policy_enabled(policy: dict[str, Any]) -> bool:
    return _policy_bool(policy, "map_cleanup_enabled", True)


def _sanitize_spec_for_policy(
    spec: GraphSpec,
    *,
    policy: dict[str, Any],
) -> tuple[GraphSpec, dict[str, int]]:
    if not _cleanup_policy_enabled(policy):
        return spec, {}
    min_letters = _policy_int(
        policy,
        "map_node_min_word_letters",
        3,
        min_value=1,
        max_value=12,
    )
    merge_similar_nodes = _policy_bool(
        policy,
        "map_merge_similar_nodes_enabled",
        str(spec.kind or "").strip().casefold() in {"mindmap", "chunkmap"},
    )
    cleaned_spec, cleanup_info = sanitize_graph_spec(
        spec,
        min_word_letters=min_letters,
        merge_similar_nodes=merge_similar_nodes,
    )
    removed = int(getattr(cleanup_info, "removed_nodes", 0) or 0)
    renamed = int(getattr(cleanup_info, "renamed_nodes", 0) or 0)
    merged = int(getattr(cleanup_info, "merged_nodes", 0) or 0)
    if removed > 0 or renamed > 0 or merged > 0:
        return cleaned_spec, {
            "removed_nodes": removed,
            "renamed_nodes": renamed,
            "merged_nodes": merged,
        }
    return cleaned_spec, {}


def _validation_limits(policy: dict, *, mode: str) -> GraphValidationLimits:
    mode_clean = str(mode or "").strip().casefold()
    hierarchical = mode_clean in {"mindmap", "chunkmap"}
    return GraphValidationLimits(
        min_nodes=_policy_int(policy, "map_min_nodes", 1, min_value=1, max_value=2000),
        max_nodes=_policy_int(policy, "map_max_nodes", 96, min_value=1, max_value=2000),
        max_edges=_policy_int(policy, "map_max_edges", 320, min_value=0, max_value=4000),
        max_depth=_policy_int(policy, "map_max_depth", 12, min_value=1, max_value=200),
        require_single_root=_policy_bool(
            policy,
            "map_require_single_root",
            hierarchical,
        ),
        allow_cycles=_policy_bool(
            policy,
            "map_allow_cycles",
            (not hierarchical),
        ),
        max_isolated_nodes=_policy_int(
            policy,
            "map_max_isolated_nodes",
            0 if hierarchical else 12,
            min_value=0,
            max_value=2000,
        ),
        require_connected=_policy_bool(
            policy,
            "map_require_connected_graph",
            mode_clean in {"graph", "mindmap", "chunkmap"},
        ),
        min_word_letters=_policy_int(
            policy,
            "map_node_min_word_letters",
            3,
            min_value=1,
            max_value=12,
        ),
    )


def _parse_and_validate(
    *,
    markdown: str,
    mode: str,
    policy: dict[str, Any],
) -> tuple[GraphSpec | None, dict[str, Any]]:
    spec = _extract_spec_best_effort(markdown, mode=mode)
    if spec is None:
        return None, {
            "ok": False,
            "reason": "parse_failed",
            "issues": [
                {
                    "code": "parse_failed",
                    "message": "Could not parse markdown into GraphSpec.",
                    "severity": "error",
                }
            ],
            "stats": {
                "nodes": 0,
                "edges": 0,
                "roots": 0,
                "isolated_nodes": 0,
                "components": 0,
                "max_depth": 0,
            },
        }
    cleanup_meta: dict[str, int] = {}
    spec, cleanup_meta = _sanitize_spec_for_policy(spec, policy=dict(policy or {}))
    limits = _validation_limits(dict(policy or {}), mode=mode or spec.kind)
    report = validate_graph_spec(spec, limits=limits)
    reason = "ok" if report.ok else "schema_invalid"
    if not report.ok:
        codes = {
            str(getattr(item, "code", "") or "").strip()
            for item in list(report.issues or [])
        }
        if "disconnected_graph" in codes:
            reason = "disconnected_graph"
    return spec, {
        "ok": bool(report.ok),
        "reason": reason,
        "kind": str(spec.kind or mode or "mindmap"),
        "issues": [issue.to_dict() for issue in list(report.issues or [])],
        "stats": dict(report.stats or {}),
        "normalized_markdown": spec_to_markdown(spec),
        **({"cleanup": cleanup_meta} if cleanup_meta else {}),
    }


def _append_issue(
    issues: list[dict[str, Any]],
    *,
    code: str,
    message: str,
    severity: str = "error",
) -> None:
    existing = {
        str(item.get("code", "") or "").strip()
        for item in list(issues or [])
        if isinstance(item, dict)
    }
    if code in existing:
        return
    issues.append({"code": code, "message": message, "severity": severity})


def _apply_grounding_to_payload(
    *,
    spec: GraphSpec | None,
    payload: dict[str, Any],
    mode: str,
    context_text: str,
    query: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    out = dict(payload or {})
    grounding = evaluate_graph_grounding(
        spec=spec,
        mode=mode,
        context_text=context_text,
        query=query,
        policy=policy,
    )
    out["grounding"] = grounding
    if not bool(grounding.get("enabled", False)) or bool(grounding.get("ok", True)):
        return out
    issues = list(out.get("issues", []) or [])
    reason = str(grounding.get("reason", "grounding_insufficient") or "grounding_insufficient")
    if reason == "meta_labels_detected":
        _append_issue(
            issues,
            code="meta_labels_detected",
            message="Graph contains meta or instruction-like node labels instead of source-grounded concepts.",
        )
    _append_issue(
        issues,
        code="grounding_insufficient",
        message=(
            "Graph is not sufficiently grounded in the provided context. "
            f"Grounded nodes: {int(grounding.get('grounded_nodes', 0) or 0)}/"
            f"{int(grounding.get('total_nodes', 0) or 0)}."
        ),
    )
    out["issues"] = issues
    out["ok"] = False
    if str(out.get("reason", "") or "").strip() in {"", "ok"}:
        out["reason"] = reason
    elif str(reason) == "meta_labels_detected":
        out["reason"] = reason
    return out


def _repair_prompt(*, mode: str, raw_markdown: str, context_text: str, query: str) -> str:
    tag = _mode_tag(mode)
    return (
        "Konvertiere die folgende Ausgabe in ein parsebares strukturiertes Graph-Format.\n"
        "Regeln:\n"
        f"- Antworte nur mit einem einzigen ```{tag} ... ``` Block.\n"
        "- Keine Erklärtexte.\n"
        "- Erhalte die inhaltliche Struktur, entferne nur Formatfehler.\n"
        "- Nutze nur Inhalte, die im Kontext oder in der bestehenden Ausgabe belegt sind.\n\n"
        + _prompt_section("Fokusfrage", query)
        + _prompt_section("Kontext", context_text)
        + "Eingabe:\n"
        + _prompt_text(raw_markdown)
    ).rstrip()


def _repair_parse_failure_with_llm(
    ctx,  # noqa: ANN001
    *,
    mode: str,
    raw_markdown: str,
    context_text: str,
    query: str,
) -> tuple[GraphSpec | None, str]:
    if not _policy_bool(dict(ctx.policy or {}), "map_parse_repair_enabled", True):
        return None, "repair_disabled"
    try:
        repaired = str(
            ctx.tools.call(
                "llm.generate",
                prompt=_repair_prompt(
                    mode=mode,
                    raw_markdown=raw_markdown,
                    context_text=context_text,
                    query=query,
                ),
            )
            or ""
        )
    except Exception:
        return None, "repair_llm_error"
    spec = _extract_spec_best_effort(repaired, mode=mode)
    if spec is None:
        return None, "repair_parse_failed"
    return spec, "repair_applied"


def _validate_markdown_with_repair(
    ctx,  # noqa: ANN001
    *,
    markdown: str,
    mode: str,
    policy: dict[str, Any],
) -> tuple[GraphSpec | None, dict[str, Any]]:
    spec, payload = _parse_and_validate(markdown=markdown, mode=mode, policy=policy)
    if spec is not None:
        return spec, payload
    focus = dict(ctx.state.get("map_focus", {}) or {})
    context_text = str((ctx.state.get("map_context", {}) or {}).get("context_text", "") or "")
    repaired_spec, repair_reason = _repair_parse_failure_with_llm(
        ctx,
        mode=mode,
        raw_markdown=markdown,
        context_text=context_text,
        query=str(focus.get("query", "") or ""),
    )
    if repaired_spec is None:
        payload["repair_reason"] = repair_reason
        return spec, payload
    repaired_payload = _parse_and_validate(
        markdown=spec_to_markdown(repaired_spec),
        mode=mode,
        policy=policy,
    )[1]
    repaired_payload["repair_reason"] = repair_reason
    return repaired_spec, repaired_payload


def _pending_map_draft_candidate(ctx) -> dict[str, Any]:  # noqa: ANN001
    candidates = dict(ctx.state.get("_candidates", {}) or {})
    return dict(candidates.get("map_draft_candidate", {}) or {})


def _candidate_map_draft_value(
    candidate_envelope: dict[str, Any],
    *,
    fallback_mode: str,
) -> dict[str, Any]:
    raw_value = candidate_envelope.get("value")
    if isinstance(raw_value, dict):
        value = dict(raw_value)
    else:
        value = {}
    return {
        "markdown": str(value.get("markdown", "") or ""),
        "mode": str(value.get("mode", fallback_mode) or fallback_mode),
    }


def validate_schema(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    draft = dict(ctx.state.get("map_draft", {}) or {})
    markdown = str(draft.get("markdown", "") or "")
    mode = str(
        draft.get("mode")
        or (ctx.state.get("map_focus", {}) or {}).get("mode")
        or "mindmap"
    ).strip().casefold()
    if not markdown.strip():
        return StepOutcome(
            value={
                "ok": False,
                "reason": "empty",
                "issues": [
                    {
                        "code": "empty_markdown",
                        "message": "Draft markdown is empty.",
                        "severity": "error",
                    }
                ],
                "stats": {
                    "nodes": 0,
                    "edges": 0,
                    "roots": 0,
                    "isolated_nodes": 0,
                    "components": 0,
                    "max_depth": 0,
                },
            }
        )
    policy = dict(ctx.policy or {})
    focus = dict(ctx.state.get("map_focus", {}) or {})
    context_text = str((ctx.state.get("map_context", {}) or {}).get("context_text", "") or "")
    query = str(focus.get("query", "") or "")
    spec, payload = _validate_markdown_with_repair(
        ctx,
        markdown=markdown,
        mode=mode,
        policy=policy,
    )
    payload = _apply_grounding_to_payload(
        spec=spec,
        payload=payload,
        mode=mode,
        context_text=context_text,
        query=query,
        policy=policy,
    )
    candidate_envelope = _pending_map_draft_candidate(ctx)
    if not candidate_envelope:
        return StepOutcome(value=payload)

    candidate_draft = _candidate_map_draft_value(candidate_envelope, fallback_mode=mode)
    candidate_mode = str(candidate_draft.get("mode", mode) or mode).strip().casefold()
    candidate_markdown = str(candidate_draft.get("markdown", "") or "")
    candidate_spec, candidate_payload = _validate_markdown_with_repair(
        ctx,
        markdown=candidate_markdown,
        mode=candidate_mode or mode,
        policy=policy,
    )
    candidate_payload = _apply_grounding_to_payload(
        spec=candidate_spec,
        payload=candidate_payload,
        mode=candidate_mode or mode,
        context_text=context_text,
        query=query,
        policy=policy,
    )
    require_single_root = _validation_limits(policy, mode=candidate_mode or mode).require_single_root
    review = review_graph_candidate(
        baseline_spec=spec,
        baseline_payload=payload,
        candidate_spec=candidate_spec,
        candidate_payload=candidate_payload,
        candidate_meta=dict(candidate_envelope.get("meta", {}) or {}),
        require_single_root=bool(require_single_root),
    )
    selected_payload = dict(candidate_payload if review.accept else payload)
    selected_payload["candidate_review"] = {
        "candidate_key": "map_draft_candidate",
        "accepted": bool(review.accept),
        "reason": str(review.reason or ""),
        "meta": dict(candidate_envelope.get("meta", {}) or {}),
        "compare": dict(review.compare or {}),
    }
    if review.accept:
        return StepOutcome(
            value=selected_payload,
            commit_candidates=("map_draft_candidate",),
        )
    return StepOutcome(
        value=selected_payload,
        discard_candidates=("map_draft_candidate",),
    )


def quality_gate(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    val = dict(ctx.state.get("map_validation", {}) or {})
    ok = bool(val.get("ok", False))
    reason = str(val.get("reason", "") or "")
    issues = list(val.get("issues", []) or [])
    if not ok and not reason:
        reason = "schema_invalid"
    return StepOutcome(
        value={
            "ok": ok,
            "reason": reason,
            "issues": issues,
        }
    )


def _close_map_prompt(
    *,
    mode: str,
    query: str,
    context_text: str,
    normalized_markdown: str,
    component_overview: str,
    round_idx: int,
    max_rounds: int,
    needs_grounding: bool,
) -> str:
    mode_clean = str(mode or "").strip().casefold()
    tag = _mode_tag(mode_clean)
    graph_term = "Mindmap" if tag == "mindmap" else "Wissensgraph"
    task_line = (
        f"Die aktuelle {graph_term}-Ausgabe ist NICHT ausreichend am Kontext geerdet.\n"
        "AUFGABE: Ersetze unpassende oder unbelegte Knoten/Relationen durch kontextbelegte Inhalte "
        "und liefere GENAU EINE zusammenhaengende Komponente.\n"
        if needs_grounding
        else (
            f"Die aktuelle {graph_term}-Ausgabe ist NICHT zusammenhaengend.\n"
            "AUFGABE: Schließe die Struktur zu GENAU EINER zusammenhaengenden Komponente.\n"
        )
    )
    return (
        task_line
        + 
        "WICHTIG: Frage explizit intern: Welche fehlenden Verbindungen oder Brueckenknoten "
        "werden benoetigt, damit alle Teilgraphen verbunden sind?\n"
        "Setze diese fehlenden Verbindungen/Knoten direkt im finalen Graphen um.\n"
        "Regeln:\n"
        f"- Antworte nur mit genau einem ```{tag} ... ``` Block.\n"
        "- Erhalte bestehende gueltige Knoten/Kanten soweit moeglich.\n"
        "- Fuege nur minimale, fachlich plausible Bruecken hinzu.\n"
        "- Nutze nur Inhalte, die im Kontext belegt sind.\n"
        "- Keine getrennten Komponenten mehr im Ergebnis.\n"
        "- Jeder Knoten braucht ein Wort (mindestens einige Buchstaben).\n"
        "- Keine Erklaerungen ausserhalb des Blocks.\n\n"
        + _prompt_section("Fokusfrage", query)
        + f"Versuch: {int(round_idx) + 1}/{int(max_rounds)}\n\n"
        + _prompt_section("Kontext", context_text)
        + _prompt_section("Aktueller Komponenten-Status", component_overview)
        + "Aktuelle Ausgabe:\n"
        + _prompt_text(normalized_markdown)
    ).rstrip()


def ensure_connected_graph(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    validation = dict(ctx.state.get("map_validation", {}) or {})
    draft = dict(ctx.state.get("map_draft", {}) or {})
    focus = dict(ctx.state.get("map_focus", {}) or {})
    mode = str(
        validation.get("kind")
        or draft.get("mode")
        or focus.get("mode")
        or "graph"
    ).strip().casefold()
    if mode not in {"graph", "mindmap", "chunkmap"}:
        return StepOutcome(value={"retry": False, "reason": "not_map_mode"})

    policy = dict(ctx.policy or {})
    max_rounds = _policy_int(policy, "graph_connect_max_tries", 3, min_value=0, max_value=12)
    round_idx = int(ctx.state.get("graph_closure_round", 0) or 0)
    force_connect_on_max = _policy_bool(policy, "graph_force_connect_on_max_tries", True)
    force_applied = bool(ctx.state.get("graph_force_applied", False))
    stats = dict(validation.get("stats", {}) or {})
    issues = list(validation.get("issues", []) or [])
    issue_codes = {
        str(item.get("code", "") or "").strip()
        for item in issues
        if isinstance(item, dict)
    }
    grounding = dict(validation.get("grounding", {}) or {})
    needs_grounding = bool(grounding.get("enabled", False)) and not bool(grounding.get("ok", True))
    components = int(stats.get("components", 0) or 0)
    is_connected = bool(validation.get("ok", False)) and components <= 1
    if is_connected:
        return StepOutcome(value={"retry": False, "reason": "connected", "round": round_idx})

    normalized = str(
        validation.get("normalized_markdown", "")
        or draft.get("markdown", "")
        or ""
    ).strip()
    if not normalized:
        return StepOutcome(value={"retry": False, "reason": "empty_graph", "round": round_idx})

    spec = _extract_spec_best_effort(normalized, mode=mode)
    if spec is None:
        return StepOutcome(value={"retry": False, "reason": "parse_failed", "round": round_idx})
    spec, _cleanup_info = _sanitize_spec_for_policy(spec, policy=policy)
    normalized = spec_to_markdown(spec)
    groups = component_groups(spec)
    if len(groups) <= 1 and (not needs_grounding):
        return StepOutcome(
            value={"retry": False, "reason": "connected", "round": round_idx},
            updates={
                "state.map_draft.markdown": normalized,
                "state.map_draft.mode": _mode_tag(mode),
            },
        )
    if round_idx >= max_rounds:
        if force_connect_on_max and (not force_applied):
            edge_label = str(policy.get("graph_bridge_label", "bridge") or "bridge").strip()
            forced_spec, added = connect_components_minimally(
                spec,
                edge_label=edge_label or "bridge",
            )
            if added > 0 and len(groups) > 1:
                return StepOutcome(
                    value={
                        "retry": True,
                        "reason": "force_connect_retry",
                        "round": round_idx,
                    },
                    updates={
                        "state.graph_force_applied": True,
                    },
                    candidate_writes={
                        "map_draft_candidate": {
                            "write_to": "state.map_draft",
                            "value": {
                                "markdown": spec_to_markdown(forced_spec),
                                "mode": _mode_tag(mode),
                            },
                            "meta": {
                                "intent": "closure",
                                "origin": "force_connect",
                                "allow_invalid_improvement": True,
                                "min_overlap_ratio": 0.25,
                                "skip_overlap_when_baseline_invalid": True,
                            },
                        }
                    },
                )
        return StepOutcome(
            value={
                "retry": False,
                "reason": "grounding_max_tries_reached" if needs_grounding else "max_tries_reached",
                "round": round_idx,
            }
        )

    query = str(focus.get("query", "") or "").strip()
    context_text = str((ctx.state.get("map_context", {}) or {}).get("context_text", "") or "")
    prompt = _close_map_prompt(
        mode=mode,
        query=query,
        context_text=context_text,
        normalized_markdown=normalized,
        component_overview=component_overview_text(spec),
        round_idx=round_idx,
        max_rounds=max_rounds,
        needs_grounding=needs_grounding or "grounding_insufficient" in issue_codes or "meta_labels_detected" in issue_codes,
    )
    next_round = round_idx + 1
    try:
        raw = str(ctx.tools.call("llm.generate", prompt=prompt) or "").strip()
    except Exception:
        return StepOutcome(
            value={"retry": next_round <= max_rounds, "reason": "closure_llm_error", "round": next_round},
            updates={"state.graph_closure_round": next_round},
        )
    if not raw:
        return StepOutcome(
            value={"retry": next_round <= max_rounds, "reason": "closure_empty", "round": next_round},
            updates={"state.graph_closure_round": next_round},
        )
    candidate_spec = _extract_spec_best_effort(raw, mode=mode)
    if candidate_spec is None:
        candidate_spec, _repair_reason = _repair_parse_failure_with_llm(
            ctx,
            mode=mode,
            raw_markdown=raw,
            context_text=context_text,
            query=query,
        )
    if candidate_spec is None:
        return StepOutcome(
            value={"retry": next_round <= max_rounds, "reason": "closure_parse_failed", "round": next_round},
            updates={"state.graph_closure_round": next_round},
        )
    candidate_spec, _cleanup_info2 = _sanitize_spec_for_policy(candidate_spec, policy=policy)
    return StepOutcome(
        value={"retry": True, "reason": "closure_retry", "round": next_round},
        updates={
            "state.graph_closure_round": next_round,
        },
        candidate_writes={
            "map_draft_candidate": {
                "write_to": "state.map_draft",
                "value": {
                    "markdown": spec_to_markdown(candidate_spec),
                    "mode": _mode_tag(mode),
                },
                "meta": {
                    "intent": "closure",
                    "origin": "llm_closure",
                    "allow_invalid_improvement": True,
                    "min_overlap_ratio": 0.25,
                    "skip_overlap_when_baseline_invalid": True,
                },
            }
        },
    )


def _refine_prompt(
    *,
    mode: str,
    query: str,
    context_text: str,
    normalized_markdown: str,
) -> str:
    tag = _mode_tag(mode)
    return (
        "Pruefe, ob diese Mindmap/Graph-Ausgabe inhaltlich sinnvoll verfeinert werden sollte.\n"
        "Wenn keine Verbesserung noetig ist, antworte exakt mit: NO_CHANGE\n"
        f"Wenn Verbesserung noetig ist, antworte nur mit einem einzigen ```{tag} ... ``` Block.\n"
        "- Keine Erklaerungen ausserhalb des Blocks.\n"
        "- Behalte Struktur/Kanten konsistent.\n"
        "- Nutze nur Inhalte, die im Kontext belegt sind.\n"
        "- Ergaenze nur sinnvolle Verfeinerungen.\n\n"
        + _prompt_section("Fokusfrage", query)
        + _prompt_section("Kontext", context_text)
        + "Aktuelle Ausgabe:\n"
        + _prompt_text(normalized_markdown)
    ).rstrip()


def _parse_refine_json(raw: str) -> tuple[bool | None, str]:
    match = _JSON_OBJECT_RE.search(str(raw or ""))
    if match is None:
        return None, ""
    try:
        data = json.loads(str(match.group(0) or ""))
    except Exception:
        return None, ""
    if not isinstance(data, dict):
        return None, ""
    decision = data.get("refine")
    markdown = data.get("markdown")
    if isinstance(markdown, str):
        return bool(decision) if decision is not None else None, markdown
    return bool(decision) if decision is not None else None, ""


def refine_nodes(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    validation = dict(ctx.state.get("map_validation", {}) or {})
    draft = dict(ctx.state.get("map_draft", {}) or {})
    focus = dict(ctx.state.get("map_focus", {}) or {})
    mode = str(
        validation.get("kind")
        or draft.get("mode")
        or focus.get("mode")
        or "mindmap"
    ).strip().casefold()
    if not bool(validation.get("ok", False)):
        return StepOutcome(value={"retry": False, "reason": "validation_not_ok"})

    policy = dict(ctx.policy or {})
    enabled = _policy_bool(policy, "map_refine_enabled", True)
    max_rounds = _policy_int(policy, "map_refine_max_rounds", 1, min_value=0, max_value=6)
    round_idx = int(ctx.state.get("refine_round", 0) or 0)
    if not enabled:
        return StepOutcome(value={"retry": False, "reason": "refine_disabled", "round": round_idx})
    if round_idx >= max_rounds:
        return StepOutcome(value={"retry": False, "reason": "refine_round_limit", "round": round_idx})

    normalized = str(
        validation.get("normalized_markdown", "")
        or draft.get("markdown", "")
        or ""
    ).strip()
    if not normalized:
        return StepOutcome(value={"retry": False, "reason": "empty_map", "round": round_idx})

    query = str(focus.get("query", "") or "")
    context_text = str((ctx.state.get("map_context", {}) or {}).get("context_text", "") or "")
    try:
        raw = str(
            ctx.tools.call(
                "llm.generate",
                prompt=_refine_prompt(
                    mode=mode,
                    query=query,
                    context_text=context_text,
                    normalized_markdown=normalized,
                ),
            )
            or ""
        ).strip()
    except Exception:
        return StepOutcome(value={"retry": False, "reason": "refine_llm_error", "round": round_idx})

    if not raw:
        return StepOutcome(value={"retry": False, "reason": "refine_empty", "round": round_idx})
    if raw.casefold() == "no_change":
        return StepOutcome(value={"retry": False, "reason": "no_change", "round": round_idx})

    decision, embedded_markdown = _parse_refine_json(raw)
    candidate = embedded_markdown or raw
    if decision is False and not embedded_markdown:
        return StepOutcome(value={"retry": False, "reason": "no_change_json", "round": round_idx})

    spec = _extract_spec_best_effort(candidate, mode=mode)
    if spec is None:
        return StepOutcome(value={"retry": False, "reason": "refine_parse_failed", "round": round_idx})

    improved_markdown = spec_to_markdown(spec)
    next_round = round_idx + 1
    return StepOutcome(
        value={"retry": True, "reason": "refined", "round": next_round},
        updates={
            "state.refine_round": next_round,
        },
        candidate_writes={
            "map_draft_candidate": {
                "write_to": "state.map_draft",
                "value": {
                    "markdown": improved_markdown,
                    "mode": _mode_tag(mode),
                },
                "meta": {
                    "intent": "refine",
                    "origin": "llm_refine",
                    "allow_invalid_improvement": False,
                    "min_overlap_ratio": 0.5,
                    "max_node_loss": 1,
                },
            }
        },
    )


def _expand_prompt(
    *,
    mode: str,
    query: str,
    context_text: str,
    normalized_markdown: str,
    round_idx: int,
    target_rounds: int,
) -> str:
    tag = _mode_tag(mode)
    return (
        "Du bist Ausbau-Agent fuer eine bestehende Mindmap/Graph-Struktur.\n"
        "Aufgabe:\n"
        "1) Wähle genau einen fachlich interessanten vorhandenen Knoten aus.\n"
        "2) Erweitere genau diesen Knoten sinnvoll um neue Unterpunkte/Relationen.\n"
        "3) Erhalte den Rest stabil und konsistent.\n"
        "Regeln:\n"
        f"- Antworte nur mit genau einem ```{tag} ... ``` Block.\n"
        "- Jeder Knoten braucht ein Wort (mindestens einige Buchstaben), sonst weglassen.\n"
        "- Ergebnis muss als eine einzige zusammenhaengende Komponente vorliegen.\n"
        "- Nutze nur Inhalte, die im Kontext belegt sind.\n"
        "- Keine Erklaerungen ausserhalb des Blocks.\n\n"
        + _prompt_section("Fokusfrage", query)
        + f"Ausbau-Runde: {int(round_idx) + 1}/{int(target_rounds)}\n\n"
        + _prompt_section("Kontext", context_text)
        + "Aktuelle Ausgabe:\n"
        + _prompt_text(normalized_markdown)
    ).rstrip()


def expand_map_depth(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    validation = dict(ctx.state.get("map_validation", {}) or {})
    draft = dict(ctx.state.get("map_draft", {}) or {})
    focus = dict(ctx.state.get("map_focus", {}) or {})
    mode = str(
        validation.get("kind")
        or draft.get("mode")
        or focus.get("mode")
        or "mindmap"
    ).strip().casefold()
    if mode not in {"mindmap", "graph", "chunkmap"}:
        return StepOutcome(value={"retry": False, "reason": "not_map_mode"})
    if not bool(validation.get("ok", False)):
        return StepOutcome(value={"retry": False, "reason": "validation_not_ok"})

    policy = dict(ctx.policy or {})
    enabled = _policy_bool(policy, "map_expand_enabled", False)
    target_rounds = _policy_int(
        policy,
        "map_expand_target_depth",
        0,
        min_value=0,
        max_value=12,
    )
    round_idx = int(ctx.state.get("expand_round", 0) or 0)
    if (not enabled) or target_rounds <= 0:
        return StepOutcome(value={"retry": False, "reason": "expand_disabled", "round": round_idx})
    if round_idx >= target_rounds:
        return StepOutcome(value={"retry": False, "reason": "expand_round_limit", "round": round_idx})

    normalized = str(
        validation.get("normalized_markdown", "")
        or draft.get("markdown", "")
        or ""
    ).strip()
    if not normalized:
        return StepOutcome(value={"retry": False, "reason": "empty_map", "round": round_idx})

    query = str(focus.get("query", "") or "").strip()
    context_text = str((ctx.state.get("map_context", {}) or {}).get("context_text", "") or "")
    prompt = _expand_prompt(
        mode=mode,
        query=query,
        context_text=context_text,
        normalized_markdown=normalized,
        round_idx=round_idx,
        target_rounds=target_rounds,
    )
    try:
        raw = str(ctx.tools.call("llm.generate", prompt=prompt) or "").strip()
    except Exception:
        return StepOutcome(value={"retry": False, "reason": "expand_llm_error", "round": round_idx})
    if not raw:
        return StepOutcome(value={"retry": False, "reason": "expand_empty", "round": round_idx})
    if raw.casefold() == "no_change":
        return StepOutcome(value={"retry": False, "reason": "expand_no_change", "round": round_idx})

    candidate_spec = _extract_spec_best_effort(raw, mode=mode)
    if candidate_spec is None:
        candidate_spec, _repair_reason = _repair_parse_failure_with_llm(
            ctx,
            mode=mode,
            raw_markdown=raw,
            context_text=context_text,
            query=query,
        )
    if candidate_spec is None:
        return StepOutcome(value={"retry": False, "reason": "expand_parse_failed", "round": round_idx})
    candidate_spec, _cleanup = _sanitize_spec_for_policy(candidate_spec, policy=policy)
    if len(component_groups(candidate_spec)) > 1:
        edge_label = str(policy.get("graph_bridge_label", "bridge") or "bridge").strip()
        candidate_spec, _added = connect_components_minimally(
            candidate_spec,
            edge_label=edge_label or "bridge",
        )
    improved_markdown = spec_to_markdown(candidate_spec)
    if improved_markdown.strip() == normalized.strip():
        return StepOutcome(value={"retry": False, "reason": "expand_no_delta", "round": round_idx})
    next_round = round_idx + 1
    return StepOutcome(
        value={
            "retry": True,
            "reason": "expanded",
            "round": next_round,
            "target_rounds": target_rounds,
        },
        updates={
            "state.expand_round": next_round,
        },
        candidate_writes={
            "map_draft_candidate": {
                "write_to": "state.map_draft",
                "value": {
                    "markdown": improved_markdown,
                    "mode": _mode_tag(mode),
                },
                "meta": {
                    "intent": "expand",
                    "origin": "llm_expand",
                    "allow_invalid_improvement": False,
                    "min_overlap_ratio": 0.6,
                    "max_node_loss": 0,
                },
            }
        },
    )


def emit_to_canvas(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    draft = dict(ctx.state.get("map_draft", {}) or {})
    validation = dict(ctx.state.get("map_validation", {}) or {})
    markdown = str(
        validation.get("normalized_markdown", "")
        or draft.get("markdown", "")
        or ""
    )
    try:
        ctx.tools.call("canvas.open_text", text=markdown, title="Mindmap")
    except Exception:
        pass
    return StepOutcome(
        updates={
            "result.markdown": markdown,
            "result.mode": str(
                validation.get("kind")
                or draft.get("mode", "mindmap")
                or "mindmap"
            ),
        },
        stop=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  V2 mindmap runners — structured iterative deepening with RAG expansion
# ─────────────────────────────────────────────────────────────────────────────

def _check_structure_pure(spec: GraphSpec, *, min_word_letters: int = 3) -> dict[str, Any]:
    """Pure-Python check: connectivity, duplicate labels, self-loops."""
    issues: list[dict[str, Any]] = []

    groups = component_groups(spec)
    if len(groups) > 1:
        issues.append({
            "code": "disconnected_graph",
            "message": f"Graph hat {len(groups)} getrennte Komponenten.",
            "severity": "error",
            "details": {"component_count": len(groups)},
        })

    # duplicate labels (case-insensitive)
    label_map: dict[str, list[str]] = {}
    for nid, node in spec.nodes.items():
        key = str(node.label or nid).strip().casefold()
        label_map.setdefault(key, []).append(nid)
    dupes = {k: v for k, v in label_map.items() if len(v) > 1}
    if dupes:
        issues.append({
            "code": "duplicate_nodes",
            "message": f"{len(dupes)} Gruppen doppelter Knotenbezeichnungen gefunden.",
            "severity": "warning",
            "details": {"examples": dict(list(dupes.items())[:5])},
        })

    self_loops = [e for e in spec.edges if e.source_id == e.target_id]
    if self_loops:
        issues.append({
            "code": "self_loops",
            "message": f"{len(self_loops)} Self-Loop-Kanten gefunden.",
            "severity": "warning",
            "details": {"count": len(self_loops)},
        })

    ok = not any(iss["severity"] == "error" for iss in issues)
    return {
        "ok": ok,
        "issues": issues,
        "node_count": len(spec.nodes),
        "edge_count": len(spec.edges),
        "component_count": len(groups),
    }


def check_structure(ctx, step, projected):  # noqa: ANN001
    """Pure-Python structural check written to state.structure_check."""
    _ = step, projected
    draft = dict(ctx.state.get("map_draft", {}) or {})
    markdown = str(draft.get("markdown", "") or "")
    mode = str(draft.get("mode", "mindmap") or "mindmap")
    draft_reason = str(draft.get("reason", "") or "").strip()
    draft_error = str(draft.get("error", "") or "").strip()
    policy = dict(ctx.policy or {})
    min_letters = _policy_int(policy, "map_node_min_word_letters", 3, min_value=1, max_value=12)

    if not markdown.strip():
        message = "Kein Entwurf vorhanden."
        if draft_reason == "empty_response":
            message = "LLM lieferte im draft_map-Schritt eine leere Antwort."
        elif draft_reason == "invalid_response_format":
            message = "LLM lieferte im draft_map-Schritt kein parsebares ```mindmap```/```graph```-Format."
        elif draft_reason == "llm_error":
            message = "LLM-Fehler im draft_map-Schritt."
            if draft_error:
                message = f"{message} {draft_error}"
        return StepOutcome(value={
            "ok": False,
            "parse_failed": True,
            "reason": draft_reason or "empty_draft",
            "issues": [{"code": "parse_failed", "message": message, "severity": "error"}],
            "node_count": 0, "edge_count": 0, "component_count": 0,
        })

    spec = _extract_spec_best_effort(markdown, mode=mode)
    if spec is None:
        return StepOutcome(value={
            "ok": False,
            "parse_failed": True,
            "issues": [{"code": "parse_failed", "message": "Entwurf konnte nicht geparst werden.", "severity": "error"}],
            "node_count": 0, "edge_count": 0, "component_count": 0,
        })

    result = _check_structure_pure(spec, min_word_letters=min_letters)
    result["parse_failed"] = False
    return StepOutcome(value=result)


def fix_graph(ctx, step, projected):  # noqa: ANN001
    """LLM-based fix for structural issues (connectivity, duplicates, self-loops)."""
    _ = step, projected
    draft = dict(ctx.state.get("map_draft", {}) or {})
    markdown = str(draft.get("markdown", "") or "")
    mode = str(draft.get("mode", "mindmap") or "mindmap")
    tag = _mode_tag(mode)
    structure_check = dict(ctx.state.get("structure_check", {}) or {})
    focus = dict(ctx.state.get("map_focus", {}) or {})
    policy = dict(ctx.policy or {})

    issues = list(structure_check.get("issues", []) or [])
    issues_text = "\n".join(
        f"- [{iss.get('code', '?')}] {iss.get('message', '')}" for iss in issues
    ) or "- Allgemeine Strukturprobleme"

    # fix_graph ONLY repairs structural issues in a valid, already-parsed graph.
    # parse_failed cases are routed back to draft_map via workflow edge.
    prompt = (
        f"Repariere die folgende {mode}-Struktur. Behebe NUR die genannten Strukturprobleme.\n\n"
        f"Probleme:\n{issues_text}\n\n"
        "STRENGE REGELN:\n"
        "- Verbinde getrennte Teilgraphen zu einer zusammenhängenden Komponente.\n"
        "- Entferne oder merge Knoten mit identischen/ähnlichen Labels.\n"
        "- Entferne Self-Loops.\n"
        "- KEINE NEUEN KNOTEN hinzufügen — verwende ausschließlich die vorhandenen Knoten.\n"
        "- KEINE neuen Inhalte erfinden — nur Struktur reparieren.\n"
        f"- Antworte NUR mit einem ```{tag} ... ``` Block ohne weitere Erklärungen.\n\n"
        + _prompt_section("Thema/Fokus", focus.get("query", ""))
        + "Aktueller Graph:\n"
        + _prompt_text(markdown)
    ).rstrip()

    try:
        raw = str(ctx.tools.call("llm.generate", prompt=prompt) or "").strip()
    except Exception:
        return StepOutcome(value={"fixed": False, "reason": "llm_error"})

    if not raw:
        return StepOutcome(value={"fixed": False, "reason": "empty_response"})

    spec = _extract_spec_best_effort(raw, mode=mode)
    if spec is None:
        return StepOutcome(value={"fixed": False, "reason": "parse_failed"})

    cleaned_spec, _ = _sanitize_spec_for_policy(spec, policy=policy)
    # Ensure connectivity with Python bridge if still disconnected
    if len(component_groups(cleaned_spec)) > 1:
        edge_label = str(policy.get("graph_bridge_label", "bridge") or "bridge").strip()
        cleaned_spec, _ = connect_components_minimally(cleaned_spec, edge_label=edge_label or "bridge")

    new_markdown = spec_to_markdown(cleaned_spec)
    return StepOutcome(
        value={"fixed": True, "reason": "llm_fix"},
        updates={"state.map_draft": {"markdown": new_markdown, "mode": _mode_tag(mode)}},
    )


def validate_semantics(ctx, step, projected):  # noqa: ANN001
    """LLM-based semantic check: do nodes and edges make sense given context?"""
    _ = step, projected
    draft = dict(ctx.state.get("map_draft", {}) or {})
    markdown = str(draft.get("markdown", "") or "")
    mode = str(draft.get("mode", "mindmap") or "mindmap")
    context_text = str((ctx.state.get("map_context", {}) or {}).get("context_text", "") or "")
    focus = dict(ctx.state.get("map_focus", {}) or {})
    policy = dict(ctx.policy or {})

    if not _policy_bool(policy, "map_semantic_check_enabled", True):
        return StepOutcome(value={"ok": True, "issues": [], "reason": "check_disabled"})

    if not markdown.strip():
        return StepOutcome(value={"ok": False, "issues": [{"message": "Leerer Entwurf."}], "reason": "empty_draft"})

    prompt = (
        "Bewerte die semantische Qualität der folgenden Mindmap/Graph-Struktur.\n"
        "Prüfe:\n"
        "1. Passt das THEMA der Mindmap zum angegebenen Fokus und Kontext? "
        "(Themen-Mismatch = ok:false)\n"
        "2. Machen alle Knoten-Bezeichnungen im Kontext des Themas Sinn?\n"
        "3. Sind die Verbindungen (Kanten) zwischen Knoten logisch und sinnvoll?\n"
        "4. Gibt es inhaltlich leere, redundante oder thematisch falsche Knoten?\n"
        "5. Stimmt die Hierarchie/Struktur mit dem Thema überein?\n\n"
        "Antworte NUR mit einem JSON-Objekt:\n"
        '{"ok": true/false, "issues": ["Problem 1", "Problem 2", ...], "summary": "Kurzbeschreibung"}\n\n'
        "Setze ok=false wenn: die Mindmap ein anderes Thema behandelt als Fokus/Kontext, "
        "oder wenn strukturelle/inhaltliche Fehler vorhanden sind.\n\n"
        + _prompt_section("Thema/Fokus", focus.get("query", ""))
        + _prompt_section("Kontext", context_text)
        + "Mindmap/Graph:\n"
        + _prompt_text(markdown)
    ).rstrip()

    try:
        raw = str(ctx.tools.call("llm.generate", prompt=prompt) or "").strip()
    except Exception:
        return StepOutcome(value={"ok": True, "issues": [], "reason": "llm_error_assume_ok"})

    json_match = _JSON_OBJECT_RE.search(raw)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            return StepOutcome(value={
                "ok": bool(data.get("ok", True)),
                "issues": list(data.get("issues", [])),
                "summary": str(data.get("summary", "")),
                "reason": "llm_evaluated",
            })
        except Exception:
            pass

    # Fallback: if LLM says something positive, assume ok
    lowered = raw.casefold()
    ok_guess = "problem" not in lowered and "fehler" not in lowered and "falsch" not in lowered
    return StepOutcome(value={"ok": ok_guess, "issues": [], "reason": "llm_no_json", "raw": raw[:200]})


def revise_map(ctx, step, projected):  # noqa: ANN001
    """LLM-based map revision based on semantic issues."""
    _ = step, projected
    draft = dict(ctx.state.get("map_draft", {}) or {})
    markdown = str(draft.get("markdown", "") or "")
    mode = str(draft.get("mode", "mindmap") or "mindmap")
    tag = _mode_tag(mode)
    semantic_check = dict(ctx.state.get("semantic_check", {}) or {})
    focus = dict(ctx.state.get("map_focus", {}) or {})
    context_text = str((ctx.state.get("map_context", {}) or {}).get("context_text", "") or "")
    policy = dict(ctx.policy or {})

    issues = list(semantic_check.get("issues", []) or [])
    issues_text = "\n".join(f"- {iss}" for iss in issues[:10]) or "- Allgemeine semantische Mängel"

    prompt = (
        f"Überarbeite die folgende {mode}-Struktur, um die genannten semantischen Probleme zu beheben.\n\n"
        f"Probleme:\n{issues_text}\n\n"
        "Regeln:\n"
        "- Ersetze falsche oder unpassende Knoten durch kontextbasierte Inhalte.\n"
        "- Korrigiere fehlerhafte Verbindungen/Relationen.\n"
        "- Entferne leere, redundante oder themenfremde Knoten.\n"
        "- Behalte valide Inhalte und die Gesamtstruktur bei.\n"
        "- Graph muss zusammenhängend bleiben.\n"
        f"- Antworte NUR mit einem ```{tag} ... ``` Block.\n\n"
        + _prompt_section("Thema/Fokus", focus.get("query", ""))
        + _prompt_section("Kontext", context_text)
        + "Aktueller Graph:\n"
        + _prompt_text(markdown)
    ).rstrip()

    try:
        raw = str(ctx.tools.call("llm.generate", prompt=prompt) or "").strip()
    except Exception:
        return StepOutcome(value={"retry": False, "reason": "llm_error"})

    if not raw:
        return StepOutcome(value={"retry": False, "reason": "empty_response"})

    spec = _extract_spec_best_effort(raw, mode=mode)
    if spec is None:
        return StepOutcome(value={"retry": False, "reason": "parse_failed"})

    cleaned_spec, _ = _sanitize_spec_for_policy(spec, policy=policy)
    if len(component_groups(cleaned_spec)) > 1:
        edge_label = str(policy.get("graph_bridge_label", "bridge") or "bridge").strip()
        cleaned_spec, _ = connect_components_minimally(cleaned_spec, edge_label=edge_label or "bridge")

    new_markdown = spec_to_markdown(cleaned_spec)
    return StepOutcome(
        value={"retry": True, "reason": "revised"},
        updates={"state.map_draft": {"markdown": new_markdown, "mode": _mode_tag(mode)}},
    )


def plan_expansion(ctx, step, projected):  # noqa: ANN001
    """LLM-based: generate next expansion question from current map, or signal done."""
    _ = step, projected
    draft = dict(ctx.state.get("map_draft", {}) or {})
    markdown = str(draft.get("markdown", "") or "")
    mode = str(draft.get("mode", "mindmap") or "mindmap")
    focus = dict(ctx.state.get("map_focus", {}) or {})
    context_text = str((ctx.state.get("map_context", {}) or {}).get("context_text", "") or "")
    policy = dict(ctx.policy or {})

    max_rounds = _policy_int(policy, "map_expand_max_rounds", 0, min_value=0, max_value=20)
    expansion_round = int(ctx.state.get("expansion_round", 0) or 0)

    if not markdown.strip():
        return StepOutcome(value={
            "has_question": False,
            "question": "",
            "reason": "empty_draft",
            "expansion_round": expansion_round,
        })

    if max_rounds <= 0 or expansion_round >= max_rounds:
        return StepOutcome(value={
            "has_question": False,
            "question": "",
            "reason": "budget_exhausted" if max_rounds > 0 else "expansion_disabled",
            "expansion_round": expansion_round,
        })

    structure_check = dict(ctx.state.get("structure_check", {}) or {})
    node_count = int(structure_check.get("node_count", 0) or 0)

    # Few nodes → broad expansion (discover new top-level branches)
    # Many nodes → deep expansion (drill into existing branches)
    if node_count <= 3:
        expansion_strategy = (
            "Die Mindmap hat sehr wenige Knoten. "
            "BREITEN-Expansion: Suche nach weiteren Hauptthemen und übergeordneten Konzepten "
            "die noch fehlen. Ziel: neue Hauptäste erschließen, nicht in die Tiefe gehen."
        )
    else:
        expansion_strategy = (
            "TIEFEN-Expansion: Wähle einen bereits vorhandenen Ast und suche nach "
            "spezifischen Details, Unterthemen oder Belegen, die diesen Ast vertiefen."
        )

    prompt = (
        "Du bist Expansions-Planer für eine Mindmap.\n"
        "Analysiere die bestehende Mindmap und den Kontext.\n"
        "Generiere eine gezielte Folgefrage, um die Mindmap zu erweitern.\n\n"
        f"Expansions-Strategie: {expansion_strategy}\n\n"
        "Die Frage soll:\n"
        "- Einen noch nicht abgedeckten Aspekt des Themas adressieren\n"
        "- Mit dem Kontext (Quellen) beantwortbar sein\n"
        "- Konkret und suchmaschinengeeignet formuliert sein\n\n"
        "Falls die Mindmap bereits umfassend ist und keine sinnvolle Erweiterung möglich ist, "
        'antworte mit: {"has_question": false, "question": "", "reason": "map_complete"}\n\n'
        "Sonst antworte mit:\n"
        '{"has_question": true, "question": "Deine Folgefrage hier", "reason": "expand"}\n\n'
        f"Erweiterungs-Runde: {expansion_round + 1}/{max_rounds} | Aktuelle Knoten: {node_count}\n\n"
        + _prompt_section("Ursprüngliche Frage/Thema", focus.get("query", ""))
        + _prompt_section("Kontext", context_text)
        + "Aktuelle Mindmap:\n"
        + _prompt_text(markdown)
    ).rstrip()

    try:
        raw = str(ctx.tools.call("llm.generate", prompt=prompt) or "").strip()
    except Exception:
        return StepOutcome(value={"has_question": False, "question": "", "reason": "llm_error", "expansion_round": expansion_round})

    json_match = _JSON_OBJECT_RE.search(raw)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            has_q = bool(data.get("has_question", False))
            return StepOutcome(
                value={
                    "has_question": has_q,
                    "question": str(data.get("question", "") or ""),
                    "reason": str(data.get("reason", "")),
                    "expansion_round": expansion_round,
                },
                updates={"state.expansion_round": expansion_round + 1} if has_q else {},
            )
        except Exception:
            pass

    # Fallback: treat as "has question" if response looks like a question
    raw_stripped = raw.strip()
    if "?" in raw_stripped and len(raw_stripped) > 10:
        return StepOutcome(
            value={"has_question": True, "question": raw_stripped[:300], "reason": "llm_fallback", "expansion_round": expansion_round},
            updates={"state.expansion_round": expansion_round + 1},
        )

    return StepOutcome(value={"has_question": False, "question": "", "reason": "llm_no_question", "expansion_round": expansion_round})


def rag_search_expand(ctx, step, projected):  # noqa: ANN001
    """RAG search using the expansion question from plan_expansion."""
    _ = step, projected
    expansion_plan = dict(ctx.state.get("expansion_plan", {}) or {})
    question = str(expansion_plan.get("question", "") or "").strip()
    policy = dict(ctx.policy or {})
    top_k = _policy_int(policy, "map_expand_rag_top_k", 5, min_value=1, max_value=20)

    if not question:
        return StepOutcome(value=[])

    try:
        hits = ctx.tools.call("rag.search", query=question, top_k=top_k)
        if not isinstance(hits, list):
            hits = []
    except Exception:
        hits = []

    return StepOutcome(value=hits)


def draft_subgraph(ctx, step, projected):  # noqa: ANN001
    """LLM: draft a new subgraph from expansion question + RAG hits."""
    _ = step, projected
    expansion_plan = dict(ctx.state.get("expansion_plan", {}) or {})
    question = str(expansion_plan.get("question", "") or "").strip()
    expansion_hits = list(ctx.state.get("expansion_hits", []) or [])
    draft = dict(ctx.state.get("map_draft", {}) or {})
    mode = str(draft.get("mode", "mindmap") or "mindmap")
    tag = _mode_tag(mode)
    focus = dict(ctx.state.get("map_focus", {}) or {})

    # Build context from RAG hits (may be strings or dicts)
    hits_text = ""
    for i, hit in enumerate(expansion_hits[:8]):
        if isinstance(hit, str):
            chunk = hit.strip()
        elif isinstance(hit, dict):
            chunk = str(hit.get("text", "") or hit.get("content", "") or "").strip()
        else:
            chunk = str(hit or "").strip()
        if chunk:
            hits_text += f"[Quelle {i + 1}]\n{chunk[:600]}\n\n"

    if not hits_text and not question:
        return StepOutcome(value={"markdown": "", "mode": mode, "question": question})

    prompt = (
        f"Erstelle einen neuen Teilgraph ({mode}) zu der folgenden Frage.\n"
        "Der Teilgraph soll:\n"
        "- Neue Aspekte abdecken, die noch nicht in der Hauptmindmap vorhanden sind\n"
        "- Ausschließlich auf den unten stehenden Quellen basieren\n"
        "- Zusammenhängend sein (eine Komponente)\n"
        "- Einen klaren Wurzelknoten haben, der die Frage beantwortet\n"
        f"- Antworte NUR mit einem ```{tag} ... ``` Block.\n\n"
        + _prompt_section("Frage", question)
        + _prompt_section("Übergeordnetes Thema", focus.get("query", ""))
        + ("Quellen:\n" + hits_text if hits_text else "")
    ).rstrip()

    try:
        raw = str(ctx.tools.call("llm.generate", prompt=prompt) or "").strip()
    except Exception:
        return StepOutcome(value={"markdown": "", "mode": mode, "question": question})

    return StepOutcome(value={"markdown": raw, "mode": mode, "question": question})


def merge_subgraph(ctx, step, projected):  # noqa: ANN001
    """LLM: merge subgraph_draft into map_draft, ensuring connectivity and no duplicates."""
    _ = step, projected
    draft = dict(ctx.state.get("map_draft", {}) or {})
    main_markdown = str(draft.get("markdown", "") or "")
    mode = str(draft.get("mode", "mindmap") or "mindmap")
    tag = _mode_tag(mode)
    subgraph_draft = dict(ctx.state.get("subgraph_draft", {}) or {})
    sub_markdown = str(subgraph_draft.get("markdown", "") or "")
    question = str(subgraph_draft.get("question", "") or "")
    focus = dict(ctx.state.get("map_focus", {}) or {})
    policy = dict(ctx.policy or {})

    if not sub_markdown.strip():
        return StepOutcome(value={"merged": False, "reason": "empty_subgraph"})

    # Parse both specs first — programmatic merge is the primary strategy
    main_spec = _extract_spec_best_effort(main_markdown, mode=mode)
    sub_spec = _extract_spec_best_effort(sub_markdown, mode=mode)

    if sub_spec is None:
        return StepOutcome(value={"merged": False, "reason": "subgraph_unparseable"})

    if main_spec is not None:
        # Programmatic merge: add subgraph nodes/edges to main spec, then connect
        import copy as _copy
        merged_nodes = dict(main_spec.nodes)
        merged_edges = list(main_spec.edges)
        for nid, node in sub_spec.nodes.items():
            if nid not in merged_nodes:
                merged_nodes[nid] = node
        # Deduplicate edges
        existing_pairs = {(e.source_id, e.target_id) for e in merged_edges}
        for e in sub_spec.edges:
            if (e.source_id, e.target_id) not in existing_pairs:
                merged_edges.append(e)
                existing_pairs.add((e.source_id, e.target_id))
        merged_roots = list(main_spec.roots) + [
            r for r in sub_spec.roots if r not in main_spec.roots
        ]
        from shared.domain.graph_spec import GraphSpec as _GS
        merged_spec = _GS(
            kind=main_spec.kind,
            title=main_spec.title,
            nodes=merged_nodes,
            roots=merged_roots,
            edges=merged_edges,
        )
        edge_label = str(policy.get("graph_bridge_label", "verbindet") or "verbindet").strip()
        if len(component_groups(merged_spec)) > 1:
            merged_spec, _ = connect_components_minimally(merged_spec, edge_label=edge_label or "verbindet")
        cleaned_spec, _ = _sanitize_spec_for_policy(merged_spec, policy=policy)
        new_markdown = spec_to_markdown(cleaned_spec)
        return StepOutcome(
            value={"merged": True, "reason": "programmatic_merge", "node_count": len(cleaned_spec.nodes)},
            updates={"state.map_draft": {"markdown": new_markdown, "mode": _mode_tag(mode)}},
        )

    # main_spec is None (unparseable main) — replace with sub normalized
    cleaned_spec, _ = _sanitize_spec_for_policy(sub_spec, policy=policy)
    new_markdown = spec_to_markdown(cleaned_spec)
    return StepOutcome(
        value={"merged": True, "reason": "sub_as_main", "node_count": len(cleaned_spec.nodes)},
        updates={"state.map_draft": {"markdown": new_markdown, "mode": _mode_tag(mode)}},
    )
