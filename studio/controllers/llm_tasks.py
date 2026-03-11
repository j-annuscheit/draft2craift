"""LLM side-task controller — glossary and mindmap generation."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal

from shared.services.llm.manager import LLMManager
from studio.controllers.llm_task_context import LLMTaskContext
from studio.controllers.llm_tasks_context import (
    _build_context_text_from_llm_context as _build_context_text_from_llm_context_fn,
    _empty_context_error as _empty_context_error_fn,
    _fallback_context_text_from_ctx as _fallback_context_text_from_ctx_fn,
    _resolve_mindmap_mode_and_query as _resolve_mindmap_mode_and_query_fn,
)
from studio.controllers.llm_tasks_finalize import (
    _finalize_glossary as _finalize_glossary_fn,
    _finalize_mindmap as _finalize_mindmap_fn,
)


# ── Typed side-task contracts ──────────────────────────────────────────────────


@dataclass(frozen=True)
class GlossaryTaskRequest:
    context_text: str
    max_terms: int = 32


@dataclass(frozen=True)
class MindmapTaskRequest:
    context_text: str
    query: str
    mode: str = "mindmap"
    max_nodes: int = 32
    chunking_strategy: str = "sliding_window"
    chunk_size: int = 900
    chunk_overlap: int = 160


@dataclass(frozen=True)
class GlossaryTaskResult:
    context_text: str
    entries: list[dict[str, object]]
    meta: dict[str, object]


@dataclass(frozen=True)
class MindmapTaskResult:
    context_text: str
    query: str
    mode: str
    markdown: str
    meta: dict[str, object]


TaskRequest = GlossaryTaskRequest | MindmapTaskRequest
TaskResult = GlossaryTaskResult | MindmapTaskResult


# ── Worker ─────────────────────────────────────────────────────────────────────


class _LLMSideTaskWorker(QObject):
    """Runs non-streaming LLM side tasks in a background thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, llm_manager: LLMManager, *, request: TaskRequest):
        super().__init__()
        self._llm_manager = llm_manager
        self._request = request

    def run(self):
        try:
            if isinstance(self._request, GlossaryTaskRequest):
                context_text = str(self._request.context_text or "")
                max_terms = int(self._request.max_terms or 32)
                entries, meta = self._llm_manager.generate_glossary_sync(
                    context_text=context_text,
                    max_terms=max_terms,
                )
                safe_entries = [
                    dict(row)
                    for row in list(entries or [])
                    if isinstance(row, dict)
                ]
                safe_meta = dict(meta or {}) if isinstance(meta, dict) else {}
                self.finished.emit(
                    GlossaryTaskResult(
                        context_text=context_text,
                        entries=safe_entries,
                        meta=safe_meta,
                    )
                )
                return

            if isinstance(self._request, MindmapTaskRequest):
                context_text = str(self._request.context_text or "")
                query = str(self._request.query or "")
                mode = str(self._request.mode or "mindmap")
                max_nodes = int(self._request.max_nodes or 32)
                chunking_strategy = str(self._request.chunking_strategy or "sliding_window")
                chunk_size = int(self._request.chunk_size or 900)
                chunk_overlap = int(self._request.chunk_overlap or 160)
                markdown, meta = self._llm_manager.generate_mindmap_sync(
                    context_text=context_text,
                    query=query,
                    mode=mode,
                    max_nodes=max_nodes,
                    chunking_strategy=chunking_strategy,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                safe_meta = dict(meta or {}) if isinstance(meta, dict) else {}
                self.finished.emit(
                    MindmapTaskResult(
                        context_text=context_text,
                        query=query,
                        mode=mode,
                        markdown=str(markdown or ""),
                        meta=safe_meta,
                    )
                )
                return

            self.failed.emit(
                "Unbekannter Hintergrundaufgabe-Typ: "
                f"{type(self._request).__name__}"
            )
        except Exception as exc:
            self.failed.emit(str(exc))


# ── Controller ─────────────────────────────────────────────────────────────────


class LLMSideTaskController(QObject):
    """Manages non-streaming glossary/mindmap LLM background tasks."""

    def __init__(
        self,
        *,
        parent: QObject,
        ctx: LLMTaskContext,
    ):
        super().__init__(parent)
        self._llm_manager = ctx.llm_manager
        self._rag_system = ctx.rag_system
        self._canvas = ctx.canvas
        self._chat_dock = ctx.chat_dock
        self._app_logger = ctx.app_logger
        self._glossary_feedback_bar = ctx.glossary_feedback_bar
        self._show_status = ctx.show_status
        self._resolve_imported_doc_content = ctx.resolve_imported_doc_content
        self._set_status_feedback_payload = ctx.set_status_feedback_payload
        self._refresh_preview_overlays = ctx.refresh_preview_overlays
        self._autosave_schedule_fn = ctx.autosave_schedule_fn

        self._thread: QThread | None = None
        self._worker: _LLMSideTaskWorker | None = None
        self._kind: str = ""
        self._done_cb = None

    # ── Public interface ───────────────────────────────────────────────

    def is_task_active(self) -> bool:
        return self._thread is not None

    def generate_glossary_from_llm_context(
        self,
        ctx: dict,
        done_cb=None,
    ) -> tuple[bool, str]:
        if not self._llm_manager.is_model_loaded():
            return False, "Kein Modell geladen. Bitte zuerst ein GGUF-Modell laden."
        if self._llm_manager.worker.isRunning() or self.is_task_active():
            return (
                False,
                "Das Modell ist gerade beschäftigt. Bitte erneut versuchen, "
                "wenn die aktuelle Generation fertig ist.",
            )

        context_text = self._build_context_text_from_llm_context(ctx)
        if not context_text:
            context_text = self._fallback_context_text_from_ctx(ctx)
        if not context_text:
            return self._empty_context_error(ctx)

        return self._start_task(
            task_kind="glossary",
            request=GlossaryTaskRequest(
                context_text=context_text,
                max_terms=32,
            ),
            status_message="Generiere Glossar aus Kontext…",
            done_cb=done_cb,
        )

    def generate_mindmap_from_llm_context(
        self,
        ctx: dict,
        query_raw: str = "",
        mode_hint: str = "auto",
        done_cb=None,
    ) -> tuple[bool, str]:
        mode, query = self._resolve_mindmap_mode_and_query(query_raw, mode_hint=mode_hint)

        if mode != "chunkmap" and not self._llm_manager.is_model_loaded():
            return False, "Kein Modell geladen. Bitte zuerst ein GGUF-Modell laden."
        if self.is_task_active():
            return (False, "Es läuft bereits eine Hintergrundaufgabe.")
        if mode != "chunkmap" and self._llm_manager.worker.isRunning():
            return (
                False,
                "Das Modell ist gerade beschäftigt. Bitte erneut versuchen, "
                "wenn die aktuelle Generation fertig ist.",
            )

        context_text = self._build_context_text_from_llm_context(ctx, max_chars=0)
        if not context_text:
            context_text = self._fallback_context_text_from_ctx(ctx, max_chars=0)
        if not context_text:
            return self._empty_context_error(ctx)

        rag_cfg = self._rag_system.config

        return self._start_task(
            task_kind="mindmap",
            request=MindmapTaskRequest(
                context_text=context_text,
                query=query,
                mode=mode,
                max_nodes=(0 if mode == "chunkmap" else 32),
                chunking_strategy=str(rag_cfg.chunking.strategy or "sliding_window"),
                chunk_size=int(rag_cfg.chunking.chunk_size or 900),
                chunk_overlap=int(rag_cfg.chunking.chunk_overlap or 160),
            ),
            status_message="Generiere MindMap/Graph/Chunk-MindMap aus Kontext…",
            done_cb=done_cb,
        )

    # ── Private helpers ────────────────────────────────────────────────

    def _start_task(
        self,
        *,
        task_kind: str,
        request: TaskRequest,
        status_message: str,
        done_cb=None,
    ) -> tuple[bool, str]:
        if self.is_task_active():
            return False, "Es läuft bereits eine Hintergrundaufgabe."

        thread = QThread(self)
        worker = _LLMSideTaskWorker(self._llm_manager, request=request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        self._worker = worker
        self._kind = str(task_kind or "")
        self._done_cb = done_cb
        self._chat_dock.set_aux_task_running(True)
        self._show_status(status_message, 2500)
        thread.start()
        return True, ""

    def _finish_task(self, ok: bool, info: str):
        callback = self._done_cb
        self._done_cb = None
        self._kind = ""
        self._worker = None
        self._thread = None
        self._chat_dock.set_aux_task_running(False)
        if callable(callback):
            try:
                callback(bool(ok), str(info or ""))
            except Exception as exc:
                self._app_logger.error("LLM", f"Side-task callback failed: {exc}")

    def _on_finished(self, payload: TaskResult):
        if isinstance(payload, GlossaryTaskResult):
            ok, info = self._finalize_glossary(
                entries=list(payload.entries or []),
                meta=dict(payload.meta or {}),
                context_text=str(payload.context_text or ""),
            )
            self._finish_task(ok, info)
            return
        if isinstance(payload, MindmapTaskResult):
            ok, info = self._finalize_mindmap(
                markdown=str(payload.markdown or ""),
                meta=dict(payload.meta or {}),
                context_text=str(payload.context_text or ""),
                query=str(payload.query or ""),
                mode=str(payload.mode or "mindmap"),
            )
            self._finish_task(ok, info)
            return
        self._finish_task(
            False,
            f"Unbekanntes Aufgaben-Ergebnis: {type(payload).__name__}",
        )

    def _on_failed(self, message: str):
        detail = str(message or "").strip() or "Unbekannter Fehler"
        self._app_logger.error("LLM", f"Hintergrundaufgabe fehlgeschlagen: {detail}")
        self._finish_task(False, detail)

    _finalize_glossary = _finalize_glossary_fn
    _finalize_mindmap = _finalize_mindmap_fn
    _build_context_text_from_llm_context = _build_context_text_from_llm_context_fn
    _fallback_context_text_from_ctx = _fallback_context_text_from_ctx_fn
    _empty_context_error = _empty_context_error_fn
    _resolve_mindmap_mode_and_query = staticmethod(
        _resolve_mindmap_mode_and_query_fn
    )
