from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject

from studio.controllers.llm_tasks import LLMSideTaskController, GlossaryTaskRequest


class LLMSideTaskControllerTests(unittest.TestCase):
    def setUp(self):
        self.ctx = Mock()
        self.parent = QObject()
        self.ctx.resolve_imported_doc_content.return_value = ""
        self.ctx.chat_dock.get_context_selection.return_value = (False, False, [])
        self.ctx.rag_system.config.chunking.strategy = "sliding_window"
        self.ctx.rag_system.config.chunking.chunk_size = 900
        self.ctx.rag_system.config.chunking.chunk_overlap = 160
        
        with patch("studio.controllers.llm_tasks.QThread"), \
             patch("studio.controllers.llm_tasks._LLMSideTaskWorker"):
            self.controller = LLMSideTaskController(
                parent=self.parent,
                ctx=self.ctx,
            )

    def test_generate_glossary_empty_context(self):
        """Test glossary generation fails with empty context."""
        self.ctx.llm_manager.is_model_loaded.return_value = True
        self.ctx.llm_manager.worker.isRunning.return_value = False
        
        ctx = {
            "file_contents": [],
            "rag_results": [],
            "selected_text": ""
        }
        
        ok, info = self.controller.generate_glossary_from_llm_context(ctx)
        
        self.assertFalse(ok)
        self.assertIn("Kein verwertbarer Kontext ausgewählt", info)

    def test_generate_glossary_success(self):
        """Test successful glossary generation."""
        self.ctx.llm_manager.is_model_loaded.return_value = True
        self.ctx.llm_manager.worker.isRunning.return_value = False
        self.controller._start_task = Mock(return_value=(True, ""))

        ctx = { "selected_text": "This is a test." }
        
        ok, info = self.controller.generate_glossary_from_llm_context(ctx)
        
        self.assertTrue(ok)
        self.assertEqual(info, "")
        self.controller._start_task.assert_called_once()
        
        # Check the request object passed to _start_task
        call_args = self.controller._start_task.call_args
        request_arg = call_args[1]['request']
        self.assertIsInstance(request_arg, GlossaryTaskRequest)
        self.assertIn("This is a test", request_arg.context_text)
        self.assertEqual(request_arg.query, "")

    def test_generate_glossary_uses_user_query_fallback(self):
        """If no explicit query is passed, context user_query is used."""
        self.ctx.llm_manager.is_model_loaded.return_value = True
        self.ctx.llm_manager.worker.isRunning.return_value = False
        self.controller._start_task = Mock(return_value=(True, ""))

        ctx = {
            "selected_text": "This is a test.",
            "user_query": "focus on technical risks",
        }

        ok, _info = self.controller.generate_glossary_from_llm_context(ctx)

        self.assertTrue(ok)
        call_args = self.controller._start_task.call_args
        request_arg = call_args[1]["request"]
        self.assertIsInstance(request_arg, GlossaryTaskRequest)
        self.assertEqual(request_arg.query, "focus on technical risks")

    def test_generate_glossary_passes_full_context_without_default_truncation(self):
        self.ctx.llm_manager.is_model_loaded.return_value = True
        self.ctx.llm_manager.worker.isRunning.return_value = False
        self.controller._start_task = Mock(return_value=(True, ""))

        tail = "TAIL_FULL_CONTEXT_GLOSSARY"
        long_text = ("X" * 26000) + tail
        ctx = {"selected_text": long_text}

        ok, _info = self.controller.generate_glossary_from_llm_context(ctx)

        self.assertTrue(ok)
        call_args = self.controller._start_task.call_args
        request_arg = call_args[1]["request"]
        self.assertIsInstance(request_arg, GlossaryTaskRequest)
        self.assertTrue(request_arg.context_text.endswith(tail))
        self.assertNotIn("[Hinweis: Kontext wurde aus Platzgründen gekürzt.]", request_arg.context_text)

    def test_generate_mindmap_mode_resolution(self):
        """Test the mindmap mode and query resolution."""
        self.ctx.llm_manager.is_model_loaded.return_value = True
        self.ctx.llm_manager.worker.isRunning.return_value = False
        self.controller._start_task = Mock(return_value=(True, ""))

        # Test graph mode
        self.controller.generate_mindmap_from_llm_context({"selected_text": "test"}, "graph: my query")
        call_args = self.controller._start_task.call_args
        request_arg = call_args[1]['request']
        self.assertEqual(request_arg.mode, "graph")
        self.assertEqual(request_arg.query, "my query")

        # Test chunkmap mode
        self.controller.generate_mindmap_from_llm_context({"selected_text": "test"}, "chunkmap: another query")
        call_args = self.controller._start_task.call_args
        request_arg = call_args[1]['request']
        self.assertEqual(request_arg.mode, "chunkmap")
        self.assertEqual(request_arg.query, "another query")

        # Test default mode
        self.controller.generate_mindmap_from_llm_context({"selected_text": "test"}, "just a query")
        call_args = self.controller._start_task.call_args
        request_arg = call_args[1]['request']
        self.assertEqual(request_arg.mode, "mindmap")
        self.assertEqual(request_arg.query, "just a query")

    def test_generate_graph_uses_user_query_fallback(self):
        """Graph generation uses user_query when query_raw is empty."""
        self.ctx.llm_manager.is_model_loaded.return_value = True
        self.ctx.llm_manager.worker.isRunning.return_value = False
        self.controller._start_task = Mock(return_value=(True, ""))

        self.controller.generate_mindmap_from_llm_context(
            {"selected_text": "test", "user_query": "focus on risks"},
            "",
            mode_hint="graph",
        )
        call_args = self.controller._start_task.call_args
        request_arg = call_args[1]["request"]
        self.assertEqual(request_arg.mode, "graph")
        self.assertEqual(request_arg.query, "focus on risks")

    def test_generate_mindmap_passes_requested_map_depth(self):
        self.ctx.llm_manager.is_model_loaded.return_value = True
        self.ctx.llm_manager.worker.isRunning.return_value = False
        self.controller._start_task = Mock(return_value=(True, ""))

        self.controller.generate_mindmap_from_llm_context(
            {"selected_text": "test"},
            "mindmap: Architektur",
            map_depth=4,
        )
        call_args = self.controller._start_task.call_args
        request_arg = call_args[1]["request"]
        self.assertEqual(request_arg.mode, "mindmap")
        self.assertEqual(int(request_arg.map_depth), 4)

if __name__ == "__main__":
    unittest.main()
