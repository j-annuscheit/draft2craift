from __future__ import annotations

import unittest

from features.canvas.structured_graph import extract_graph_spec
from services.llm.manager import LLMManager


class ChunkMindMapModeTests(unittest.TestCase):
    def test_chunk_mode_works_without_loaded_llm(self):
        manager = LLMManager()
        context = (
            "# Bericht\n\n"
            "## Abschnitt Eins\n\n"
            "Das ist ein Testabschnitt mit mehreren Aussagen.\n\n"
            "## Abschnitt Zwei\n\n"
            "Hier folgt ein weiterer Abschnitt mit Zusatzdetails."
        )

        markdown, meta = manager.generate_mindmap_sync(
            context_text=context,
            query="Strukturtest",
            mode="chunkmap",
            max_nodes=32,
            chunking_strategy="recursive",
            chunk_size=260,
            chunk_overlap=40,
        )

        self.assertTrue(bool(markdown.strip()))
        self.assertTrue(bool(meta.get("applied")))
        self.assertEqual(str(meta.get("variant", "")), "chunkmap")
        self.assertEqual(str(meta.get("kind", "")), "mindmap")

        spec = extract_graph_spec(markdown)
        self.assertIsNotNone(spec)
        assert spec is not None
        labels = {node.label for node in spec.nodes.values()}
        self.assertIn("Abschnitt Eins", labels)
        self.assertIn("Abschnitt Zwei", labels)

        leaf_nodes = [
            node
            for node in spec.nodes.values()
            if not node.children and node.node_id != "root"
        ]
        self.assertGreaterEqual(len(leaf_nodes), 2)
        self.assertTrue(all(str(node.quote or "").strip() for node in leaf_nodes))

    def test_chunk_leaf_keeps_full_chunk_text(self):
        manager = LLMManager()
        marker = "TAIL_MARKER_987654321"
        long_body = (
            "Dies ist ein sehr langer Absatz, der als einzelner Chunk bleiben soll. "
            + ("Fuelltext " * 40)
            + marker
        )
        context = (
            "# Dokument\n\n"
            "## Kapitel A\n\n"
            f"{long_body}"
        )

        markdown, meta = manager.generate_mindmap_sync(
            context_text=context,
            query="Chunk Volltext",
            mode="chunk",
            max_nodes=12,
            chunking_strategy="section",
            chunk_size=4000,
            chunk_overlap=100,
        )

        self.assertTrue(bool(meta.get("applied")))
        spec = extract_graph_spec(markdown)
        self.assertIsNotNone(spec)
        assert spec is not None

        chunk_quotes = [
            str(node.quote or "")
            for node in spec.nodes.values()
            if node.node_id.startswith("chunk-")
        ]
        self.assertTrue(chunk_quotes)
        self.assertTrue(any(marker in quote for quote in chunk_quotes))


if __name__ == "__main__":
    unittest.main()
