from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

import pytest

from shared.domain.graph_codec import extract_graph_spec
from shared.services.agentic import AgenticWorkflowService, build_tools


_DEFAULT_AIA_PATH = Path(
    "/home/be/.local/share/draft2craift/draft2craift/autosave_project/knowledge/doc_0000.md"
)


def _extract_between(text: str, start: str, end: str) -> str:
    raw = str(text or "")
    i = raw.find(start)
    if i < 0:
        return ""
    j = raw.find(end, i + len(start))
    if j < 0:
        return raw[i + len(start) :].strip()
    return raw[i + len(start) : j].strip()


def _classify_focus(query: str) -> str:
    q = str(query or "").strip().casefold()
    if any(token in q for token in ("bleu", "wmt", "ergebnis", "resultat", "results", "training cost")):
        return "results"
    if any(
        token in q
        for token in (
            "multi-head",
            "scaled dot-product",
            "self-attention",
            "encoder",
            "decoder",
            "mask",
        )
    ):
        return "attention"
    if any(token in q for token in ("training", "optimizer", "schedule", "warmup", "dropout", "regularization")):
        return "training"
    if any(token in q for token in ("position", "positional", "sinusoidal")):
        return "position"
    return "overview"


def _mindmap_overview() -> str:
    return (
        "```mindmap\n"
        "Attention Is All You Need (Transformer)\n"
        "  Motivation\n"
        "    Ohne Rekurrenz und ohne Convolution\n"
        "    Stärkere Parallelisierung im Training\n"
        "  Architektur\n"
        "    Encoder-Stack (N=6)\n"
        "    Decoder-Stack (N=6)\n"
        "    Residual-Verbindungen + Layer Normalization\n"
        "  Attention-Mechanik\n"
        "    Scaled Dot-Product Attention\n"
        "    Multi-Head Attention (h=8, d_k=d_v=64)\n"
        "  Positionsinformation\n"
        "    Sinusoidale Positional Encoding\n"
        "  Training\n"
        "    Adam + Warmup (4000 Schritte)\n"
        "    Batching nach Sequenzlänge\n"
        "  Ergebnisse\n"
        "    WMT14 EN-DE: BLEU 28.4 (Transformer big)\n"
        "    WMT14 EN-FR: BLEU 41.8 (Transformer big)\n"
        "```"
    )


def _mindmap_attention_focus() -> str:
    return (
        "```mindmap\n"
        "Transformer Attention-Design\n"
        "  Scaled Dot-Product Attention\n"
        "    Softmax(QK^T / sqrt(d_k))\n"
        "    Skalierung stabilisiert Gradienten\n"
        "  Multi-Head Attention\n"
        "    Mehrere Köpfe für unterschiedliche Repräsentationsräume\n"
        "    Standard: h=8, d_k=d_v=64\n"
        "  Drei Einsätze im Modell\n"
        "    Encoder Self-Attention\n"
        "    Decoder Self-Attention mit Masking\n"
        "    Encoder-Decoder Attention\n"
        "  Nutzen\n"
        "    Globale Abhängigkeiten mit kurzen Pfaden\n"
        "```"
    )


def _mindmap_results_focus() -> str:
    return (
        "```mindmap\n"
        "Transformer Ergebnisse und Aufwand\n"
        "  Hauptbenchmarks\n"
        "    WMT14 EN-DE: BLEU 28.4 (big)\n"
        "    WMT14 EN-FR: BLEU 41.8 (big)\n"
        "  Vergleich zu früheren Ansätzen\n"
        "    Übertrifft frühere Single-Modelle und Ensembles\n"
        "    Deutlich geringerer Trainingsaufwand\n"
        "  Trainingsprofil\n"
        "    Base: 100k Schritte, ~12h auf 8x P100\n"
        "    Big: 300k Schritte, ~3.5 Tage auf 8x P100\n"
        "  Schlussfolgerung\n"
        "    Bessere Qualität bei besserer Parallelisierbarkeit\n"
        "```"
    )


def _mindmap_training_focus() -> str:
    return (
        "```mindmap\n"
        "Transformer Trainingsregime\n"
        "  Daten\n"
        "    WMT14 EN-DE ~4.5M Satzpaare\n"
        "    WMT14 EN-FR ~36M Satzpaare\n"
        "  Optimizer\n"
        "    Adam (beta1=0.9, beta2=0.98, eps=1e-9)\n"
        "    Lernraten-Warmup: 4000 Schritte\n"
        "  Regularisierung\n"
        "    Dropout (typisch 0.1)\n"
        "    Label Smoothing (eps_ls=0.1)\n"
        "  Inferenz\n"
        "    Beam Search (Beam 4, alpha 0.6)\n"
        "```"
    )


def _mindmap_position_focus() -> str:
    return (
        "```mindmap\n"
        "Positional Encoding im Transformer\n"
        "  Problemstellung\n"
        "    Keine Rekurrenz und keine Convolution\n"
        "    Positionsinformation muss explizit injiziert werden\n"
        "  Sinusoidale Kodierung\n"
        "    Sinus- und Kosinusfunktionen über verschiedene Frequenzen\n"
        "    Erlaubt Repräsentation relativer Offsets\n"
        "  Vergleich\n"
        "    Gelerntes Positional Embedding liefert ähnliche Resultate\n"
        "  Praktischer Nutzen\n"
        "    Bessere Extrapolation auf längere Sequenzen\n"
        "```"
    )


def _map_for_query(query: str) -> str:
    focus = _classify_focus(query)
    if focus == "attention":
        return _mindmap_attention_focus()
    if focus == "results":
        return _mindmap_results_focus()
    if focus == "training":
        return _mindmap_training_focus()
    if focus == "position":
        return _mindmap_position_focus()
    return _mindmap_overview()


@dataclass
class _PlannerWorker:
    _agent_iterations: int = 0

    def count_tokens(self, _text: str) -> int:
        return 128

    def context_window(self, _default_n_ctx: int = 4096) -> int:
        return 4096

    def run_completion_sync(self, prompt: str, **_kwargs: Any) -> str:
        text = str(prompt or "")
        low = text.casefold()
        if "extrahiere 3-5 schlüsselkonzepte" in low:
            if "bleu" in low or "wmt" in low:
                return "Transformer, BLEU, WMT 2014, Training"
            if "multi-head" in low or "scaled dot-product" in low:
                return "Multi-Head Attention, Scaled Dot-Product, Encoder, Decoder"
            if "position" in low:
                return "Positional Encoding, Sinusoidal, Sequence Order"
            if "training" in low or "warmup" in low:
                return "Training, Adam, Warmup, Dropout"
            return "Transformer, Architecture, Attention, Results"

        if "du bist ein retrieval-agent" in low:
            self._agent_iterations += 1
            query = _extract_between(
                text,
                "Ziel-Anfrage:\n",
                "\n\nBereits extrahierte Konzepte:",
            ).casefold()
            if self._agent_iterations == 1:
                if "bleu" in query or "wmt" in query:
                    return (
                        '{"action":"tool","tool":"heading_search",'
                        '"args":{"pattern":"Results|Machine Translation|WMT|BLEU","max_sections":6},'
                        '"reason":"zuerst benchmark-abschnitte"}'
                    )
                if "multi-head" in query or "scaled dot-product" in query:
                    return (
                        '{"action":"tool","tool":"heading_search",'
                        '"args":{"pattern":"3.2|Attention|Multi-Head|Scaled Dot-Product","max_sections":6},'
                        '"reason":"architektur-abschnitt lokalisieren"}'
                    )
                if "position" in query:
                    return (
                        '{"action":"tool","tool":"heading_search",'
                        '"args":{"pattern":"3.5 Positional Encoding|sinusoidal","max_sections":4},'
                        '"reason":"positionsabschnitt priorisieren"}'
                    )
                return (
                    '{"action":"tool","tool":"heading_search",'
                    '"args":{"pattern":"Abstract|Model Architecture|Training|Results","max_sections":8},'
                    '"reason":"ueberblicksabschnitte sammeln"}'
                )
            if self._agent_iterations == 2:
                if "bleu" in query or "wmt" in query:
                    return (
                        '{"action":"tool","tool":"regex_search",'
                        '"args":{"pattern":"BLEU|WMT 2014|3.5 days|100,000 steps","max_results":8},'
                        '"reason":"metriken und kosten absichern"}'
                    )
                if "multi-head" in query or "scaled dot-product" in query:
                    return (
                        '{"action":"tool","tool":"regex_search",'
                        '"args":{"pattern":"Scaled Dot-Product Attention|Multi-Head Attention|h = 8|d k = d v","max_results":8},'
                        '"reason":"kerndetails extrahieren"}'
                    )
                if "position" in query:
                    return (
                        '{"action":"tool","tool":"regex_search",'
                        '"args":{"pattern":"sinusoidal|positional encoding|wavelengths","max_results":6},'
                        '"reason":"positionsdetails absichern"}'
                    )
                return (
                    '{"action":"tool","tool":"regex_search",'
                    '"args":{"pattern":"Transformer|Encoder|Decoder|self-attention|WMT","max_results":10},'
                    '"reason":"belegstellen fuer kernknoten"}'
                )
            return '{"action":"finish","reason":"evidenz ausreichend"}'

        if "überarbeite diese" in low and "originale struktur:\n" in low:
            original = _extract_between(text, "Originale Struktur:\n", "\n\nKontext (maßgebliche Quelle):")
            return original or _mindmap_overview()

        return ""


@dataclass
class _LLMManagerStub:
    worker: _PlannerWorker

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
        _ = context_text, mode, max_nodes, chunking_strategy, chunk_size, chunk_overlap
        return _map_for_query(query), {"reason": "aiayn_stub", "mode": "mindmap"}


@dataclass(frozen=True)
class _Scenario:
    scenario_id: str
    query: str
    retrieval_strategy: str
    factcheck: bool
    agent_max_iterations: int
    max_nodes: int
    max_refinement_rounds: int
    required_keywords: tuple[str, ...]
    min_hits: int
    min_root_children: int


def _load_aiayn_markdown() -> str:
    override = str(os.environ.get("D2C_AIA1706_MD_PATH", "") or "").strip()
    path = Path(override) if override else _DEFAULT_AIA_PATH
    if not path.exists():
        pytest.skip(
            "AIAYN source markdown not found. "
            f"Expected at: {path} (override with D2C_AIA1706_MD_PATH)."
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    if "Attention Is All You Need" not in text:
        pytest.skip(f"Unexpected markdown content for AIAYN testcase: {path}")
    return text


def _quality_summary(markdown: str, *, scenario: _Scenario) -> dict[str, object]:
    spec = extract_graph_spec(markdown)
    assert spec is not None, "generated markdown must be parseable as structured mindmap"
    assert str(spec.kind or "").casefold() == "mindmap"

    nodes = dict(spec.nodes or {})
    roots = [str(x or "") for x in list(spec.roots or []) if str(x or "").strip()]
    assert roots, "mindmap must have at least one root"
    root = nodes.get(roots[0])
    root_label = str(getattr(root, "label", "") or "")
    assert any(token in root_label.casefold() for token in ("attention", "transformer"))

    node_count = len(nodes)
    assert node_count >= 6
    assert node_count <= int(scenario.max_nodes)

    root_children = list(getattr(root, "children", []) or []) if root is not None else []
    assert len(root_children) >= int(scenario.min_root_children)

    corpus = " ".join(
        [
            str(getattr(node, "label", "") or "")
            for node in list(nodes.values())
        ]
        + [
            str(getattr(node, "quote", "") or "")
            for node in list(nodes.values())
            if str(getattr(node, "quote", "") or "").strip()
        ]
    ).casefold()
    keyword_hits = sum(1 for term in scenario.required_keywords if str(term).casefold() in corpus)
    assert keyword_hits >= int(scenario.min_hits)
    assert "softwareentwicklungserfolg" not in corpus

    return {
        "node_count": node_count,
        "root_label": root_label,
        "keyword_hits": keyword_hits,
        "keywords": list(scenario.required_keywords),
    }


def _scenarios() -> list[_Scenario]:
    return [
        _Scenario(
            scenario_id="overview_none",
            query="Welche zentralen Konzepte beantworten die Fragestellung im Kontext?",
            retrieval_strategy="none",
            factcheck=False,
            agent_max_iterations=3,
            max_nodes=28,
            max_refinement_rounds=0,
            required_keywords=("architektur", "attention", "training", "bleu"),
            min_hits=3,
            min_root_children=4,
        ),
        _Scenario(
            scenario_id="overview_rag_factcheck",
            query="Welche zentralen Konzepte beantworten die Fragestellung im Kontext?",
            retrieval_strategy="rag",
            factcheck=True,
            agent_max_iterations=4,
            max_nodes=36,
            max_refinement_rounds=1,
            required_keywords=("encoder", "decoder", "multi-head", "wmt14"),
            min_hits=3,
            min_root_children=4,
        ),
        _Scenario(
            scenario_id="overview_agent_factcheck",
            query="Welche zentralen Konzepte beantworten die Fragestellung im Kontext?",
            retrieval_strategy="agent",
            factcheck=True,
            agent_max_iterations=6,
            max_nodes=36,
            max_refinement_rounds=1,
            required_keywords=("transformer", "attention", "training", "ergebnisse"),
            min_hits=4,
            min_root_children=4,
        ),
        _Scenario(
            scenario_id="focus_attention_rag",
            query="Wie funktioniert Multi-Head Attention im Encoder und Decoder des Transformers?",
            retrieval_strategy="rag",
            factcheck=True,
            agent_max_iterations=4,
            max_nodes=32,
            max_refinement_rounds=1,
            required_keywords=("scaled dot-product", "multi-head", "encoder", "decoder", "mask"),
            min_hits=4,
            min_root_children=3,
        ),
        _Scenario(
            scenario_id="focus_results_agent",
            query="Welche BLEU-Ergebnisse und Trainingsaufwände berichtet das Paper konkret?",
            retrieval_strategy="agent",
            factcheck=True,
            agent_max_iterations=6,
            max_nodes=32,
            max_refinement_rounds=1,
            required_keywords=("bleu", "wmt14", "28.4", "41.8", "3.5"),
            min_hits=4,
            min_root_children=3,
        ),
        _Scenario(
            scenario_id="focus_position_none",
            query="Welche Rolle spielt Positional Encoding im Transformer?",
            retrieval_strategy="none",
            factcheck=False,
            agent_max_iterations=3,
            max_nodes=24,
            max_refinement_rounds=0,
            required_keywords=("positional", "sinus", "sequence", "position"),
            min_hits=3,
            min_root_children=3,
        ),
    ]


def test_aiayn_mindmap_quality_matrix(tmp_path: Path):
    source_md = _load_aiayn_markdown()
    scenarios = _scenarios()
    results: list[dict[str, object]] = []

    for scenario in scenarios:
        manager = _LLMManagerStub(worker=_PlannerWorker())
        tools = build_tools(
            llm_manager=manager,
            source_texts=[("arxiv_1706.03762.md", source_md)],
        )
        service = AgenticWorkflowService(plugin_manager=object())
        run = service.run_mindmap(
            request={
                "query": scenario.query,
                "context_text": source_md,
                "retrieval_strategy": scenario.retrieval_strategy,
                "agent_max_iterations": scenario.agent_max_iterations,
                "factcheck": scenario.factcheck,
                "max_refinement_rounds": scenario.max_refinement_rounds,
                "max_nodes": scenario.max_nodes,
            },
            tools=tools,
            profile_id="mindmap_v2_local",
            enabled=True,
        )

        assert bool(run.ok), f"{scenario.scenario_id}: run must succeed, errors={list(run.errors or [])}"
        markdown = str(run.result.get("markdown", "") or "")
        quality = _quality_summary(markdown, scenario=scenario)

        state = dict(run.state or {})
        metrics = dict(run.metrics or {})
        tool_calls = dict(metrics.get("tool_calls", {}) or {})
        snippets = list(state.get("rag_snippets", []) or [])
        retrieval_steps = list(state.get("retrieval_agent_steps", []) or [])

        if scenario.retrieval_strategy == "none":
            assert snippets == []
            assert retrieval_steps == []
            assert tool_calls == {}
        elif scenario.retrieval_strategy == "rag":
            assert snippets, f"{scenario.scenario_id}: rag should provide evidence snippets"
            assert int(tool_calls.get("rag.search", 0)) >= 1
        else:
            assert retrieval_steps, f"{scenario.scenario_id}: agent strategy needs retrieval steps"
            assert any(str(row.get("action", "")).casefold() == "tool" for row in retrieval_steps)
            assert int(tool_calls.get("heading_search", 0)) + int(tool_calls.get("regex_search", 0)) >= 1

        trace_rows = list(run.trace or [])
        assert any(str(row.step_id or "") == "structure_validation" and str(row.status or "") == "ok" for row in trace_rows)
        if scenario.factcheck:
            assert any(str(row.step_id or "") == "fact_verification" for row in trace_rows)

        results.append(
            {
                "scenario_id": scenario.scenario_id,
                "query": scenario.query,
                "retrieval_strategy": scenario.retrieval_strategy,
                "factcheck": bool(scenario.factcheck),
                "quality": quality,
                "tool_calls": tool_calls,
                "rag_snippets": len(snippets),
                "retrieval_steps": len(retrieval_steps),
                "trace_steps": len(trace_rows),
                "markdown_preview": markdown[:1200],
            }
        )

    report_path = tmp_path / "aiayn_mindmap_matrix_report.json"
    report_path.write_text(
        json.dumps(
            {
                "paper": "arxiv 1706.03762",
                "total_scenarios": len(scenarios),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    assert report_path.exists()
