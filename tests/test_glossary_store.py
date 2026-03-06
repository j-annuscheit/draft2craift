from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.highlights.store import HighlightStore


class GlossaryStoreTests(unittest.TestCase):
    def test_list_glossary_entries_returns_terms_and_definitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "highlights.json"
            store = HighlightStore(path=path)
            store.replace_glossary_entries(
                entries=[
                    {
                        "term": "LLM",
                        "definition": "Large language model.",
                        "aliases": ["Large Language Model"],
                    },
                    {
                        "term": "Token",
                        "definition": "Kleinste Verarbeitungseinheit.",
                        "aliases": [],
                    },
                ],
                panel_scope="*",
                apply_all_tabs=True,
            )

            rows = store.list_glossary_entries()
            terms = [str(row.get("term", "")) for row in rows]
            defs = {
                str(row.get("term", "")): str(row.get("definition", ""))
                for row in rows
            }

            self.assertEqual(
                terms,
                ["Large Language Model", "LLM", "Token"],
            )
            self.assertEqual(defs["LLM"], "Large language model.")
            self.assertEqual(defs["Token"], "Kleinste Verarbeitungseinheit.")

    def test_list_glossary_entries_is_empty_after_replace_with_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "highlights.json"
            store = HighlightStore(path=path)
            store.replace_glossary_entries(
                entries=[{"term": "LLM", "definition": "A"}],
                panel_scope="*",
                apply_all_tabs=True,
            )
            self.assertTrue(store.list_glossary_entries())

            store.replace_glossary_entries(
                entries=[],
                panel_scope="*",
                apply_all_tabs=True,
            )
            self.assertEqual(store.list_glossary_entries(), [])


if __name__ == "__main__":
    unittest.main()
