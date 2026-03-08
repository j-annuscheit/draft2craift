from __future__ import annotations

import unittest

from features.importer.workers import MarkdownLLMFixWorker


class ImportMarkdownFixWorkerTests(unittest.TestCase):
    def test_strip_new_single_emphasis_markup(self):
        original = "In nerhalb des Abschnitts."
        candidate = "In *nerhalb* des Abschnitts."
        cleaned = MarkdownLLMFixWorker._strip_new_single_emphasis_markup(
            original,
            candidate,
        )
        self.assertEqual(cleaned, "In nerhalb des Abschnitts.")

    def test_escape_internal_word_asterisks(self):
        source = "Künstler*innen und Sportler*innen"
        escaped = MarkdownLLMFixWorker._escape_internal_word_asterisks(source)
        self.assertEqual(escaped, r"Künstler\*innen und Sportler\*innen")

    def test_promote_bold_numbered_heading_with_inline_body(self):
        source = (
            "**5.2.4 Basis- und Vergleichstexte** "
            "Im Anschluss an die Erhebung der persoenlichen Daten ..."
        )
        out = MarkdownLLMFixWorker._promote_bold_numbered_headings(source, offset=1)
        self.assertTrue(out.startswith("#### 5.2.4 Basis- und Vergleichstexte"))
        self.assertIn(
            "\n\nIm Anschluss an die Erhebung der persoenlichen Daten ...",
            out,
        )

    def test_do_not_promote_score_legend_line_with_multiple_bold_spans(self):
        source = "**0 P.** **1 P.** **2 P.** Trifft nicht zu Trifft teilweise zu Trifft zu"
        out = MarkdownLLMFixWorker._promote_bold_numbered_headings(source, offset=1)
        self.assertEqual(out, source)

    def test_do_not_relevel_score_like_heading(self):
        source = "## 0 P."
        out = MarkdownLLMFixWorker._normalize_numbered_heading_levels(
            source,
            offset=1,
        )
        self.assertEqual(out, source)

    def test_normalize_numbered_heading_levels(self):
        source = "### 5.2.4 Basis- und Vergleichstexte"
        out = MarkdownLLMFixWorker._normalize_numbered_heading_levels(
            source,
            offset=1,
        )
        self.assertEqual(out, "#### 5.2.4 Basis- und Vergleichstexte")

    def test_infer_numbered_heading_offset(self):
        source = (
            "## 1 Einleitung\n"
            "### 1.1 Ziel\n"
            "#### 1.1.1 Methodik\n"
        )
        offset = MarkdownLLMFixWorker._infer_numbered_heading_offset(source, default=1)
        self.assertEqual(offset, 1)


if __name__ == "__main__":
    unittest.main()
