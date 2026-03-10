from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from shared.services.highlights import store_matching


class HighlightTermRegexCacheTests(unittest.TestCase):
    def test_compiled_pattern_is_reused_for_same_term_and_flags(self):
        store_matching._compiled_term_pattern.cache_clear()
        with patch(
            "shared.services.highlights.store_matching.re.compile",
            wraps=re.compile,
        ) as compile_mock:
            spans1 = store_matching.find_term_spans(
                "Alpha beta alpha",
                term="alpha",
                case_sensitive=False,
                whole_word=False,
            )
            spans2 = store_matching.find_term_spans(
                "alpha alpha",
                term="alpha",
                case_sensitive=False,
                whole_word=False,
            )

        self.assertEqual(spans1, [(0, 5), (11, 16)])
        self.assertEqual(spans2, [(0, 5), (6, 11)])
        self.assertEqual(compile_mock.call_count, 1)

    def test_compiled_pattern_cache_key_respects_word_and_case_flags(self):
        store_matching._compiled_term_pattern.cache_clear()
        with patch(
            "shared.services.highlights.store_matching.re.compile",
            wraps=re.compile,
        ) as compile_mock:
            _ = store_matching.find_term_spans(
                "alpha Alpha",
                term="alpha",
                case_sensitive=False,
                whole_word=False,
            )
            _ = store_matching.find_term_spans(
                "alpha Alpha",
                term="alpha",
                case_sensitive=True,
                whole_word=False,
            )
            _ = store_matching.find_term_spans(
                "alpha Alpha",
                term="alpha",
                case_sensitive=True,
                whole_word=True,
            )

        self.assertEqual(compile_mock.call_count, 3)


if __name__ == "__main__":
    unittest.main()
