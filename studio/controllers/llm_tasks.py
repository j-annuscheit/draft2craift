"""LLM side-task controller — glossary and mindmap generation."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLabel,
    QMessageBox,
    QSlider,
    QVBoxLayout,
)

from shared.domain.user_mode import resolve_feature_label
from shared.services.agentic.settings import AgenticRuntimeSettings
from shared.services.highlights.store import get_highlight_store
from shared.services.llm.manager import LLMManager
from studio.glossary.editor import GlossaryEditorDialog
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
    query: str = ""


@dataclass(frozen=True)
class MindmapTaskRequest:
    context_text: str
    query: str
    mode: str = "mindmap"
    max_nodes: int = 32
    chunking_strategy: str = "sliding_window"
    chunk_size: int = 900
    chunk_overlap: int = 160
    map_depth: int = 0


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


def _agentic_map_meta(run_result, *, mode: str) -> dict[str, object]:  # noqa: ANN001
    state = dict(getattr(run_result, "state", {}) or {})
    metrics = dict(getattr(run_result, "metrics", {}) or {})
    map_result = dict(state.get("map_result", {}) or {})
    map_metrics = dict(state.get("map_metrics", {}) or {})
    map_coverage = dict(state.get("map_coverage", {}) or {})

    # v1 workflow: stats in map_validation.stats
    validation = dict(state.get("map_validation", {}) or {})
    v1_stats = dict(validation.get("stats", {}) or {})

    # v2 workflow: stats in structure_check (node_count, edge_count, component_count)
    structure_check = dict(state.get("structure_check", {}) or {})

    fallback_stats = dict(map_result.get("stats", {}) or {})
    nodes = int(v1_stats.get("nodes", fallback_stats.get("nodes", structure_check.get("node_count", 0))) or 0)
    edges = int(v1_stats.get("edges", fallback_stats.get("edges", structure_check.get("edge_count", 0))) or 0)
    components = int(v1_stats.get("components", fallback_stats.get("components", structure_check.get("component_count", 0))) or 0)

    return {
        "kind": str(validation.get("kind", mode) or mode),
        "variant": str(mode or ""),
        "reason": "agentic",
        "nodes": nodes,
        "edges": edges,
        "roots": int(v1_stats.get("roots", 0) or 0),
        "isolated_nodes": int(v1_stats.get("isolated_nodes", 0) or 0),
        "components": components,
        "max_depth": int(v1_stats.get("max_depth", 0) or 0),
        "root_label": str(map_result.get("root_label", "") or ""),
        "cleanup": dict(validation.get("cleanup", {}) or {}),
        "candidate_review": dict(validation.get("candidate_review", {}) or {}),
        "workflow_id": str(getattr(run_result, "workflow_id", "") or ""),
        "profile_id": str(getattr(run_result, "profile_id", "") or ""),
        "errors": list(getattr(run_result, "errors", []) or []),
        "metrics": metrics,
        "trace_path": str(metrics.get("trace_path", "") or ""),
        "graph_closure_round": int(state.get("graph_closure_round", 0) or 0),
        "refine_round": int(state.get("refine_round", 0) or 0),
        "expand_round": int(state.get("expand_round", 0) or 0),
        "expansion_round": int(state.get("expansion_round", map_metrics.get("expansion_round", 0)) or 0),
        "gap_round": int(map_metrics.get("gap_round", 0) or 0),
        "coverage_ratio": float(map_coverage.get("coverage_ratio", 0.0) or 0.0),
    }


# ── Worker ─────────────────────────────────────────────────────────────────────


class _LLMSideTaskWorker(QObject):
    """Runs non-streaming LLM side tasks in a background thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        llm_manager: LLMManager,
        *,
        request: TaskRequest,
        agentic_settings: AgenticRuntimeSettings | None = None,
    ):
        super().__init__()
        self._llm_manager = llm_manager
        self._request = request
        self._agentic_settings = (
            agentic_settings.clone()
            if isinstance(agentic_settings, AgenticRuntimeSettings)
            else None
        )

    def run(self):
        try:
            if isinstance(self._request, GlossaryTaskRequest):
                context_text = str(self._request.context_text or "")
                max_terms = int(self._request.max_terms or 32)
                query = str(self._request.query or "")
                entries, meta = self._llm_manager.generate_glossary_sync(
                    context_text=context_text,
                    max_terms=max_terms,
                    focus_query=query,
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
                map_depth = max(0, min(12, int(self._request.map_depth or 0)))
                mode_clean = str(mode or "").strip().casefold()
                workflow_key = "graph" if mode_clean == "graph" else "mindmap"
                agentic_opts = (
                    self._agentic_settings.run_options_for(workflow_key)
                    if self._agentic_settings is not None
                    else {}
                )
                agentic_enabled = bool(agentic_opts.get("enabled", False))
                if (
                    mode_clean == "graph"
                    and (not agentic_enabled)
                    and self._agentic_settings is not None
                ):
                    fallback_opts = self._agentic_settings.run_options_for("mindmap")
                    if bool(fallback_opts.get("enabled", False)):
                        agentic_opts = dict(fallback_opts or {})
                        agentic_enabled = True
                if agentic_enabled:
                    try:
                        from shared.services.agentic import AgenticWorkflowService, build_tools

                        default_profile_id = (
                            "graph_connected_component"
                            if mode_clean == "graph"
                            else "mindmap_grounded_graph"
                        )
                        profile_id = str(
                            agentic_opts.get(
                                "profile_id",
                                default_profile_id,
                            )
                            or default_profile_id
                        ).strip()
                        policy_overrides = dict(agentic_opts.get("policy_overrides", {}) or {})
                        policy_overrides["map_require_connected_graph"] = True
                        policy_overrides.setdefault("map_cleanup_enabled", True)
                        policy_overrides.setdefault("map_node_min_word_letters", 3)
                        if mode_clean != "graph":
                            policy_overrides.setdefault("map_max_expansion_rounds", max(4, map_depth * 3) if map_depth > 0 else 24)
                        else:
                            # graph workflow (v1-style) still uses expand_enabled / target_depth
                            if map_depth > 0:
                                policy_overrides["map_expand_enabled"] = True
                                policy_overrides["map_expand_target_depth"] = map_depth
                            else:
                                policy_overrides.setdefault("map_expand_enabled", False)
                                policy_overrides.setdefault("map_expand_target_depth", 0)
                        run_kwargs = {
                            "request": {
                                "mode": mode,
                                "scope": "selection",
                                "query": query,
                                "depth": map_depth,
                                "context_text": context_text,
                            },
                            "profile_id": profile_id or default_profile_id,
                            "enabled": agentic_enabled,
                            "policy_overrides": policy_overrides,
                            "overlay_profile_ids": list(
                                agentic_opts.get("overlay_profile_ids", []) or []
                            ),
                            "env_name": str(agentic_opts.get("env_name", "") or ""),
                            "tools": build_tools(
                                llm_manager=self._llm_manager,
                                source_texts=[("Kontext", context_text)],
                            ),
                        }
                        svc = AgenticWorkflowService()
                        run_result = (
                            svc.run_graph(**run_kwargs)
                            if mode_clean == "graph"
                            else svc.run_mindmap(**run_kwargs)
                        )
                        if bool(run_result.ok):
                            markdown = str(run_result.result.get("markdown", "") or "")
                            self.finished.emit(
                                MindmapTaskResult(
                                    context_text=context_text,
                                    query=query,
                                    mode=mode,
                                    markdown=markdown,
                                    meta=_agentic_map_meta(run_result, mode=mode),
                                )
                            )
                            return
                        if mode_clean == "graph":
                            errors = list(run_result.errors or [])
                            self.finished.emit(
                                MindmapTaskResult(
                                    context_text=context_text,
                                    query=query,
                                    mode=mode,
                                    markdown="",
                                    meta={
                                        "kind": "graph",
                                        "variant": "graph",
                                        "reason": "agentic_failed",
                                        "error": "; ".join(
                                            str(item or "").strip()
                                            for item in errors[:4]
                                            if str(item or "").strip()
                                        ) or "Graph konnte nicht zu einer Komponente geschlossen werden.",
                                        "workflow_id": str(run_result.workflow_id or ""),
                                        "profile_id": str(run_result.profile_id or ""),
                                        "errors": errors,
                                        "metrics": dict(run_result.metrics or {}),
                                    },
                                )
                            )
                            return
                    except Exception as exc:
                        if mode_clean == "graph":
                            self.failed.emit(f"Graph-Agentic fehlgeschlagen: {exc}")
                            return
                        pass
                non_agentic_max_nodes = max_nodes
                if mode_clean in {"mindmap", "graph"} and map_depth > 0:
                    non_agentic_max_nodes = max(
                        int(non_agentic_max_nodes or 0),
                        min(128, 12 + (map_depth * 12)),
                    )
                markdown, meta = self._llm_manager.generate_mindmap_sync(
                    context_text=context_text,
                    query=query,
                    mode=mode,
                    max_nodes=non_agentic_max_nodes,
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
        self._build_llm_context_cb = ctx.build_llm_context
        self._get_user_mode = ctx.get_user_mode
        self._get_agentic_settings = ctx.get_agentic_settings
        self._is_prompt_editor_allowed = ctx.is_prompt_editor_allowed
        self._dialog_manager = ctx.dialog_manager

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
        query_raw: str = "",
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

        context_text = self._build_context_text_from_llm_context(ctx, max_chars=0)
        if not context_text:
            context_text = self._fallback_context_text_from_ctx(ctx, max_chars=0)
        if not context_text:
            return self._empty_context_error(ctx)
        query = str(query_raw or "").strip()
        if not query:
            query = str(ctx.get("user_query", "") or "").strip()

        return self._start_task(
            task_kind="glossary",
            request=GlossaryTaskRequest(
                context_text=context_text,
                max_terms=32,
                query=query,
            ),
            status_message="Generiere Glossar aus Kontext…",
            done_cb=done_cb,
        )

    def generate_mindmap_from_llm_context(
        self,
        ctx: dict,
        query_raw: str = "",
        mode_hint: str = "auto",
        map_depth: int = 0,
        done_cb=None,
    ) -> tuple[bool, str]:
        resolved_query_raw = str(query_raw or "").strip()
        if not resolved_query_raw:
            resolved_query_raw = str(ctx.get("user_query", "") or "").strip()
        mode, query = self._resolve_mindmap_mode_and_query(
            resolved_query_raw,
            mode_hint=mode_hint,
        )

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
                map_depth=max(0, min(12, int(map_depth or 0))),
            ),
            status_message="Generiere MindMap/Graph/Chunk-MindMap aus Kontext…",
            done_cb=done_cb,
        )

    def _prompt_map_depth_for_mode(
        self,
        *,
        parent,
        user_mode: str,
        mode_hint: str,
    ) -> int | None:
        mode = str(mode_hint or "").strip().casefold()
        if mode not in {"mindmap", "graph"}:
            return 0
        title = resolve_feature_label(
            user_mode,
            "mindmap.generate.dialog.depth.title",
            "Ausbautiefe festlegen",
        )
        intro = resolve_feature_label(
            user_mode,
            "mindmap.generate.dialog.depth.intro",
            "Wie tief soll der Agent den Graph/Mindmap iterativ ausbauen? 0 = deaktiviert.",
        )
        value_prefix = resolve_feature_label(
            user_mode,
            "mindmap.generate.dialog.depth.value_prefix",
            "Tiefe",
        )
        ok_text = resolve_feature_label(
            user_mode,
            "mindmap.generate.dialog.button.ok",
            "OK",
        )
        cancel_text = resolve_feature_label(
            user_mode,
            "mindmap.generate.dialog.button.cancel",
            "Cancel",
        )

        dialog = QDialog(parent)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        intro_lbl = QLabel(intro)
        intro_lbl.setWordWrap(True)
        layout.addWidget(intro_lbl)

        slider = QSlider(Qt.Orientation.Horizontal, dialog)
        slider.setRange(0, 6)
        slider.setSingleStep(1)
        slider.setPageStep(1)
        slider.setTickInterval(1)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setValue(2)
        layout.addWidget(slider)

        value_lbl = QLabel("")
        layout.addWidget(value_lbl)

        def _sync_value(value: int) -> None:
            value_lbl.setText(f"{value_prefix}: {int(value)}")

        slider.valueChanged.connect(_sync_value)
        _sync_value(int(slider.value()))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText(ok_text)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText(cancel_text)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return int(slider.value())

    def toggle_glossary_overlays(self, checked: bool) -> None:
        get_highlight_store().set_glossary_enabled(bool(checked))
        self._refresh_preview_overlays()
        self._show_status("Glossar-Overlay: AN" if checked else "Glossar-Overlay: AUS", 2500)

    def open_glossary_editor(self) -> None:
        parent = self.parent()
        if parent is None:
            return

        def _create() -> GlossaryEditorDialog:
            dialog = GlossaryEditorDialog(
                parent,
                user_mode=self._get_user_mode(),
            )
            dialog.glossary_saved.connect(self.on_glossary_saved_from_editor)
            return dialog

        self._dialog_manager.show_dialog("glossary-editor", _create)

    def on_glossary_saved_from_editor(self, count: int) -> None:
        self._refresh_preview_overlays()
        overlays_on = get_highlight_store().is_glossary_enabled()
        suffix = "" if overlays_on else " (Overlay aktuell AUS)."
        self._show_status(f"Glossar gespeichert: {int(count)} Begriffe{suffix}", 4500)

    def generate_glossary_from_context(self) -> None:
        parent = self.parent()
        if parent is None:
            return
        _err = lambda ok, info: (not ok) and QMessageBox.information(parent, "Glossar", info)
        ok, info = self.generate_glossary_from_llm_context(
            self._build_llm_context_cb(),
            done_cb=_err,
        )
        if not ok:
            QMessageBox.information(parent, "Glossar", info)

    def generate_mindmap_from_context(self) -> None:
        parent = self.parent()
        if parent is None:
            return
        ctx_payload = self._build_llm_context_cb()
        query_hint = str(ctx_payload.get("user_query", "") or "").strip()
        user_mode = self._get_user_mode()
        title = resolve_feature_label(
            user_mode,
            "mindmap.generate.dialog.title",
            "MindMap/Graph/Chunk-MindMap generieren",
        )
        output_label = resolve_feature_label(
            user_mode,
            "mindmap.generate.dialog.output_format",
            "Ausgabeformat:",
        )
        ok_text = resolve_feature_label(
            user_mode,
            "mindmap.generate.dialog.button.ok",
            "OK",
        )
        cancel_text = resolve_feature_label(
            user_mode,
            "mindmap.generate.dialog.button.cancel",
            "Cancel",
        )
        mode_options = [
            (
                "chunkmap",
                resolve_feature_label(
                    user_mode,
                    "mindmap.generate.dialog.option.chunkmap",
                    "Chunk-MindMap",
                ),
            ),
            (
                "mindmap",
                resolve_feature_label(
                    user_mode,
                    "mindmap.generate.dialog.option.mindmap",
                    "MindMap",
                ),
            ),
            (
                "graph",
                resolve_feature_label(
                    user_mode,
                    "mindmap.generate.dialog.option.graph",
                    "Graph",
                ),
            ),
        ]
        mode_dialog = QInputDialog(parent)
        mode_dialog.setWindowTitle(title)
        mode_dialog.setLabelText(output_label)
        mode_dialog.setComboBoxItems([label for _, label in mode_options])
        mode_dialog.setTextValue(mode_options[0][1])
        mode_dialog.setOkButtonText(ok_text)
        mode_dialog.setCancelButtonText(cancel_text)
        if mode_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected_mode_label = str(mode_dialog.textValue() or "")
        mode_hint = mode_options[0][0]
        for mode_name, mode_label in mode_options:
            if mode_label == selected_mode_label:
                mode_hint = mode_name
                break
        query_defaults = {
            "graph": resolve_feature_label(
                user_mode,
                "mindmap.generate.dialog.query_default.graph",
                "Welche zentralen Entitäten und Beziehungen sind im Kontext belegt?",
            ),
            "chunkmap": resolve_feature_label(
                user_mode,
                "mindmap.generate.dialog.query_default.chunkmap",
                "Wie ist der Kontext nach Überschriften und Chunks strukturiert?",
            ),
            "mindmap": resolve_feature_label(
                user_mode,
                "mindmap.generate.dialog.query_default.mindmap",
                "Welche zentralen Konzepte beantworten die Fragestellung im Kontext?",
            ),
        }
        query_label = resolve_feature_label(
            user_mode,
            "mindmap.generate.dialog.query_label",
            "Fragestellung (optional):",
        )
        query_dialog = QInputDialog(parent)
        query_dialog.setWindowTitle(title)
        query_dialog.setInputMode(QInputDialog.InputMode.TextInput)
        query_dialog.setOption(
            QInputDialog.InputDialogOption.UsePlainTextEditForTextInput,
            True,
        )
        query_dialog.setLabelText(query_label)
        query_dialog.setTextValue(
            query_hint or query_defaults.get(mode_hint, query_defaults["mindmap"])
        )
        query_dialog.setOkButtonText(ok_text)
        query_dialog.setCancelButtonText(cancel_text)
        if query_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        query_raw = query_dialog.textValue()
        map_depth = self._prompt_map_depth_for_mode(
            parent=parent,
            user_mode=user_mode,
            mode_hint=mode_hint,
        )
        if map_depth is None:
            return
        _err2 = lambda ok2, info: (not ok2) and QMessageBox.information(parent, "MindMap/Graph", info)
        ok, info = self.generate_mindmap_from_llm_context(
            ctx_payload,
            str(query_raw or ""),
            mode_hint=mode_hint,
            map_depth=int(map_depth or 0),
            done_cb=_err2,
        )
        if not ok:
            QMessageBox.information(parent, "MindMap/Graph", info)

    def edit_system_prompt(self) -> None:
        parent = self.parent()
        if parent is None:
            return
        user_mode = self._get_user_mode()
        if not self._is_prompt_editor_allowed(user_mode):
            QMessageBox.information(
                parent,
                "Prompt Editor",
                "Im Einfach-Modus ist der Prompt-Editor ausgeblendet.\nWechsle zu Plus oder Experte.",
            )
            return
        from studio.dialogs.prompt_editor import PromptEditorDialog

        self._dialog_manager.show_dialog(
            "prompt-editor",
            lambda: PromptEditorDialog(self._llm_manager, user_mode, parent=parent),
            on_accept=lambda _dlg: self._autosave_schedule_fn(300),
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

        agentic_settings = None
        try:
            settings = self._get_agentic_settings()
            if isinstance(settings, AgenticRuntimeSettings):
                agentic_settings = settings.clone()
        except Exception:
            agentic_settings = None

        thread = QThread(self)
        worker = _LLMSideTaskWorker(
            self._llm_manager,
            request=request,
            agentic_settings=agentic_settings,
        )
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
