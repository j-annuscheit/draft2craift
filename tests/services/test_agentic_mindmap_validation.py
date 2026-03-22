from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

from shared.domain.graph_codec import extract_graph_spec
from shared.services.agentic.workers.maps.check_structure import run as check_structure
from shared.services.agentic.workers.maps.draft_map_raw import run as draft_map_raw
from shared.services.agentic.workers.maps.emit_to_canvas import run as emit_to_canvas
from shared.services.agentic.workers.maps.ground_map_draft import run as ground_map_draft
from shared.services.agentic.workers.maps.parse_map_draft import run as parse_map_draft
from shared.services.agentic.workers.maps.prompts import (
    _close_map_prompt,
    _expand_prompt,
    _refine_prompt,
    _repair_prompt,
)
from shared.services.agentic.workers.maps.validate_schema import run as validate_schema


def _ctx(
    *,
    markdown: str,
    mode: str = "mindmap",
    policy: dict | None = None,
    tool_impl: Callable[[str], object] | None = None,
    candidate: dict | None = None,
    context_text: str = "",
    query: str = "",
):
    calls: list[dict[str, object]] = []

    def _call(name: str, **kwargs):
        calls.append({"tool": name, **dict(kwargs or {})})
        if callable(tool_impl):
            return tool_impl(name)
        return None

    return SimpleNamespace(
        state={
            "map_draft_raw": {},
            "map_draft": {"markdown": markdown, "mode": mode},
            "map_focus": {"mode": mode, "query": query},
            "map_context": {"context_text": context_text},
            "map_validation": {},
            "_candidates": dict(candidate or {}),
        },
        policy=dict(policy or {}),
        request={},
        result={},
        tools=SimpleNamespace(call=_call),
        errors=[],
        _calls=calls,
    )


def _run_draft_pipeline(ctx):
    raw = draft_map_raw(ctx, None, None)
    ctx.state["map_draft_raw"] = dict(raw.value or {})
    parsed = parse_map_draft(ctx, None, None)
    ctx.state["map_draft"] = dict(parsed.value or {})
    grounded = ground_map_draft(ctx, None, None)
    return raw, parsed, grounded


def test_validate_schema_accepts_valid_mindmap_markdown():
    ctx = _ctx(
        markdown="```mindmap\n- Root\n  - Child\n```",
        mode="mindmap",
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    assert payload.get("ok") is True
    normalized = str(payload.get("normalized_markdown", "") or "")
    assert "```mindmap" in normalized


def test_validate_schema_rejects_self_edge_graph():
    ctx = _ctx(
        markdown=(
            "```graph\n"
            '{"type":"graph","title":"G","nodes":[{"id":"a","label":"Alpha"}],'
            '"edges":[{"from":"a","to":"a"}]}'
            "\n```"
        ),
        mode="graph",
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    assert payload.get("ok") is False
    issues = list(payload.get("issues", []) or [])
    assert any(str(item.get("code", "")) == "self_edge" for item in issues)


def test_validate_schema_applies_policy_limits():
    ctx = _ctx(
        markdown="```mindmap\n- Root\n  - Child\n```",
        mode="mindmap",
        policy={"map_max_nodes": 1},
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    assert payload.get("ok") is False
    issues = list(payload.get("issues", []) or [])
    assert any(str(item.get("code", "")) == "nodes_over_limit" for item in issues)


def test_validate_schema_accepts_mermaid_graph_block():
    ctx = _ctx(
        markdown=(
            "## Mindmap-Ausgabe\n\n"
            "```mermaid\n"
            "graph TD\n"
            "A[draft2craift] --> B(Writing Studio);\n"
            "B --> C{Core Features};\n"
            "C --> D[Markdown Editor];\n"
            "```\n"
        ),
        mode="mindmap",
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    assert payload.get("ok") is True
    stats = dict(payload.get("stats", {}) or {})
    assert int(stats.get("nodes", 0) or 0) >= 3
    assert int(stats.get("edges", 0) or 0) >= 2


def test_validate_schema_repairs_parse_failure_via_llm():
    repaired = (
        "```mindmap\n"
        "{\n"
        '  "type": "mindmap",\n'
        '  "title": "Repaired",\n'
        '  "nodes": [{"id":"root","label":"Root","children":[{"id":"child","label":"Child"}]}]\n'
        "}\n"
        "```"
    )
    ctx = _ctx(
        markdown="```\\n- unstructured block without graph tag\\n```",
        mode="mindmap",
        policy={"map_parse_repair_enabled": True},
        tool_impl=lambda tool_name: repaired if tool_name == "llm.generate" else None,
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    assert payload.get("ok") is True
    assert str(payload.get("repair_reason", "")) == "repair_applied"


def test_validate_schema_repairs_malformed_json_like_mindmap_instead_of_simple_fallback():
    repaired = (
        "```mindmap\n"
        "{\n"
        '  "type": "mindmap",\n'
        '  "title": "Recovered",\n'
        '  "nodes": [{"id":"root","label":"Recovered","children":[{"id":"child","label":"Topic"}]}]\n'
        "}\n"
        "```"
    )
    ctx = _ctx(
        markdown=(
            "```mindmap\n"
            "{\n"
            '  "type": "mindmap",\n'
            '  "title": "Broken",\n'
            '  "nodes": [\n'
            '    {"id":"root","label":"Root","children":[\n'
            '      {"id":"children","label":"children:","children":[\n'
            '        {"id":"text-topic","label":"- text: \\"Topic\\""}\n'
            "      ]}\n"
            "    ]}\n"
            "  ]\n"
            "\n"
            "```"
        ),
        mode="mindmap",
        policy={"map_parse_repair_enabled": True},
        tool_impl=lambda tool_name: repaired if tool_name == "llm.generate" else None,
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    normalized = str(payload.get("normalized_markdown", "") or "")
    assert payload.get("ok") is True
    assert str(payload.get("repair_reason", "")) == "repair_applied"
    assert "children:" not in normalized
    assert "Recovered" in normalized


def test_validate_schema_rejects_malformed_json_like_mindmap_when_repair_disabled():
    ctx = _ctx(
        markdown=(
            "```mindmap\n"
            "{\n"
            '  "type": "mindmap",\n'
            '  "title": "Broken",\n'
            '  "nodes": [{"id":"root","label":"Root","children":[{"id":"broken","label":"children:"}]}]\n'
            "\n"
            "```"
        ),
        mode="mindmap",
        policy={"map_parse_repair_enabled": False},
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    assert payload.get("ok") is False
    assert str(payload.get("reason", "")) == "parse_failed"
    assert str(payload.get("repair_reason", "")) == "repair_disabled"


def test_validate_schema_graph_cleanup_removes_structural_noise():
    ctx = _ctx(
        markdown=(
            "```graph\n"
            "{\n"
            '  "type": "graph",\n'
            '  "title": "Graph",\n'
            '  "nodes": [\n'
            '    {"id":"export","label":"\\"Export\\","},\n'
            '    {"id":"","label":"},"},\n'
            '    {"id":"junk","label":"{"}\n'
            "  ],\n"
            '  "edges": []\n'
            "}\n"
            "```"
        ),
        mode="graph",
        policy={"map_cleanup_enabled": True},
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    normalized = str(payload.get("normalized_markdown", "") or "")
    cleanup = dict(payload.get("cleanup", {}) or {})
    assert '"id": ""' not in normalized
    assert int(cleanup.get("removed_nodes", 0) or 0) >= 1


def test_validate_schema_drops_nodes_without_word_like_text():
    ctx = _ctx(
        markdown=(
            "```mindmap\n"
            "{\n"
            '  "type": "mindmap",\n'
            '  "title": "MindMap",\n'
            '  "nodes": [{"id":"a","label":"A"},{"id":"b","label":"B"}]\n'
            "}\n"
            "```"
        ),
        mode="mindmap",
        policy={"map_cleanup_enabled": True, "map_node_min_word_letters": 3},
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    cleanup = dict(payload.get("cleanup", {}) or {})
    assert payload.get("ok") is False
    assert int(cleanup.get("removed_nodes", 0) or 0) >= 2


def test_validate_schema_merges_near_duplicate_mindmap_nodes():
    ctx = _ctx(
        markdown=(
            "```mindmap\n"
            "{\n"
            '  "type": "mindmap",\n'
            '  "title": "MindMap",\n'
            '  "nodes": [\n'
            '    {"id":"root","label":"Root","children":[\n'
            '      {"id":"risk-a","label":"Technical Risks"},\n'
            '      {"id":"risk-b","label":"technical risk"}\n'
            "    ]}\n"
            "  ]\n"
            "}\n"
            "```"
        ),
        mode="mindmap",
        policy={
            "map_cleanup_enabled": True,
            "map_merge_similar_nodes_enabled": True,
        },
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    cleanup = dict(payload.get("cleanup", {}) or {})
    normalized = str(payload.get("normalized_markdown", "") or "")
    spec = extract_graph_spec(normalized)
    assert payload.get("ok") is True
    assert int(cleanup.get("merged_nodes", 0) or 0) >= 1
    assert spec is not None
    assert len(spec.nodes) == 2


def test_validate_schema_can_keep_near_duplicates_when_disabled():
    ctx = _ctx(
        markdown=(
            "```mindmap\n"
            "{\n"
            '  "type": "mindmap",\n'
            '  "title": "MindMap",\n'
            '  "nodes": [\n'
            '    {"id":"root","label":"Root","children":[\n'
            '      {"id":"risk-a","label":"Technical Risks"},\n'
            '      {"id":"risk-b","label":"technical risk"}\n'
            "    ]}\n"
            "  ]\n"
            "}\n"
            "```"
        ),
        mode="mindmap",
        policy={
            "map_cleanup_enabled": True,
            "map_merge_similar_nodes_enabled": False,
        },
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    normalized = str(payload.get("normalized_markdown", "") or "")
    spec = extract_graph_spec(normalized)
    assert payload.get("ok") is True
    assert spec is not None
    assert len(spec.nodes) == 3


def test_validate_schema_commits_valid_candidate_over_invalid_baseline():
    ctx = _ctx(
        markdown="```mindmap\n{\n  \"type\": \"mindmap\",\n  \"title\": \"Broken\",\n  \"nodes\": []\n}\n```",
        mode="mindmap",
        candidate={
            "map_draft_candidate": {
                "value": {
                    "markdown": "```mindmap\n- Root\n  - Child\n```",
                    "mode": "mindmap",
                },
                "meta": {"intent": "closure"},
            }
        },
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    review = dict(payload.get("candidate_review", {}) or {})
    assert payload.get("ok") is True
    assert out.commit_candidates == ("map_draft_candidate",)
    assert out.discard_candidates == ()
    assert review.get("accepted") is True


def test_validate_schema_discards_invalid_expand_candidate_when_baseline_is_valid():
    ctx = _ctx(
        markdown="```mindmap\n- Root\n  - Child\n```",
        mode="mindmap",
        candidate={
            "map_draft_candidate": {
                "value": {
                    "markdown": "```mindmap\n{\"type\":\"mindmap\",\"title\":\"Bad\",\"nodes\":[]}\n```",
                    "mode": "mindmap",
                },
                "meta": {"intent": "expand"},
            }
        },
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    review = dict(payload.get("candidate_review", {}) or {})
    assert payload.get("ok") is True
    assert out.commit_candidates == ()
    assert out.discard_candidates == ("map_draft_candidate",)
    assert review.get("accepted") is False
    assert str(review.get("reason", "")) in {
        "candidate_parse_failed",
        "candidate_broke_validation",
        "candidate_not_better",
        "candidate_too_much_content_loss",
    }


def test_validate_schema_can_keep_invalid_closure_candidate_when_it_improves_components():
    ctx = _ctx(
        markdown="```mindmap\nAlpha\nBeta\nGamma\n```",
        mode="mindmap",
        candidate={
            "map_draft_candidate": {
                "value": {
                    "markdown": "```mindmap\nAlpha\n  Beta\nGamma\n```",
                    "mode": "mindmap",
                },
                "meta": {
                    "intent": "closure",
                    "allow_invalid_improvement": True,
                    "min_overlap_ratio": 0.2,
                },
            }
        },
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    review = dict(payload.get("candidate_review", {}) or {})
    stats = dict(payload.get("stats", {}) or {})
    assert out.commit_candidates == ("map_draft_candidate",)
    assert review.get("accepted") is True
    assert int(stats.get("components", 0) or 0) < 3


def test_validate_schema_rejects_meta_graph_that_is_not_grounded_in_context():
    ctx = _ctx(
        markdown=(
            "```graph\n"
            "{\n"
            '  "type": "graph",\n'
            '  "title": "Graph",\n'
            '  "nodes": [\n'
            '    {"id":"r","label":"**Relation:** Die Art der Beziehung zwischen den Knoten."},\n'
            '    {"id":"m","label":"Ich habe versucht, den Text in ein strukturiertes Graph-Format zu uebersetzen."},\n'
            '    {"id":"b","label":"Between \\"A\\" und \\"B\\" impliziert werden."}\n'
            "  ],\n"
            '  "edges": [{"from":"r","to":"m"},{"from":"m","to":"b"}]\n'
            "}\n"
            "```"
        ),
        mode="graph",
        policy={
            "map_require_context_grounding": True,
            "map_min_grounded_nodes": 2,
            "map_min_grounded_ratio": 0.45,
            "map_max_meta_nodes": 1,
            "map_max_meta_node_ratio": 0.34,
        },
        context_text="Alpha haengt mit Beta zusammen. Beta fuehrt zu Gamma.",
        query="Welche Entitaeten und Beziehungen sind im Kontext belegt?",
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    issues = {str(item.get("code", "")) for item in list(payload.get("issues", []) or [])}
    grounding = dict(payload.get("grounding", {}) or {})
    assert payload.get("ok") is False
    assert grounding.get("ok") is False
    assert "grounding_insufficient" in issues
    assert "meta_labels_detected" in issues


def test_validate_schema_prefers_unterminated_structured_graph_block_over_preamble():
    ctx = _ctx(
        markdown=(
            "Kurzer Vorspann, der kein Graph ist.\n\n"
            "## Graph-Ausgabe\n\n"
            "```\n"
            "{\n"
            '  "type": "graph",\n'
            '  "title": "G",\n'
            '  "nodes": ["Alpha", "Beta", "Gamma"],\n'
            '  "edges": [\n'
            '    {"source":"Alpha","target":"Beta","label":"uses"},\n'
            '    {"source":"Beta","target":"Gamma","label":"connects"}\n'
            "  ]\n"
            "}\n"
        ),
        mode="graph",
        policy={"map_require_context_grounding": False},
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    stats = dict(payload.get("stats", {}) or {})
    normalized = str(payload.get("normalized_markdown", "") or "")
    assert int(stats.get("nodes", 0) or 0) == 3
    assert int(stats.get("edges", 0) or 0) == 2
    assert "Alpha" in normalized
    assert "Graph-Ausgabe" not in normalized


def test_validate_schema_discards_ungrounded_candidate_even_when_connected():
    ctx = _ctx(
        markdown=(
            "```graph\n"
            '{"type":"graph","title":"G","nodes":[{"id":"a","label":"Alpha"},{"id":"b","label":"Beta"}],'
            '"edges":[{"from":"a","to":"b"}]}\n'
            "```"
        ),
        mode="graph",
        policy={
            "map_require_context_grounding": True,
            "map_min_grounded_nodes": 2,
            "map_min_grounded_ratio": 0.45,
        },
        context_text="Alpha verbindet Beta.",
        query="Welche Entitaeten sind belegt?",
        candidate={
            "map_draft_candidate": {
                "value": {
                    "markdown": (
                        "```graph\n"
                        '{"type":"graph","title":"G","nodes":[{"id":"x","label":"Kuenstliche Intelligenz"},'
                        '{"id":"y","label":"Maschinelles Lernen"},{"id":"z","label":"Neuronale Netze"}],'
                        '"edges":[{"from":"x","to":"y"},{"from":"y","to":"z"}]}\n'
                        "```"
                    ),
                    "mode": "graph",
                },
                "meta": {"intent": "closure"},
            }
        },
    )
    out = validate_schema(ctx, None, None)
    payload = dict(out.value or {})
    review = dict(payload.get("candidate_review", {}) or {})
    assert payload.get("ok") is True
    assert out.commit_candidates == ()
    assert out.discard_candidates == ("map_draft_candidate",)
    assert review.get("accepted") is False
    assert str(review.get("reason", "")) == "candidate_not_grounded"


def test_emit_to_canvas_prefers_normalized_markdown():
    ctx = _ctx(
        markdown="```mindmap\n- Raw\n```",
        mode="mindmap",
    )
    ctx.state["map_validation"] = {
        "ok": True,
        "kind": "mindmap",
        "normalized_markdown": "```mindmap\n- Normalized\n```",
    }
    out = emit_to_canvas(ctx, None, None)
    assert out.stop is True
    assert ctx._calls
    assert str(ctx._calls[-1].get("text", "")) == "```mindmap\n- Normalized\n```"


def test_draft_graphspec_prompt_contains_full_context_text():
    tail = "TAIL_FULL_CONTEXT_DRAFT"
    context_text = ("A" * 7000) + tail
    prompts: list[str] = []
    ctx = SimpleNamespace(
        state={
            "map_context": {"context_text": context_text},
            "map_focus": {"mode": "mindmap", "query": "Kernideen"},
            "map_draft_raw": {},
        },
        policy={},
        tools=SimpleNamespace(
            call=lambda name, **kwargs: prompts.append(str(kwargs.get("prompt", ""))) or "```mindmap\n- Root\n```"
        ),
    )
    _raw, _parsed, out = _run_draft_pipeline(ctx)
    assert str((out.value or {}).get("markdown", "")).strip()
    assert prompts
    assert tail in prompts[-1]


def test_draft_graphspec_normalizes_parseable_noncanonical_output():
    calls = {"count": 0}
    ctx = SimpleNamespace(
        state={
            "map_context": {"context_text": "Alpha und Beta."},
            "map_focus": {"mode": "mindmap", "query": "Kernideen"},
            "map_draft_raw": {},
            "structure_check": {},
        },
        policy={},
        tools=SimpleNamespace(
            call=lambda name, **kwargs: (
                calls.__setitem__("count", calls["count"] + 1)
                or '{"type":"mindmap","title":"M","nodes":[{"id":"root","label":"Root","children":[{"id":"child","label":"Child"}]}]}'
            )
        ),
    )
    _raw, _parsed, out = _run_draft_pipeline(ctx)
    payload = dict(out.value or {})
    assert calls["count"] == 1
    assert str(payload.get("reason", "")) == "normalized_response_format"
    assert "```mindmap" in str(payload.get("markdown", "") or "")


def test_draft_graphspec_repairs_invalid_response_format():
    calls = {"count": 0}

    def _tool(name: str, **kwargs):
        _ = name, kwargs
        calls["count"] += 1
        if calls["count"] == 1:
            return "```mindmap\n{\n  \"type\": \"mindmap\",\n  \"nodes\": [\n```"
        return "```mindmap\n- Root\n  - Child\n```"

    ctx = SimpleNamespace(
        state={
            "map_context": {"context_text": "Root und Child stehen im Kontext."},
            "map_focus": {"mode": "mindmap", "query": "Kernideen"},
            "map_draft_raw": {},
            "structure_check": {},
        },
        policy={"map_parse_repair_enabled": True},
        tools=SimpleNamespace(call=_tool),
    )
    _raw, _parsed, out = _run_draft_pipeline(ctx)
    payload = dict(out.value or {})
    assert calls["count"] == 2
    assert str(payload.get("reason", "")) == "repair_applied"
    assert "```mindmap" in str(payload.get("markdown", "") or "")


def test_prompt_builders_keep_full_context_and_state_text():
    tail_context = "TAIL_FULL_CONTEXT"
    tail_raw = "TAIL_FULL_RAW"
    tail_overview = "TAIL_FULL_OVERVIEW"
    tail_markdown = "TAIL_FULL_MARKDOWN"
    context_text = ("B" * 7000) + tail_context
    raw_markdown = ("C" * 9000) + tail_raw
    component_overview = ("D" * 6000) + tail_overview
    normalized_markdown = ("E" * 13000) + tail_markdown

    repair_prompt = _repair_prompt(
        mode="mindmap",
        raw_markdown=raw_markdown,
        context_text=context_text,
        query="Langfrage",
    )
    close_prompt = _close_map_prompt(
        mode="mindmap",
        query="Langfrage",
        context_text=context_text,
        normalized_markdown=normalized_markdown,
        component_overview=component_overview,
        round_idx=1,
        max_rounds=3,
        needs_grounding=False,
    )
    refine_prompt = _refine_prompt(
        mode="mindmap",
        query="Langfrage",
        context_text=context_text,
        normalized_markdown=normalized_markdown,
    )
    expand_prompt = _expand_prompt(
        mode="mindmap",
        query="Langfrage",
        context_text=context_text,
        normalized_markdown=normalized_markdown,
        round_idx=1,
        target_rounds=3,
    )

    assert tail_context in repair_prompt
    assert tail_raw in repair_prompt
    assert tail_context in close_prompt
    assert tail_overview in close_prompt
    assert tail_markdown in close_prompt
    assert tail_context in refine_prompt
    assert tail_markdown in refine_prompt
    assert tail_context in expand_prompt
    assert tail_markdown in expand_prompt


def test_check_structure_reports_empty_draft_reason_from_draft_step():
    ctx = _ctx(
        markdown="",
        mode="mindmap",
    )
    ctx.state["map_draft"] = {
        "markdown": "",
        "mode": "mindmap",
        "reason": "llm_error",
        "error": "Prompt exceeds model context window.",
    }
    out = check_structure(ctx, None, None)
    payload = dict(out.value or {})
    issues = list(payload.get("issues", []) or [])
    assert payload.get("ok") is False
    assert payload.get("parse_failed") is True
    assert str(payload.get("reason", "")) == "llm_error"
    assert any("context window" in str(item.get("message", "")).casefold() for item in issues)
