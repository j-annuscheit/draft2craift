"""Suite definitions and field guides for testcase editing."""
from __future__ import annotations

from testcase_studio.models import FieldGuide, SuiteSpec

SUITE_SPECS: tuple[SuiteSpec, ...] = (
    SuiteSpec("rag", "RAG", "RAG-Fall mit Query, Doks und Include/Exclude-Zitaten.", ("query", "documents")),
    SuiteSpec("pdf", "PDF->Markdown", "PDF-Konvertierungsfall mit pdf + expected.", ("pdf", "expected")),
    SuiteSpec("glossary", "Glossary", "Glossarfall mit markdown und target/excluded terms.", ("target_terms",)),
    SuiteSpec(
        "factcheck",
        "Fact-Check",
        "Fact-Check-Fall mit target, sources, gt_facts und gt_verdicts.",
        ("target_markdown", "sources", "gt_facts_markdown", "gt_verdicts_markdown"),
    ),
    SuiteSpec("judge", "Judge", "Pairwise-Judge mit prompt + winner/loser.", ("prompt", "answer_winner", "answer_loser")),
    SuiteSpec("llmcompare", "LLM-Compare", "Vergleichsfall mit prompt.", ("prompt",)),
)
SUITE_BY_ID = {spec.suite_id: spec for spec in SUITE_SPECS}

FIELD_GUIDES: dict[str, list[FieldGuide]] = {
    "rag": [
        FieldGuide("labels", "Labels", False, "Mehrere Label, Komma oder Zeilen", "rag\nfeedback", 70),
        FieldGuide("query", "Query", True, "Einzelne Suchanfrage", "Welche Vorteile hat Solarenergie?"),
        FieldGuide(
            "documents",
            "Markdown-Dokumente",
            True,
            "Eine Zeile je Dokument: /path.md | Name|/path.md | Name::Inline",
            "energie.md|eval/examples/fixtures/rag_doc_1.md",
            92,
        ),
        FieldGuide("include_quotes", "Include-Zitate", False, "Erwartete Textstellen", "Senkung lokaler Emissionen", 82),
        FieldGuide("exclude_quotes", "Exclude-Zitate", False, "Nicht erlaubte Textstellen", "Kohle ist emissionsfrei", 82),
        FieldGuide("top_k", "Top-K", False, "Optional Zahl", "3"),
    ],
    "pdf": [
        FieldGuide("labels", "Labels", False, "Mehrere Label", "smoke\nreflow\nparagraphs", 72),
        FieldGuide("pdf", "PDF-Pfad", True, "Pfad zur PDF", "eval/examples/fixtures/pdf_eval/01_wrapped_paragraph.pdf"),
        FieldGuide("expected", "GT-Markdown-Pfad", True, "Pfad zur erwarteten Markdown-Datei", "eval/examples/fixtures/pdf_eval/01_wrapped_paragraph.expected.md"),
        FieldGuide("settings", "Settings (JSON)", False, "Optionales JSON mit PDF-Overrides", '{"para_mode":"smart"}', 82),
        FieldGuide("thresholds", "Thresholds (JSON)", False, "Optionales JSON mit Schwellwerten", '{"token_f1":0.92}', 82),
    ],
    "glossary": [
        FieldGuide("labels", "Labels", False, "Mehrere Label", "glossary\nfeedback", 70),
        FieldGuide("markdown", "Markdown-Pfad", False, "Alternative zu markdown_text", "eval/examples/fixtures/glossary_eval/01_llm_basics.md"),
        FieldGuide("markdown_text", "Markdown-Inhalt direkt", False, "Alternative zu markdown", "# LLM\nEin LLM arbeitet mit Tokens.", 88),
        FieldGuide("target_terms", "Target-Terms", True, "Eine Zeile je Soll-Begriff", "LLM\nToken\nKontextfenster", 82),
        FieldGuide("excluded_terms", "Excluded-Terms", False, "Nicht erlaubte Begriffe", "Placebo-Begriff", 82),
        FieldGuide("max_terms", "max_terms", False, "Optional Zahl", "24"),
        FieldGuide("context_max_chars", "context_max_chars", False, "Optional Zahl", "22000"),
        FieldGuide("threshold_recall", "threshold_recall", False, "Optional Float 0..1", "0.67"),
    ],
    "factcheck": [
        FieldGuide("labels", "Labels", False, "Mehrere Label", "smoke\ncity\ncontradiction", 72),
        FieldGuide("target_markdown", "Target-Markdown-Pfad", True, "Pfad zum Zieltext", "fixtures/factcheck_eval/01_city_target.md"),
        FieldGuide("sources", "Sources", True, "Eine Zeile je Quelle: /path.md oder Name|/path.md", "source_a|fixtures/factcheck_eval/01_city_source_a.md", 92),
        FieldGuide("gt_facts_markdown", "GT-Facts-Pfad", True, "Pfad zur Ground-Truth-Facts-Datei", "fixtures/factcheck_eval/01_city.gt_facts.md"),
        FieldGuide("gt_verdicts_markdown", "GT-Verdicts-Pfad", True, "Pfad zur Ground-Truth-Verdicts-Datei", "fixtures/factcheck_eval/01_city.gt_verdicts.md"),
        FieldGuide("mode", "Mode", False, "Optional: all|extract|verify|full", "full"),
        FieldGuide("threshold_extract_recall", "threshold_extract_recall", False, "Optional Float 0..1", "0.67"),
        FieldGuide("threshold_verify_status", "threshold_verify_status", False, "Optional Float 0..1", "0.67"),
        FieldGuide("threshold_full_f1", "threshold_full_f1", False, "Optional Float 0..1", "0.50"),
        FieldGuide("source_max_chars", "source_max_chars", False, "Optional Zahl", "24000"),
        FieldGuide("target_max_chars", "target_max_chars", False, "Optional Zahl", "20000"),
        FieldGuide("max_verify_facts", "max_verify_facts", False, "Optional Zahl (0=alle)", "0"),
    ],
    "judge": [
        FieldGuide("labels", "Labels", False, "Mehrere Label", "smoke\ninstruction_following", 70),
        FieldGuide("prompt", "Prompt", True, "Einzelner Prompt", "Nenne drei Vorteile von Code Reviews.", 74),
        FieldGuide("answer_winner", "Answer Winner", True, "Bessere Referenzantwort", "- Fruehes Finden von Fehlern", 88),
        FieldGuide("answer_loser", "Answer Looser", True, "Schwaechere Vergleichsantwort", "Code Reviews helfen bei Qualitaet.", 88),
        FieldGuide("prompt_max_chars", "prompt_max_chars", False, "Optional Zahl", "6000"),
        FieldGuide("answer_max_chars", "answer_max_chars", False, "Optional Zahl", "8000"),
    ],
    "llmcompare": [
        FieldGuide("labels", "Labels", False, "Mehrere Label", "reasoning\nquality", 70),
        FieldGuide("prompt", "Prompt", True, "Vergleichsprompt", "Erklaere Durchsatz vs Latenz in 4 Saetzen.", 74),
        FieldGuide("prompt_max_chars", "prompt_max_chars", False, "Optional Zahl", "6000"),
    ],
}
