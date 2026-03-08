from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt

from .entry import copy_runtime_state, is_pdf_path
from .models import PDFImportSettings
from .ui_constants import _STATUS_DONE, _STATUS_ERROR, _STATUS_PENDING
from .workers import (
    ConversionWorker,
    DetectWorker,
    FontAnalysisWorker,
    MarkdownLLMFixWorker,
    SingleConversionWorker,
)


class FileImportWorkersMixin:
    """Conversion, detect, analyze and batch worker orchestration."""

    def _llm_fix_label_prefix(self, path: str) -> str:
        entry = self._entries.get(str(path or ""))
        name = str(getattr(entry, "name", "") or "").strip()
        return f"LLM-Fix ({name})" if name else "LLM-Fix"

    def _set_llm_fix_status_for_path(
        self,
        path: str,
        text: str,
        *,
        tooltip: str = "",
        visible: bool = True,
    ):
        key = str(path or "").strip()
        if not key:
            return
        cache = getattr(self, "_llm_fix_status_by_path", None)
        if not isinstance(cache, dict):
            cache = {}
            setattr(self, "_llm_fix_status_by_path", cache)
        cache[key] = {
            "text": str(text or ""),
            "tooltip": str(tooltip or text or ""),
            "visible": bool(visible),
        }
        if str(getattr(self, "_current_path", "") or "").strip() != key:
            return
        self._preview_status.setText(str(text or ""))
        self._preview_status.setToolTip(str(tooltip or text or ""))
        self._preview_status.setVisible(bool(visible))

    def _sync_llm_fix_status_for_current_path(self):
        key = str(getattr(self, "_current_path", "") or "").strip()
        cache = getattr(self, "_llm_fix_status_by_path", None)
        state = cache.get(key) if isinstance(cache, dict) and key else None
        if isinstance(state, dict):
            text = str(state.get("text", "") or "")
            tooltip = str(state.get("tooltip", "") or text)
            visible = bool(state.get("visible", False))
            self._preview_status.setText(text)
            self._preview_status.setToolTip(tooltip)
            self._preview_status.setVisible(visible and bool(text.strip()))
            return
        current_text = str(self._preview_status.text() or "").strip()
        if current_text.startswith("LLM-Fix") or current_text.startswith("Fix by LLM"):
            self._preview_status.setText("")
            self._preview_status.setToolTip("")
            self._preview_status.setVisible(False)

    def _resolve_llm_manager(self) -> Any:
        parent = self.parent()
        while parent is not None:
            manager = getattr(parent, "llm_manager", None)
            if manager is not None:
                return manager
            parent_fn = getattr(parent, "parent", None)
            parent = parent_fn() if callable(parent_fn) else None
        return None

    def _refresh_llm_fix_button(self):
        btn = getattr(self, "_btn_llm_fix", None)
        if btn is None:
            return
        default_tip = (
            "Korrigiert Markdown-Struktur blockweise per LLM "
            "(Ueberschriften, Tabellen, Zeilenumbrueche, OCR-Formatfehler). "
            "Inhalte sollen unveraendert bleiben."
        )
        llm_worker = getattr(self, "_llm_fix_worker", None)
        if llm_worker is not None and llm_worker.isRunning():
            btn.setEnabled(False)
            btn.setToolTip("Fix by LLM laeuft bereits…")
            return

        path = str(getattr(self, "_current_path", "") or "")
        entry = self._entries.get(path) if path else None
        if entry is None or not str(entry.markdown or "").strip():
            btn.setEnabled(False)
            btn.setToolTip("Zuerst eine Datei konvertieren, damit Markdown vorhanden ist.")
            return

        manager = self._resolve_llm_manager()
        if manager is None:
            btn.setEnabled(False)
            btn.setToolTip("Kein LLM-Manager gefunden.")
            return
        if not bool(getattr(manager, "is_model_loaded", lambda: False)()):
            btn.setEnabled(False)
            btn.setToolTip("Bitte zuerst ein GGUF-Modell laden.")
            return
        running_fn = getattr(getattr(manager, "worker", None), "isRunning", None)
        if callable(running_fn) and bool(running_fn()):
            btn.setEnabled(False)
            btn.setToolTip("LLM ist aktuell beschaeftigt.")
            return

        btn.setEnabled(True)
        btn.setToolTip(default_tip)

    def _run_llm_fix_current_markdown(self):
        running = self._llm_fix_worker
        if running is not None and running.isRunning():
            return

        path = str(self._current_path or "")
        if not path:
            return
        entry = self._entries.get(path)
        if entry is None:
            return
        markdown = str(entry.markdown or "")
        if not markdown.strip():
            msg = f"{self._llm_fix_label_prefix(path)}: kein Markdown vorhanden."
            self._set_llm_fix_status_for_path(path, msg, tooltip=msg, visible=True)
            self._refresh_llm_fix_button()
            return

        manager = self._resolve_llm_manager()
        if manager is None or not bool(getattr(manager, "is_model_loaded", lambda: False)()):
            msg = f"{self._llm_fix_label_prefix(path)}: kein Modell geladen."
            self._set_llm_fix_status_for_path(path, msg, tooltip=msg, visible=True)
            self._refresh_llm_fix_button()
            return
        running_fn = getattr(getattr(manager, "worker", None), "isRunning", None)
        if callable(running_fn) and bool(running_fn()):
            msg = f"{self._llm_fix_label_prefix(path)}: LLM beschaeftigt."
            self._set_llm_fix_status_for_path(path, msg, tooltip=msg, visible=True)
            self._refresh_llm_fix_button()
            return

        start_msg = f"{self._llm_fix_label_prefix(path)}: startet…"
        self._set_llm_fix_status_for_path(path, start_msg, tooltip=start_msg, visible=True)
        self._llm_fix_path = path
        self._llm_fix_worker = MarkdownLLMFixWorker(manager, markdown, self)
        self._llm_fix_worker.progress.connect(self._on_llm_fix_progress)
        self._llm_fix_worker.done.connect(self._on_llm_fix_done)
        self._refresh_llm_fix_button()
        self._llm_fix_worker.start()

    def _on_llm_fix_progress(self, done: int, total: int, info: str):
        total_safe = max(1, int(total))
        done_safe = max(0, min(int(done), total_safe))
        path = str(getattr(self, "_llm_fix_path", "") or "")
        text = f"{self._llm_fix_label_prefix(path)}: {done_safe}/{total_safe}"
        detail = str(info or "").strip()
        self._set_llm_fix_status_for_path(
            path,
            text,
            tooltip=f"{text} ({detail})" if detail else text,
            visible=True,
        )

    def _on_llm_fix_done(self, markdown: str, meta: object):
        self._llm_fix_worker = None
        path = str(getattr(self, "_llm_fix_path", "") or "")
        self._llm_fix_path = None
        entry = self._entries.get(path) if path else None
        fixed = str(markdown or "")
        if entry is not None and fixed:
            entry.markdown = fixed
            if entry.status != _STATUS_ERROR:
                entry.status = _STATUS_DONE
                self._update_list_item(path, _STATUS_DONE)
            if self._current_path == path:
                self._preview.set_markdown_text(fixed)
                if entry.is_pdf():
                    self._pdf_viewer.update_markdown(fixed)

        meta_map = meta if isinstance(meta, dict) else {}
        chunks = int(meta_map.get("chunks", 0) or 0)
        processed = int(meta_map.get("processed_chunks", 0) or 0)
        changed = int(meta_map.get("changed_chunks", 0) or 0)
        unchanged = int(meta_map.get("unchanged_chunks", 0) or 0)
        rejected = int(meta_map.get("rejected_chunks", 0) or 0)
        errors = int(meta_map.get("error_chunks", 0) or 0)
        skipped = int(meta_map.get("skipped_chunks", 0) or 0)
        stopped = bool(meta_map.get("stopped", False))
        reason = str(meta_map.get("reason", "") or "")

        if stopped:
            message = f"{self._llm_fix_label_prefix(path)}: gestoppt."
            detail_message = (
                f"Fix by LLM gestoppt: {processed}/{chunks} bearbeitet, "
                f"{skipped} uebersprungen."
            )
        elif chunks > 0:
            message = f"{self._llm_fix_label_prefix(path)}: {changed}/{chunks} geaendert."
            detail_message = (
                f"Fix by LLM fertig: {changed}/{chunks} Bloecke geaendert, "
                f"{unchanged} unveraendert, {rejected} verworfen, {errors} Fehler."
            )
        elif reason:
            message = f"{self._llm_fix_label_prefix(path)}: {reason}"
            detail_message = f"Fix by LLM: {reason}"
        else:
            message = f"{self._llm_fix_label_prefix(path)}: beendet."
            detail_message = message
        self._set_llm_fix_status_for_path(
            path,
            message,
            tooltip=detail_message,
            visible=True,
        )
        self._btn_open.setEnabled(self._has_converted())
        self._refresh_llm_fix_button()

    def _run_preview(self):
        if not self._current_path or (self._preview_worker and self._preview_worker.isRunning()):
            return
        settings = self._pdf_panel.get_settings()
        entry = self._entries.get(self._current_path)
        if entry is None:
            return
        copy_runtime_state(entry.pdf_settings, settings, keep_detection=True)
        entry.pdf_settings = settings
        self._pdf_viewer.refresh_settings(settings, entry.body_size)
        self._preview_status.setText("Converting…")
        self._preview_status.setVisible(True)
        self._pdf_panel.widget().setEnabled(False)
        self._preview_worker = SingleConversionWorker(self._current_path, settings, self)
        self._preview_worker.done.connect(self._on_preview_done)
        self._preview_worker.start()

    def _on_preview_done(self, markdown: str, error: str):
        self._preview_status.setVisible(False)
        is_pdf = self._current_path is not None and is_pdf_path(self._current_path)
        self._pdf_panel.set_enabled_for_pdf(is_pdf)

        if error:
            self._preview.set_markdown_text(
                f"# Conversion Error\n\n```\n{error}\n```\n"
            )
            self._tabs.setCurrentIndex(1)
            self._refresh_llm_fix_button()
            return

        self._preview.set_markdown_text(markdown)
        self._tabs.setCurrentIndex(1)
        if self._current_path and self._current_path in self._entries:
            entry = self._entries[self._current_path]
            entry.markdown = markdown
            entry.status = _STATUS_DONE
            self._update_list_item(self._current_path, _STATUS_DONE)
            self._btn_open.setEnabled(True)
            settings = entry.pdf_settings
            if settings.detected_info:
                self._pdf_panel.set_detect_info(settings.detected_info)
            if is_pdf:
                self._pdf_viewer.update_markdown(markdown)
        feedback_bar = getattr(self, "_feedback_bar", None)
        if feedback_bar is not None:
            feedback_bar.activate("file_import")
        self._refresh_llm_fix_button()

    def _run_detect(self):
        if not self._current_path or (self._detect_worker and self._detect_worker.isRunning()):
            return
        settings = self._pdf_panel.get_settings()
        entry = self._entries.get(self._current_path)
        if entry is None:
            return
        if not settings.auto_hf_detect:
            self._pdf_panel.set_detect_info("Manual mode active. Switch to Auto-Detect mode first.")
            return
        copy_runtime_state(entry.pdf_settings, settings, keep_detection=False)
        entry.pdf_settings = settings
        self._pdf_panel.set_detect_info("Analysing PDF, please wait…")
        self._btn_add.setEnabled(False)
        self._detect_worker = DetectWorker(self._current_path, settings, self)
        self._detect_worker.done.connect(self._on_detect_done)
        self._detect_worker.start()

    def _on_detect_done(self, result: dict):
        self._btn_add.setEnabled(True)
        top = float(result.get("top_margin", 0.0))
        bottom = float(result.get("bottom_margin", 0.0))
        info = str(result.get("info", ""))
        top_by_page = {int(k): float(v) for k, v in dict(result.get("top_by_page", {})).items()}
        bottom_by_page = {int(k): float(v) for k, v in dict(result.get("bottom_by_page", {})).items()}
        rects_by_page: dict[int, dict[str, list[tuple[float, float, float, float]]]] = {}
        for k, value in dict(result.get("hf_rects_by_page", {})).items():
            page_index = int(k)
            item = value or {}
            rects_by_page[page_index] = {
                "header": [tuple(rect) for rect in item.get("header", [])],
                "footer": [tuple(rect) for rect in item.get("footer", [])],
            }

        self._pdf_panel.set_detect_info(info)
        if self._current_path and self._current_path in self._entries:
            settings = self._entries[self._current_path].pdf_settings
            settings.detected_top = top
            settings.detected_bottom = bottom
            settings.detected_info = info
            settings.detected_top_by_page = top_by_page
            settings.detected_bottom_by_page = bottom_by_page
            settings.detected_hf_rects_by_page = rects_by_page

        if self._current_path and self._current_path in self._entries:
            entry = self._entries[self._current_path]
            self._pdf_viewer.refresh_settings(
                entry.pdf_settings,
                entry.body_size,
            )

    def _run_font_analysis(self):
        if not self._current_path or (self._font_worker and self._font_worker.isRunning()):
            return
        settings = self._pdf_panel.get_settings()
        entry = self._entries.get(self._current_path)
        if entry is None:
            return
        copy_runtime_state(entry.pdf_settings, settings, keep_detection=True)
        self._pdf_panel.set_font_info({"info": "Analysing font sizes, please wait…"})
        self._btn_add.setEnabled(False)
        self._font_worker = FontAnalysisWorker(self._current_path, settings, self)
        self._font_worker.done.connect(self._on_font_analysis_done)
        self._font_worker.start()

    def _on_font_analysis_done(self, result: dict):
        self._btn_add.setEnabled(True)
        self._pdf_panel.set_font_info(result)
        if self._current_path and self._current_path in self._entries:
            body_size = result.get("body_size", 0.0)
            entry = self._entries[self._current_path]
            entry.pdf_settings.font_info = result.get("info", "")
            entry.body_size = body_size
            self._pdf_viewer.update_body_size(body_size, entry.pdf_settings)

    def _start_import(self):
        if self._worker and self._worker.isRunning():
            return
        if self._current_path:
            self._save_panel_settings(self._current_path)
        paths = list(self._entries.keys())
        if not paths:
            return
        settings_map = {path: self._entries[path].pdf_settings for path in paths}
        self._progress.setVisible(True)
        self._progress.setMaximum(len(paths))
        self._progress.setValue(0)
        self._progress_lbl.setText(f"0 / {len(paths)} converted")
        self._btn_import.setEnabled(False)
        self._btn_add.setEnabled(False)
        manager = self._resolve_llm_manager()
        model_loaded = bool(
            manager is not None
            and bool(getattr(manager, "is_model_loaded", lambda: False)())
        )
        backend = "thread" if model_loaded else "process"
        if model_loaded:
            self._preview_status.setText(
                "Import: Kompatibilitaetsmodus aktiv (Thread-Pool, Modell geladen)."
            )
            self._preview_status.setVisible(True)
        self._worker = ConversionWorker(
            paths,
            settings_map,
            self,
            parallel_backend=backend,
        )
        self._worker.file_done.connect(self._on_file_done)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()
        self._refresh_llm_fix_button()

    def _on_file_done(
        self,
        index: int,
        name: str,
        path: str,
        markdown: str,
        error: str,
        used_settings: object,
    ):
        del index
        done_before = sum(1 for entry in self._entries.values() if entry.status != _STATUS_PENDING)
        entry = self._entries.get(path)
        if entry is None:
            return
        if isinstance(used_settings, PDFImportSettings):
            copy_runtime_state(
                used_settings,
                entry.pdf_settings,
                keep_detection=True,
            )
        if error:
            entry.markdown = f"# {name}\n\n*Error: {error}*\n"
            entry.error = error
            entry.status = _STATUS_ERROR
        else:
            entry.markdown = markdown
            entry.status = _STATUS_DONE
        self._update_list_item(path, entry.status)
        if self._current_path == path and entry.is_pdf():
            settings = entry.pdf_settings
            self._pdf_panel.set_settings(settings)
            self._pdf_viewer.refresh_settings(
                settings,
                float(entry.body_size or 0.0),
                entry.markdown,
            )
        if done_before == 0:
            for i in range(self._list.count()):
                if self._list.item(i).data(Qt.ItemDataRole.UserRole) == path:
                    self._list.setCurrentItem(self._list.item(i))
                    break
        done = sum(1 for entry in self._entries.values() if entry.status != _STATUS_PENDING)
        total = len(self._entries)
        self._progress.setValue(done)
        self._progress_lbl.setText(f"{done} / {total} converted")
        self._refresh_llm_fix_button()

    def _on_all_done(self):
        self._btn_import.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._btn_open.setEnabled(self._has_converted())
        self._refresh_llm_fix_button()
