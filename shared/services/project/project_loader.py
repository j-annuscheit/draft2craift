"""Project load service for restoring complete app state."""
from __future__ import annotations

import base64
import json
import pickle
from typing import Any

from PySide6.QtCore import QByteArray

from shared.services.highlights.store import get_highlight_store
from shared.services.project.project_variables import normalize_project_variables
from shared.services.rag.config import RAGConfig

from .project_paths import ProjectPaths


class ProjectSchemaError(ValueError):
    """Raised when ``project.json`` does not match the expected schema."""


class ProjectLoader:
    """Restore the full application state from a persisted project folder."""

    def __init__(self, *, paths: ProjectPaths):
        self._paths = paths

    def load(self, mw: Any) -> None:
        data = self._read_manifest()

        self._restore_project_variables(mw, data)
        self._restore_highlights(mw)
        self._restore_rag_config(mw, data)
        self._restore_knowledge_files(mw, data)
        self._restore_rag_index(mw)
        self._restore_optional_embeddings(mw)
        self._restore_canvas_tabs(mw, data)
        self._restore_chat_history(mw)
        self._restore_chunk_claim_cache(mw)
        self._restore_log_entries(mw)
        self._restore_rag_results(mw, data)
        self._restore_settings(mw, data)
        self._restore_llm_ui(mw, data)
        self._restore_ui_state(mw, data)

    def _restore_highlights(self, mw: Any) -> None:
        store = get_highlight_store()
        store.rebind_path(self._paths.highlights, reload=True)
        action = getattr(mw, "_action_glossary_overlay", None)
        if action is None:
            return
        try:
            blocked = action.blockSignals(True)
            action.setChecked(store.is_glossary_enabled())
            action.blockSignals(blocked)
        except Exception:
            return

    def _read_manifest(self) -> dict:
        if not self._paths.manifest.exists():
            raise FileNotFoundError(f"No project.json found in:\n{self._paths.base}")

        with open(self._paths.manifest, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        return self._validate_manifest(raw)

    @staticmethod
    def _validate_manifest(raw: object) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ProjectSchemaError(
                "Top-level JSON must be an object."
            )

        if "version" not in raw:
            raise ProjectSchemaError("Missing required field 'version'.")
        version = raw.get("version")
        if not isinstance(version, int):
            raise ProjectSchemaError(
                f"Field 'version' must be int, got {type(version).__name__}."
            )
        if version != 2:
            raise ProjectSchemaError(
                f"Unsupported project version: {version} (expected 2)."
            )

        required_dict_fields = ("rag_config", "canvas", "knowledge", "settings", "llm", "ui")
        for key in required_dict_fields:
            if key not in raw:
                raise ProjectSchemaError(f"Missing required field '{key}'.")
            value = raw.get(key)
            if not isinstance(value, dict):
                raise ProjectSchemaError(
                    f"Field '{key}' must be an object, got {type(value).__name__}."
                )

        project_variables = raw.get("project_variables")
        if project_variables is not None and not isinstance(project_variables, dict):
            raise ProjectSchemaError(
                "Field 'project_variables' must be an object when present."
            )
        if isinstance(project_variables, dict):
            for key, value in project_variables.items():
                if not isinstance(key, str):
                    raise ProjectSchemaError(
                        "Field 'project_variables' must use string keys."
                    )
                if not isinstance(value, str):
                    raise ProjectSchemaError(
                        f"Field 'project_variables.{key}' must be string, got {type(value).__name__}."
                    )

        canvas = raw["canvas"]
        if "tabs" not in canvas:
            raise ProjectSchemaError("Missing required field 'canvas.tabs'.")
        tabs = canvas.get("tabs")
        if not isinstance(tabs, list):
            raise ProjectSchemaError(
                f"Field 'canvas.tabs' must be an array, got {type(tabs).__name__}."
            )
        for idx, tab_item in enumerate(tabs):
            if not isinstance(tab_item, dict):
                raise ProjectSchemaError(
                    f"Field 'canvas.tabs[{idx}]' must be an object, got {type(tab_item).__name__}."
                )
            for field_name in ("title", "file_path", "canvas_file"):
                field_value = tab_item.get(field_name)
                if not isinstance(field_value, str):
                    raise ProjectSchemaError(
                        f"Field 'canvas.tabs[{idx}].{field_name}' must be string, got {type(field_value).__name__}."
                    )
            read_only = tab_item.get("read_only")
            if not isinstance(read_only, bool):
                raise ProjectSchemaError(
                    f"Field 'canvas.tabs[{idx}].read_only' must be bool, got {type(read_only).__name__}."
                )
        current_tab = canvas.get("current_tab")
        if current_tab is not None and not isinstance(current_tab, int):
            raise ProjectSchemaError(
                f"Field 'canvas.current_tab' must be int when present, got {type(current_tab).__name__}."
            )

        knowledge = raw["knowledge"]
        if "files" not in knowledge:
            raise ProjectSchemaError("Missing required field 'knowledge.files'.")
        files = knowledge.get("files")
        if not isinstance(files, list):
            raise ProjectSchemaError(
                f"Field 'knowledge.files' must be an array, got {type(files).__name__}."
            )
        for idx, file_item in enumerate(files):
            if not isinstance(file_item, dict):
                raise ProjectSchemaError(
                    f"Field 'knowledge.files[{idx}]' must be an object, got {type(file_item).__name__}."
                )
            for field_name in ("display_name", "original_path", "knowledge_file"):
                field_value = file_item.get(field_name)
                if not isinstance(field_value, str):
                    raise ProjectSchemaError(
                        f"Field 'knowledge.files[{idx}].{field_name}' must be string, got {type(field_value).__name__}."
                    )

        settings = raw["settings"]
        required_settings_fields = (
            "prompts",
            "speech",
            "preview_page_margin",
            "preview_theme",
            "preview_style",
            "theme",
        )
        for key in required_settings_fields:
            if key not in settings:
                raise ProjectSchemaError(f"Missing required field 'settings.{key}'.")

        prompts = settings.get("prompts")
        if not isinstance(prompts, dict):
            raise ProjectSchemaError(
                f"Field 'settings.prompts' must be an object, got {type(prompts).__name__}."
            )

        speech = settings.get("speech")
        if not isinstance(speech, dict):
            raise ProjectSchemaError(
                f"Field 'settings.speech' must be an object, got {type(speech).__name__}."
            )

        preview_page_margin = settings.get("preview_page_margin")
        if not isinstance(preview_page_margin, dict):
            raise ProjectSchemaError(
                "Field 'settings.preview_page_margin' must be an object."
            )
        margin_enabled = preview_page_margin.get("enabled")
        margin_em = preview_page_margin.get("em")
        if not isinstance(margin_enabled, bool):
            raise ProjectSchemaError(
                f"Field 'settings.preview_page_margin.enabled' must be bool, got {type(margin_enabled).__name__}."
            )
        if not isinstance(margin_em, (int, float)):
            raise ProjectSchemaError(
                f"Field 'settings.preview_page_margin.em' must be number, got {type(margin_em).__name__}."
            )

        preview_theme = settings.get("preview_theme")
        if not isinstance(preview_theme, str):
            raise ProjectSchemaError(
                f"Field 'settings.preview_theme' must be string, got {type(preview_theme).__name__}."
            )

        preview_style = settings.get("preview_style")
        if not isinstance(preview_style, dict):
            raise ProjectSchemaError(
                f"Field 'settings.preview_style' must be an object, got {type(preview_style).__name__}."
            )

        theme = settings.get("theme")
        if not isinstance(theme, str):
            raise ProjectSchemaError(
                f"Field 'settings.theme' must be string, got {type(theme).__name__}."
            )

        rag_results = raw.get("rag_results")
        if rag_results is not None:
            if not isinstance(rag_results, list):
                raise ProjectSchemaError(
                    f"Field 'rag_results' must be an array when present, got {type(rag_results).__name__}."
                )
            for idx, item in enumerate(rag_results):
                if not isinstance(item, dict):
                    raise ProjectSchemaError(
                        f"Field 'rag_results[{idx}]' must be an object, got {type(item).__name__}."
                    )

        return raw

    @staticmethod
    def _restore_rag_config(mw: Any, data: dict) -> None:
        rag_cfg_data = data["rag_config"]
        mw.rag_system.config = RAGConfig.from_dict(rag_cfg_data)

    @staticmethod
    def _restore_project_variables(mw: Any, data: dict) -> None:
        setter = getattr(mw, "set_project_variables", None)
        if not callable(setter):
            return
        variables = normalize_project_variables(data.get("project_variables", {}))
        setter(variables, notify=False)

    def _restore_knowledge_files(self, mw: Any, data: dict) -> None:
        # Block auto-reindex while restoring so background worker does not run.
        mw._file_registry.clear()
        imported_files = mw.knowledge_dock.imported_files
        imported_files.blockSignals(True)
        imported_files.clear_all()

        mw.chat_dock.context_panel.clear_docs()
        viewer_tabs = mw.knowledge_dock.doc_viewer.tabs.tab_widget
        while viewer_tabs.count() > 0:
            viewer_tabs.removeTab(0)

        for file_data in data["knowledge"]["files"]:
            display_name = file_data["display_name"]
            original_path = file_data["original_path"]
            knowledge_file = file_data["knowledge_file"]
            markdown = self._read_knowledge_markdown(knowledge_file)

            mw._file_registry[display_name] = (original_path, markdown)
            imported_files.add_file(display_name, markdown)
            mw.chat_dock.context_panel.add_document(display_name, markdown)
            mw.knowledge_dock.open_content(display_name, markdown, doc_key=display_name)

        imported_files.blockSignals(False)
        if viewer_tabs.count() == 0:
            mw.knowledge_dock.doc_viewer.tabs.add_tab()
        if hasattr(mw, "_update_loaded_menu"):
            try:
                mw._update_loaded_menu()
            except Exception:
                pass

    def _read_knowledge_markdown(self, knowledge_file: str) -> str:
        knowledge_path = self._paths.resolve_knowledge_file(knowledge_file)
        return knowledge_path.read_text(encoding="utf-8")

    def _restore_rag_index(self, mw: Any) -> None:
        if not self._paths.rag_index.exists():
            return
        try:
            with open(self._paths.rag_index, "rb") as handle:
                rag_state = pickle.load(handle)
            mw.rag_system.load_state(rag_state)
        except Exception:
            # Keep load flow alive; project can still open without restored index.
            return

    def _restore_optional_embeddings(self, mw: Any) -> None:
        if not self._paths.rag_embeddings.exists():
            return
        try:
            import torch  # type: ignore

            embeddings = torch.load(str(self._paths.rag_embeddings), map_location="cpu")
            with mw.rag_system._lock:
                mw.rag_system._st_embeddings = embeddings
        except Exception:
            # Optional artifact, ignore if missing or incompatible.
            return

    def _restore_canvas_tabs(self, mw: Any, data: dict) -> None:
        tab_widget = mw.canvas.tabs.tab_widget
        while tab_widget.count() > 0:
            tab_widget.removeTab(0)

        canvas_data = data["canvas"]
        for tab_data in canvas_data["tabs"]:
            canvas_file = tab_data["canvas_file"]
            content = self._read_canvas_content(canvas_file)
            mw.canvas.tabs.add_tab(
                title=tab_data["title"],
                content=content,
                file_path=tab_data["file_path"],
                read_only=tab_data["read_only"],
            )

        if tab_widget.count() == 0:
            mw.canvas.tabs.add_tab()
        else:
            current = canvas_data.get("current_tab", 0)
            if 0 <= current < tab_widget.count():
                tab_widget.setCurrentIndex(current)

    def _read_canvas_content(self, canvas_file: str) -> str:
        if not canvas_file:
            return ""
        return self._paths.resolve_canvas_file(canvas_file).read_text(encoding="utf-8")

    def _restore_chat_history(self, mw: Any) -> None:
        if not self._paths.chat_history.exists():
            raise FileNotFoundError(f"No chat/history.json found in:\n{self._paths.base}")

        with open(self._paths.chat_history, "r", encoding="utf-8") as handle:
            chat_history = json.load(handle)
        if not isinstance(chat_history, dict):
            raise ProjectSchemaError("Field 'chat.history' must be an object.")

        history_widget = mw.chat_dock.history
        history_widget.import_sessions(chat_history)

    def _restore_chunk_claim_cache(self, mw: Any) -> None:
        importer = getattr(mw.chat_dock, "import_chunk_claim_cache", None)
        if not callable(importer):
            raise AttributeError("chat_dock.import_chunk_claim_cache is required.")

        payload: object = {}
        if self._paths.chat_chunk_claim_cache.exists():
            with open(self._paths.chat_chunk_claim_cache, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        importer(payload)

    def _restore_log_entries(self, mw: Any) -> None:
        if not self._paths.log_entries.exists():
            raise FileNotFoundError(f"No logs/entries.json found in:\n{self._paths.base}")

        with open(self._paths.log_entries, "r", encoding="utf-8") as handle:
            log_entries = json.load(handle)
        if not isinstance(log_entries, list):
            raise ProjectSchemaError("Field 'logs.entries' must be an array.")

        mw.app_logger.clear()
        for index, entry in enumerate(log_entries):
            if not isinstance(entry, dict):
                raise ProjectSchemaError(
                    f"Field 'logs.entries[{index}]' must be an object, got {type(entry).__name__}."
                )
            mw.app_logger._entries.append(
                (
                    entry["ts"],
                    entry["level"],
                    entry["category"],
                    entry["message"],
                )
            )
        mw.log_dock._rebuild_from_history()

    @staticmethod
    def _restore_rag_results(mw: Any, data: dict) -> None:
        rag_results = data.get("rag_results", [])
        rag_tabs = mw.knowledge_dock.rag_panel.tabs.tab_widget
        while rag_tabs.count() > 0:
            rag_tabs.removeTab(0)

        for item in rag_results:
            mw.knowledge_dock.rag_panel.tabs.add_tab(
                title=item.get("title", "🔍 RAG"),
                content=item.get("content", ""),
            )

        if rag_tabs.count() == 0:
            mw.knowledge_dock.rag_panel.tabs.add_tab(title="🔍 RAG")

        mw.knowledge_dock.rag_panel.set_debug_history(data.get("rag_debug_history", []))

        search_query = data.get("rag_search_query", "")
        if search_query:
            mw.knowledge_dock.rag_panel.search_input.setText(search_query)

    @staticmethod
    def _restore_settings(mw: Any, data: dict) -> None:
        settings = data.get("settings", {})
        if not isinstance(settings, dict):
            raise ProjectSchemaError("Invalid field 'settings': expected object.")

        prompts = settings.get("prompts")
        if not isinstance(prompts, dict):
            raise ProjectSchemaError("Invalid field 'settings.prompts': expected object.")
        mw.llm_manager.set_prompt_set(prompts)

        speech = settings.get("speech")
        if not isinstance(speech, dict):
            raise ProjectSchemaError("Invalid field 'settings.speech': expected object.")
        mw.apply_speech_settings(speech)

        preview_page_margin = settings.get("preview_page_margin")
        if not isinstance(preview_page_margin, dict):
            raise ProjectSchemaError(
                "Invalid field 'settings.preview_page_margin': expected object."
            )
        mw.apply_preview_page_margin_settings(preview_page_margin)

        preview_theme = settings.get("preview_theme")
        if not isinstance(preview_theme, str):
            raise ProjectSchemaError(
                "Invalid field 'settings.preview_theme': expected string."
            )
        mw.apply_preview_theme_id(preview_theme, persist=True)

        preview_style = settings.get("preview_style")
        if not isinstance(preview_style, dict):
            raise ProjectSchemaError(
                "Invalid field 'settings.preview_style': expected object."
            )
        mw.apply_preview_style_settings(preview_style, persist=True)

        theme = settings.get("theme")
        if not isinstance(theme, str):
            raise ProjectSchemaError("Invalid field 'settings.theme': expected string.")
        mw.apply_theme_id(theme, persist=True)

    @staticmethod
    def _restore_llm_ui(mw: Any, data: dict) -> None:
        llm_data = data.get("llm", {})
        model_panel = mw.chat_dock.model_panel

        if "model_path" in llm_data:
            model_panel.model_path.setText(llm_data["model_path"])
        if "model_backend" in llm_data:
            model_panel.set_model_backend(str(llm_data["model_backend"] or "auto"))
        if "nli_model_id" in llm_data:
            model_panel.nli_model_id.setText(llm_data["nli_model_id"])
        if "ctx_size" in llm_data:
            model_panel.ctx_spin.setValue(llm_data["ctx_size"])
        if "gpu_layers" in llm_data:
            model_panel.gpu_spin.setValue(llm_data["gpu_layers"])
        if "threads" in llm_data:
            model_panel.threads_spin.setValue(llm_data["threads"])
        if "trust_remote_code" in llm_data:
            model_panel.trust_remote_code_cb.setChecked(
                bool(llm_data["trust_remote_code"])
            )
        if "max_tokens" in llm_data:
            model_panel.max_tokens_spin.setValue(llm_data["max_tokens"])
        if "temperature" in llm_data:
            model_panel.temp_spin.setValue(llm_data["temperature"])
        if "top_p" in llm_data:
            model_panel.top_p_spin.setValue(llm_data["top_p"])
        if "repeat_penalty" in llm_data:
            model_panel.repeat_penalty_spin.setValue(llm_data["repeat_penalty"])
        if "forbidden_chars" in llm_data:
            model_panel.forbidden_chars_edit.setText(llm_data["forbidden_chars"])
        if "apply_selection_direct" in llm_data:
            mw.chat_dock.apply_selection_cb.setChecked(llm_data["apply_selection_direct"])

    @staticmethod
    def _restore_ui_state(mw: Any, data: dict) -> None:
        ui = data.get("ui", {})

        if "window_geometry" in ui:
            mw.restoreGeometry(QByteArray(base64.b64decode(ui["window_geometry"])))
        if "window_state" in ui:
            mw.restoreState(QByteArray(base64.b64decode(ui["window_state"])))

        if "user_mode" in ui:
            mw.set_user_mode(ui["user_mode"], notify=False)

        if "log_enabled" in ui:
            mw.app_logger.enabled = ui["log_enabled"]
            mw.log_dock._enabled_cb.setChecked(ui["log_enabled"])

        # Setting combos triggers _on_filter_changed -> _rebuild_from_history.
        if "log_level_filter" in ui:
            mw.log_dock._level_combo.setCurrentText(ui["log_level_filter"])
        if "log_cat_filter" in ui:
            mw.log_dock._cat_combo.setCurrentText(ui["log_cat_filter"])

        context_panel = mw.chat_dock.context_panel
        if "context_use_canvas" in ui:
            context_panel._use_canvas.setChecked(ui["context_use_canvas"])
        if "context_use_rag" in ui:
            context_panel._use_rag.setChecked(ui["context_use_rag"])
        for name, checked in ui.get("context_doc_checks", {}).items():
            checkbox = context_panel._cbs.get(name)
            if checkbox is not None:
                checkbox.setChecked(checked)
