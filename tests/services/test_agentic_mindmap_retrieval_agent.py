from __future__ import annotations

from dataclasses import dataclass

from shared.services.agentic import AgenticWorkflowService, build_tools
from shared.services.agentic.service import _snippet_fingerprint


@dataclass
class _WorkerStub:
    responses: list[str]

    def count_tokens(self, _text: str) -> int:
        return 32

    def context_window(self, _default_n_ctx: int = 4096) -> int:
        return 4096

    def run_completion_sync(self, _prompt: str, **_kwargs) -> str:
        if not self.responses:
            return ""
        return str(self.responses.pop(0))


@dataclass
class _LLMManagerStub:
    worker: _WorkerStub

    def generate_mindmap_sync(
        self,
        *,
        context_text: str,
        query: str,
        mode: str = "mindmap",
        max_nodes: int = 32,
        chunking_strategy: str = "sliding_window",
        chunk_size: int = 900,
        chunk_overlap: int = 160,
    ) -> tuple[str, dict[str, object]]:
        _ = context_text, query, mode, max_nodes, chunking_strategy, chunk_size, chunk_overlap
        text = str(self.worker.run_completion_sync("mindmap_prompt") or "")
        return text, {"reason": "stub", "mode": str(mode or "mindmap")}


@dataclass
class _LLMManagerStubWithNLI(_LLMManagerStub):
    def verify_nli_sync(self, premise: str, hypothesis: str) -> dict[str, object]:
        _ = premise, hypothesis
        return {"label": "contradiction"}


def test_mindmap_retrieval_agent_selects_tools_and_collects_snippets():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Attention, Transformer",
                '{"action":"tool","tool":"heading_search","args":{"pattern":"Attention","max_sections":2},"reason":"erst headings"}',
                '{"action":"tool","tool":"regex_search","args":{"pattern":"Self-attention","max_results":2},"reason":"dann präzise regex"}',
                '{"action":"finish","reason":"genug Evidenz"}',
                '```mindmap\nTransformer\n  Attention\n    Self-Attention :: "Self-attention explains token dependencies."\n```',
            ]
        )
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[
            (
                "paper.md",
                "# Attention\nSelf-attention explains token dependencies.\n"
                "The transformer uses attention heads.",
            ),
        ],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Wie funktioniert Attention?",
            "context_text": "Kontext zu Transformer-Architektur.",
            "retrieval_strategy": "agent",
            "agent_max_iterations": 5,
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 16,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    assert "mindmap" in str(run.result.get("markdown", "")).casefold()
    steps = list(run.state.get("retrieval_agent_steps", []) or [])
    assert any(str(row.get("tool", "")) == "heading_search" for row in steps)
    assert any(str(row.get("tool", "")) == "regex_search" for row in steps)
    snippets = list(run.state.get("rag_snippets", []) or [])
    assert snippets
    metrics = dict(run.metrics or {})
    assert str(metrics.get("retrieval_strategy", "")) == "agent"
    tool_calls = dict(metrics.get("tool_calls", {}) or {})
    assert int(tool_calls.get("heading_search", 0)) >= 1
    assert int(tool_calls.get("regex_search", 0)) >= 1


def test_mindmap_retrieval_strategy_none_skips_retrieval():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Transformer",
                '```mindmap\nTransformer\n  Decoder\n```',
            ]
        )
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[("doc.md", "# Heading\nBeispieltext.")],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Transformer",
            "context_text": "Nur Basiskontext.",
            "retrieval_strategy": "none",
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 8,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    assert list(run.state.get("rag_snippets", []) or []) == []
    metrics = dict(run.metrics or {})
    assert str(metrics.get("retrieval_strategy", "")) == "none"
    assert dict(metrics.get("tool_calls", {}) or {}) == {}


def test_mindmap_agent_recovery_uses_nohit_limit_instead_of_long_heading_loop():
    # The agent is given a source with NO Markdown headings and a small budget.
    # Heading_search will return 0 raw hits every time (no headings to match).
    # Regex and rag searches may find content (the source does have keywords).
    # The test verifies:
    #   1. heading_search is not called in a wasteful infinite loop (≤ 6 times)
    #   2. The agent terminates via budget_exhausted or nohit_limit
    #   3. The run succeeds (produces a mindmap from the available context)
    # Note: the improved agent now correctly distinguishes "tool returned results
    # already seen" (not a no-hit) from "tool returned nothing" (a real no-hit),
    # so the agent may run a few more iterations than the earlier rigid count before
    # budget_exhausted triggers. We provide extra invalid-plan responses and the
    # mindmap response for draft_generation.
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Attention, Transformer",          # concept_extraction
                "invalid-plan",                    # agent iter 1
                "invalid-plan",                    # agent iter 2
                "invalid-plan",                    # agent iter 3
                "invalid-plan",                    # agent iter 4
                "invalid-plan",                    # agent iter 5
                "invalid-plan",                    # agent iter 6
                "invalid-plan",                    # agent iter 7
                "invalid-plan",                    # agent iter 8
                "invalid-plan",                    # agent iter 9 (extra for improved agent)
                '```mindmap\nTransformer\n  Attention\n```',  # draft_generation
            ]
        )
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[
            (
                "doc.md",
                "Transformer und Attention sind Kernkonzepte. "
                "Der Abschnitt hat absichtlich keine Markdown-Überschrift.",
            )
        ],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Self-Attention und Encoder",
            "context_text": "Transformer und Attention sind wichtige Begriffe.",
            "retrieval_strategy": "agent",
            "agent_max_iterations": 20,
            "agent_budget_points": 8.0,
            "agent_max_consecutive_nohit": 3,
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 16,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    metrics = dict(run.metrics or {})
    tool_calls = dict(metrics.get("tool_calls", {}) or {})
    # Regression guard: avoid expensive long loops like 20x heading_search with 0 hits.
    assert int(tool_calls.get("heading_search", 0)) <= 6
    steps = list(run.state.get("retrieval_agent_steps", []) or [])
    assert any(str(row.get("action", "")) in {"finish_no_signal", "budget_exhausted"} for row in steps)


def test_mindmap_agent_respects_tool_capability_switches():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Transformer, Attention",
                '{"action":"tool","tool":"heading_search","args":{"pattern":"Attention"},"reason":"try heading"}',
                '{"action":"finish","reason":"done"}',
                '```mindmap\nTransformer\n  Attention\n```',
            ]
        )
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[("paper.md", "# Attention\nSelf-attention details.")],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Attention?",
            "context_text": "Kontext.",
            "retrieval_strategy": "agent",
            "agent_max_iterations": 6,
            "allow_heading_search": False,
            "allow_regex_search": False,
            "allow_full_text_search": False,
            "allow_rag_search": True,
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 12,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    tool_calls = dict(dict(run.metrics or {}).get("tool_calls", {}) or {})
    assert int(tool_calls.get("heading_search", 0)) == 0
    assert int(tool_calls.get("rag.search", 0)) >= 1


def test_mindmap_agent_stops_repeating_stale_rag_searches():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Attention, Transformer",
                '{"action":"rag.search","args":{"query":"Attention","top_k":4},"reason":"retry 1"}',
                '{"action":"rag.search","args":{"query":"Attention","top_k":4},"reason":"retry 2"}',
                '{"action":"rag.search","args":{"query":"Attention","top_k":4},"reason":"retry 3"}',
                '{"action":"rag.search","args":{"query":"Attention","top_k":4},"reason":"retry 4"}',
                '{"action":"finish","reason":"done"}',
                '```mindmap\nTransformer\n  Attention\n```',
            ]
        )
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[("paper.md", "# Attention\nSelf-attention details.")],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Attention?",
            "context_text": "Kontext.",
            "retrieval_strategy": "agent",
            "allow_heading_search": False,
            "allow_regex_search": False,
            "allow_full_text_search": False,
            "allow_rag_search": True,
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 12,
            "agent_budget_points": 8.0,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    tool_calls = dict(dict(run.metrics or {}).get("tool_calls", {}) or {})
    assert int(tool_calls.get("rag.search", 0)) <= 6
    steps = list(dict(run.state or {}).get("retrieval_agent_steps", []) or [])
    assert steps


def test_mindmap_agent_accepts_shorthand_action_tool_name():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Transformer, Attention",
                '{"action":"rag.search","args":{"query":"Attention","top_k":4},"reason":"retrieve by shorthand action"}',
                '{"action":"finish","reason":"done"}',
                '```mindmap\nTransformer\n  Attention\n```',
            ]
        )
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[("paper.md", "# Attention\nSelf-attention details.")],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Attention?",
            "context_text": "Kontext.",
            "retrieval_strategy": "agent",
            "allow_heading_search": False,
            "allow_regex_search": False,
            "allow_full_text_search": False,
            "allow_rag_search": True,
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 12,
            "agent_budget_points": 8.0,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    tool_calls = dict(dict(run.metrics or {}).get("tool_calls", {}) or {})
    assert int(tool_calls.get("rag.search", 0)) >= 1
    steps = list(dict(run.state or {}).get("retrieval_agent_steps", []) or [])
    assert any(
        str(row.get("action", "")).casefold() == "tool"
        and str(row.get("tool", "")).strip() == "rag.search"
        for row in steps
    )
    assert not any(
        str(row.get("reason", "")).strip() == "invalid_plan_recovery"
        for row in steps
    )


def test_mindmap_agent_accepts_action_and_tool_both_set_to_rag_search():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Transformer, Attention",
                '{"action":"rag.search","tool":"rag.search","args":{"query":"Attention","top_k":4},"reason":"retrieve with duplicated tool name"}',
                '{"action":"finish","reason":"done"}',
                '```mindmap\nTransformer\n  Attention\n```',
            ]
        )
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[("paper.md", "# Attention\nSelf-attention details.")],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Attention?",
            "context_text": "Kontext.",
            "retrieval_strategy": "agent",
            "allow_heading_search": False,
            "allow_regex_search": False,
            "allow_full_text_search": False,
            "allow_rag_search": True,
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 12,
            "agent_budget_points": 8.0,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    steps = list(dict(run.state or {}).get("retrieval_agent_steps", []) or [])
    assert any(
        str(row.get("action", "")).casefold() == "tool"
        and str(row.get("tool", "")).strip() == "rag.search"
        for row in steps
    )


def test_snippet_fingerprint_distinguishes_same_prefix_pdf_snippets():
    prefix = "Kontext › 4 Why Self-Attention In this section we compare various aspects of self-attention"
    first = prefix + " and recurrent layers A"
    second = prefix + " and recurrent layers B"

    assert _snippet_fingerprint(first) != _snippet_fingerprint(second)


def test_mindmap_invalid_unstructured_output_fails_validation():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Softwareentwicklung, Teamarbeit",
                (
                    "Softwareentwicklungserfolg\n"
                    "  Teamarbeit\n"
                    "    Kommunikation :: \"Offene Kommunikation fördert Zusammenarbeit.\""
                ),
            ]
        )
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[("doc.md", "Kommunikation und Teamarbeit sind wichtig.")],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Welche Faktoren beeinflussen den Erfolg?",
            "context_text": "Kontext zur Softwareentwicklung.",
            "retrieval_strategy": "none",
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 8,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is False
    assert str(run.result.get("markdown", "") or "") == ""
    assert any("Ungültige Struktur" in str(err or "") for err in list(run.errors or []))
    trace = list(run.trace or [])
    assert any(str(step.step_id) == "structure_validation" and str(step.status) == "error" for step in trace)
    validation = dict(run.state.get("structure_validation", {}) or {})
    assert bool(validation.get("ok", True)) is False
    assert "draft_markdown_raw" not in dict(run.state or {})


def test_mindmap_raw_draft_is_only_logged_when_enabled():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Softwareentwicklung, Teamarbeit",
                (
                    "Softwareentwicklungserfolg\n"
                    "  Teamarbeit\n"
                    "    Kommunikation :: \"Offene Kommunikation fördert Zusammenarbeit.\""
                ),
            ]
        )
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[("doc.md", "Kommunikation und Teamarbeit sind wichtig.")],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Welche Faktoren beeinflussen den Erfolg?",
            "context_text": "Kontext zur Softwareentwicklung.",
            "retrieval_strategy": "none",
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 8,
            "log_draft_markdown": True,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is False
    assert str(run.state.get("draft_markdown_raw", "") or "").strip()
    assert bool(run.state.get("draft_markdown_logged", False)) is True


def test_mindmap_refinement_rejects_invalid_rewrite_and_keeps_valid_draft():
    llm = _LLMManagerStubWithNLI(
        worker=_WorkerStub(
            responses=[
                "Transformer, Attention",
                (
                    "```mindmap\n"
                    '{\n'
                    '  "type": "mindmap",\n'
                    '  "title": "Transformer",\n'
                    '  "nodes": [\n'
                    '    {\n'
                    '      "id": "transformer",\n'
                    '      "label": "Transformer",\n'
                    '      "children": [\n'
                    '        {\n'
                    '          "id": "architecture",\n'
                    '          "label": "Architecture",\n'
                    '          "children": [\n'
                    '            {\n'
                    '              "id": "architecture-quote",\n'
                    '              "label": "Encoder-Decoder",\n'
                    '              "quote": "The Transformer follows this overall architecture"\n'
                    '            }\n'
                    '          ]\n'
                    '        }\n'
                    '      ]\n'
                    '    }\n'
                    '  ]\n'
                    '}\n'
                    "```"
                ),
                "This is not a mindmap anymore.",
            ]
        )
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[("paper.md", "The Transformer follows this overall architecture.")],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Welche zentralen Konzepte?",
            "context_text": "The Transformer follows this overall architecture.",
            "retrieval_strategy": "none",
            "factcheck": True,
            "max_refinement_rounds": 1,
            "max_nodes": 8,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    markdown = str(run.result.get("markdown", "") or "")
    assert "Transformer" in markdown
    assert "mindmap" in markdown.casefold()
    validation = dict(run.state.get("structure_validation", {}) or {})
    assert bool(validation.get("ok", False)) is True


def test_mindmap_incremental_merge_accumulates_partial_maps():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Transformer, Attention",
                (
                    "```mindmap\n"
                    "Transformer\n"
                    "  Architektur\n"
                    "    Encoder-Decoder :: \"The Transformer follows this overall architecture\"\n"
                    "```"
                ),
                (
                    "```mindmap\n"
                    "Transformer\n"
                    "  Ergebnisse\n"
                    "    BLEU-Werte :: \"Our model achieves 28.4 BLEU\"\n"
                    "```"
                ),
                "",
            ]
        )
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[
            (
                "paper.md",
                "# Architektur\nThe Transformer follows this overall architecture.\n\n"
                "# Ergebnisse\nOur model achieves 28.4 BLEU.\n",
            )
        ],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Was sind die zentralen Konzepte?",
            "context_text": (
                "# Architektur\nThe Transformer follows this overall architecture.\n\n"
                "# Ergebnisse\nOur model achieves 28.4 BLEU.\n"
            ),
            "retrieval_strategy": "none",
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 12,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    markdown = str(run.result.get("markdown", "") or "")
    assert "Architektur" in markdown
    assert "Ergebnisse" in markdown
    draft_progress = list(dict(run.state or {}).get("draft_progress", []) or [])
    assert len(draft_progress) >= 2
