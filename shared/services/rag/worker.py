"""QThread worker for non-blocking RAG operations."""
from __future__ import annotations

import queue as _queue

from PySide6.QtCore import QObject, QThread, Signal

from shared.services.rag.orchestrator import RAGSystem


class RAGWorker(QThread):
    """Background worker serializing RAG tasks away from the main thread."""

    search_complete = Signal(str, list, dict)
    index_complete = Signal(int)
    status_changed = Signal(str)

    def __init__(self, rag: RAGSystem, parent: QObject | None = None):
        super().__init__(parent)
        self._rag = rag
        self._queue: _queue.Queue = _queue.Queue()

    def enqueue_search(self, query: str) -> None:
        self._drain("search")
        self._queue.put(("search", query))
        if not self.isRunning():
            self.start()

    def enqueue_index(self, entries: list[tuple[str, str]]) -> None:
        self._drain("index")
        self._queue.put(("index", list(entries)))
        if not self.isRunning():
            self.start()

    def stop_and_wait(self, timeout_ms: int = 5000) -> bool:
        self._queue.put(("stop", None))
        return bool(self.wait(timeout_ms))

    def _drain(self, task_type: str) -> None:
        kept: list[tuple[str, object]] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except _queue.Empty:
                break
            if item[0] != task_type:
                kept.append(item)
        for item in kept:
            self._queue.put(item)

    def run(self) -> None:
        while True:
            try:
                task, data = self._queue.get(timeout=0.5)
            except _queue.Empty:
                return

            if task == "stop":
                return

            if task == "search":
                self.status_changed.emit("Searching…")
                failed = False
                try:
                    with self._rag._lock:
                        results, debug_info = self._rag.search(data, with_debug=True)
                except Exception as exc:
                    failed = True
                    results = []
                    debug_info = {
                        "backend": self._rag.current_backend(),
                        "failed": True,
                        "error": str(exc),
                        "warnings": [str(exc)],
                    }
                    self.status_changed.emit(f"RAG error: {exc}")
                self.search_complete.emit(data, results, debug_info)
                if not failed:
                    self.status_changed.emit("")
                continue

            if task == "index":
                n_entries = len(data)
                if self._rag._log:
                    self._rag._log.debug("RAG", f"[WORKER] index_task_start  |  entries={n_entries}")
                self.status_changed.emit(f"Indexing {n_entries} file{'s' if n_entries != 1 else ''}…")
                with self._rag._lock:
                    count, skipped, removed = self._rag.sync_index(data)
                self.index_complete.emit(count)
                if self._rag._log:
                    self._rag._log.debug(
                        "RAG",
                        f"Index task complete  |  indexed={count}  skipped={skipped}  removed={removed}",
                    )
                    self._rag._log.debug("RAG", "[WORKER] index_task_done")
                self.status_changed.emit("")
                continue
