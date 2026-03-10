from __future__ import annotations

import json
import unittest

import pytest
from PySide6.QtWidgets import QApplication

from studio.canvas.preview.pane import CanvasPreviewPane
from studio.canvas.graph.renderer import extract_graph_spec
from studio.canvas.editor import MarkdownEditor


_GRAPH_MARKDOWN = """```mindmap
Root
  Child
```"""
_LONG_CHUNK_QUOTE = "ChunkStart " + ("x" * 180) + " ChunkEndMarker"
_GRAPH_MARKDOWN_LONG_QUOTE = "```mindmap\n" + json.dumps(
    {
        "type": "mindmap",
        "title": "Long Quote",
        "nodes": [
            {
                "id": "root",
                "label": "Root",
                "children": [
                    {
                        "id": "chunk_1",
                        "label": "Chunk 01",
                        "quote": _LONG_CHUNK_QUOTE,
                    }
                ],
            }
        ],
    },
    ensure_ascii=False,
    indent=2,
) + "\n```"
_GRAPH_MARKDOWN_NESTED = "```mindmap\n" + json.dumps(
    {
        "type": "mindmap",
        "title": "Nested",
        "nodes": [
            {
                "id": "root",
                "label": "Root",
                "children": [
                    {
                        "id": "h1",
                        "label": "H1",
                        "children": [
                            {
                                "id": "h1a",
                                "label": "H1A",
                                "children": [
                                    {
                                        "id": "leaf",
                                        "label": "Leaf",
                                        "quote": "Q",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    },
    ensure_ascii=False,
    indent=2,
) + "\n```"


pytestmark = pytest.mark.usefixtures("qt_app")


def _process_events() -> None:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


class PreviewStructuredGraphCommitTests(unittest.TestCase):
    def _build_pane(self) -> tuple[CanvasPreviewPane, MarkdownEditor]:
        editor = MarkdownEditor(read_only=False)
        pane = CanvasPreviewPane(
            allow_editing=True,
            show_title=False,
            sync_cursor_with_editor=False,
        )
        pane.bind_editor(editor)
        pane.show()
        _process_events()
        return pane, editor

    @classmethod
    def _visible_node_ids(cls, pane: CanvasPreviewPane) -> set[str]:
        scene = pane._graph_scene
        if scene is None:
            return set()
        out: set[str] = set()
        for item in scene.items():
            node_id = getattr(item, "_node_id", None)
            if isinstance(node_id, str) and node_id:
                out.add(node_id)
        return out

    def test_commit_does_not_overwrite_editor_when_structured_graph_active(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText(_GRAPH_MARKDOWN)
            pane._render()
            self.assertTrue(pane._structured_view_active)

            original_text = editor.toPlainText()
            pane._view.setMarkdown("plain text")
            pane._preview_edit_active = True
            pane._commit_preview_edit_to_markdown()

            self.assertEqual(editor.toPlainText(), original_text)
            self.assertFalse(pane._preview_edit_active)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_entering_structured_graph_mode_cancels_pending_preview_commit(self):
        pane, editor = self._build_pane()
        try:
            spec = extract_graph_spec(_GRAPH_MARKDOWN)
            self.assertIsNotNone(spec)

            pane._preview_edit_active = True
            pane._preview_to_markdown_timer.start(10_000)
            pane._set_structured_graph_state(spec)

            self.assertTrue(pane._structured_view_active)
            self.assertFalse(pane._preview_to_markdown_timer.isActive())
            self.assertFalse(pane._preview_edit_active)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_graph_node_tooltip_keeps_full_quote_text(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText(_GRAPH_MARKDOWN_LONG_QUOTE)
            pane._render()
            self.assertTrue(pane._structured_view_active)
            scene = pane._graph_scene
            self.assertIsNotNone(scene)
            assert scene is not None
            tips = [item.toolTip() for item in scene.items() if item.toolTip()]
            self.assertTrue(any("ChunkEndMarker" in tip for tip in tips))
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_mindmap_initially_shows_only_base_nodes(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText(_GRAPH_MARKDOWN_NESTED)
            pane._render()
            self.assertTrue(pane._structured_view_active)
            visible = self._visible_node_ids(pane)
            self.assertIn("root", visible)
            self.assertIn("h1", visible)
            self.assertNotIn("h1a", visible)
            self.assertNotIn("leaf", visible)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()

    def test_mindmap_reopen_resets_descendant_expansion(self):
        pane, editor = self._build_pane()
        try:
            editor.setPlainText(_GRAPH_MARKDOWN_NESTED)
            pane._render()
            self.assertTrue(pane._structured_view_active)

            pane._on_graph_node_toggled("h1")
            _process_events()
            visible = self._visible_node_ids(pane)
            self.assertIn("h1a", visible)
            self.assertNotIn("leaf", visible)

            pane._on_graph_node_toggled("h1a")
            _process_events()
            visible = self._visible_node_ids(pane)
            self.assertIn("leaf", visible)

            pane._on_graph_node_toggled("h1")
            _process_events()
            visible = self._visible_node_ids(pane)
            self.assertNotIn("h1a", visible)
            self.assertNotIn("leaf", visible)

            pane._on_graph_node_toggled("h1")
            _process_events()
            visible = self._visible_node_ids(pane)
            self.assertIn("h1a", visible)
            # Reopen must not keep descendant expansion from previous run.
            self.assertNotIn("leaf", visible)
        finally:
            pane.deleteLater()
            editor.deleteLater()
            _process_events()


if __name__ == "__main__":
    unittest.main()
