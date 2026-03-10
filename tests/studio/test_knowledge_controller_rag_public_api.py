from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QDialog

from shared.services.rag.config import RAGConfig
from studio.controllers.knowledge_controller import KnowledgeController


class _SignalStub:
    def __init__(self):
        self.connected: list[object] = []
        self.disconnected: list[object] = []

    def connect(self, slot):
        self.connected.append(slot)

    def disconnect(self, slot):
        self.disconnected.append(slot)


class _RAGWorkerStub:
    def __init__(self):
        self.st_loaded = _SignalStub()
        self.enqueued_models: list[str | None] = []

    def enqueue_load_st(self, model_name: str | None = None) -> None:
        self.enqueued_models.append(model_name)


class _KnowledgeDockStub:
    def __init__(self):
        self.rag_worker = _RAGWorkerStub()
        self.reindex_calls = 0

    def suspend_reindex(self) -> None:
        return None

    def resume_reindex(self, *, flush: bool = True) -> None:
        _ = flush
        return None

    def reindex_rag(self) -> None:
        self.reindex_calls += 1

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


class _AppContextStub:
    def __init__(self):
        self.window = object()
        self.status_messages: list[tuple[str, int]] = []
        self.autosave_delays: list[int] = []

    def get_user_mode(self) -> str:
        return "plus"

    def show_status(self, message: str, timeout_ms: int = 0) -> None:
        self.status_messages.append((message, timeout_ms))

    def schedule_autosave(self, delay_ms: int = 900) -> None:
        self.autosave_delays.append(delay_ms)


class _AppLoggerStub:
    def __init__(self):
        self.debug_entries: list[tuple[str, str]] = []
        self.info_entries: list[tuple[str, str]] = []

    def debug(self, category: str, message: str) -> None:
        self.debug_entries.append((category, message))

    def info(self, category: str, message: str) -> None:
        self.info_entries.append((category, message))


class _RAGSystemPublicStub:
    """Public-only rag-system surface (intentionally no _st_model attribute)."""

    def __init__(self):
        self.config = RAGConfig()
        self.config.backend.use_st = False
        self.st_model_loaded = False

    def current_backend(self) -> str:
        return "tfidf"


class _AcceptedDialogStub:
    def __init__(self, *_args, **_kwargs):
        self._cfg = RAGConfig()
        self._cfg.backend.use_st = True

    def exec(self):
        return QDialog.DialogCode.Accepted

    def get_config(self) -> RAGConfig:
        return self._cfg


class KnowledgeControllerRagPublicApiTests(unittest.TestCase):
    def test_settings_dialog_uses_public_st_model_loaded_flag(self):
        rag_system = _RAGSystemPublicStub()
        knowledge_dock = _KnowledgeDockStub()
        context = _AppContextStub()
        logger = _AppLoggerStub()
        controller = KnowledgeController(
            file_registry={},
            knowledge_dock=knowledge_dock,
            chat_dock=_ChatDockStub(),
            app_context=context,
            app_logger=logger,
            rag_system=rag_system,
        )

        with patch(
            "studio.knowledge.rag_settings.dialog.RAGSettingsDialog",
            _AcceptedDialogStub,
        ):
            controller.open_rag_settings_dialog()

        self.assertEqual(len(knowledge_dock.rag_worker.enqueued_models), 1)
        self.assertEqual(knowledge_dock.reindex_calls, 1)
        self.assertEqual(context.autosave_delays, [350])


if __name__ == "__main__":
    unittest.main()
