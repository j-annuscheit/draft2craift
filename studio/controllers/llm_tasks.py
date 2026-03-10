"""LLM side-task controller — glossary and mindmap generation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, QThread, Signal

from shared.services.highlights.store import get_highlight_store
from shared.services.llm.manager import LLMManager
from studio.controllers.llm_task_context import LLMTaskContext


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

    def _finalize_glossary(
        self,
        *,
        entries: list[dict],
        meta: dict,
        context_text: str,
    ) -> tuple[bool, str]:
        reason = str(meta.get("reason", "") or "")
        if not entries:
            detail = str(meta.get("error", "") or "").strip()
            if reason == "context_too_large" and detail:
                return False, detail
            if reason in {"empty", "parse_failed"}:
                retried = bool(meta.get("retried", False))
                parse_mode = str(meta.get("parse", "") or "").strip() or "n/a"
                return (
                    False,
                    "Es konnten keine Glossar-Einträge erzeugt werden.\n"
                    "Die Modellausgabe war leer oder nicht als Glossar parsebar.\n"
                    f"Retry ausgeführt: {'ja' if retried else 'nein'} | Parse-Modus: {parse_mode}",
                )
            return (
                False,
                "Es konnten keine Glossar-Einträge erzeugt werden.\n"
                f"Grund: {reason or 'unbekannt'}",
            )

        count = get_highlight_store().replace_glossary_entries(
            entries=entries,
            panel_scope="*",
            apply_all_tabs=True,
        )
        self._set_status_feedback_payload(
            {
                "glossary": {
                    "count": count,
                    "entries": entries[:64],
                },
                "context_preview": context_text[:4000],
                "meta": meta,
            }
        )
        self._glossary_feedback_bar.activate("glossary")
        self._refresh_preview_overlays()
        overlays_on = get_highlight_store().is_glossary_enabled()
        self._show_status(
            (
                f"Glossar aktualisiert: {count} Begriffe."
                if overlays_on
                else f"Glossar aktualisiert: {count} Begriffe (Overlay aktuell AUS)."
            ),
            4500,
        )
        self._autosave_schedule_fn(350)
        return True, f"{count} Begriffe"

    def _finalize_mindmap(
        self,
        *,
        markdown: str,
        meta: dict,
        context_text: str,
        query: str,
        mode: str,
    ) -> tuple[bool, str]:
        reason = str(meta.get("reason", "") or "")
        if not str(markdown or "").strip():
            detail = str(meta.get("error", "") or "").strip()
            if reason == "context_too_large" and detail:
                return False, detail
            return (
                False,
                "Es konnte keine Struktur erzeugt werden.\n"
                f"Grund: {reason or 'unbekannt'}",
            )

        kind = str(meta.get("kind", mode) or mode).strip().casefold()
        variant = str(meta.get("variant", mode) or mode).strip().casefold()
        if variant == "chunkmap" or mode.strip().casefold() == "chunkmap":
            label = "Chunk-MindMap"
        elif kind == "graph":
            label = "Graph"
        else:
            label = "MindMap"
        title = f"{label} {datetime.now().strftime('%H:%M')}"
        self._canvas.tabs.add_tab(title=title, content=markdown, read_only=False)
        self._set_status_feedback_payload(
            {
                "mindmap": {
                    "query": query,
                    "mode": mode,
                    "markdown": markdown[:12000],
                },
                "context_preview": context_text[:4000],
                "meta": meta,
            }
        )
        self._glossary_feedback_bar.activate("mindmap")
        self._show_status(
            (
                f"{label} erstellt: {int(meta.get('nodes', 0) or 0)} Knoten, "
                f"{int(meta.get('edges', 0) or 0)} Verbindungen."
            ),
            5000,
        )
        self._autosave_schedule_fn(350)
        return (
            True,
            f"{label}: {int(meta.get('nodes', 0) or 0)} Knoten, "
            f"{int(meta.get('edges', 0) or 0)} Verbindungen",
        )

    def _build_context_text_from_llm_context(
        self,
        ctx: dict,
        *,
        max_chars: int = 22000,
    ) -> str:
        parts: list[str] = []
        try:
            char_limit = int(max_chars)
        except (TypeError, ValueError):
            char_limit = 22000
        unlimited = char_limit <= 0
        total_len = 0
        truncated = False

        def add_chunk(label: str, content: str) -> bool:
            nonlocal total_len, truncated
            body = str(content or "").strip()
            if not body:
                return True
            header = f"## {label}\n"
            footer = "\n\n"
            if unlimited:
                chunk = f"{header}{body}{footer}"
                parts.append(chunk)
                total_len += len(chunk)
                return True
            room = char_limit - total_len - len(header) - len(footer)
            if room <= 0:
                truncated = True
                return False
            if len(body) > room:
                suffix = "\n\n[... gekürzt ...]"
                keep = max(0, room - len(suffix))
                body = body[:keep].rstrip()
                if keep > 0:
                    body += suffix
                truncated = True
            chunk = f"{header}{body}{footer}"
            parts.append(chunk)
            total_len += len(chunk)
            return total_len < char_limit

        for name, content in list(ctx.get("file_contents", []) or []):
            if not add_chunk(f"Quelle: {name}", str(content or "")):
                break

        if unlimited or total_len < char_limit:
            for path, score, excerpt in list(ctx.get("rag_results", []) or []):
                label = str(path or "").strip() or "RAG Results"
                try:
                    score_text = f"{float(score):.2f}"
                except (TypeError, ValueError):
                    score_text = "?"
                if not add_chunk(
                    f"RAG: {label} (score {score_text})",
                    str(excerpt or ""),
                ):
                    break

        if unlimited or total_len < char_limit:
            selected_text = str(ctx.get("selected_text", "") or "").strip()
            if selected_text:
                add_chunk("Ausgewählter Text (Draft)", selected_text)

        # Recovery path: selected docs checked but context payload arrived empty.
        if not parts:
            _use_canvas, _use_rag, doc_selection = self._chat_dock.get_context_selection()
            for name, _content in list(doc_selection or []):
                doc_name = str(name or "").strip()
                if not doc_name:
                    continue
                resolved = self._resolve_imported_doc_content(doc_name)
                if not resolved:
                    continue
                if not add_chunk(f"Quelle: {doc_name}", resolved):
                    break

        text = "".join(parts).strip()
        if (not unlimited) and truncated and text:
            return f"{text}\n\n[Hinweis: Kontext wurde aus Platzgründen gekürzt.]"
        return text

    def _fallback_context_text_from_ctx(
        self,
        ctx: dict,
        *,
        max_chars: int = 22000,
    ) -> str:
        out: list[str] = []
        try:
            char_limit = int(max_chars)
        except (TypeError, ValueError):
            char_limit = 22000
        unlimited = char_limit <= 0
        total_len = 0
        truncated = False

        def add_raw(label: str, content: str) -> bool:
            nonlocal total_len, truncated
            body = str(content or "").strip()
            if not body:
                return True
            header = f"[{label}]\n"
            footer = "\n\n"
            if unlimited:
                block = f"{header}{body}{footer}"
                out.append(block)
                total_len += len(block)
                return True
            room = char_limit - total_len - len(header) - len(footer)
            if room <= 0:
                truncated = True
                return False
            if len(body) > room:
                suffix = "\n\n[... gekürzt ...]"
                keep = max(0, room - len(suffix))
                body = body[:keep].rstrip()
                if keep > 0:
                    body += suffix
                truncated = True
            block = f"{header}{body}{footer}"
            out.append(block)
            total_len += len(block)
            return total_len < char_limit

        for item in list(ctx.get("file_contents", []) or []):
            if not isinstance(item, (tuple, list)) or len(item) < 2:
                continue
            name = str(item[0] or "").strip() or "Quelle"
            body = str(item[1] or "")
            if not body.strip():
                body = self._resolve_imported_doc_content(name)
            if not add_raw(f"Quelle: {name}", body):
                break

        if unlimited or total_len < char_limit:
            for item in list(ctx.get("rag_results", []) or []):
                if not isinstance(item, (tuple, list)) or len(item) < 3:
                    continue
                path = str(item[0] or "").strip() or "RAG Results"
                excerpt = str(item[2] or "")
                if not add_raw(f"RAG: {path}", excerpt):
                    break

        if unlimited or total_len < char_limit:
            selected = str(ctx.get("selected_text", "") or "")
            if selected.strip():
                add_raw("Ausgewählter Text (Draft)", selected)

        text = "".join(out).strip()
        if (not unlimited) and truncated and text:
            return f"{text}\n\n[Hinweis: Kontext wurde aus Platzgründen gekürzt.]"
        return text

    def _empty_context_error(self, ctx: dict) -> tuple[bool, str]:
        selected_text_len = len(str(ctx.get("selected_text", "") or "").strip())
        file_count = len(list(ctx.get("file_contents", []) or []))
        rag_count = len(list(ctx.get("rag_results", []) or []))
        file_lens = [
            (
                str(item[0] if isinstance(item, (tuple, list)) and item else ""),
                len(
                    str(
                        item[1]
                        if isinstance(item, (tuple, list)) and len(item) > 1
                        else ""
                    ).strip()
                ),
            )
            for item in list(ctx.get("file_contents", []) or [])[:6]
        ]
        _use_canvas, _use_rag, doc_selection = self._chat_dock.get_context_selection()
        selected_doc_names = [
            str(name or "").strip()
            for name, _ in list(doc_selection or [])
            if str(name or "").strip()
        ]
        return (
            False,
            "Kein verwertbarer Kontext ausgewählt.\n"
            f"(ctx: files={file_count}, rag={rag_count}, selected_text_len={selected_text_len}; "
            f"selected_docs={selected_doc_names[:6]}; file_lens={file_lens})",
        )

    @staticmethod
    def _resolve_mindmap_mode_and_query(
        query_raw: str,
        *,
        mode_hint: str = "auto",
    ) -> tuple[str, str]:
        query = str(query_raw or "").strip()
        forced_mode = str(mode_hint or "").strip().casefold()
        mode = "mindmap"
        if forced_mode in {"mindmap", "graph", "chunkmap", "chunk"}:
            mode = "chunkmap" if forced_mode in {"chunkmap", "chunk"} else forced_mode
            low = query.casefold()
            if low.startswith("graph:") or low.startswith("wissensgraph:"):
                query = query.split(":", 1)[1].strip()
            elif low.startswith("mindmap:") or low.startswith("map:"):
                query = query.split(":", 1)[1].strip()
            elif low.startswith("chunkmap:") or low.startswith("chunk:"):
                query = query.split(":", 1)[1].strip()
        else:
            low = query.casefold()
            if low.startswith("graph:"):
                mode = "graph"
                query = query.split(":", 1)[1].strip()
            elif low.startswith("wissensgraph:"):
                mode = "graph"
                query = query.split(":", 1)[1].strip()
            elif low.startswith("mindmap:") or low.startswith("map:"):
                mode = "mindmap"
                query = query.split(":", 1)[1].strip()
            elif low.startswith("chunkmap:") or low.startswith("chunk:"):
                mode = "chunkmap"
                query = query.split(":", 1)[1].strip()
            elif "wissensgraph" in low:
                mode = "graph"
        if not query:
            if mode == "graph":
                query = (
                    "Welche zentralen Entitäten und Beziehungen sind im Kontext belegt?"
                )
            elif mode == "chunkmap":
                query = (
                    "Wie ist der Kontext nach Überschriften und Chunks strukturiert?"
                )
            else:
                query = (
                    "Welche zentralen Konzepte beantworten die Fragestellung im Kontext?"
                )
        return mode, query
