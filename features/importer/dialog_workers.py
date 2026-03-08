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

    def _has_running_background_worker(self) -> bool:
        if bool(getattr(self, "_llm_fix_batch_active", False)):
            return True
        workers = (
            getattr(self, "_worker", None),
            getattr(self, "_preview_worker", None),
            getattr(self, "_detect_worker", None),
            getattr(self, "_font_worker", None),
            getattr(self, "_llm_fix_worker", None),
        )
        for worker in workers:
            if worker is None:
                continue
            is_running = getattr(worker, "isRunning", None)
            if callable(is_running) and bool(is_running()):
                return True
        return False

    def _update_open_button_state(self):
        btn = getattr(self, "_btn_open", None)
        if btn is None:
            return
        busy = self._has_running_background_worker()
        can_open = self._has_converted() and not busy
        btn.setEnabled(bool(can_open))
        if busy:
            btn.setToolTip("Bitte warten: Import/Analyse laeuft noch.")
        elif self._has_converted():
            btn.setToolTip("Konvertierte Dateien importieren und Dialog schliessen")
        else:
            btn.setToolTip("Noch keine konvertierten Dateien vorhanden")

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

    def _ordered_entry_paths(self) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        file_list = getattr(self, "_list", None)
        if file_list is not None:
            for idx in range(file_list.count()):
                item = file_list.item(idx)
                path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
                if not path or path in seen or path not in self._entries:
                    continue
                ordered.append(path)
                seen.add(path)
        for path in self._entries.keys():
            key = str(path or "").strip()
            if not key or key in seen:
                continue
            ordered.append(key)
            seen.add(key)
        return ordered

    def _llm_fix_candidate_paths(self) -> list[str]:
        candidates: list[str] = []
        for path in self._ordered_entry_paths():
            entry = self._entries.get(path)
            if entry is None:
                continue
            if str(entry.markdown or "").strip():
                candidates.append(path)
        return candidates

    def _finish_llm_fix_batch(self):
        self._llm_fix_batch_active = False
        self._llm_fix_queue = []
        self._llm_fix_total = 0
        self._llm_fix_done_count = 0
        self._update_open_button_state()
        self._refresh_llm_fix_button()

    def _start_next_llm_fix_job(self, manager: Any):
        running = getattr(self, "_llm_fix_worker", None)
        if running is not None and running.isRunning():
            return

        queue = getattr(self, "_llm_fix_queue", None)
        if not isinstance(queue, list):
            queue = []
            self._llm_fix_queue = queue

        while queue:
            path = str(queue.pop(0) or "").strip()
            entry = self._entries.get(path)
            markdown = str(getattr(entry, "markdown", "") or "")
            if entry is None or not markdown.strip():
                self._llm_fix_done_count = int(self._llm_fix_done_count) + 1
                continue

            running_fn = getattr(getattr(manager, "worker", None), "isRunning", None)
            if callable(running_fn) and bool(running_fn()):
                msg = f"{self._llm_fix_label_prefix(path)}: LLM beschaeftigt."
                self._set_llm_fix_status_for_path(path, msg, tooltip=msg, visible=True)
                self._finish_llm_fix_batch()
                return

            file_total = max(1, int(getattr(self, "_llm_fix_total", 1) or 1))
            file_idx = max(1, min(file_total, int(self._llm_fix_done_count) + 1))
            start_msg = (
                f"{self._llm_fix_label_prefix(path)}: "
                f"Datei {file_idx}/{file_total} startet…"
            )
            self._set_llm_fix_status_for_path(
                path,
                start_msg,
                tooltip=start_msg,
                visible=True,
            )
            self._llm_fix_path = path
            self._llm_fix_worker = MarkdownLLMFixWorker(manager, markdown, self)
            self._llm_fix_worker.progress.connect(self._on_llm_fix_progress)
            self._llm_fix_worker.done.connect(self._on_llm_fix_done)
            self._update_open_button_state()
            self._refresh_llm_fix_button()
            self._llm_fix_worker.start()
            return

        total_files = int(getattr(self, "_llm_fix_total", 0) or 0)
        done_files = min(total_files, int(getattr(self, "_llm_fix_done_count", 0) or 0))
        current = str(getattr(self, "_current_path", "") or "").strip()
        if current and total_files > 0:
            summary = f"LLM-Fix: Batch fertig ({done_files}/{total_files} Dateien)."
            self._set_llm_fix_status_for_path(
                current,
                summary,
                tooltip=summary,
                visible=True,
            )
        self._finish_llm_fix_batch()

    def _refresh_llm_fix_button(self):
        btn = getattr(self, "_btn_llm_fix", None)
        if btn is None:
            return
        default_tip = (
            "Korrigiert die Markdown-Struktur fuer alle geladenen Dateien nacheinander "
            "(Ueberschriften, Tabellen, Zeilenumbrueche, OCR-Formatfehler). "
            "Inhalte sollen unveraendert bleiben."
        )
        if bool(getattr(self, "_llm_fix_batch_active", False)):
            btn.setEnabled(False)
            btn.setToolTip("Fix by LLM laeuft bereits…")
            return
        llm_worker = getattr(self, "_llm_fix_worker", None)
        if llm_worker is not None and llm_worker.isRunning():
            btn.setEnabled(False)
            btn.setToolTip("Fix by LLM laeuft bereits…")
            return

        if not self._llm_fix_candidate_paths():
            btn.setEnabled(False)
            btn.setToolTip("Zuerst Dateien konvertieren, damit Markdown vorhanden ist.")
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
        if bool(getattr(self, "_llm_fix_batch_active", False)):
            return
        running = self._llm_fix_worker
        if running is not None and running.isRunning():
            return

        candidates = self._llm_fix_candidate_paths()
        if not candidates:
            path = str(getattr(self, "_current_path", "") or "").strip()
            if not path and self._entries:
                path = next(iter(self._entries.keys()))
            msg = f"{self._llm_fix_label_prefix(path)}: kein Markdown vorhanden."
            self._set_llm_fix_status_for_path(path, msg, tooltip=msg, visible=True)
            self._refresh_llm_fix_button()
            return

        manager = self._resolve_llm_manager()
        if manager is None or not bool(getattr(manager, "is_model_loaded", lambda: False)()):
            path = str(getattr(self, "_current_path", "") or "").strip() or candidates[0]
            msg = f"{self._llm_fix_label_prefix(path)}: kein Modell geladen."
            self._set_llm_fix_status_for_path(path, msg, tooltip=msg, visible=True)
            self._refresh_llm_fix_button()
            return
        running_fn = getattr(getattr(manager, "worker", None), "isRunning", None)
        if callable(running_fn) and bool(running_fn()):
            path = str(getattr(self, "_current_path", "") or "").strip() or candidates[0]
            msg = f"{self._llm_fix_label_prefix(path)}: LLM beschaeftigt."
            self._set_llm_fix_status_for_path(path, msg, tooltip=msg, visible=True)
            self._refresh_llm_fix_button()
            return

        self._llm_fix_queue = list(candidates)
        self._llm_fix_total = len(candidates)
        self._llm_fix_done_count = 0
        self._llm_fix_batch_active = True
        self._start_next_llm_fix_job(manager)

    def _on_llm_fix_progress(self, done: int, total: int, info: str):
        total_safe = max(1, int(total))
        done_safe = max(0, min(int(done), total_safe))
        path = str(getattr(self, "_llm_fix_path", "") or "")
        file_total = max(1, int(getattr(self, "_llm_fix_total", 1) or 1))
        file_idx = max(1, min(file_total, int(getattr(self, "_llm_fix_done_count", 0)) + 1))
        text = (
            f"{self._llm_fix_label_prefix(path)}: "
            f"Datei {file_idx}/{file_total}, Block {done_safe}/{total_safe}"
        )
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
        file_total = max(1, int(getattr(self, "_llm_fix_total", 1) or 1))
        file_idx = max(1, min(file_total, int(getattr(self, "_llm_fix_done_count", 0)) + 1))
        skipped_total = max(0, unchanged + rejected + skipped)
        skipped_breakdown = (
            f"skipped={skipped_total} "
            f"(gleich={unchanged}, fehlgeschlagen={rejected}, nicht_bearbeitet={skipped})"
        )

        if stopped:
            message = (
                f"{self._llm_fix_label_prefix(path)}: Datei {file_idx}/{file_total} "
                f"gestoppt | geaendert={changed} | {skipped_breakdown} | fehler={errors}"
            )
            detail_message = (
                f"Fix by LLM gestoppt: {processed}/{chunks} bearbeitet, "
                f"{skipped} uebersprungen."
            )
        elif chunks > 0:
            message = (
                f"{self._llm_fix_label_prefix(path)}: Datei {file_idx}/{file_total} | "
                f"geaendert={changed}/{chunks} | {skipped_breakdown} | fehler={errors}"
            )
            detail_message = (
                f"Fix by LLM fertig: {changed}/{chunks} Bloecke geaendert, "
                f"{unchanged} unveraendert, {rejected} verworfen, {errors} Fehler."
            )
        elif reason:
            message = (
                f"{self._llm_fix_label_prefix(path)}: Datei {file_idx}/{file_total} | "
                f"{reason} | {skipped_breakdown} | fehler={errors}"
            )
            detail_message = f"Fix by LLM: {reason}"
        else:
            message = (
                f"{self._llm_fix_label_prefix(path)}: Datei {file_idx}/{file_total} "
                f"beendet | geaendert={changed} | {skipped_breakdown} | fehler={errors}"
            )
            detail_message = message
        self._set_llm_fix_status_for_path(
            path,
            message,
            tooltip=detail_message,
            visible=True,
        )
        self._llm_fix_done_count = min(
            int(getattr(self, "_llm_fix_total", 0) or 0),
            int(getattr(self, "_llm_fix_done_count", 0) or 0) + 1,
        )
        manager = self._resolve_llm_manager()
        if bool(getattr(self, "_llm_fix_batch_active", False)) and manager is not None:
            self._start_next_llm_fix_job(manager)
            return
        self._finish_llm_fix_batch()

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
        self._update_open_button_state()
        self._preview_worker.start()

    def _on_preview_done(self, markdown: str, error: str):
        self._preview_worker = None
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
            self._update_open_button_state()
            settings = entry.pdf_settings
            if settings.detected_info:
                self._pdf_panel.set_detect_info(settings.detected_info)
            if is_pdf:
                self._pdf_viewer.update_markdown(markdown)
        feedback_bar = getattr(self, "_feedback_bar", None)
        if feedback_bar is not None:
            feedback_bar.activate("file_import")
        self._update_open_button_state()
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
        self._update_open_button_state()
        self._detect_worker.start()

    def _on_detect_done(self, result: dict):
        self._detect_worker = None
        self._btn_add.setEnabled(True)
        self._update_open_button_state()
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
        self._update_open_button_state()
        self._font_worker.start()

    def _on_font_analysis_done(self, result: dict):
        self._font_worker = None
        self._btn_add.setEnabled(True)
        self._update_open_button_state()
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
        self._btn_remove.setEnabled(False)
        self._list.setEnabled(False)
        self._tabs.setEnabled(False)
        self._pdf_panel.widget().setEnabled(False)
        self._pending_select_after_import = None
        self._update_open_button_state()
        has_pdf = any(is_pdf_path(path) for path in paths)
        # PDF conversion can become GIL-heavy in-thread and freeze the UI when a
        # model is loaded. Run PDFs in an isolated spawned process (serial) to
        # keep UI responsive and avoid fitz/LLM same-process contention.
        backend = "process"
        max_workers = 1 if has_pdf else None
        if has_pdf:
            self._preview_status.setText(
                "Import: Isolierter PDF-Prozessmodus aktiv (seriell)."
            )
            self._preview_status.setVisible(True)
        self._worker = ConversionWorker(
            paths,
            settings_map,
            self,
            parallel_backend=backend,
            max_workers=max_workers,
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
        running_batch = bool(self._worker is not None and self._worker.isRunning())
        if (not running_batch) and self._current_path == path and entry.is_pdf():
            settings = entry.pdf_settings
            self._pdf_panel.set_settings(settings)
            self._pdf_viewer.refresh_settings(
                settings,
                float(entry.body_size or 0.0),
                entry.markdown,
            )
        if done_before == 0 and not self._pending_select_after_import:
            self._pending_select_after_import = path
        done = sum(1 for entry in self._entries.values() if entry.status != _STATUS_PENDING)
        total = len(self._entries)
        self._progress.setValue(done)
        self._progress_lbl.setText(f"{done} / {total} converted")
        self._update_open_button_state()
        self._refresh_llm_fix_button()

    def _on_all_done(self):
        self._worker = None
        self._btn_import.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._btn_remove.setEnabled(True)
        self._list.setEnabled(True)
        self._tabs.setEnabled(True)
        if self._current_path and self._current_path in self._entries:
            self._pdf_panel.set_enabled_for_pdf(self._entries[self._current_path].is_pdf())
        else:
            self._pdf_panel.widget().setEnabled(False)
        pending_path = str(getattr(self, "_pending_select_after_import", "") or "").strip()
        if pending_path:
            for i in range(self._list.count()):
                item = self._list.item(i)
                if str(item.data(Qt.ItemDataRole.UserRole) or "") == pending_path:
                    self._list.setCurrentItem(item)
                    break
        self._pending_select_after_import = None
        self._update_open_button_state()
        self._refresh_llm_fix_button()
