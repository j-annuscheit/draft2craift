"""Knowledge/imported-document coordination extracted from MainWindow."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QMessageBox

from studio.controllers.knowledge_ports import ChatDockPort, KnowledgeDockPort
from studio.dialogs.window_manager import find_dialog_manager
from studio.importer.dialog import FileImportDialog

if TYPE_CHECKING:
    from shared.services.rag.orchestrator import RAGSystem
    from studio.app_context import AppContext
    from studio.logger import AppLogger


class KnowledgeController:
    """Owns imported-document registry orchestration across UI surfaces."""

    _LOG_PREFIX = "[IMPORT/VIEWER]"

    def __init__(
        self,
        *,
        file_registry: dict[str, tuple[str, str]],
        knowledge_dock: KnowledgeDockPort,
        chat_dock: ChatDockPort,
        app_context: AppContext,
        app_logger: AppLogger,
        rag_system: RAGSystem,
    ) -> None:
        self._validate_ports(knowledge_dock=knowledge_dock, chat_dock=chat_dock)
        self._file_registry = file_registry
        self._knowledge_dock = knowledge_dock
        self._chat_dock = chat_dock
        self._context = app_context
        self._app_logger = app_logger
        self._rag_system = rag_system
        self._parent = app_context.window
        self._loaded_menu = None
        self._st_loaded_connected = False

    def is_rag_busy(self) -> bool:
        """Return True if the RAG worker thread is currently running."""
        worker = getattr(self._knowledge_dock, "rag_worker", None)
        if worker is None:
            return False
        return bool(worker.isRunning())

    def set_loaded_menu(self, menu) -> None:
        self._loaded_menu = menu

    def update_loaded_menu(self) -> None:
        menu = self._loaded_menu
        if menu is None:
            return
        menu.clear()
        if not self._file_registry:
            menu.setEnabled(False)
            return
        menu.setEnabled(True)
        for display_name in self._file_registry:
            action = menu.addAction(display_name)
            action.triggered.connect(
                lambda _checked=False, n=display_name: self.open_loaded_file(n)
            )

    def open_import_dialog(self, *, feedback_service: object) -> None:
        manager = find_dialog_manager(self._parent)
        if manager is None:
            return

        def _create() -> FileImportDialog:
            dialog = FileImportDialog(
                self._parent,
                user_mode=self._context.get_user_mode(),
                feedback_service=feedback_service,
            )
            dialog.files_imported.connect(self.on_files_imported)
            return dialog

        existing = manager.get("import-dialog")
        manager.show_dialog("import-dialog", _create)
        if existing is not None:
            self._context.show_status("Import-Fenster ist bereits geöffnet.", 2500)

    def import_dialog_busy(self) -> bool:
        manager = find_dialog_manager(self._parent)
        if manager is None:
            return False
        dialog = manager.get("import-dialog")
        if dialog is None:
            return False
        busy_check = getattr(dialog, "_has_running_background_worker", None)
        if not callable(busy_check):
            return False
        try:
            return bool(busy_check())
        except Exception:
            return False

    def shutdown(
        self,
        *,
        stop_timeout_ms: int = 5000,
        terminate_timeout_ms: int = 2000,
    ) -> bool:
        """Stop the RAG worker thread safely during app shutdown."""
        worker = getattr(self._knowledge_dock, "rag_worker", None)
        if worker is None or not worker.isRunning():
            return True
        if worker.stop_and_wait(int(stop_timeout_ms)):
            return True
        self._app_logger.warning(
            "SYS",
            f"RAG worker did not stop within {int(stop_timeout_ms)}ms; terminating thread.",
        )
        worker.terminate()
        if worker.wait(int(terminate_timeout_ms)):
            return True
        self._app_logger.error(
            "SYS",
            (
                "RAG worker did not terminate within "
                f"{int(terminate_timeout_ms)}ms; aborting shutdown."
            ),
        )
        return False

    def open_loaded_file(self, display_name: str) -> None:
        entry = self._file_registry.get(str(display_name or ""))
        if not entry:
            return
        _path, markdown = entry
        self._knowledge_dock.open_content(
            str(display_name or ""),
            markdown,
            doc_key=str(display_name or ""),
        )

    def on_files_imported(self, results: list) -> None:
        total_results = len(results or [])
        if total_results <= 0:
            return
        self._app_logger.debug(
            "SYS",
            f"{self._LOG_PREFIX} Begin handover  |  files={total_results}",
        )
        newly_added: list[tuple[str, str]] = []

        for name, path, markdown in results:
            display_name = str(name or "")
            counter = 1
            while display_name in self._file_registry:
                stem, _, ext = display_name.rpartition(".")
                if ext:
                    display_name = f"{stem} ({counter}).{ext}"
                else:
                    display_name = f"{display_name} ({counter})"
                counter += 1
            self._file_registry[display_name] = (str(path or ""), str(markdown or ""))
            newly_added.append((display_name, str(markdown or "")))

        self.update_loaded_menu()
        self._app_logger.debug(
            "SYS",
            (
                f"{self._LOG_PREFIX} Registry updated  |  "
                f"new={len(newly_added)}  total={len(self._file_registry)}"
            ),
        )
        if not newly_added:
            return

        reindex_paused = False
        previous_autosave_suspended = bool(self._context.get_autosave_suspended())
        self._context.set_autosave_suspended(True)

        try:
            self._knowledge_dock.suspend_reindex()
            reindex_paused = True
            self._app_logger.debug("SYS", f"{self._LOG_PREFIX} Reindex scheduling suspended")

            self._knowledge_dock.add_imported_files(newly_added)
            self._app_logger.debug("SYS", f"{self._LOG_PREFIX} Imported-files panel updated")

            total_new = len(newly_added)
            for idx, (display_name, markdown) in enumerate(newly_added, start=1):
                activate = idx == 1
                self._app_logger.debug(
                    "SYS",
                    (
                        f"{self._LOG_PREFIX} Open doc tab  |  "
                        f"{idx}/{total_new}  title={display_name}  "
                        f"chars={len(markdown or '')}  activate={int(activate)}"
                    ),
                )
                self._knowledge_dock.open_content(
                    display_name,
                    markdown,
                    doc_key=display_name,
                    activate=activate,
                )
                self._chat_dock.add_document(display_name, markdown)

        finally:
            self._context.set_autosave_suspended(previous_autosave_suspended)
            try:
                self._app_logger.debug(
                    "SYS",
                    f"{self._LOG_PREFIX} [CHKPT] immediate_autosave_start",
                )
                self._context.flush_autosave_full()
                self._app_logger.debug(
                    "SYS",
                    f"{self._LOG_PREFIX} [CHKPT] immediate_autosave_done",
                )
            except Exception as exc:
                self._app_logger.error(
                    "SYS",
                    f"{self._LOG_PREFIX} Immediate autosave failed: {exc}",
                )
            if reindex_paused:
                self._app_logger.debug(
                    "SYS",
                    f"{self._LOG_PREFIX} Resume reindex delayed (250ms)",
                )
                QTimer.singleShot(250, self._resume_reindex)

        self._context.schedule_autosave(320)
        self._app_logger.debug("SYS", f"{self._LOG_PREFIX} Handover complete")

    @staticmethod
    def unique_imported_name(desired: str, existing: set[str], current: str) -> str:
        target = str(desired or "").strip() or str(current or "").strip() or "Document"
        if target == current or target not in existing:
            return target

        stem, dot, ext = target.rpartition(".")
        root = stem if dot else target
        suffix = f".{ext}" if dot else ""
        idx = 1
        while True:
            candidate = f"{root} ({idx}){suffix}"
            if candidate not in existing or candidate == current:
                return candidate
            idx += 1

    def resolve_imported_registry_key(self, name: str) -> str:
        """Resolve one canonical registry key from user-facing input.

        Source of truth is always ``self._file_registry``.
        Fallback matching is accepted only when it resolves to exactly one key.
        """
        key = str(name or "").strip()
        if not key:
            return ""
        if key in self._file_registry:
            return key

        key_low = key.casefold()
        casefold_matches = [
            raw
            for raw in (
                str(existing or "").strip()
                for existing in self._file_registry.keys()
            )
            if raw and raw.casefold() == key_low
        ]
        if len(casefold_matches) == 1:
            return casefold_matches[0]
        if len(casefold_matches) > 1:
            self._app_logger.warning(
                "SYS",
                (
                    f"{self._LOG_PREFIX} Ambiguous imported-doc lookup "
                    f"(case-insensitive): input='{key}', matches={casefold_matches[:6]}"
                ),
            )
            return ""

        key_stem = os.path.splitext(key)[0].strip().casefold()
        if not key_stem:
            return ""
        stem_matches = [
            raw
            for raw in (
                str(existing or "").strip()
                for existing in self._file_registry.keys()
            )
            if raw and os.path.splitext(raw)[0].strip().casefold() == key_stem
        ]
        if len(stem_matches) == 1:
            return stem_matches[0]
        if len(stem_matches) > 1:
            self._app_logger.warning(
                "SYS",
                (
                    f"{self._LOG_PREFIX} Ambiguous imported-doc lookup "
                    f"(stem-insensitive): input='{key}', matches={stem_matches[:6]}"
                ),
            )
        return ""

    def rename_imported_document(self, old_name: str, new_name: str) -> None:
        old_key = self.resolve_imported_registry_key(old_name)
        requested = str(new_name or "").strip()
        if not requested or old_key == requested:
            return
        if not old_key:
            self._context.show_status(
                f"Dokument nicht gefunden oder nicht eindeutig: {str(old_name or '').strip()}",
                5000,
            )
            return

        existing = set(self._file_registry.keys())
        existing.discard(old_key)
        final_name = self.unique_imported_name(requested, existing, old_key)

        entry = self._file_registry.pop(old_key)
        self._file_registry[final_name] = entry
        self.update_loaded_menu()

        self._knowledge_dock.rename_viewer_document(old_key, final_name)
        self._knowledge_dock.rename_imported_file(old_key, final_name)
        self._chat_dock.rename_document(old_key, final_name)
        self._context.refresh_context_bar()

        if final_name != requested:
            self._context.show_status(
                f"Dokument umbenannt: '{requested}' bereits vergeben, nutze '{final_name}'.",
                5000,
            )
        else:
            self._context.show_status(f"Dokument umbenannt: {old_key} -> {final_name}", 4000)
        self._context.schedule_autosave(250)

    def remove_imported_document(self, display_name: str) -> None:
        key = self.resolve_imported_registry_key(display_name)
        if not key:
            self._context.show_status(
                f"Dokument nicht gefunden oder nicht eindeutig: {str(display_name or '').strip()}",
                5000,
            )
            return

        existed = key in self._file_registry
        self._file_registry.pop(key, None)
        self.update_loaded_menu()

        self._knowledge_dock.remove_imported_file(key)
        self._knowledge_dock.remove_viewer_document(key)
        self._chat_dock.remove_document(key)
        self._context.refresh_context_bar()

        if existed:
            self._context.show_status(
                f"Dokument entfernt: {key}. Für Nutzung bitte erneut importieren.",
                5000,
            )
            self._context.schedule_autosave(250)

    def resolve_imported_doc_content(self, name: str) -> str:
        canonical_key = self.resolve_imported_registry_key(name)
        if not canonical_key:
            return ""
        entry = self._file_registry.get(canonical_key)
        if not isinstance(entry, tuple) or len(entry) < 2:
            return ""
        return str(entry[1] or "").strip()

    @staticmethod
    def _validate_ports(*, knowledge_dock: object, chat_dock: object) -> None:
        if not isinstance(knowledge_dock, KnowledgeDockPort):
            raise TypeError(
                "KnowledgeController requires a KnowledgeDockPort-compatible object."
            )
        if not isinstance(chat_dock, ChatDockPort):
            raise TypeError(
                "KnowledgeController requires a ChatDockPort-compatible object."
            )

    def _resume_reindex(self) -> None:
        self._knowledge_dock.resume_reindex(flush=True)

    # ── RAG settings ──────────────────────────────────────────────────

    def open_rag_settings_dialog(self) -> None:
        from studio.knowledge.rag_settings.dialog import RAGSettingsDialog
        manager = find_dialog_manager(self._parent)
        if manager is not None:
            manager.show_dialog(
                "rag-settings",
                lambda: RAGSettingsDialog(
                    self._rag_system.config,
                    self._parent,
                    user_mode=self._context.get_user_mode(),
                ),
                on_accept=lambda dlg: self._apply_rag_settings_dialog(dlg),
            )
            return
        dlg = RAGSettingsDialog(
            self._rag_system.config,
            self._parent,
            user_mode=self._context.get_user_mode(),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_rag_settings_dialog(dlg)

    def try_load_sentence_transformers(self) -> None:
        self._rag_system.config.backend.use_st = True
        worker = self._knowledge_dock.rag_worker
        if self._st_loaded_connected:
            worker.st_loaded.disconnect(self._on_st_loaded)
            self._st_loaded_connected = False
        worker.st_loaded.connect(self._on_st_loaded)
        self._st_loaded_connected = True
        worker.enqueue_load_st(self._rag_system.config.backend.st_model_name)
        self._context.schedule_autosave(350)

    def _on_st_loaded(self, ok: bool) -> None:
        self._st_loaded_connected = False
        if ok:
            QMessageBox.information(
                self._parent, "RAG Backend",
                "sentence-transformers loaded.\nRAG now uses semantic (cosine-similarity) embeddings.",
            )
        else:
            QMessageBox.warning(
                self._parent, "RAG Backend",
                "sentence-transformers not available — using TF-IDF.\n\n"
                "Install with:\n  pip install sentence-transformers",
            )

    def _apply_rag_settings_dialog(self, dialog: QDialog) -> None:
        get_config = getattr(dialog, "get_config", None)
        if not callable(get_config):
            return
        old_model = self._rag_system.config.backend.st_model_name
        new_cfg = get_config()
        self._rag_system.config = new_cfg
        if new_cfg.backend.use_st and (
            not self._rag_system.st_model_loaded
            or new_cfg.backend.st_model_name != old_model
        ):
            if self._st_loaded_connected:
                self._knowledge_dock.rag_worker.st_loaded.disconnect(self._on_st_loaded)
                self._st_loaded_connected = False
            self._knowledge_dock.rag_worker.st_loaded.connect(self._on_st_loaded)
            self._st_loaded_connected = True
            self._knowledge_dock.rag_worker.enqueue_load_st(new_cfg.backend.st_model_name)
        self._knowledge_dock.reindex_rag()
        self._app_logger.info(
            "SYS",
            f"RAG reconfigured | backends={self._rag_system.current_backend()} "
            f"strategy={new_cfg.chunking.strategy}",
        )
        self._context.show_status(
            f"RAG re-indexed  ·  strategy: {new_cfg.chunking.strategy}"
            f"  ·  chunks: {new_cfg.chunking.chunk_size} chars"
            f"  ·  backends: {self._rag_system.current_backend()}",
            4000,
        )
        self._context.schedule_autosave(350)
