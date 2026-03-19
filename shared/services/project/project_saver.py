"""Project save service for serializing complete app state."""
from __future__ import annotations

import base64
import json
import pickle
from pathlib import Path
from typing import Any

from shared.services.highlights.store import get_highlight_store
from shared.services.highlights.store_storage import save_store_data
from shared.services.project.project_variables import normalize_project_variables

from .project_paths import ProjectPaths


class ProjectSaver:
    """Serialize the full application state into a project folder."""

    def __init__(self, *, paths: ProjectPaths, include_st_embeddings: bool):
        self._paths = paths
        self._include_st_embeddings = bool(include_st_embeddings)

    def save(self, mw: Any) -> None:
        self._paths.ensure_save_dirs()

        canvas_tabs_data = self._save_canvas_tabs(mw)
        knowledge_files_data = self._save_knowledge_files(mw)
        rag_state = self._save_rag_index(mw)
        self._save_optional_embeddings(mw, rag_state)
        self._save_chat_history(mw)
        self._save_chunk_claim_cache(mw)
        self._save_log_entries(mw)
        self._save_highlights()
        rag_results = self._collect_rag_results(mw)

        manifest = self._build_manifest(
            mw=mw,
            canvas_tabs_data=canvas_tabs_data,
            knowledge_files_data=knowledge_files_data,
            rag_results=rag_results,
        )
        self._write_json(self._paths.manifest, manifest)

    def _save_canvas_tabs(self, mw: Any) -> list[dict]:
        tab_widget = mw.canvas.tabs.tab_widget
        canvas_tabs_data: list[dict] = []
        written_files: set[str] = set()

        for index in range(tab_widget.count()):
            panel = tab_widget.widget(index)
            editor = getattr(panel, "editor", None)
            if editor is None:
                continue

            canvas_file = f"doc_{index:04d}.md"
            (self._paths.canvas / canvas_file).write_text(
                editor.toPlainText(),
                encoding="utf-8",
            )
            written_files.add(canvas_file)
            canvas_tabs_data.append(
                {
                    "title": tab_widget.tabText(index),
                    "file_path": str(getattr(panel, "file_path", "") or ""),
                    "canvas_file": canvas_file,
                    "read_only": bool(editor.isReadOnly()),
                }
            )

        self._delete_stale_files(self._paths.canvas, "doc_*.md", written_files)
        return canvas_tabs_data

    def _save_knowledge_files(self, mw: Any) -> list[dict]:
        knowledge_map: dict[str, tuple[str, str]] = {}
        knowledge_order: list[str] = []

        registry = getattr(mw, "_file_registry", {})
        if isinstance(registry, dict):
            for display_name, entry in registry.items():
                if isinstance(entry, tuple) and len(entry) >= 2:
                    self._merge_knowledge_item(
                        knowledge_map,
                        knowledge_order,
                        display_name,
                        entry[0],
                        entry[1],
                    )

        imported_entries = getattr(
            getattr(mw, "knowledge_dock", None),
            "imported_files",
            None,
        )
        imported_map: dict[str, str] = {}
        if imported_entries is not None:
            getter = getattr(imported_entries, "get_all_documents", None)
            if callable(getter):
                try:
                    snapshot = getter()
                    if isinstance(snapshot, dict):
                        imported_map = {str(k): str(v or "") for k, v in snapshot.items()}
                except Exception:
                    imported_map = {}
        if isinstance(imported_map, dict):
            for display_name, markdown in imported_map.items():
                self._merge_knowledge_item(
                    knowledge_map,
                    knowledge_order,
                    display_name,
                    "",
                    markdown,
                )

        context_panel = getattr(getattr(mw, "chat_dock", None), "context_panel", None)
        context_docs: dict[str, str] = {}
        if context_panel is not None:
            getter = getattr(context_panel, "get_all_documents", None)
            if callable(getter):
                try:
                    snapshot = getter()
                    if isinstance(snapshot, dict):
                        context_docs = {str(k): str(v or "") for k, v in snapshot.items()}
                except Exception:
                    context_docs = {}
        if isinstance(context_docs, dict):
            for display_name, markdown in context_docs.items():
                self._merge_knowledge_item(
                    knowledge_map,
                    knowledge_order,
                    display_name,
                    "",
                    markdown,
                )

        knowledge_files_data: list[dict] = []
        written_files: set[str] = set()
        for index, display_name in enumerate(knowledge_order):
            original_path, markdown = knowledge_map.get(display_name, ("", ""))
            knowledge_file = f"doc_{index:04d}.md"
            (self._paths.knowledge / knowledge_file).write_text(
                markdown,
                encoding="utf-8",
            )
            written_files.add(knowledge_file)
            knowledge_files_data.append(
                {
                    "display_name": display_name,
                    "original_path": original_path,
                    "knowledge_file": knowledge_file,
                }
            )

        self._delete_stale_files(self._paths.knowledge, "doc_*.md", written_files)
        return knowledge_files_data

    def _save_rag_index(self, mw: Any) -> dict:
        rag_state = mw.rag_system.dump_state()
        with open(self._paths.rag_index, "wb") as handle:
            pickle.dump(rag_state, handle, protocol=pickle.HIGHEST_PROTOCOL)
        return rag_state

    def _save_optional_embeddings(self, mw: Any, rag_state: dict) -> None:
        if not self._include_st_embeddings:
            return
        if not bool(rag_state.get("has_st_embeddings")):
            return

        try:
            import torch  # type: ignore

            with mw.rag_system._lock:
                raw_embeddings = dict(getattr(mw.rag_system, "_st_embeddings", {}) or {})

            snapshot: dict[str, Any] = {}
            for key, value in raw_embeddings.items():
                item = value
                if hasattr(item, "detach"):
                    try:
                        item = item.detach()
                    except Exception:
                        pass
                if hasattr(item, "cpu"):
                    try:
                        item = item.cpu()
                    except Exception:
                        pass
                if hasattr(item, "clone"):
                    try:
                        item = item.clone()
                    except Exception:
                        pass
                snapshot[str(key)] = item

            if snapshot:
                torch.save(snapshot, str(self._paths.rag_embeddings))
        except Exception:
            # Embeddings are optional and may be unavailable on lightweight setups.
            return

    def _save_chat_history(self, mw: Any) -> None:
        history_widget = mw.chat_dock.history
        history = history_widget.export_sessions()
        self._write_json(self._paths.chat_history, history)

    def _save_chunk_claim_cache(self, mw: Any) -> None:
        claim_cache: dict[str, object] = {}
        exporter = getattr(getattr(mw, "chat_dock", None), "export_chunk_claim_cache", None)
        if callable(exporter):
            try:
                exported = exporter()
                if isinstance(exported, dict):
                    claim_cache = exported
            except Exception:
                claim_cache = {}
        self._write_json(self._paths.chat_chunk_claim_cache, claim_cache)

    def _save_log_entries(self, mw: Any) -> None:
        log_entries = [
            {"ts": ts, "level": level, "category": category, "message": message}
            for ts, level, category, message in mw.app_logger.get_entries()
        ]
        self._write_json(self._paths.log_entries, log_entries)

    def _save_highlights(self) -> None:
        snapshot = get_highlight_store().snapshot()
        save_store_data(self._paths.highlights, snapshot)

    def _collect_rag_results(self, mw: Any) -> list[dict]:
        rag_tab_widget = mw.knowledge_dock.rag_panel.tabs.tab_widget
        rag_tabs_wrap = mw.knowledge_dock.rag_panel.tabs
        results: list[dict] = []
        for index in range(rag_tab_widget.count()):
            panel = rag_tab_widget.widget(index)
            editor = getattr(panel, "editor", None)
            if editor is None:
                continue
            title = (
                rag_tabs_wrap.get_tab_full_title(index)
                if hasattr(rag_tabs_wrap, "get_tab_full_title")
                else rag_tab_widget.tabText(index)
            )
            results.append({"title": title, "content": editor.toPlainText()})
        return results

    def _build_manifest(
        self,
        *,
        mw: Any,
        canvas_tabs_data: list[dict],
        knowledge_files_data: list[dict],
        rag_results: list[dict],
    ) -> dict:
        context_panel = mw.chat_dock.context_panel
        use_canvas, use_rag, _ = context_panel.get_selection()
        doc_checks = {
            name: checkbox.isChecked()
            for name, checkbox in context_panel._cbs.items()
        }

        model_panel = mw.chat_dock.model_panel
        llm_data = {
            "model_path": model_panel.model_path.text(),
            "model_backend": model_panel.get_model_backend(),
            "nli_model_id": model_panel.nli_model_id.text(),
            "ctx_size": model_panel.ctx_spin.value(),
            "gpu_layers": model_panel.gpu_spin.value(),
            "threads": model_panel.threads_spin.value(),
            "trust_remote_code": bool(model_panel.trust_remote_code_cb.isChecked()),
            "max_tokens": model_panel.max_tokens_spin.value(),
            "temperature": model_panel.temp_spin.value(),
            "top_p": model_panel.top_p_spin.value(),
            "repeat_penalty": model_panel.repeat_penalty_spin.value(),
            "forbidden_chars": model_panel.forbidden_chars_edit.text(),
            "apply_selection_direct": mw.chat_dock.apply_selection_cb.isChecked(),
        }

        geometry_b64 = base64.b64encode(mw.saveGeometry().data()).decode()
        state_b64 = base64.b64encode(mw.saveState().data()).decode()
        project_variables_getter = getattr(mw, "get_project_variables", None)
        project_variables = {}
        if callable(project_variables_getter):
            try:
                project_variables = normalize_project_variables(
                    project_variables_getter()
                )
            except Exception:
                project_variables = {}

        return {
            "version": 1,
            "rag_config": mw.rag_system.config.to_dict(),
            "project_variables": project_variables,
            "settings": {
                "prompts": mw.llm_manager.get_prompt_set(),
                "speech": mw.get_speech_settings(),
                "preview_page_margin": mw.get_preview_page_margin_settings(),
                "preview_theme": mw.get_preview_theme_id(),
                "theme": mw.get_theme_id(),
            },
            "llm": llm_data,
            "canvas": {
                "current_tab": mw.canvas.tabs.tab_widget.currentIndex(),
                "tabs": canvas_tabs_data,
            },
            "knowledge": {
                "files": knowledge_files_data,
            },
            "rag_results": rag_results,
            "rag_debug_history": mw.knowledge_dock.rag_panel.get_debug_history(),
            "rag_search_query": mw.knowledge_dock.rag_panel.search_input.text(),
            "ui": {
                "window_geometry": geometry_b64,
                "window_state": state_b64,
                "user_mode": getattr(mw, "user_mode", "plus"),
                "log_enabled": mw.app_logger.enabled,
                "log_level_filter": mw.log_dock._level_filter,
                "log_cat_filter": mw.log_dock._cat_filter,
                "context_use_canvas": use_canvas,
                "context_use_rag": use_rag,
                "context_doc_checks": doc_checks,
            },
        }

    @staticmethod
    def _merge_knowledge_item(
        knowledge_map: dict[str, tuple[str, str]],
        knowledge_order: list[str],
        display_name: object,
        original_path: object,
        markdown: object,
    ) -> None:
        name = str(display_name or "").strip()
        if not name:
            return

        src_path = str(original_path or "").strip()
        src_markdown = str(markdown or "")
        existing = knowledge_map.get(name)
        if existing is None:
            knowledge_map[name] = (src_path, src_markdown)
            knowledge_order.append(name)
            return

        old_path, old_markdown = existing
        merged_path = old_path or src_path
        merged_markdown = old_markdown
        if (not old_markdown.strip()) and src_markdown.strip():
            merged_markdown = src_markdown
        knowledge_map[name] = (merged_path, merged_markdown)

    @staticmethod
    def _delete_stale_files(folder: Path, pattern: str, keep_names: set[str]) -> None:
        for stale_path in folder.glob(pattern):
            if stale_path.name in keep_names:
                continue
            try:
                stale_path.unlink()
            except Exception:
                continue

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
