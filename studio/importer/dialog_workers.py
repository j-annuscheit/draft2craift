from __future__ import annotations

from PySide6.QtCore import Qt

from shared.domain.user_mode import resolve_feature_label
from shared.services.importer.entry import copy_runtime_state, is_pdf_path
from shared.services.importer.models import PDFImportSettings
from .ui_constants import _STATUS_DONE, _STATUS_ERROR, _STATUS_PENDING
from .dialog_workers_llm_fix import (
    _finish_llm_fix_batch as _finish_llm_fix_batch_fn,
    _llm_fix_candidate_paths as _llm_fix_candidate_paths_fn,
    _llm_fix_label_prefix as _llm_fix_label_prefix_fn,
    _on_llm_fix_done as _on_llm_fix_done_fn,
    _on_llm_fix_progress as _on_llm_fix_progress_fn,
    _ordered_entry_paths as _ordered_entry_paths_fn,
    _refresh_llm_fix_button as _refresh_llm_fix_button_fn,
    _resolve_llm_manager as _resolve_llm_manager_fn,
    _run_llm_fix_current_markdown as _run_llm_fix_current_markdown_fn,
    _set_llm_fix_status_for_path as _set_llm_fix_status_for_path_fn,
    _start_next_llm_fix_job as _start_next_llm_fix_job_fn,
    _sync_llm_fix_status_for_current_path as _sync_llm_fix_status_for_current_path_fn,
)
from .workers import (
    ConversionWorker,
    DetectWorker,
    FontAnalysisWorker,
    SingleConversionWorker,
)


def _label(self, key: str, default: str) -> str:
    return resolve_feature_label(
        str(getattr(self, "_user_mode", "") or ""),
        key,
        default,
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
            btn.setToolTip(
                _label(
                    self,
                    "importer.dialog.button.open.tooltip.busy",
                    "Please wait: import/analysis is still running.",
                )
            )
        elif self._has_converted():
            btn.setToolTip(
                _label(
                    self,
                    "importer.dialog.button.open.tooltip.ready",
                    "Import converted files and close dialog",
                )
            )
        else:
            btn.setToolTip(
                _label(
                    self,
                    "importer.dialog.button.open.tooltip.empty",
                    "No converted files available yet",
                )
            )

    _llm_fix_label_prefix = _llm_fix_label_prefix_fn
    _set_llm_fix_status_for_path = _set_llm_fix_status_for_path_fn
    _sync_llm_fix_status_for_current_path = _sync_llm_fix_status_for_current_path_fn
    _resolve_llm_manager = _resolve_llm_manager_fn
    _ordered_entry_paths = _ordered_entry_paths_fn
    _llm_fix_candidate_paths = _llm_fix_candidate_paths_fn
    _finish_llm_fix_batch = _finish_llm_fix_batch_fn
    _start_next_llm_fix_job = _start_next_llm_fix_job_fn
    _refresh_llm_fix_button = _refresh_llm_fix_button_fn
    _run_llm_fix_current_markdown = _run_llm_fix_current_markdown_fn
    _on_llm_fix_progress = _on_llm_fix_progress_fn
    _on_llm_fix_done = _on_llm_fix_done_fn

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
        self._preview_status.setText(
            _label(
                self,
                "importer.dialog.preview_status.converting",
                "Converting…",
            )
        )
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
            template = _label(
                self,
                "importer.dialog.preview_status.error_markdown.template",
                "# Conversion Error\n\n```\n{error}\n```\n",
            )
            try:
                rendered = template.format(error=error)
            except Exception:
                rendered = f"# Conversion Error\n\n```\n{error}\n```\n"
            self._preview.set_markdown_text(
                rendered
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
            self._pdf_panel.set_detect_info(
                _label(
                    self,
                    "importer.dialog.detect.manual_mode_active",
                    "Manual mode active. Switch to Auto-Detect mode first.",
                )
            )
            return
        copy_runtime_state(entry.pdf_settings, settings, keep_detection=False)
        entry.pdf_settings = settings
        self._pdf_panel.set_detect_info(
            _label(
                self,
                "importer.dialog.detect.running",
                "Analysing PDF, please wait…",
            )
        )
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
        self._pdf_panel.set_font_info(
            {
                "info": _label(
                    self,
                    "importer.dialog.font_analysis.running",
                    "Analysing font sizes, please wait…",
                )
            }
        )
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
