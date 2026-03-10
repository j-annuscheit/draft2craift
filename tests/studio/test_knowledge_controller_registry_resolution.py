from __future__ import annotations

import unittest

from shared.services.rag.config import RAGConfig
from studio.controllers.knowledge_controller import KnowledgeController


class _SignalStub:
    def connect(self, _slot):
        return None

    def disconnect(self, _slot):
        return None


class _RAGWorkerStub:
    def __init__(self):
        self.st_loaded = _SignalStub()

    def enqueue_load_st(self, model_name: str | None = None) -> None:
        _ = model_name
        return None


class _KnowledgeDockStub:
    def __init__(self):
        self.rag_worker = _RAGWorkerStub()

    def suspend_reindex(self) -> None:
        return None

    def resume_reindex(self, *, flush: bool = True) -> None:
        _ = flush
        return None

    def reindex_rag(self) -> None:
        return None

    def add_imported_files(self, entries: list[tuple[str, str]]) -> None:
        _ = entries
        return None

    def open_content(
        self,
        title: str,
        content: str,
        doc_key: str = "",
        *,
        activate: bool = True,
    ) -> None:
        _ = (title, content, doc_key, activate)
        return None

    def rename_viewer_document(self, old_doc_key: str, new_doc_key: str) -> bool:
        _ = (old_doc_key, new_doc_key)
        return True

    def rename_imported_file(self, old_name: str, new_name: str) -> str:
        _ = old_name
        return new_name

    def remove_imported_file(self, name: str) -> None:
        _ = name
        return None

    def remove_viewer_document(self, doc_key: str) -> None:
        _ = doc_key
        return None


class _ChatDockStub:
    def add_document(self, name: str, content: str) -> None:
        _ = (name, content)
        return None

    def rename_document(self, old_name: str, new_name: str) -> str:
        _ = old_name
        return new_name

    def remove_document(self, name: str) -> None:
        _ = name
        return None


class _ContextStub:
    def __init__(self):
        self.window = object()
        self.status_messages: list[tuple[str, int]] = []

    def show_status(self, message: str, timeout_ms: int = 0) -> None:
        self.status_messages.append((message, timeout_ms))

    def refresh_context_bar(self) -> None:
        return None

    def schedule_autosave(self, delay_ms: int = 900) -> None:
        _ = delay_ms
        return None

    def set_autosave_suspended(self, _value: bool) -> None:
        return None

    def get_autosave_suspended(self) -> bool:
        return False

    def flush_autosave_full(self) -> None:
        return None

    def get_user_mode(self) -> str:
        return "plus"


class _LoggerStub:
    def __init__(self):
        self.warning_entries: list[tuple[str, str]] = []

    def warning(self, category: str, message: str) -> None:
        self.warning_entries.append((category, message))

    def debug(self, _category: str, _message: str) -> None:
        return None

    def info(self, _category: str, _message: str) -> None:
        return None

    def error(self, _category: str, _message: str) -> None:
        return None


class _RAGSystemStub:
    def __init__(self):
        self.config = RAGConfig()
        self.st_model_loaded = False

    def current_backend(self) -> str:
        return "tfidf"


class KnowledgeControllerRegistryResolutionTests(unittest.TestCase):
    def _make_controller(self, file_registry: dict[str, tuple[str, str]]):
        logger = _LoggerStub()
        context = _ContextStub()
        controller = KnowledgeController(
            file_registry=file_registry,
            knowledge_dock=_KnowledgeDockStub(),
            chat_dock=_ChatDockStub(),
            app_context=context,
            app_logger=logger,
            rag_system=_RAGSystemStub(),
        )
        return controller, logger, context

    def test_resolve_imported_doc_content_prefers_exact_registry_key(self):
        controller, _logger, _context = self._make_controller(
            {"Alpha.md": ("/tmp/alpha.md", "Alpha Content")}
        )

        self.assertEqual(
            controller.resolve_imported_doc_content("Alpha.md"),
            "Alpha Content",
        )

    def test_resolve_imported_doc_content_allows_unique_stem_fallback(self):
        controller, _logger, _context = self._make_controller(
            {"Alpha.md": ("/tmp/alpha.md", "Alpha Content")}
        )

        self.assertEqual(
            controller.resolve_imported_doc_content("alpha"),
            "Alpha Content",
        )

    def test_resolve_imported_doc_content_rejects_ambiguous_stem_match(self):
        controller, logger, _context = self._make_controller(
            {
                "Alpha.md": ("/tmp/alpha.md", "Alpha Content"),
                "alpha.txt": ("/tmp/alpha.txt", "Alpha Text Content"),
            }
        )

        self.assertEqual(controller.resolve_imported_doc_content("alpha"), "")
        self.assertTrue(logger.warning_entries)

    def test_remove_imported_document_rejects_ambiguous_name(self):
        file_registry = {
            "Alpha.md": ("/tmp/alpha.md", "Alpha Content"),
            "alpha.txt": ("/tmp/alpha.txt", "Alpha Text Content"),
        }
        controller, _logger, context = self._make_controller(file_registry)

        controller.remove_imported_document("alpha")

        self.assertEqual(set(file_registry.keys()), {"Alpha.md", "alpha.txt"})
        self.assertTrue(context.status_messages)
        self.assertIn("nicht eindeutig", context.status_messages[-1][0])


if __name__ == "__main__":
    unittest.main()
