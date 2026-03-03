from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import os

from PySide6.QtCore import QThread, Signal

from .convert import convert_file
from .models import PDFImportSettings
from .pdf import (
    analyze_pdf_fonts,
    convert_pdf_with_settings,
    detect_pdf_hf_layout,
)

_MAX_PARALLEL_CONVERSIONS = max(1, min(6, os.cpu_count() or 1))


def _convert_one_job(
    index: int,
    path: str,
    settings: PDFImportSettings,
) -> tuple[int, str, str, str, str, PDFImportSettings]:
    """Process-pool entrypoint: convert a single file and return worker payload."""
    name = os.path.basename(path)
    try:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            md = convert_pdf_with_settings(path, settings)
        else:
            md = convert_file(path)
        return (index, name, path, md, "", settings)
    except Exception as exc:
        return (index, name, path, "", str(exc), settings)

class ConversionWorker(QThread):
    file_done = Signal(int, str, str, str, str, object)
    all_done  = Signal()

    def __init__(self, paths: list[str], settings_map: dict[str, PDFImportSettings], parent=None):
        super().__init__(parent)
        self._paths        = paths
        self._settings_map = settings_map
        self._stop         = False

    def run(self):
        jobs = [
            (i, path, self._settings_map.get(path, PDFImportSettings()))
            for i, path in enumerate(self._paths)
        ]
        if not jobs:
            self.all_done.emit()
            return

        worker_count = min(len(jobs), _MAX_PARALLEL_CONVERSIONS)
        use_parallel = worker_count > 1

        if use_parallel:
            try:
                # "spawn" is safer with Qt apps than forking from a worker thread.
                mp_ctx = multiprocessing.get_context("spawn")
                with ProcessPoolExecutor(
                    max_workers=worker_count,
                    mp_context=mp_ctx,
                ) as pool:
                    future_map = {
                        pool.submit(_convert_one_job, idx, path, settings): (idx, path)
                        for idx, path, settings in jobs
                    }
                    for fut in as_completed(future_map):
                        if self._stop:
                            for pending in future_map:
                                pending.cancel()
                            break
                        fallback_idx, fallback_path = future_map[fut]
                        try:
                            idx, name, path, md, error, settings = fut.result()
                        except Exception as exc:
                            idx = fallback_idx
                            path = fallback_path
                            name = os.path.basename(path)
                            md = ""
                            error = str(exc)
                            settings = self._settings_map.get(path, PDFImportSettings())
                        self.file_done.emit(idx, name, path, md, error, settings)
                self.all_done.emit()
                return
            except Exception:
                # Fallback to in-thread sequential mode if process pool init fails.
                pass

        for i, path, settings in jobs:
            if self._stop:
                break
            idx, name, job_path, md, error, used_settings = _convert_one_job(i, path, settings)
            self.file_done.emit(idx, name, job_path, md, error, used_settings)
        self.all_done.emit()

    def request_stop(self):
        self._stop = True


class SingleConversionWorker(QThread):
    done = Signal(str, str)

    def __init__(self, path: str, settings: PDFImportSettings, parent=None):
        super().__init__(parent)
        self._path     = path
        self._settings = settings

    def run(self):
        try:
            ext = os.path.splitext(self._path)[1].lower()
            md  = convert_pdf_with_settings(self._path, self._settings) if ext == ".pdf" \
                  else convert_file(self._path)
            self.done.emit(md, "")
        except Exception as exc:
            self.done.emit("", str(exc))


class DetectWorker(QThread):
    done = Signal(dict)

    def __init__(self, path: str, settings: PDFImportSettings, parent=None):
        super().__init__(parent)
        self._path     = path
        self._settings = settings

    def run(self):
        try:
            result = detect_pdf_hf_layout(self._path, self._settings)
            self.done.emit(result)
        except Exception as exc:
            self.done.emit({
                "top_margin": 0.0,
                "bottom_margin": 0.0,
                "info": f"Detection error: {exc}",
                "top_by_page": {},
                "bottom_by_page": {},
                "hf_rects_by_page": {},
            })


class FontAnalysisWorker(QThread):
    """Runs font size analysis on a PDF and emits the result dict."""
    done = Signal(dict)

    def __init__(self, path: str, settings: PDFImportSettings, parent=None):
        super().__init__(parent)
        self._path     = path
        self._settings = settings

    def run(self):
        try:
            result = analyze_pdf_fonts(self._path, self._settings)
        except Exception as exc:
            result = {"info": f"Analysis error: {exc}", "body_size": 11.0,
                      "clusters": [], "body_fonts": [], "heading_fonts": [],
                      "suggested_h1": 1.40, "suggested_h2": 1.20, "suggested_h3": 1.05}
        self.done.emit(result)
