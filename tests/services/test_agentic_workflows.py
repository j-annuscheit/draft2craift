from __future__ import annotations

from pathlib import Path

from shared.domain.graph_codec import extract_graph_spec
from shared.domain.graph_validation import GraphValidationLimits, validate_graph_spec
from shared.services.agentic.service import AgenticWorkflowService


def _service() -> AgenticWorkflowService:
    return AgenticWorkflowService(repo_root=Path("/home/be/test_claude/canvas2"))


def test_factcheck_workflow_runs_and_emits_rows():
    svc = _service()
    result = svc.run(
        workflow_id="factcheck_agentic",
        profile_id="factcheck_regex_only",
        request={
            "q": [("doc1", "Alice lebt in Berlin.")],
            "c": "Alice lebt in Berlin. Bob lebt in Paris.",
            "o": {"rows": [{"fact": "Alice lebt in Berlin."}]},
        },
        tools={
            "rag.search": lambda **kwargs: [
                "Alice lebt in Berlin.",
                "Bob lebt in Paris.",
            ],
            "nli.verify": lambda premise, hypothesis: {
                "label": "entailment" if str(hypothesis) in str(premise) else "neutral",
                "score": 0.91 if str(hypothesis) in str(premise) else 0.1,
            },
            "llm.generate": lambda **kwargs: "ok",
        },
    )
    assert result.ok is True
    rows = list(result.result.get("o", []) or [])
    assert rows
    facts = {str(row.get("fact", "")) for row in rows}
    assert "Bob lebt in Paris." in facts


def test_factcheck_workflow_respects_max_evidence_chunks_and_can_disable_nli():
    svc = _service()
    rag_calls: list[dict[str, object]] = []
    nli_calls = {"count": 0}
    result = svc.run(
        workflow_id="factcheck_agentic",
        profile_id="factcheck_regex_only",
        request={
            "q": [("doc1", "Alice lebt in Berlin.")],
            "c": "Alice lebt in Berlin.",
            "o": {"rows": []},
        },
        policy_overrides={
            "allow_nli": False,
            "max_evidence_chunks": 1,
        },
        tools={
            "rag.search": lambda **kwargs: (
                rag_calls.append(dict(kwargs or {})) or ["Alice lebt in Berlin.", "Zusatzbeleg"]
            ),
            "nli.verify": lambda **kwargs: nli_calls.__setitem__("count", nli_calls["count"] + 1),
            "llm.generate": lambda **kwargs: "ok",
        },
    )
    assert result.ok is True
    rows = list(result.result.get("o", []) or [])
    assert rows
    assert nli_calls["count"] == 0
    assert rag_calls
    evidence = str(rows[0].get("evidence", "") or "")
    assert "Zusatzbeleg" not in evidence
    assert "Alice lebt in Berlin." in evidence


def test_chat_workflow_runs():
    svc = _service()
    result = svc.run(
        workflow_id="chat_agentic",
        profile_id="chat_grounded_strict",
        request={"question": "Was steht in den Quellen?"},
        tools={
            "rag.search": lambda **kwargs: ["Quelle A: Fakt 1", "Quelle B: Fakt 2"],
            "llm.generate": lambda **kwargs: "Antwort mit Quellenbezug.",
        },
    )
    assert result.ok is True
    payload = result.result.get("response", {})
    assert "Antwort" in str(payload.get("text", ""))


def test_canvas_workflow_runs_and_calls_apply():
    svc = _service()
    calls: list[str] = []

    def _apply(**kwargs):
        calls.append(str(kwargs.get("text", "")))

    result = svc.run(
        workflow_id="canvas_agentic",
        profile_id="canvas_grounded_rewrite",
        request={"instruction": "Kürze den Text.", "selected_text": "Langer Text."},
        tools={
            "llm.generate": lambda **kwargs: "Gekürzter Text.",
            "canvas.apply": _apply,
        },
    )
    assert result.ok is True
    assert calls and calls[-1] == "Gekürzter Text."


def test_mindmap_v3_workflow_runs_and_opens_canvas_text():
    svc = _service()
    opened: list[str] = []
    llm_calls = {"count": 0}

    def _llm(**_kwargs):
        llm_calls["count"] += 1
        prompt = str(_kwargs.get("prompt", "") or "")
        if "Parent: Methoden" in prompt:
            return '{"children":[{"label":"Datenerhebung"},{"label":"Auswertung"}]}'
        if "Parent: Ergebnisse" in prompt:
            return '{"children":[{"label":"Befunde"},{"label":"Interpretation"}]}'
        if "Parent: Einleitung" in prompt:
            return '{"children":[{"label":"Zielsetzung"}]}'
        return '{"children":[{"label":"Kontext"}]}'

    result = svc.run(
        workflow_id="mindmap_agentic",
        profile_id="mindmap_grounded_graph",
        request={
            "mode": "mindmap",
            "query": "technische Risiken und zentrale Projektstruktur",
            "depth": 4,
            "context_text": (
                "# Projekt\n\n"
                "## Einleitung\nDas Projekt beschreibt Zielsetzung und Kontext.\n\n"
                "## Methoden\nDie Arbeit beschreibt Datenerhebung und Auswertung.\n\n"
                "## Ergebnisse\nDie Ergebnisse zeigen Befunde und Interpretation.\n"
            ),
        },
        tools={
            "llm.generate": _llm,
            "canvas.open_text": lambda **kwargs: opened.append(str(kwargs.get("text", ""))),
        },
    )
    assert result.ok is True
    assert opened
    spec = extract_graph_spec(opened[-1])
    assert spec is not None
    report = validate_graph_spec(
        spec,
        limits=GraphValidationLimits(
            require_single_root=True,
            allow_cycles=False,
            require_connected=True,
        ),
    )
    assert report.ok is True
    assert llm_calls["count"] >= 1


def test_mindmap_v3_workflow_falls_back_to_seed_when_llm_returns_empty():
    svc = _service()
    opened: list[str] = []

    result = svc.run(
        workflow_id="mindmap_agentic",
        profile_id="mindmap_grounded_graph",
        request={
            "mode": "mindmap",
            "query": "Projektueberblick",
            "depth": 3,
            "context_text": (
                "# Projekt\n\n"
                "## Einleitung\nDas Projekt beschreibt Zielsetzung.\n\n"
                "## Ergebnisse\nDie Ergebnisse zeigen Befunde.\n"
            ),
        },
        tools={
            "llm.generate": lambda **_kwargs: "",
            "canvas.open_text": lambda **kwargs: opened.append(str(kwargs.get("text", ""))),
        },
    )
    assert result.ok is True
    assert opened
    assert "Einleitung" in opened[-1]
    assert "Ergebnisse" in opened[-1]


def test_graph_workflow_closes_disconnected_components():
    svc = _service()
    opened: list[str] = []
    llm_calls = {"count": 0}

    def _llm_generate(**_kwargs):
        llm_calls["count"] += 1
        if llm_calls["count"] == 1:
            return (
                "```graph\n"
                '{"type":"graph","title":"G","nodes":[{"id":"a","label":"Alpha"},{"id":"b","label":"Beta"},'
                '{"id":"c","label":"Gamma"},{"id":"d","label":"Delta"}],'
                '"edges":[{"from":"a","to":"b"},{"from":"c","to":"d"}]}'
                "\n```"
            )
        return (
            "```graph\n"
            '{"type":"graph","title":"G","nodes":[{"id":"a","label":"Alpha"},{"id":"b","label":"Beta"},'
            '{"id":"c","label":"Gamma"},{"id":"d","label":"Delta"}],'
            '"edges":[{"from":"a","to":"b"},{"from":"b","to":"c"},{"from":"c","to":"d"}]}'
            "\n```"
        )

    result = svc.run(
        workflow_id="graph_agentic",
        profile_id="graph_connected_component",
        request={
            "mode": "graph",
            "scope": "selection",
            "query": "Verbinde alle Teilgraphen",
            "context_text": "A zu B. C zu D. B verbindet zu C.",
        },
        tools={
            "llm.generate": _llm_generate,
            "canvas.open_text": lambda **kwargs: opened.append(str(kwargs.get("text", ""))),
        },
    )
    assert result.ok is True
    assert opened
    spec = extract_graph_spec(opened[-1])
    assert spec is not None
    report = validate_graph_spec(
        spec,
        limits=GraphValidationLimits(require_connected=True),
    )
    assert report.ok is True
    assert int(report.stats.get("components", 0) or 0) == 1
    assert llm_calls["count"] >= 2


def test_mindmap_v3_candidate_commits_update_result():
    svc = _service()
    opened: list[str] = []
    llm_calls = {"count": 0}

    def _llm(**_kwargs):
        llm_calls["count"] += 1
        prompt = str(_kwargs.get("prompt", "") or "")
        if "Parent: Architektur" in prompt:
            return '{"children":[{"label":"Module"},{"label":"Schnittstellen"}]}'
        return '{"children":[{"label":"Anforderungen"}]}'

    result = svc.run(
        workflow_id="mindmap_agentic",
        profile_id="mindmap_grounded_graph",
        request={
            "mode": "mindmap",
            "query": "Architektur",
            "depth": 4,
            "context_text": (
                "# System\n\n"
                "## Architektur\nDie Architektur beschreibt Module und Schnittstellen.\n\n"
                "## Risiken\nAnforderungen und Risiken muessen sichtbar sein.\n"
            ),
        },
        tools={
            "llm.generate": _llm,
            "canvas.open_text": lambda **kwargs: opened.append(str(kwargs.get("text", ""))),
        },
    )
    assert result.ok is True
    assert opened
    assert "Module" in opened[-1]
    assert "Schnittstellen" in opened[-1]
    assert int(result.state.get("map_metrics", {}).get("candidate_commits", 0) or 0) >= 1


def test_mindmap_v3_seed_enrichment_adds_grounded_top_level_nodes():
    svc = _service()
    opened: list[str] = []

    def _llm(**kwargs):
        prompt = str(kwargs.get("prompt", "") or "")
        if "Startbaum einer Mindmap" in prompt:
            return '{"nodes":[{"label":"Architektur"},{"label":"Risiken"}]}'
        return ""

    result = svc.run(
        workflow_id="mindmap_agentic",
        profile_id="mindmap_grounded_graph",
        request={
            "mode": "mindmap",
            "query": "Architektur und Risiken",
            "depth": 2,
            "context_text": (
                "# Projekt\n\n"
                "## Einleitung\nDas Projekt beschreibt Architektur und Risiken im Ueberblick.\n\n"
                "## Umsetzung\nDie Umsetzung beleuchtet Module, Schnittstellen und Prioritaeten.\n"
            ),
        },
        tools={
            "llm.generate": _llm,
            "canvas.open_text": lambda **kwargs: opened.append(str(kwargs.get("text", ""))),
        },
    )
    assert result.ok is True
    assert opened
    assert "Architektur" in opened[-1]
    assert "Risiken" in opened[-1]


def test_mindmap_v3_repairs_inline_child_output_without_llm_retry():
    svc = _service()
    opened: list[str] = []

    def _llm(**kwargs):
        prompt = str(kwargs.get("prompt", "") or "")
        if "Startbaum einer Mindmap" in prompt:
            return ""
        if "Parent: Methoden" in prompt:
            return "Datenerhebung, Auswertung"
        return ""

    result = svc.run(
        workflow_id="mindmap_agentic",
        profile_id="mindmap_grounded_graph",
        request={
            "mode": "mindmap",
            "query": "Methoden",
            "depth": 3,
            "context_text": (
                "# Studie\n\n"
                "## Methoden\nDie Methoden umfassen Datenerhebung und Auswertung.\n\n"
                "## Ergebnisse\nDie Ergebnisse werden spaeter diskutiert.\n"
            ),
        },
        tools={
            "llm.generate": _llm,
            "canvas.open_text": lambda **kwargs: opened.append(str(kwargs.get("text", ""))),
        },
    )
    assert result.ok is True
    assert opened
    assert "Datenerhebung" in opened[-1]
    assert "Auswertung" in opened[-1]
    repaired_steps = [trace for trace in list(result.trace or []) if trace.step_id == "repair_child_nodes"]
    assert repaired_steps
    assert any(bool(dict(step.output.get("meta", {}) or {}).get("repaired", False)) for step in repaired_steps)


def test_mindmap_v3_gap_fill_adds_missing_focus_nodes():
    svc = _service()
    opened: list[str] = []

    def _llm(**kwargs):
        prompt = str(kwargs.get("prompt", "") or "")
        if "Startbaum einer Mindmap" in prompt:
            return ""
        if "Du schliesst eine konkrete Inhaltsluecke" in prompt:
            return '{"children":[{"label":"Sicherheit"},{"label":"Zeitplan"}]}'
        return ""

    result = svc.run(
        workflow_id="mindmap_agentic",
        profile_id="mindmap_grounded_graph",
        request={
            "mode": "mindmap",
            "query": "Sicherheit und Zeitplan",
            "depth": 2,
            "context_text": (
                "# Projekt\n\n"
                "## Architektur\nDas System hat Module und Schnittstellen.\n\n"
                "Der kritische Pfad betrifft Sicherheit und Zeitplan.\n\n"
                "## Betrieb\nDeployment und Monitoring werden dokumentiert.\n"
            ),
        },
        tools={
            "llm.generate": _llm,
            "canvas.open_text": lambda **kwargs: opened.append(str(kwargs.get("text", ""))),
        },
        policy_overrides={"map_seed_enrichment_enabled": False},
    )
    assert result.ok is True
    assert opened
    assert "Sicherheit" in opened[-1]
    assert "Zeitplan" in opened[-1]
    assert int(result.state.get("map_metrics", {}).get("gap_round", 0) or 0) >= 1


def test_graph_workflow_expand_loop_respects_target_depth():
    svc = _service()
    opened: list[str] = []
    llm_calls = {"count": 0}

    def _llm_generate(**_kwargs):
        llm_calls["count"] += 1
        if llm_calls["count"] == 1:
            return (
                "```graph\n"
                '{"type":"graph","title":"G","nodes":[{"id":"alpha","label":"Alpha"},{"id":"beta","label":"Beta"}],'
                '"edges":[{"from":"alpha","to":"beta"}]}'
                "\n```"
            )
        if llm_calls["count"] == 2:
            return (
                "```graph\n"
                '{"type":"graph","title":"G","nodes":[{"id":"alpha","label":"Alpha"},{"id":"beta","label":"Beta"},'
                '{"id":"gamma","label":"Gamma"}],'
                '"edges":[{"from":"alpha","to":"beta"},{"from":"beta","to":"gamma"}]}'
                "\n```"
            )
        return (
            "```graph\n"
            '{"type":"graph","title":"G","nodes":[{"id":"alpha","label":"Alpha"},{"id":"beta","label":"Beta"},'
            '{"id":"gamma","label":"Gamma"},{"id":"delta","label":"Delta"}],'
            '"edges":[{"from":"alpha","to":"beta"},{"from":"beta","to":"gamma"},{"from":"gamma","to":"delta"}]}'
            "\n```"
        )

    result = svc.run(
        workflow_id="graph_agentic",
        profile_id="graph_connected_component",
        request={
            "mode": "graph",
            "scope": "selection",
            "query": "Baue den Graph weiter aus",
            "context_text": "Alpha zu Beta zu Gamma zu Delta.",
        },
        policy_overrides={
            "map_expand_enabled": True,
            "map_expand_target_depth": 2,
        },
        tools={
            "llm.generate": _llm_generate,
            "canvas.open_text": lambda **kwargs: opened.append(str(kwargs.get("text", ""))),
        },
    )
    assert result.ok is True
    assert opened
    assert int(result.state.get("expand_round", 0) or 0) == 2
    assert llm_calls["count"] >= 3


def test_graph_workflow_recovers_from_connected_but_off_topic_draft():
    svc = _service()
    opened: list[str] = []
    llm_calls = {"count": 0}

    def _llm_generate(**_kwargs):
        llm_calls["count"] += 1
        if llm_calls["count"] == 1:
            return (
                "```graph\n"
                '{"type":"graph","title":"G","nodes":[{"id":"ai","label":"Kuenstliche Intelligenz"},'
                '{"id":"ml","label":"Maschinelles Lernen"},{"id":"nn","label":"Neuronale Netze"}],'
                '"edges":[{"from":"ai","to":"ml"},{"from":"ml","to":"nn"}]}\n'
                "```"
            )
        return (
            "```graph\n"
            '{"type":"graph","title":"G","nodes":[{"id":"alpha","label":"Alpha"},'
            '{"id":"beta","label":"Beta"},{"id":"gamma","label":"Gamma"}],'
            '"edges":[{"from":"alpha","to":"beta","label":"verbindet"},{"from":"beta","to":"gamma","label":"fuehrt zu"}]}\n'
            "```"
        )

    result = svc.run(
        workflow_id="graph_agentic",
        profile_id="graph_connected_component",
        request={
            "mode": "graph",
            "scope": "selection",
            "query": "Welche zentralen Entitaeten und Beziehungen sind im Kontext belegt?",
            "context_text": "Alpha verbindet Beta. Beta fuehrt zu Gamma.",
        },
        tools={
            "llm.generate": _llm_generate,
            "canvas.open_text": lambda **kwargs: opened.append(str(kwargs.get("text", ""))),
        },
    )
    assert result.ok is True
    assert opened
    assert "Alpha" in opened[-1]
    assert "Kuenstliche Intelligenz" not in opened[-1]
    assert llm_calls["count"] >= 2


def test_profile_wiring_overrides_runner_for_factcheck_regex():
    svc = _service()
    calls: list[str] = []

    def _rag_search(**kwargs):
        calls.append(str(kwargs.get("mode", "")))
        return ["Beleg"]

    result = svc.run(
        workflow_id="factcheck_agentic",
        profile_id="factcheck_regex_only",
        request={
            "q": [],
            "c": "Testaussage.",
            "o": {"rows": []},
        },
        tools={
            "rag.search": _rag_search,
            "nli.verify": lambda **kwargs: {"label": "neutral", "score": 0.2},
            "llm.generate": lambda **kwargs: "ok",
        },
    )
    assert result.ok is True
    assert calls
    assert all(mode == "regex" for mode in calls)


def test_run_mindmap_wrapper_accepts_enabled_override(monkeypatch):
    monkeypatch.delenv("D2C_AGENTIC_MINDMAP", raising=False)
    svc = _service()

    result = svc.run_mindmap(
        request={
            "mode": "mindmap",
            "query": "Test",
            "depth": 3,
            "context_text": "# Thema\n\n## Unterpunkt\nThema A ist der Hauptpunkt. Thema B ist ein Unterpunkt.",
        },
        profile_id="mindmap_grounded_graph",
        enabled=True,
        tools={
            "llm.generate": lambda **_kwargs: '{"children":[{"label":"Thema B"}]}',
            "canvas.open_text": lambda **kwargs: None,
        },
    )
    assert result.ok is True


def test_run_chat_wrapper_accepts_enabled_override(monkeypatch):
    monkeypatch.delenv("D2C_AGENTIC_CHAT", raising=False)
    svc = _service()
    result = svc.run_chat(
        request={"question": "Was steht in den Quellen?"},
        profile_id="chat_grounded_strict",
        enabled=True,
        tools={
            "rag.search": lambda **kwargs: ["Quelle A: Fakt 1"],
            "llm.generate": lambda **kwargs: "Antwort mit Quellenbezug.",
        },
    )
    assert result.ok is True


def test_run_graph_wrapper_accepts_enabled_override(monkeypatch):
    monkeypatch.delenv("D2C_AGENTIC_GRAPH", raising=False)
    monkeypatch.delenv("D2C_AGENTIC_MINDMAP", raising=False)
    svc = _service()
    result = svc.run_graph(
        request={
            "query": "Verbinde den Graphen",
            "context_text": "A -> B -> C",
        },
        profile_id="graph_connected_component",
        enabled=True,
        tools={
            "llm.generate": lambda **kwargs: "```graph\nAlpha --> Beta\nBeta --> Gamma\n```",
            "canvas.open_text": lambda **kwargs: None,
        },
    )
    assert result.ok is True


def test_graph_workflow_fails_when_disconnected_and_no_force_connect():
    svc = _service()
    result = svc.run(
        workflow_id="graph_agentic",
        profile_id="graph_connected_component",
        request={
            "mode": "graph",
            "scope": "selection",
            "query": "Verbinde alles",
            "context_text": "A zu B. C zu D.",
        },
        policy_overrides={
            "graph_connect_max_tries": 0,
            "graph_force_connect_on_max_tries": False,
            "map_require_connected_graph": True,
        },
        tools={
            "llm.generate": lambda **kwargs: (
                "```graph\n"
                '{"type":"graph","nodes":[{"id":"a","label":"Alpha"},{"id":"b","label":"Beta"},'
                '{"id":"c","label":"Gamma"},{"id":"d","label":"Delta"}],'
                '"edges":[{"from":"a","to":"b"},{"from":"c","to":"d"}]}'
                "\n```"
            ),
            "canvas.open_text": lambda **kwargs: None,
        },
    )
    assert result.ok is False
    assert result.errors


def test_graph_workflow_force_connects_on_max_tries():
    svc = _service()
    result = svc.run(
        workflow_id="graph_agentic",
        profile_id="graph_connected_component",
        request={
            "mode": "graph",
            "scope": "selection",
            "query": "Verbinde alles",
            "context_text": "A zu B. C zu D.",
        },
        policy_overrides={
            "graph_connect_max_tries": 0,
            "graph_force_connect_on_max_tries": True,
            "map_require_connected_graph": True,
        },
        tools={
            "llm.generate": lambda **kwargs: (
                "```graph\n"
                '{"type":"graph","nodes":[{"id":"a","label":"Alpha"},{"id":"b","label":"Beta"},'
                '{"id":"c","label":"Gamma"},{"id":"d","label":"Delta"}],'
                '"edges":[{"from":"a","to":"b"},{"from":"c","to":"d"}]}'
                "\n```"
            ),
            "canvas.open_text": lambda **kwargs: None,
        },
    )
    validation = dict(result.state.get("map_validation", {}) or {})
    stats = dict(validation.get("stats", {}) or {})
    assert result.ok is True
    assert validation.get("ok") is True
    assert int(stats.get("components", 0) or 0) == 1
    assert bool(result.state.get("graph_force_applied", False)) is True
