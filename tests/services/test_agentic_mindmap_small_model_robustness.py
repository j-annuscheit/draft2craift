from __future__ import annotations

from dataclasses import dataclass, field

from shared.domain.graph_codec import extract_graph_spec
from shared.services.agentic import AgenticWorkflowService, build_tools


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
    map_response: str
    captured_map_queries: list[str] = field(default_factory=list)
    captured_map_contexts: list[str] = field(default_factory=list)

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
        self.captured_map_queries.append(str(query or ""))
        self.captured_map_contexts.append(str(context_text or ""))
        return str(self.map_response or ""), {"reason": "stub", "mode": str(mode or "mindmap")}


def test_mindmap_repair_pass_fixes_invalid_draft_format():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Transformer, Attention, Training",
                (
                    "```mindmap\n"
                    "Transformer Überblick\n"
                    "  Architektur\n"
                    "    Encoder und Decoder\n"
                    "  Attention\n"
                    "    Multi-Head Attention\n"
                    "  Ergebnisse\n"
                    "    BLEU 28.4 auf WMT14 EN-DE\n"
                    "```"
                ),
            ]
        ),
        map_response="Das ist kein valider strukturierter MindMap-Codeblock.",
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[
            (
                "paper.md",
                "# Attention Is All You Need\n"
                "The Transformer relies on self-attention mechanisms.\n"
                "WMT14 EN-DE reaches BLEU 28.4 with Transformer big.",
            ),
        ],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Gib einen Überblick über die Kernbeiträge.",
            "context_text": (
                "# Attention Is All You Need\n"
                "The Transformer relies on self-attention mechanisms.\n"
                "WMT14 EN-DE reaches BLEU 28.4 with Transformer big."
            ),
            "retrieval_strategy": "none",
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 18,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    markdown = str(run.result.get("markdown", "") or "")
    assert extract_graph_spec(markdown) is not None
    metrics = dict(run.metrics or {})
    assert str(metrics.get("draft_generation_strategy", "") or "")
    trace = list(run.trace or [])
    assert any(str(step.step_id or "") in {"draft_generation", "draft_repair"} for step in trace)


def test_agent_policy_warmstart_keeps_retrieval_robust_when_plan_is_invalid():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Attention, Encoder, Decoder",
                "kein json format",
                '{"action":"finish","reason":"enough"}',
            ]
        ),
        map_response=(
            "```mindmap\n"
            "Transformer\n"
            "  Attention\n"
            "    Multi-Head\n"
            "  Architektur\n"
            "    Encoder-Decoder\n"
            "```"
        ),
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[
            (
                "paper.md",
                "# 3 Model Architecture\n"
                "The encoder is composed of a stack of layers.\n"
                "The decoder includes masked self-attention.\n"
                "Multi-head attention attends to different representation subspaces.",
            ),
        ],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Wie funktionieren Attention und Encoder-Decoder Zusammenspiel?",
            "context_text": "Kontext",
            "retrieval_strategy": "agent",
            "agent_max_iterations": 4,
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 20,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    state = dict(run.state or {})
    snippets = list(state.get("rag_snippets", []) or [])
    assert snippets
    agent_steps = list(state.get("retrieval_agent_steps", []) or [])
    assert any(str(row.get("action", "")).casefold() == "policy_tool" for row in agent_steps)
    tool_calls = dict(dict(run.metrics or {}).get("tool_calls", {}) or {})
    assert int(tool_calls.get("heading_search", 0)) + int(tool_calls.get("rag.search", 0)) >= 1


def test_agent_parser_accepts_fenced_json_plans():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Attention, Encoder, Decoder",
                (
                    "```json\n"
                    "{\"action\":\"tool\",\"tool\":\"heading_search\","
                    "\"args\":{\"pattern\":\"Attention|Encoder|Decoder\",\"max_sections\":3},"
                    "\"reason\":\"strukturabschnitt\"}\n"
                    "```"
                ),
                '{"action":"finish","reason":"enough"}',
            ]
        ),
        map_response=(
            "```mindmap\n"
            "Transformer\n"
            "  Attention\n"
            "    Multi-Head\n"
            "  Architektur\n"
            "    Encoder-Decoder\n"
            "```"
        ),
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[
            (
                "paper.md",
                "# 3 Model Architecture\n"
                "The encoder is composed of a stack of layers.\n"
                "The decoder includes masked self-attention.\n"
                "Multi-head attention attends to different representation subspaces.",
            ),
        ],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Wie funktionieren Attention und Encoder-Decoder Zusammenspiel?",
            "context_text": "Kontext",
            "retrieval_strategy": "agent",
            "agent_max_iterations": 4,
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 20,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    agent_steps = list(dict(run.state or {}).get("retrieval_agent_steps", []) or [])
    tool_calls = dict(dict(run.metrics or {}).get("tool_calls", {}) or {})
    assert int(tool_calls.get("heading_search", 0)) >= 1
    assert agent_steps
    assert any(str(row.get("tool", "")).casefold() == "heading_search" for row in agent_steps)


def test_empty_query_uses_deterministic_overview_query():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Transformer, Attention, Training",
            ]
        ),
        map_response=(
            "```mindmap\n"
            "Attention Is All You Need (Transformer)\n"
            "  Architektur\n"
            "    Encoder und Decoder\n"
            "  Attention\n"
            "    Multi-Head Attention\n"
            "```"
        ),
    )
    tools = build_tools(
        llm_manager=llm,
        source_texts=[
            (
                "paper.md",
                "# Attention Is All You Need\n"
                "The Transformer relies on self-attention mechanisms.\n"
                "WMT14 EN-DE reaches BLEU 28.4 with Transformer big.",
            ),
        ],
    )
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "",
            "context_text": "# Attention Is All You Need\nTransformer overview context.",
            "retrieval_strategy": "none",
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 18,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    assert llm.captured_map_queries
    assert "übersicht" in str(llm.captured_map_queries[0]).casefold()
    assert str(dict(run.state or {}).get("query_origin", "")) == "auto_overview"
    assert bool(str(dict(run.state or {}).get("effective_query", "")).strip()) is True
    assert str(dict(run.metrics or {}).get("query_origin", "")) == "auto_overview"


def test_retrieval_none_passes_long_document_context_to_generation():
    tail_marker = "TAIL_CONTEXT_MARKER_AIAYN_1706"
    long_context = "# Attention Is All You Need\n" + ("Transformer context.\n" * 8000) + tail_marker
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Transformer, Attention, Training",
            ]
        ),
        map_response=(
            "```mindmap\n"
            "Attention Is All You Need (Transformer)\n"
            "  Architektur\n"
            "    Encoder und Decoder\n"
            "  Attention\n"
            "    Multi-Head Attention\n"
            "```"
        ),
    )
    tools = build_tools(llm_manager=llm, source_texts=[("paper.md", long_context)])
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Welche zentralen Konzepte gibt es?",
            "context_text": long_context,
            "retrieval_strategy": "none",
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 18,
            "context_max_chars": 500000,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    assert llm.captured_map_contexts
    ctx_used = str(llm.captured_map_contexts[-1] or "")
    assert tail_marker in ctx_used
    assert len(ctx_used) >= 40000


def test_off_topic_mindmap_is_rejected_by_grounding_validation():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Transformer, Attention, Training",
                (
                    "```mindmap\n"
                    "Effektive Präsentation halten\n"
                    "  Zielgruppenanalyse :: \"Verstehe die Bedürfnisse der Zuhörer.\"\n"
                    "  Struktur :: \"Organisiere die Rede klar.\"\n"
                    "```"
                ),
            ]
        ),
        map_response=(
            "```mindmap\n"
            "Effektive Präsentation halten\n"
            "  Zielgruppenanalyse :: \"Verstehe die Bedürfnisse der Zuhörer.\"\n"
            "  Struktur :: \"Organisiere die Rede klar.\"\n"
            "```"
        ),
    )
    source = (
        "# Attention Is All You Need\n"
        "The Transformer relies on self-attention mechanisms.\n"
        "WMT14 EN-DE reaches BLEU 28.4 with Transformer big."
    )
    tools = build_tools(llm_manager=llm, source_texts=[("paper.md", source)])
    svc = AgenticWorkflowService(plugin_manager=object())
    run = svc.run_mindmap(
        request={
            "query": "Welche zentralen Konzepte beantworten die Fragestellung im Kontext?",
            "context_text": source,
            "retrieval_strategy": "none",
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 18,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is False
    assert any("Erdung" in str(err or "") for err in list(run.errors or []))
    assert int(dict(run.metrics or {}).get("grounding_issue_count", 0)) >= 1


def test_explicit_main_nodes_in_query_trigger_targeted_repair_and_reduce_off_topic_failures():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                # concept_extraction initially drifts off-topic
                "Burnout, Persönliche Faktoren, Organisatorische Faktoren",
                # draft_repair produces a grounded map aligned to required main nodes
                (
                    "```mindmap\n"
                    "Attention Is All You Need\n"
                    "  Vor dem Paper\n"
                    "    Sequenzmodelle :: \"based on complex recurrent or convolutional neural networks\"\n"
                    "  Idee des Papers\n"
                    "    Transformer :: \"based solely on attention mechanisms\"\n"
                    "  Besonderheiten des Algorithmus\n"
                    "    Multi-Head Attention :: \"we employ h = 8 parallel attention layers\"\n"
                    "  Auswirkungen der neuen Technik\n"
                    "    BLEU Ergebnisse :: \"Our model achieves 28.4 BLEU on the WMT 2014 English-to-German translation task\"\n"
                    "  Risiken der Technik\n"
                    "    Interpretierbarkeit :: \"self-attention could yield more interpretable models\"\n"
                    "```"
                ),
            ]
        ),
        map_response=(
            "```mindmap\n"
            "Burnout\n"
            "  Persönliche Faktoren\n"
            "    Arbeitsbelastung :: \"hoch\"\n"
            "  Organisatorische Faktoren\n"
            "    Teamkonflikte :: \"kritisch\"\n"
            "```"
        ),
    )
    source = (
        "# Attention Is All You Need\n"
        "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.\n"
        "The Transformer is based solely on attention mechanisms.\n"
        "We employ h = 8 parallel attention layers, or heads.\n"
        "Our model achieves 28.4 BLEU on the WMT 2014 English-to-German translation task.\n"
        "Self-attention could yield more interpretable models."
    )
    tools = build_tools(llm_manager=llm, source_texts=[("arxiv_1706.03762.pdf", source)])
    svc = AgenticWorkflowService(plugin_manager=object())
    query = (
        "Nutze die Hauptknoten: Vor dem Paper, Idee des Papers, Besonderheiten des Algorithmus, "
        "Auswirkungen der neuen Technik, Risiken der Technik."
    )
    run = svc.run_mindmap(
        request={
            "query": query,
            "context_text": source,
            "retrieval_strategy": "rag",
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 24,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    markdown = str(run.result.get("markdown", "") or "")
    assert "Vor dem Paper" in markdown
    assert "Idee des Papers" in markdown
    assert "Besonderheiten des Algorithmus" in markdown
    assert "Auswirkungen der neuen Technik" in markdown
    assert "Risiken der Technik" in markdown
    metrics = dict(run.metrics or {})
    assert list(metrics.get("required_main_nodes", []) or [])


def test_required_main_nodes_strict_repair_step_recovers_from_language_drift():
    llm = _LLMManagerStub(
        worker=_WorkerStub(
            responses=[
                "Transformer, Attention, BLEU",
                (
                    "```mindmap\n"
                    "Idea of Papers\n"
                    "  Attention Is All You Need\n"
                    "    Abstract\n"
                    "```"
                ),
                (
                    "```mindmap\n"
                    "Idea of Papers\n"
                    "  Attention Is All You Need\n"
                    "    Abstract\n"
                    "```"
                ),
                (
                    "```mindmap\n"
                    "Attention Is All You Need\n"
                    "  Vor dem Paper\n"
                    "    Sequenzmodelle :: \"based on complex recurrent or convolutional neural networks\"\n"
                    "  Idee des Papers\n"
                    "    Transformer :: \"based solely on attention mechanisms\"\n"
                    "  Besonderheiten des Algorithmus\n"
                    "    Multi-Head Attention :: \"we employ h = 8 parallel attention layers\"\n"
                    "  Auswirkungen der neuen Technik\n"
                    "    BLEU Ergebnisse :: \"Our model achieves 28.4 BLEU\"\n"
                    "  Risiken der Technik\n"
                    "    Interpretierbarkeit :: \"self-attention could yield more interpretable models\"\n"
                    "```"
                ),
            ]
        ),
        map_response=(
            "```mindmap\n"
            "Idea of Papers\n"
            "  Attention Is All You Need\n"
            "    Abstract\n"
            "```"
        ),
    )
    source = (
        "# Attention Is All You Need\n"
        "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.\n"
        "The Transformer is based solely on attention mechanisms.\n"
        "We employ h = 8 parallel attention layers, or heads.\n"
        "Our model achieves 28.4 BLEU on the WMT 2014 English-to-German translation task.\n"
        "Self-attention could yield more interpretable models."
    )
    tools = build_tools(llm_manager=llm, source_texts=[("arxiv_1706.03762.pdf", source)])
    svc = AgenticWorkflowService(plugin_manager=object())
    query = (
        "Nutze die Hauptknoten: Vor dem Paper, Idee des Papers, Besonderheiten des Algorithmus, "
        "Auswirkungen der neuen Technik, Risiken der Technik."
    )
    run = svc.run_mindmap(
        request={
            "query": query,
            "context_text": source,
            "retrieval_strategy": "none",
            "factcheck": False,
            "max_refinement_rounds": 0,
            "max_nodes": 24,
        },
        tools=tools,
        profile_id="mindmap_v2_local",
        enabled=True,
    )

    assert bool(run.ok) is True
    markdown = str(run.result.get("markdown", "") or "")
    assert "Vor dem Paper" in markdown
    assert "Idee des Papers" in markdown
    assert "Besonderheiten des Algorithmus" in markdown
    assert "Auswirkungen der neuen Technik" in markdown
    assert "Risiken der Technik" in markdown
    trace = list(run.trace or [])
    assert trace
