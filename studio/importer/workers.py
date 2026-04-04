from __future__ import annotations

from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)
import multiprocessing
import os
from typing import Any

from PySide6.QtCore import QThread, Signal

from shared.services.importer.convert import convert_file
from shared.services.importer.models import PDFImportSettings
from shared.services.importer.pdf.extract import convert_pdf_with_settings
from shared.services.importer.pdf.fonts import analyze_pdf_fonts
from shared.services.importer.pdf.layout import detect_pdf_hf_layout
from studio.importer.markdown_fix_utils import (
    _accept_candidate as _accept_candidate_fn,
    _escape_internal_word_asterisks as _escape_internal_word_asterisks_fn,
    _extract_markdown_payload as _extract_markdown_payload_fn,
    _harmonize_numbered_headings as _harmonize_numbered_headings_fn,
    _infer_numbered_heading_offset as _infer_numbered_heading_offset_fn,
    _normalize_numbered_heading_levels as _normalize_numbered_heading_levels_fn,
    _page_marker_signature as _page_marker_signature_fn,
    _preserve_chunk_edge_newlines as _preserve_chunk_edge_newlines_fn,
    _promote_bold_numbered_headings as _promote_bold_numbered_headings_fn,
    _remove_leaked_prompt_tags as _remove_leaked_prompt_tags_fn,
    _restore_heading_boundaries as _restore_heading_boundaries_fn,
    _restore_page_markers as _restore_page_markers_fn,
    _restore_percent_signs as _restore_percent_signs_fn,
    _split_markdown_chunks as _split_markdown_chunks_fn,
    _strip_new_single_emphasis_markup as _strip_new_single_emphasis_markup_fn,
)

_MAX_PARALLEL_CONVERSIONS = max(1, min(6, os.cpu_count() or 1))


def _convert_one_job(
    index: int,
    path: str,
    settings: PDFImportSettings,
) -> tuple[int, str, str, str, str, PDFImportSettings]:
    """Process-pool entrypoint: convert a single file and return worker payload."""
    from shared.services.importer.url_utils import is_url, is_pdf_url, url_display_name

    if is_url(path):
        name = url_display_name(path)
        try:
            if is_pdf_url(path):
                md = convert_pdf_with_settings(path, settings)
            else:
                md = f"# {name}\n\n*Nur PDF-URLs werden unterstützt.*\n"
            return (index, name, path, md, "", settings)
        except Exception as exc:
            return (index, name, path, "", str(exc), settings)

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

    def __init__(
        self,
        paths: list[str],
        settings_map: dict[str, PDFImportSettings],
        parent=None,
        *,
        parallel_backend: str = "process",
        max_workers: int | None = None,
    ):
        super().__init__(parent)
        self._paths        = paths
        self._settings_map = settings_map
        self._stop         = False
        backend = str(parallel_backend or "process").strip().lower()
        self._parallel_backend = backend if backend in {"process", "thread"} else "process"
        self._max_workers = (
            _MAX_PARALLEL_CONVERSIONS
            if max_workers is None
            else max(1, int(max_workers))
        )

    def run(self):
        jobs = [
            (i, path, self._settings_map.get(path, PDFImportSettings()))
            for i, path in enumerate(self._paths)
        ]
        if not jobs:
            self.all_done.emit()
            return

        worker_count = min(len(jobs), self._max_workers)
        from shared.services.importer.url_utils import is_url, is_pdf_url
        has_pdf_jobs = any(
            os.path.splitext(path)[1].lower() == ".pdf"
            or (is_url(path) and is_pdf_url(path))
            for _idx, path, _settings in jobs
        )

        if worker_count > 1 and self._parallel_backend == "thread":
            try:
                with ThreadPoolExecutor(max_workers=worker_count) as pool:
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
                # Fallback to in-thread sequential mode if thread pool init fails.
                pass

        if self._parallel_backend == "process":
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
            except Exception as exc:
                # Do NOT fall back to in-thread PDF conversion when process
                # isolation was requested: native PDF libs may crash the app.
                if has_pdf_jobs:
                    for idx, path, settings in jobs:
                        if self._stop:
                            break
                        name = os.path.basename(path)
                        error = f"Isolated PDF process failed: {exc}"
                        self.file_done.emit(idx, name, path, "", error, settings)
                    self.all_done.emit()
                    return
                # Non-PDF fallback can still run sequentially.

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


class MarkdownLLMFixWorker(QThread):
    """Chunk-wise Markdown cleanup via loaded GGUF LLM."""

    progress = Signal(int, int, str)  # done, total, info
    done = Signal(str, object)  # markdown, meta

    def __init__(
        self,
        llm_manager: Any,
        markdown_text: str,
        parent=None,
    ):
        super().__init__(parent)
        self._llm_manager = llm_manager
        self._markdown_text = str(markdown_text or "")
        self._stop = False

    def request_stop(self):
        self._stop = True

    _split_markdown_chunks = staticmethod(_split_markdown_chunks_fn)
    _page_marker_signature = staticmethod(_page_marker_signature_fn)
    _accept_candidate = staticmethod(_accept_candidate_fn)
    _extract_markdown_payload = staticmethod(_extract_markdown_payload_fn)
    _remove_leaked_prompt_tags = staticmethod(_remove_leaked_prompt_tags_fn)
    _restore_percent_signs = staticmethod(_restore_percent_signs_fn)
    _restore_page_markers = staticmethod(_restore_page_markers_fn)
    _escape_internal_word_asterisks = staticmethod(
        _escape_internal_word_asterisks_fn
    )
    _strip_new_single_emphasis_markup = staticmethod(
        _strip_new_single_emphasis_markup_fn
    )
    _preserve_chunk_edge_newlines = staticmethod(_preserve_chunk_edge_newlines_fn)
    _restore_heading_boundaries = staticmethod(_restore_heading_boundaries_fn)
    _infer_numbered_heading_offset = staticmethod(_infer_numbered_heading_offset_fn)
    _promote_bold_numbered_headings = staticmethod(
        _promote_bold_numbered_headings_fn
    )
    _normalize_numbered_heading_levels = staticmethod(
        _normalize_numbered_heading_levels_fn
    )
    _harmonize_numbered_headings = staticmethod(_harmonize_numbered_headings_fn)

    def run(self):
        text = str(self._markdown_text or "")
        if not text.strip():
            self.done.emit(
                text,
                {
                    "applied": False,
                    "reason": "empty_markdown",
                    "chunks": 0,
                },
            )
            return

        manager = self._llm_manager
        if manager is None:
            self.done.emit(
                text,
                {
                    "applied": False,
                    "reason": "llm_manager_missing",
                    "chunks": 0,
                },
            )
            return

        heading_offset = self._infer_numbered_heading_offset(text, default=1)
        chunks = self._split_markdown_chunks(text)
        total = len(chunks)
        if total <= 0:
            self.done.emit(
                text,
                {
                    "applied": False,
                    "reason": "no_chunks",
                    "chunks": 0,
                },
            )
            return

        out_chunks: list[str] = []
        processed = 0
        changed = 0
        unchanged = 0
        rejected = 0
        errors = 0

        for idx, chunk in enumerate(chunks, 1):
            if self._stop:
                out_chunks.extend(chunks[idx - 1 :])
                break
            processed += 1
            info = f"Block {idx}/{total}"
            self.progress.emit(idx - 1, total, info)

            try:
                fixed_raw, meta = manager.fix_markdown_chunk_sync(
                    chunk,
                    stop_requested=lambda: bool(self._stop),
                )
            except Exception as exc:
                fixed_raw = chunk
                meta = {"applied": False, "reason": f"exception:{exc}"}

            reason = str(meta.get("reason", "") if isinstance(meta, dict) else "")
            if self._stop or reason == "stopped":
                out_chunks.append(chunk)
                out_chunks.extend(chunks[idx:])
                break

            fixed = self._extract_markdown_payload(str(fixed_raw or ""))
            fixed = self._remove_leaked_prompt_tags(chunk, fixed)
            fixed = self._restore_percent_signs(chunk, fixed)
            fixed = self._restore_page_markers(chunk, fixed)
            fixed = self._escape_internal_word_asterisks(fixed)
            fixed = self._strip_new_single_emphasis_markup(chunk, fixed)
            fixed = self._restore_heading_boundaries(chunk, fixed)
            fixed = self._preserve_chunk_edge_newlines(chunk, fixed)
            if not self._accept_candidate(chunk, fixed):
                out_chunks.append(chunk)
                rejected += 1
                reason = str(meta.get("reason", "") if isinstance(meta, dict) else "")
                if (
                    reason.startswith("exception")
                    or "error" in reason.casefold()
                    or "fallback" in reason.casefold()
                ):
                    errors += 1
                continue

            out_chunks.append(fixed)
            if fixed != chunk:
                changed += 1
            else:
                unchanged += 1

        final_text = "".join(out_chunks) if out_chunks else text
        final_text = self._harmonize_numbered_headings(final_text, heading_offset)
        final_text = self._escape_internal_word_asterisks(final_text)
        skipped = max(0, int(total - processed))
        self.progress.emit(total, total, "Fertig")
        self.done.emit(
            final_text,
            {
                "applied": True,
                "reason": "ok",
                "chunks": total,
                "processed_chunks": processed,
                "changed_chunks": changed,
                "unchanged_chunks": unchanged,
                "rejected_chunks": rejected,
                "error_chunks": errors,
                "skipped_chunks": skipped,
                "stopped": bool(self._stop),
            },
        )
