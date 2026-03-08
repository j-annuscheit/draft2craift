from __future__ import annotations

import unittest

from features.chat.factcheck_utils import (
    compose_fact_check_markdown,
    evidence_in_source_texts,
    parse_fact_candidates,
    parse_single_fact_verification,
)


class FactcheckUtilsBehaviorTests(unittest.TestCase):
    def test_parse_fact_candidates_prefers_llm_json_facts(self):
        target = (
            "Die Anlage startete 2024 und kostet 12 Mio Euro. "
            "Sie steht in Berlin."
        )
        llm_response = (
            "["
            "\"Die Anlage kostete 12 Mio Euro.\","
            "\"Die Anlage startete 2024.\""
            "]"
        )

        facts = parse_fact_candidates(llm_response, target)
        self.assertGreaterEqual(len(facts), 2)
        self.assertEqual(facts[0], "Die Anlage kostete 12 Mio Euro.")
        self.assertEqual(facts[1], "Die Anlage startete 2024.")

    def test_parse_fact_candidates_filters_fragment_entries(self):
        target = "Dummy."
        llm_response = (
            "```json\n"
            "[\n"
            "  \"view.\",\n"
            "  \"- -\",\n"
            "  \"Item 1\",\n"
            "  \"Die Anlage startete 2024 und kostet 12 Mio Euro.\"\n"
            "]\n"
            "```"
        )
        facts = parse_fact_candidates(llm_response, target)
        self.assertEqual(facts, ["Die Anlage startete 2024 und kostet 12 Mio Euro."])

    def test_parse_single_fact_verification_without_evidence_stays_empty(self):
        response = (
            "{"
            "\"to_check\":\"Die Anlage startete 2024.\","
            "\"status\":\"belegt\","
            "\"evidence\":\"\","
            "\"source\":\"\""
            "}"
        )
        parsed = parse_single_fact_verification(
            response=response,
            fact="Die Anlage startete 2024.",
            fact_index=0,
            sources=[("Doc A", "Die Anlage startete 2024 laut Bericht.")],
        )
        self.assertEqual(parsed["status"], "nicht_belegt")
        self.assertEqual(parsed["evidence"], "")
        self.assertEqual(parsed["sources"], "")

    def test_parse_single_fact_verification_accepts_decision_and_keeps_belegt(self):
        quote = (
            "Die Anlage startete 2024 laut Bericht und wurde danach "
            "in mehreren Schritten erweitert."
        )
        response = (
            "{"
            "\"to_check\":\"Die Anlage startete 2024.\","
            "\"decision\":\"entailment\","
            "\"evidence\":\"" + quote + "\","
            "\"source\":\"Doc A\""
            "}"
        )
        parsed = parse_single_fact_verification(
            response=response,
            fact="Die Anlage startete 2024.",
            fact_index=0,
            sources=[("Doc A", quote + " Weitere Details folgen.")],
        )
        self.assertEqual(parsed["status"], "belegt")
        self.assertEqual(parsed["sources"], "Doc A")
        self.assertIn("Die Anlage startete 2024", parsed["evidence"])

    def test_parse_single_fact_verification_infers_source_for_long_evidence(self):
        long_prefix = "Einleitung " * 70
        quote = (
            "Die Anlage startete 2024 laut Bericht und wurde danach "
            "in mehreren Schritten erweitert."
        )
        source_text = (long_prefix + quote + " Schluss.").strip()
        response = (
            "{"
            "\"to_check\":\"Die Anlage startete 2024.\","
            "\"status\":\"belegt\","
            "\"evidence\":\"" + source_text + "\","
            "\"source\":\"\""
            "}"
        )
        parsed = parse_single_fact_verification(
            response=response,
            fact="Die Anlage startete 2024.",
            fact_index=0,
            sources=[("Doc A", source_text)],
        )
        self.assertEqual(parsed["status"], "belegt")
        self.assertEqual(parsed["sources"], "Doc A")
        self.assertTrue(parsed["evidence"].endswith("…"))

    def test_evidence_in_source_texts_accepts_fuzzy_pdf_word_splits(self):
        evidence = (
            "Zwischen der Identifizierung der Texte und dem Bildungsstand "
            "konnte ein starker Zusammenhang festgestellt werden."
        )
        source = (
            "Zwischen der Identifizierung der Texte und dem Bil dungsstand "
            "konnte ein starker Zu sammenhang festgestellt werden."
        )
        found, score = evidence_in_source_texts(evidence, [source])
        self.assertTrue(found)
        self.assertGreaterEqual(score, 0.62)

    def test_parse_single_fact_verification_keeps_belegt_with_fuzzy_source_match(self):
        response = (
            "{"
            "\"to_check\":\"Ein starker Zusammenhang zwischen Bildungsstand und Identifizierung wurde festgestellt.\","
            "\"status\":\"belegt\","
            "\"evidence\":\"Zwischen der Identifizierung der Texte und dem Bildungsstand konnte ein starker Zusammenhang festgestellt werden.\","
            "\"source\":\"BA\""
            "}"
        )
        source = (
            "Zwischen der Identifizierung der Texte und dem Bil dungsstand "
            "konnte ein starker Zu sammenhang festgestellt werden."
        )
        parsed = parse_single_fact_verification(
            response=response,
            fact="Ein starker Zusammenhang zwischen Bildungsstand und Identifizierung wurde festgestellt.",
            fact_index=0,
            sources=[("BA", source)],
        )
        self.assertEqual(parsed["status"], "belegt")

    def test_compose_fact_check_markdown_has_no_dash_placeholder_for_empty_evidence(self):
        md = compose_fact_check_markdown(
            rows=[
                {
                    "id": "C1",
                    "status": "nicht_belegt",
                    "fact": "Die Anlage startete 2024.",
                    "sources": "",
                    "evidence": "",
                    "reason": "",
                }
            ],
            target_label="Target",
        )
        self.assertIn("| C1 | Die Anlage startete 2024. |  |  | 🔴 nicht_belegt |", md)
        self.assertNotIn("—", md)

    def test_compose_fact_check_markdown_shows_confidence_next_to_status(self):
        md = compose_fact_check_markdown(
            rows=[
                {
                    "id": "C1",
                    "status": "belegt",
                    "fact": "Die Anlage startete 2024.",
                    "sources": "Doc A",
                    "evidence": "Die Anlage startete 2024.",
                    "confidence": "0.8735",
                    "reason": "",
                }
            ],
            target_label="Target",
        )
        self.assertIn("🟢 belegt (0.87)", md)

    def test_compose_fact_check_markdown_strips_html_br_artifacts(self):
        md = compose_fact_check_markdown(
            rows=[
                {
                    "id": "C14",
                    "status": "belegt",
                    "fact": "Erster Teil<br>Zweiter Teil",
                    "sources": "Doc A",
                    "evidence": "Chunk A<br/>Chunk B",
                    "confidence": "0.7400",
                    "reason": "",
                }
            ],
            target_label="Target",
        )
        self.assertNotIn("<br>", md)
        self.assertNotIn("<br/>", md)
        self.assertIn("Erster Teil Zweiter Teil", md)
        self.assertIn("Chunk A Chunk B", md)

    def test_parse_fact_candidates_splits_on_html_br(self):
        target = "Aussage eins.<br>Aussage zwei."
        facts = parse_fact_candidates("[]", target)
        self.assertEqual(facts, ["Aussage eins.", "Aussage zwei."])

    def test_compose_fact_check_markdown_decodes_and_sanitizes_escaped_br(self):
        md = compose_fact_check_markdown(
            rows=[
                {
                    "id": "C1",
                    "status": "belegt",
                    "fact": "Teil 1 &lt;br&gt; Teil 2",
                    "sources": "Doc A",
                    "evidence": "X &lt;BR /&gt; Y",
                    "confidence": "0.91",
                    "reason": "",
                }
            ],
            target_label="Target",
        )
        self.assertNotIn("&lt;br&gt;", md.casefold())
        self.assertNotIn("<br", md.casefold())
        self.assertIn("Teil 1 Teil 2", md)
        self.assertIn("X Y", md)

    def test_compose_fact_check_markdown_allows_custom_evidence_header(self):
        md = compose_fact_check_markdown(
            rows=[
                {
                    "id": "C1",
                    "status": "belegt",
                    "fact": "F1",
                    "sources": "Doc A",
                    "evidence": "E1",
                }
            ],
            target_label="Target",
            evidence_header="Evidenz (LLM-Output, kein Direktzitat)",
        )
        self.assertIn(
            "| ID | Fakt | Evidenz (LLM-Output, kein Direktzitat) | Quelle | Status |",
            md,
        )

    def test_compose_fact_check_markdown_allows_reason_column(self):
        md = compose_fact_check_markdown(
            rows=[
                {
                    "id": "C1",
                    "status": "belegt",
                    "fact": "F1",
                    "sources": "Doc A",
                    "evidence": "E1",
                    "reason": "Bezug auf identische Kernaussage",
                    "confidence": "0.93",
                }
            ],
            target_label="Target",
            reason_header="Begründung",
        )
        self.assertIn(
            "| ID | Fakt | Evidenz | Quelle | Begründung | Status |",
            md,
        )
        self.assertIn(
            "| C1 | F1 | E1 | Doc A | Bezug auf identische Kernaussage | 🟢 belegt (0.93) |",
            md,
        )

    def test_compose_fact_check_markdown_escapes_markdown_specials_in_cells(self):
        md = compose_fact_check_markdown(
            rows=[
                {
                    "id": "C5",
                    "status": "widerspruch",
                    "fact": "A | B `code` **bold** [x](y)",
                    "sources": "README.md",
                    "evidence": "```powershell Get-Item```",
                    "confidence": "0.99",
                    "reason": "",
                }
            ],
            target_label="Target",
        )
        self.assertNotIn("```", md)
        self.assertIn("A / B", md)
        self.assertNotIn("| B `code`", md)
        self.assertIn("&#96;", md)

    def test_compose_fact_check_markdown_rewrites_pipes_to_plain_text(self):
        md = compose_fact_check_markdown(
            rows=[
                {
                    "id": "C2",
                    "status": "belegt",
                    "fact": "Knowledge Dock | Draft | AI Chat Dock",
                    "sources": "README.md",
                    "evidence": "left | center | right",
                    "confidence": "0.97",
                    "reason": "",
                }
            ],
            target_label="Target",
        )
        self.assertIn("Knowledge Dock / Draft / AI Chat Dock", md)
        self.assertIn("left / center / right", md)


if __name__ == "__main__":
    unittest.main()
