from __future__ import annotations

import unittest

from studio.chat.factcheck.pipeline import FactCheckPipelineMixin
from studio.chat.factcheck.utils import build_source_chunks, select_evidence_snippet


class _HistoryStub:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    def add_message(self, role: str, message: str):
        self.messages.append((role, message))


class _NLIStub:
    def is_nli_model_loaded(self) -> bool:
        return True

    def verify_nli_sync(self, premise: str, hypothesis: str) -> dict[str, object]:
        p = str(premise or "")
        h = str(hypothesis or "")
        if "5 Bruecken" in p and "5 Bruecken" in h:
            return {
                "label": "entailment",
                "score": 0.91,
                "evidence": "Die Stadt hat 5 Bruecken.",
                "reason": "direct_match",
            }
        if "8 Bruecken" in h and "5 Bruecken" in p:
            return {
                "label": "contradiction",
                "score": 0.82,
                "evidence": "Die Stadt hat 5 Bruecken.",
                "reason": "numeric_conflict",
            }
        return {
            "label": "neutral",
            "score": 0.22,
            "evidence": "",
            "reason": "no_support",
        }


class _DockProxy(FactCheckPipelineMixin):
    def __init__(self):
        self.llm = _NLIStub()
        self.history = _HistoryStub()
        self._fact_result_handler = None
        self._pending_fact_check = False
        self._pending_fact_stage = ""
        self._pending_fact_target_text = ""
        self._pending_fact_target_label = ""
        self._pending_fact_sources: list[tuple[str, str]] = []
        self._pending_fact_facts: list[str] = []
        self._pending_fact_results: list[dict[str, str]] = []
        self._pending_fact_index = 0


class FactcheckNliFlowTests(unittest.TestCase):
    def test_build_source_chunks_splits_long_text(self):
        long_text = ("Abschnitt A " * 90) + "\n\n" + ("Abschnitt B " * 90)
        chunks = build_source_chunks([("Doc A", long_text)], chunk_size=300, chunk_overlap=80)
        self.assertGreaterEqual(len(chunks), 2)
        for name, chunk in chunks:
            self.assertEqual(name, "Doc A")
            self.assertTrue(chunk.strip())

    def test_select_evidence_snippet_prefers_matching_sentence(self):
        fact = "Die Stadt hat 5 Bruecken."
        chunk = (
            "Einleitung ohne Fakten. "
            "Die Stadt hat 5 Bruecken und einen Flusshafen. "
            "Weitere Randnotiz."
        )
        snippet = select_evidence_snippet(fact, chunk, max_chars=90)
        self.assertIn("5 Bruecken", snippet)

    def test_handle_extract_stage_uses_nli_and_marks_supported(self):
        dock = _DockProxy()
        dock._pending_fact_check = True
        dock._pending_fact_stage = "extract"
        dock._pending_fact_target_text = "Die Stadt hat 5 Bruecken."
        dock._pending_fact_target_label = "Target"
        dock._pending_fact_sources = [
            ("Doc A", "Die Stadt hat 5 Bruecken. Laut Bericht seit 2018 unveraendert."),
            ("Doc B", "Andere Quelle ohne relevanten Satz."),
        ]

        dock._handle_fact_pipeline_complete('["Die Stadt hat 5 Bruecken."]')

        self.assertFalse(dock._pending_fact_check)
        assistant_messages = [msg for role, msg in dock.history.messages if role == "assistant"]
        self.assertTrue(assistant_messages)
        self.assertIn("belegt", assistant_messages[-1])
        self.assertIn("belegt (0.91)", assistant_messages[-1])
        self.assertIn("Doc A", assistant_messages[-1])
        self.assertIn(
            "Die Stadt hat 5 Bruecken. Laut Bericht seit 2018 unveraendert.",
            assistant_messages[-1],
        )

    def test_verify_facts_with_nli_requires_entailment_for_belegt(self):
        dock = _DockProxy()
        results = dock._verify_facts_with_nli(
            facts=["Die Stadt hat 8 Bruecken."],
            source_chunks=[("Doc A", "Die Stadt hat 5 Bruecken.")],
        )
        self.assertEqual(len(results), 1)
        self.assertNotEqual(results[0]["status"], "belegt")

    def test_extract_stage_prefers_llm_json_facts(self):
        dock = _DockProxy()
        dock._pending_fact_check = True
        dock._pending_fact_stage = "extract"
        dock._pending_fact_target_text = "Satz eins. Satz zwei."
        dock._pending_fact_target_label = "Target"
        dock._pending_fact_sources = [("Doc A", "Nur Satz eins ist als Chunk enthalten.")]

        dock._handle_fact_pipeline_complete('["Satz eins."]')

        assistant_messages = [msg for role, msg in dock.history.messages if role == "assistant"]
        self.assertTrue(assistant_messages)
        self.assertIn("Satz eins.", assistant_messages[-1])
        self.assertNotIn("Satz zwei.", assistant_messages[-1])

    def test_verify_facts_with_nli_prefers_best_entailment_across_all_chunks(self):
        class _CustomNLI:
            def verify_nli_sync(self, premise: str, hypothesis: str) -> dict[str, object]:
                if "chunk-a" in premise:
                    return {"label": "entailment", "score": 0.31, "reason": "weak_hit"}
                if "chunk-b" in premise:
                    return {"label": "contradiction", "score": 0.98, "reason": "strong_conflict"}
                if "chunk-c" in premise:
                    return {"label": "entailment", "score": 0.72, "reason": "best_hit"}
                return {"label": "neutral", "score": 0.20, "reason": "none"}

        dock = _DockProxy()
        dock.llm = _CustomNLI()
        results = dock._verify_facts_with_nli(
            facts=["Beispiel-Fakt"],
            source_chunks=[
                ("Doc A", "chunk-a"),
                ("Doc B", "chunk-b"),
                ("Doc C", "chunk-c"),
            ],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "belegt")
        self.assertEqual(results[0]["sources"], "Doc C")
        self.assertEqual(results[0]["confidence"], "0.7200")

    def test_verify_facts_with_nli_marks_low_entailment_as_teilweise(self):
        class _LowEntailNLI:
            def verify_nli_sync(self, premise: str, hypothesis: str) -> dict[str, object]:
                if "hit" in premise:
                    return {"label": "entailment", "score": 0.41, "reason": "low_entailment"}
                return {"label": "contradiction", "score": 0.93, "reason": "conflict"}

        dock = _DockProxy()
        dock.llm = _LowEntailNLI()
        results = dock._verify_facts_with_nli(
            facts=["Beispiel-Fakt"],
            source_chunks=[
                ("Doc A", "hit"),
                ("Doc B", "other"),
            ],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "teilweise")
        self.assertEqual(results[0]["sources"], "Doc A")
        self.assertEqual(results[0]["confidence"], "0.4100")

    def test_verify_facts_with_nli_uses_best_contradiction_when_no_entailment(self):
        class _NoEntailNLI:
            def verify_nli_sync(self, premise: str, hypothesis: str) -> dict[str, object]:
                if "a" in premise:
                    return {"label": "contradiction", "score": 0.64, "reason": "weak_conflict"}
                if "b" in premise:
                    return {"label": "contradiction", "score": 0.91, "reason": "strong_conflict"}
                return {"label": "neutral", "score": 0.22, "reason": "none"}

        dock = _DockProxy()
        dock.llm = _NoEntailNLI()
        results = dock._verify_facts_with_nli(
            facts=["Beispiel-Fakt"],
            source_chunks=[
                ("Doc A", "a"),
                ("Doc B", "b"),
                ("Doc C", "c"),
            ],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "widerspruch")
        self.assertEqual(results[0]["sources"], "Doc B")
        self.assertEqual(results[0]["confidence"], "0.9100")

    def test_verify_facts_with_nli_uses_sentence_pass_when_chunk_has_no_entailment(self):
        class _SentenceFallbackNLI:
            def verify_nli_sync(self, premise: str, hypothesis: str) -> dict[str, object]:
                text = str(premise or "").strip()
                if text == "Dieser zweite Vergleichstext wurde von 70,7 % als KI-generiert bewertet.":
                    return {"label": "entailment", "score": 0.79, "reason": "sentence_hit"}
                if "Rauschen ohne Bezug." in text and "70,7 %" in text:
                    return {"label": "contradiction", "score": 0.92, "reason": "chunk_noise"}
                return {"label": "neutral", "score": 0.21, "reason": "none"}

        dock = _DockProxy()
        dock.llm = _SentenceFallbackNLI()
        chunk = (
            "Rauschen ohne Bezug. "
            "Dieser zweite Vergleichstext wurde von 70,7 % als KI-generiert bewertet."
        )
        results = dock._verify_facts_with_nli(
            facts=["Beim zweiten Vergleichstext waren es 70,7 %, die ihn als KI-generiert bewerteten."],
            source_chunks=[("Doc A", chunk)],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "belegt")
        self.assertEqual(results[0]["sources"], "Doc A")
        self.assertEqual(results[0]["confidence"], "0.7900")
        self.assertIn("Rauschen ohne Bezug.", results[0]["evidence"])

    def test_verify_facts_with_nli_uses_best_contradiction_after_sentence_pass(self):
        class _SentenceContradictionNLI:
            def verify_nli_sync(self, premise: str, hypothesis: str) -> dict[str, object]:
                text = str(premise or "").strip()
                if text == "Der zweite Vergleichstext war nicht KI-generiert.":
                    return {"label": "contradiction", "score": 0.97, "reason": "sentence_conflict"}
                if "Hintergrundtext." in text:
                    return {"label": "contradiction", "score": 0.41, "reason": "weak_chunk_conflict"}
                return {"label": "neutral", "score": 0.20, "reason": "none"}

        dock = _DockProxy()
        dock.llm = _SentenceContradictionNLI()
        chunk = "Hintergrundtext. Der zweite Vergleichstext war nicht KI-generiert."
        results = dock._verify_facts_with_nli(
            facts=["Der zweite Vergleichstext war KI-generiert."],
            source_chunks=[("Doc A", chunk)],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "widerspruch")
        self.assertEqual(results[0]["sources"], "Doc A")
        self.assertEqual(results[0]["confidence"], "0.9700")

    def test_verify_facts_with_nli_stops_on_strong_entailment(self):
        class _StrongEarlyStopNLI:
            def __init__(self):
                self.calls = 0

            def verify_nli_sync(self, premise: str, hypothesis: str) -> dict[str, object]:
                self.calls += 1
                if "first-hit" in premise:
                    return {"label": "entailment", "score": 0.95, "reason": "strong_match"}
                if "second-should-not-run" in premise:
                    return {"label": "contradiction", "score": 0.99, "reason": "should_not_happen"}
                return {"label": "neutral", "score": 0.20, "reason": "none"}

        backend = _StrongEarlyStopNLI()
        dock = _DockProxy()
        dock.llm = backend
        results = dock._verify_facts_with_nli(
            facts=["Beispiel-Fakt"],
            source_chunks=[
                ("Doc A", "first-hit"),
                ("Doc B", "second-should-not-run"),
            ],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "belegt")
        self.assertEqual(results[0]["sources"], "Doc A")
        self.assertEqual(backend.calls, 1)

    def test_parse_llm_chunk_verdict_maps_json_status_and_numeric_check(self):
        dock = _DockProxy()
        label, score, reason, evidence, numeric_check = dock._parse_llm_chunk_verdict(
            '{"status":"teilweise","confidence":0.44,"reason":"fast passend","numeric_check":"consistent","evidence":"Zitat"}'
        )
        self.assertEqual(label, "entailment")
        self.assertAlmostEqual(score, 0.44, places=4)
        self.assertIn("numeric_check=consistent", reason)
        self.assertEqual(evidence, "Zitat")
        self.assertEqual(numeric_check, "consistent")

    def test_llm_chunk_stage_stops_on_strong_entailment(self):
        dock = _DockProxy()
        dock._pending_fact_check = True
        dock._pending_fact_stage = "verify_llm_chunk"
        dock._pending_fact_facts = ["Die Stadt hat 5 Bruecken."]
        dock._pending_fact_results = []
        setattr(
            dock,
            "_pending_llm_chunk_units",
            [
                {
                    "source": "Doc A",
                    "premise": "Die Stadt hat 5 Bruecken laut Bericht.",
                    "evidence": "Die Stadt hat 5 Bruecken laut Bericht.",
                    "mode": "chunk",
                },
                {
                    "source": "Doc B",
                    "premise": "Andere Aussage.",
                    "evidence": "Andere Aussage.",
                    "mode": "chunk",
                },
            ],
        )
        setattr(dock, "_pending_llm_fact_index", 0)
        setattr(dock, "_pending_llm_chunk_index", 0)
        setattr(dock, "_pending_llm_tracker", dock._new_nli_tracker())
        setattr(dock, "_pending_llm_done_checks", 0)
        setattr(dock, "_pending_llm_total_checks", 2)
        setattr(dock, "_pending_llm_next_progress", 10)
        setattr(dock, "_pending_llm_trackers", [dock._new_nli_tracker()])
        setattr(dock, "_pending_llm_fact_done", [False])
        dock._start_next_llm_chunk_verify_call = lambda: None

        dock._handle_fact_pipeline_complete('{"decision":"entailment","confidence":0.95,"reason":"strong_match","evidence":"Die Stadt hat 5 Bruecken laut Bericht."}')

        self.assertEqual(getattr(dock, "_pending_llm_done_checks", 0), 1)
        self.assertEqual(getattr(dock, "_pending_llm_fact_index", 0), 1)
        self.assertEqual(getattr(dock, "_pending_llm_chunk_index", 0), 0)
        self.assertEqual(getattr(dock, "_pending_llm_fact_done", [False])[0], True)

    def test_calibrate_llm_chunk_replaces_hallucinated_evidence_and_downgrades(self):
        dock = _DockProxy()
        label, score, reason, evidence = dock._calibrate_llm_chunk_result(
            fact="Die Stadt hat 5 Bruecken.",
            chunk_text="Im Bericht steht nur: Die Stadt hat einen Bahnhof.",
            label="entailment",
            score=0.97,
            reason="model_confident",
            evidence_hint="Die Stadt hat 5 Bruecken.",
            numeric_check="none",
        )
        self.assertEqual(label, "neutral")
        self.assertLess(score, 0.50)
        self.assertIn("evidence_not_in_chunk_replaced", reason)
        self.assertIn("Bahnhof", evidence)

    def test_llm_chunk_stage_advances_fact_before_chunk(self):
        dock = _DockProxy()
        dock._pending_fact_check = True
        dock._pending_fact_stage = "verify_llm_chunk"
        dock._pending_fact_facts = ["F1", "F2"]
        dock._pending_fact_results = []
        setattr(
            dock,
            "_pending_llm_chunk_units",
            [
                {"source": "Doc A", "premise": "P1", "evidence": "E1", "mode": "chunk"},
                {"source": "Doc B", "premise": "P2", "evidence": "E2", "mode": "chunk"},
            ],
        )
        setattr(dock, "_pending_llm_fact_index", 0)
        setattr(dock, "_pending_llm_chunk_index", 0)
        setattr(dock, "_pending_llm_tracker", dock._new_nli_tracker())
        setattr(dock, "_pending_llm_trackers", [dock._new_nli_tracker(), dock._new_nli_tracker()])
        setattr(dock, "_pending_llm_fact_done", [False, False])
        setattr(dock, "_pending_llm_done_checks", 0)
        setattr(dock, "_pending_llm_total_checks", 4)
        setattr(dock, "_pending_llm_next_progress", 10)
        dock._start_next_llm_chunk_verify_call = lambda: None

        dock._handle_fact_pipeline_complete(
            '{"decision":"neutral","confidence":0.51,"reason":"none"}'
        )

        self.assertEqual(getattr(dock, "_pending_llm_fact_index", 0), 1)
        self.assertEqual(getattr(dock, "_pending_llm_chunk_index", 0), 0)

    def test_llm_chunk_result_reason_mentions_chunk_only(self):
        dock = _DockProxy()
        tracker = dock._new_nli_tracker()
        tracker["best_label"] = "neutral"
        tracker["best_score"] = 0.67
        tracker["best_source"] = "Doc A"
        tracker["best_chunk"] = "Chunk A"
        tracker["best_reason"] = "no_support"

        row = dock._build_nli_result_row(
            0,
            "F1",
            tracker,
            method="llm_chunk",
        )

        self.assertIn("Chunk-Pass", row["reason"])
        self.assertNotIn("Satz-Pass", row["reason"])

    def test_compose_factcheck_markdown_for_methods_renders_both_sections(self):
        dock = _DockProxy()
        dock._pending_fact_target_label = "Target"
        dock._pending_fact_results = []
        setattr(dock, "_pending_fact_run_order", ["nli", "llm"])
        setattr(
            dock,
            "_pending_fact_method_results",
            {
                "nli": [
                    {
                        "id": "C1",
                        "status": "belegt",
                        "fact": "F1",
                        "sources": "Doc A",
                        "evidence": "E1",
                        "confidence": "0.77",
                    }
                ],
                "llm": [
                    {
                        "id": "C1",
                        "status": "widerspruch",
                        "fact": "F1",
                        "sources": "Doc B",
                        "evidence": "E2",
                        "confidence": "0.81",
                    }
                ],
            },
        )
        markdown = dock._compose_factcheck_markdown_for_methods()
        self.assertIn("### NLI (Chunk->Satz)", markdown)
        self.assertIn("### LLM (Chunk-weise)", markdown)
        self.assertIn("Doc A", markdown)
        self.assertIn("Doc B", markdown)

    def test_normalize_factcheck_selection_falls_back_to_nli_on_unknown_mode(self):
        dock = _DockProxy()
        modes = dock._normalize_factcheck_selection("both")
        self.assertEqual(modes, ["nli"])

    def test_compose_factcheck_markdown_for_methods_renders_llm_global_section(self):
        dock = _DockProxy()
        dock._pending_fact_target_label = "Target"
        setattr(dock, "_pending_fact_run_order", ["llm_global"])
        setattr(
            dock,
            "_pending_fact_method_results",
            {
                "llm_global": [
                    {
                        "id": "C1",
                        "status": "belegt",
                        "fact": "F1",
                        "sources": "Doc Z",
                        "evidence": "E-Z",
                        "confidence": "0.88",
                    }
                ]
            },
        )
        markdown = dock._compose_factcheck_markdown_for_methods()
        self.assertIn("LLM (Alle Quellen pro Fakt)", markdown)
        self.assertIn(
            "| ID | Fakt | Evidenz (LLM-Output, kein Direktzitat) | Quelle | Begründung | Status |",
            markdown,
        )
        self.assertIn("Doc Z", markdown)

    def test_compose_factcheck_markdown_for_methods_adds_overview_status_table(self):
        dock = _DockProxy()
        dock._pending_fact_target_label = "Target"
        setattr(dock, "_pending_fact_run_order", ["nli", "llm_chunk", "llm_global"])
        setattr(
            dock,
            "_pending_fact_method_results",
            {
                "nli": [
                    {"id": "C1", "fact": "F1", "status": "belegt", "confidence": "0.91"},
                    {"id": "C2", "fact": "F2", "status": "nicht_belegt", "confidence": "0.44"},
                ],
                "llm_chunk": [
                    {"id": "C1", "fact": "F1", "status": "teilweise", "confidence": "0.55"},
                    {"id": "C2", "fact": "F2", "status": "widerspruch", "confidence": "0.88"},
                ],
                "llm_global": [
                    {"id": "C1", "fact": "F1", "status": "belegt", "confidence": "0.72"},
                    {"id": "C2", "fact": "F2", "status": "belegt", "confidence": "0.67"},
                ],
            },
        )

        markdown = dock._compose_factcheck_markdown_for_methods()
        self.assertIn(
            "| ID | Fakt | Status1: NLI (Chunk->Satz) | Status2: LLM (Chunk-weise) | Status3: LLM (Alle Quellen pro Fakt) |",
            markdown,
        )

    def test_normalize_factcheck_selection_supports_llm_claim_nli_alias(self):
        dock = _DockProxy()
        modes = dock._normalize_factcheck_selection("claims_nli")
        self.assertEqual(modes, ["llm_claim_nli"])

    def test_chunk_claim_cache_export_import_roundtrip(self):
        dock = _DockProxy()
        entries = dock._build_source_chunk_entries(
            [("Doc A", "Die Stadt hat 5 Bruecken. Die Stadt hat einen Hafen.")]
        )
        self.assertTrue(entries)
        first = entries[0]
        dock._store_cached_chunk_claims(first, ["Die Stadt hat 5 Bruecken."])
        exported = dock.export_chunk_claim_cache()

        dock2 = _DockProxy()
        dock2.import_chunk_claim_cache(exported)
        claims = dock2._get_cached_chunk_claims(first)
        self.assertIn("Die Stadt hat 5 Bruecken.", claims)

    def test_build_claim_nli_units_uses_cached_claims(self):
        dock = _DockProxy()
        entries = dock._build_source_chunk_entries(
            [("Doc A", "Die Stadt hat 5 Bruecken. Die Stadt hat einen Hafen.")]
        )
        self.assertTrue(entries)
        first = entries[0]
        dock._store_cached_chunk_claims(first, ["Die Stadt hat 5 Bruecken."])
        units = dock._build_claim_nli_units(entries)
        self.assertTrue(units)
        self.assertEqual(units[0]["source"], "Doc A")
        self.assertEqual(units[0]["premise"], "Die Stadt hat 5 Bruecken.")

    def test_compose_factcheck_markdown_uses_claim_mode_evidence_header(self):
        dock = _DockProxy()
        dock._pending_fact_target_label = "Target"
        setattr(dock, "_pending_fact_run_order", ["llm_claim_nli"])
        setattr(
            dock,
            "_pending_fact_method_results",
            {
                "llm_claim_nli": [
                    {
                        "id": "C1",
                        "status": "belegt",
                        "fact": "F1",
                        "sources": "Doc A",
                        "evidence": "Claim aus Chunk",
                        "confidence": "0.71",
                    }
                ]
            },
        )
        markdown = dock._compose_factcheck_markdown_for_methods()
        self.assertIn("LLM-Claims + NLI", markdown)
        self.assertIn(
            "| ID | Fakt | Evidenz (extrahierter Chunk-Claim) | Quelle | Status |",
            markdown,
        )

    def test_build_source_contexts_from_context_ignores_draft_and_keeps_rag(self):
        dock = _DockProxy()
        ctx = {
            "file_contents": [
                ("Draft: Draft 1", "Draft text"),
                ("Doc A", "Quelle A"),
            ],
            "rag_results": [
                ("/tmp/path/B.pdf", 0.9, "RAG Excerpt"),
            ],
        }
        sources = dock._build_source_contexts_from_context(ctx)
        self.assertEqual(sources[0], ("Doc A", "Quelle A"))
        self.assertEqual(sources[1], ("B.pdf", "RAG Excerpt"))

    def test_start_chunk_claim_precompute_uses_cache_complete_fast_path(self):
        dock = _DockProxy()
        sources = [("Doc A", "Die Stadt hat 5 Bruecken.")]
        entries = dock._build_source_chunk_entries(sources)
        self.assertTrue(entries)
        dock._store_cached_chunk_claims(entries[0], ["Die Stadt hat 5 Bruecken."])
        ok, info = dock._start_chunk_claim_precompute(sources)
        self.assertTrue(ok)
        self.assertIn("Cache vollständig", info)
        self.assertFalse(bool(getattr(dock, "_pending_chunk_claim_precompute", False)))


if __name__ == "__main__":
    unittest.main()
