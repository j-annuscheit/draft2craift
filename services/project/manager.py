"""
Project Manager
===============
Saves and loads the complete draft2craift application state to/from a project folder.

Project folder structure
------------------------
<folder>/
  project.json       — manifest (version, config, UI state, rag results)
  canvas/
    doc_0000.md      — one file per canvas tab
    …
  knowledge/
    doc_0000.md      — one file per imported document (Markdown)
    …
  rag/
    index.pkl        — TF-IDF index + all chunk caches (pickle)
    embeddings.pt    — ST embeddings (torch.save, optional)
  chat/
    history.json     — chat tabs + history payload
  logs/
    entries.json     — debug log entries [{ts, level, category, message}, …]
"""
from __future__ import annotations

import base64
import dataclasses
import json
import pickle
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QMessageBox

from services.rag.system import RAGConfig


class ProjectManager:
    """
    Stateless helper that serialises / deserialises the full draft2craift state.

    Both methods accept *mw* (a ``MainWindow`` instance) duck-typed as ``Any``
    to avoid circular imports.
    """

    # ── Save ──────────────────────────────────────────────────────────────────

    def save_project(self, mw: Any, folder: str) -> bool:
        """
        Write all application state into *folder*.

        Returns ``True`` on success, ``False`` on error (error already shown
        via QMessageBox).
        """
        try:
            base = Path(folder)
            (base / "canvas").mkdir(parents=True, exist_ok=True)
            (base / "knowledge").mkdir(exist_ok=True)
            (base / "rag").mkdir(exist_ok=True)
            (base / "chat").mkdir(exist_ok=True)
            (base / "logs").mkdir(exist_ok=True)

            # ── Draft tabs ────────────────────────────────────────────────────
            tw = mw.canvas.tabs.tab_widget
            canvas_tabs_data: list[dict] = []
            written_canvas_files: set[str] = set()
            for i in range(tw.count()):
                panel = tw.widget(i)
                editor = getattr(panel, "editor", None)
                if editor is None:
                    continue
                canvas_file = f"doc_{i:04d}.md"
                (base / "canvas" / canvas_file).write_text(
                    editor.toPlainText(), encoding="utf-8"
                )
                written_canvas_files.add(canvas_file)
                canvas_tabs_data.append({
                    "title":       tw.tabText(i),
                    "file_path":   str(getattr(panel, "file_path", "") or ""),
                    "canvas_file": canvas_file,
                    "read_only":   editor.isReadOnly(),
                })
            for stale_path in (base / "canvas").glob("doc_*.md"):
                if stale_path.name in written_canvas_files:
                    continue
                try:
                    stale_path.unlink()
                except Exception:
                    continue

            # ── Knowledge files ───────────────────────────────────────────────
            knowledge_map: dict[str, tuple[str, str]] = {}
            knowledge_order: list[str] = []

            def merge_knowledge_item(
                display_name: object,
                orig_path: object,
                markdown: object,
            ):
                name = str(display_name or "").strip()
                if not name:
                    return
                src_path = str(orig_path or "").strip()
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

            registry = getattr(mw, "_file_registry", {})
            if isinstance(registry, dict):
                for display_name, entry in registry.items():
                    if (
                        isinstance(entry, tuple)
                        and len(entry) >= 2
                    ):
                        merge_knowledge_item(
                            display_name,
                            entry[0],
                            entry[1],
                        )

            imported_entries = getattr(
                getattr(mw, "knowledge_dock", None),
                "imported_files",
                None,
            )
            imported_map = getattr(imported_entries, "_entries", {})
            if isinstance(imported_map, dict):
                for display_name, markdown in imported_map.items():
                    merge_knowledge_item(display_name, "", markdown)

            ctx_panel = getattr(getattr(mw, "chat_dock", None), "context_panel", None)
            ctx_docs = getattr(ctx_panel, "_docs", {})
            if isinstance(ctx_docs, dict):
                for display_name, markdown in ctx_docs.items():
                    merge_knowledge_item(display_name, "", markdown)

            knowledge_files_data: list[dict] = []
            written_knowledge_files: set[str] = set()
            for idx, display_name in enumerate(knowledge_order):
                orig_path, markdown = knowledge_map.get(display_name, ("", ""))
                knowledge_file = f"doc_{idx:04d}.md"
                (base / "knowledge" / knowledge_file).write_text(
                    markdown, encoding="utf-8"
                )
                written_knowledge_files.add(knowledge_file)
                knowledge_files_data.append({
                    "display_name":  display_name,
                    "original_path": orig_path,
                    "knowledge_file": knowledge_file,
                })
            for stale_path in (base / "knowledge").glob("doc_*.md"):
                if stale_path.name in written_knowledge_files:
                    continue
                try:
                    stale_path.unlink()
                except Exception:
                    continue

            # ── RAG index (pickle) ────────────────────────────────────────────
            rag_state = mw.rag_system.dump_state()
            with open(base / "rag" / "index.pkl", "wb") as fh:
                pickle.dump(rag_state, fh, protocol=pickle.HIGHEST_PROTOCOL)

            # ── ST embeddings (optional, torch) ───────────────────────────────
            if rag_state["has_st_embeddings"]:
                try:
                    import torch  # type: ignore
                    torch.save(
                        mw.rag_system._st_embeddings,
                        str(base / "rag" / "embeddings.pt"),
                    )
                except Exception:
                    pass  # embeddings are optional

            # ── Chat history (all tabs) ─────────────────────────────────────
            history_widget = mw.chat_dock.history
            if hasattr(history_widget, "export_sessions"):
                history = history_widget.export_sessions()
            else:
                history = [
                    {"role": r, "content": c}
                    for r, c in history_widget.get_history()
                ]
            with open(base / "chat" / "history.json", "w", encoding="utf-8") as fh:
                json.dump(history, fh, ensure_ascii=False, indent=2)

            # ── Log entries ───────────────────────────────────────────────────
            log_entries = [
                {"ts": ts, "level": level, "category": cat, "message": msg}
                for ts, level, cat, msg in mw.app_logger.get_entries()
            ]
            with open(base / "logs" / "entries.json", "w", encoding="utf-8") as fh:
                json.dump(log_entries, fh, ensure_ascii=False, indent=2)

            # ── RAG results tabs ──────────────────────────────────────────────
            rag_tabs = mw.knowledge_dock.rag_panel.tabs.tab_widget
            rag_tabs_wrap = mw.knowledge_dock.rag_panel.tabs
            rag_results: list[dict] = []
            for i in range(rag_tabs.count()):
                panel = rag_tabs.widget(i)
                editor = getattr(panel, "editor", None)
                if editor is not None:
                    title = (
                        rag_tabs_wrap.get_tab_full_title(i)
                        if hasattr(rag_tabs_wrap, "get_tab_full_title")
                        else rag_tabs.tabText(i)
                    )
                    rag_results.append({
                        "title":   title,
                        "content": editor.toPlainText(),
                    })

            # ── UI state ──────────────────────────────────────────────────────
            ctx_panel = mw.chat_dock.context_panel
            use_canvas, use_rag, _ = ctx_panel.get_selection()
            doc_checks = {
                name: cb.isChecked()
                for name, cb in ctx_panel._cbs.items()
            }

            model_panel = mw.chat_dock.model_panel
            llm_data = {
                "model_path":   model_panel.model_path.text(),
                "ctx_size":     model_panel.ctx_spin.value(),
                "gpu_layers":   model_panel.gpu_spin.value(),
                "threads":      model_panel.threads_spin.value(),
                "max_tokens":   model_panel.max_tokens_spin.value(),
                "temperature":  model_panel.temp_spin.value(),
                "top_p":        model_panel.top_p_spin.value(),
                "repeat_penalty": model_panel.repeat_penalty_spin.value(),
                "forbidden_chars": model_panel.forbidden_chars_edit.text(),
                "apply_selection_direct": mw.chat_dock.apply_selection_cb.isChecked(),
            }

            geom_b64  = base64.b64encode(mw.saveGeometry().data()).decode()
            state_b64 = base64.b64encode(mw.saveState().data()).decode()

            manifest = {
                "version": 1,
                "rag_config": dataclasses.asdict(mw.rag_system.config),
                "settings": {
                    "prompts": mw.llm_manager.get_prompt_set(),
                    "speech": (
                        mw.get_speech_settings()
                        if hasattr(mw, "get_speech_settings")
                        else {}
                    ),
                    "preview_page_margin": (
                        mw.get_preview_page_margin_settings()
                        if hasattr(mw, "get_preview_page_margin_settings")
                        else {}
                    ),
                    "theme": (
                        mw.get_theme_id()
                        if hasattr(mw, "get_theme_id")
                        else "dark"
                    ),
                },
                "llm": llm_data,
                "canvas": {
                    "current_tab": tw.currentIndex(),
                    "tabs": canvas_tabs_data,
                },
                "knowledge": {
                    "files": knowledge_files_data,
                },
                "rag_results":      rag_results,
                "rag_debug_history": mw.knowledge_dock.rag_panel.get_debug_history(),
                "rag_search_query": mw.knowledge_dock.rag_panel.search_input.text(),
                "ui": {
                    "window_geometry":    geom_b64,
                    "window_state":       state_b64,
                    "user_mode":          getattr(mw, "user_mode", "plus"),
                    "log_enabled":        mw.app_logger.enabled,
                    "log_level_filter":   mw.log_dock._level_filter,
                    "log_cat_filter":     mw.log_dock._cat_filter,
                    "context_use_canvas": use_canvas,
                    "context_use_rag":    use_rag,
                    "context_doc_checks": doc_checks,
                },
            }

            with open(base / "project.json", "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2)

            return True

        except Exception as exc:
            QMessageBox.warning(
                None, "Save Project Failed",
                f"Could not save project:\n{exc}",
            )
            return False

    # ── Load ──────────────────────────────────────────────────────────────────

    def load_project(self, mw: Any, folder: str) -> bool:
        """
        Restore all application state from *folder*.

        Returns ``True`` on success, ``False`` on error (error already shown
        via QMessageBox).
        """
        try:
            base = Path(folder)
            manifest_path = base / "project.json"

            if not manifest_path.exists():
                QMessageBox.warning(
                    None, "Load Project",
                    f"No project.json found in:\n{folder}",
                )
                return False

            with open(manifest_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            if data.get("version") != 1:
                QMessageBox.warning(
                    None, "Load Project",
                    "Unknown project format version — cannot load.",
                )
                return False

            # 1. RAGConfig ─────────────────────────────────────────────────────
            rag_cfg_data = data.get("rag_config", {})
            try:
                mw.rag_system.config = RAGConfig(**rag_cfg_data)
            except Exception:
                pass  # keep current defaults on field mismatch

            # 2. Knowledge files ───────────────────────────────────────────────
            # Block the auto-reindex signal while we restore files so the
            # RAGWorker is not triggered; we restore the index from pickle below.
            mw._file_registry.clear()
            mw.knowledge_dock.imported_files.blockSignals(True)
            mw.knowledge_dock.imported_files.clear_all()
            mw.chat_dock.context_panel.clear_docs()
            viewer_tabs = mw.knowledge_dock.doc_viewer.tabs.tab_widget
            while viewer_tabs.count() > 0:
                viewer_tabs.removeTab(0)

            for file_data in data.get("knowledge", {}).get("files", []):
                display_name   = file_data["display_name"]
                orig_path      = file_data.get("original_path", "")
                knowledge_file = file_data["knowledge_file"]
                knowledge_path = base / "knowledge" / knowledge_file
                try:
                    markdown = knowledge_path.read_text(encoding="utf-8")
                except Exception:
                    markdown = str(file_data.get("markdown", "") or "")
                if not isinstance(markdown, str):
                    markdown = str(markdown or "")
                mw._file_registry[display_name] = (orig_path, markdown)
                mw.knowledge_dock.imported_files.add_file(display_name, markdown)
                mw.chat_dock.context_panel.add_document(display_name, markdown)
                mw.knowledge_dock.open_content(
                    display_name,
                    markdown,
                    doc_key=display_name,
                )

            mw.knowledge_dock.imported_files.blockSignals(False)
            if viewer_tabs.count() == 0:
                mw.knowledge_dock.doc_viewer.tabs.add_tab()
            mw._update_loaded_menu()

            # 3. RAG index from pickle ─────────────────────────────────────────
            rag_index_path = base / "rag" / "index.pkl"
            if rag_index_path.exists():
                try:
                    with open(rag_index_path, "rb") as fh:
                        rag_state = pickle.load(fh)
                    mw.rag_system.load_state(rag_state)
                except Exception as exc:
                    QMessageBox.warning(
                        None, "Load Project",
                        f"RAG index could not be restored:\n{exc}\n\n"
                        "The knowledge base will be empty.",
                    )

            # 4. ST embeddings (optional) ──────────────────────────────────────
            embeddings_path = base / "rag" / "embeddings.pt"
            if embeddings_path.exists():
                try:
                    import torch  # type: ignore
                    embeddings = torch.load(
                        str(embeddings_path), map_location="cpu"
                    )
                    with mw.rag_system._lock:
                        mw.rag_system._st_embeddings = embeddings
                except Exception:
                    pass  # embeddings are optional

            # 5. Draft tabs ────────────────────────────────────────────────────
            tw = mw.canvas.tabs.tab_widget
            while tw.count() > 0:
                tw.removeTab(0)

            canvas_data = data.get("canvas", {})
            referenced_canvas_files: set[str] = set()
            for tab_data in canvas_data.get("tabs", []):
                canvas_file = tab_data.get("canvas_file", "")
                if canvas_file:
                    referenced_canvas_files.add(str(canvas_file))
                try:
                    content = (base / "canvas" / canvas_file).read_text(
                        encoding="utf-8"
                    ) if canvas_file else ""
                except Exception:
                    content = ""
                mw.canvas.tabs.add_tab(
                    title=tab_data.get("title", "Draft"),
                    content=content,
                    file_path=tab_data.get("file_path", ""),
                    read_only=tab_data.get("read_only", False),
                )

            recovered_tabs = 0
            canvas_dir = base / "canvas"
            if canvas_dir.exists():
                for orphan in sorted(canvas_dir.glob("doc_*.md")):
                    if orphan.name in referenced_canvas_files:
                        continue
                    try:
                        content = orphan.read_text(encoding="utf-8")
                    except Exception:
                        continue
                    if not str(content or "").strip():
                        continue
                    mw.canvas.tabs.add_tab(
                        title=f"Wiederhergestellt {orphan.stem}",
                        content=content,
                        file_path="",
                        read_only=False,
                    )
                    recovered_tabs += 1

            if tw.count() == 0:
                mw.canvas.tabs.add_tab()
            else:
                current = canvas_data.get("current_tab", 0)
                if 0 <= current < tw.count():
                    tw.setCurrentIndex(current)
            if recovered_tabs > 0:
                try:
                    sb = mw.statusBar()
                    if sb is not None:
                        sb.showMessage(
                            f"Zusätzliche Draft-Tabs wiederhergestellt: {recovered_tabs}",
                            6000,
                        )
                except Exception:
                    pass

            # 6. Chat history (all tabs, backward-compatible) ────────────────
            chat_path = base / "chat" / "history.json"
            if chat_path.exists():
                try:
                    with open(chat_path, "r", encoding="utf-8") as fh:
                        chat_history = json.load(fh)
                    history_widget = mw.chat_dock.history
                    if hasattr(history_widget, "import_sessions"):
                        history_widget.import_sessions(chat_history)
                    else:
                        history_widget.clear_history()
                        if isinstance(chat_history, list):
                            for entry in chat_history:
                                if not isinstance(entry, dict):
                                    continue
                                history_widget.add_message(
                                    entry.get("role", ""),
                                    entry.get("content", ""),
                                )
                except Exception:
                    pass

            # 7. Log entries ───────────────────────────────────────────────────
            log_path = base / "logs" / "entries.json"
            if log_path.exists():
                try:
                    with open(log_path, "r", encoding="utf-8") as fh:
                        log_entries = json.load(fh)
                    mw.app_logger.clear()
                    for entry in log_entries:
                        mw.app_logger._entries.append((
                            entry["ts"],
                            entry["level"],
                            entry["category"],
                            entry["message"],
                        ))
                    mw.log_dock._rebuild_from_history()
                except Exception:
                    pass

            # 8. RAG results tabs ──────────────────────────────────────────────
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

            mw.knowledge_dock.rag_panel.set_debug_history(
                data.get("rag_debug_history", [])
            )

            search_q = data.get("rag_search_query", "")
            if search_q:
                mw.knowledge_dock.rag_panel.search_input.setText(search_q)

            # 9. Prompt settings ──────────────────────────────────────────────
            settings = data.get("settings", {})
            if isinstance(settings, dict):
                prompts = settings.get("prompts", {})
                if isinstance(prompts, dict):
                    mw.llm_manager.set_prompt_set(prompts)
                speech = settings.get("speech", {})
                if hasattr(mw, "apply_speech_settings"):
                    mw.apply_speech_settings(speech)
                preview_page_margin = settings.get("preview_page_margin", {})
                if hasattr(mw, "apply_preview_page_margin_settings"):
                    mw.apply_preview_page_margin_settings(preview_page_margin)
                theme = settings.get("theme", "dark")
                if hasattr(mw, "apply_theme_id"):
                    mw.apply_theme_id(theme, persist=True)

            # 10. LLM UI fields (model is NOT reloaded automatically) ──────────
            llm_data = data.get("llm", {})
            model_panel = mw.chat_dock.model_panel
            if "model_path" in llm_data:
                model_panel.model_path.setText(llm_data["model_path"])
            if "ctx_size" in llm_data:
                model_panel.ctx_spin.setValue(llm_data["ctx_size"])
            if "gpu_layers" in llm_data:
                model_panel.gpu_spin.setValue(llm_data["gpu_layers"])
            if "threads" in llm_data:
                model_panel.threads_spin.setValue(llm_data["threads"])
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
            # Backward compatibility (projects saved before dedicated settings.prompts).
            if (
                "settings" not in data
                and "system_prompts" in llm_data
                and isinstance(llm_data["system_prompts"], dict)
            ):
                mw.llm_manager.set_prompt_set(llm_data["system_prompts"])
            elif "settings" not in data and "system_prompt" in llm_data:
                mw.llm_manager.set_system_prompt(llm_data["system_prompt"])

            # 11. UI state ─────────────────────────────────────────────────────
            ui = data.get("ui", {})

            if "window_geometry" in ui:
                mw.restoreGeometry(
                    QByteArray(base64.b64decode(ui["window_geometry"]))
                )
            if "window_state" in ui:
                mw.restoreState(
                    QByteArray(base64.b64decode(ui["window_state"]))
                )

            if "user_mode" in ui and hasattr(mw, "set_user_mode"):
                mw.set_user_mode(ui["user_mode"], notify=False)

            if "log_enabled" in ui:
                mw.app_logger.enabled = ui["log_enabled"]
                mw.log_dock._enabled_cb.setChecked(ui["log_enabled"])

            # Setting the combos triggers _on_filter_changed → _rebuild_from_history
            if "log_level_filter" in ui:
                mw.log_dock._level_combo.setCurrentText(ui["log_level_filter"])
            if "log_cat_filter" in ui:
                mw.log_dock._cat_combo.setCurrentText(ui["log_cat_filter"])

            ctx_panel = mw.chat_dock.context_panel
            if "context_use_canvas" in ui:
                ctx_panel._use_canvas.setChecked(ui["context_use_canvas"])
            if "context_use_rag" in ui:
                ctx_panel._use_rag.setChecked(ui["context_use_rag"])
            for name, checked in ui.get("context_doc_checks", {}).items():
                cb = ctx_panel._cbs.get(name)
                if cb is not None:
                    cb.setChecked(checked)

            return True

        except Exception as exc:
            QMessageBox.warning(
                None, "Load Project Failed",
                f"Could not load project:\n{exc}",
            )
            return False
