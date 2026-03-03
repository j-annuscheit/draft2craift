from __future__ import annotations

from PySide6.QtCore import Qt

from .entry import copy_runtime_state, is_pdf_path
from .models import PDFImportSettings
from .ui_constants import _STATUS_DONE, _STATUS_ERROR, _STATUS_PENDING
from .workers import ConversionWorker, DetectWorker, FontAnalysisWorker, SingleConversionWorker


class FileImportWorkersMixin:
    """Conversion, detect, analyze and batch worker orchestration."""

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
        self._worker = ConversionWorker(paths, settings_map, self)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

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

    def _on_all_done(self):
        self._btn_import.setEnabled(True)
        self._btn_add.setEnabled(True)
        self._btn_open.setEnabled(self._has_converted())
