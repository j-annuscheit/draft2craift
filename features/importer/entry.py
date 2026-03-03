"""Importer entry model and state helpers."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .models import PDFImportSettings
from .ui_constants import _STATUS_DONE, _STATUS_PENDING


@dataclass
class ImportEntry:
    """In-memory state for one file in the import dialog."""

    path: str
    name: str
    markdown: str = ""
    status: str = _STATUS_PENDING
    error: str = ""
    pdf_settings: PDFImportSettings = field(default_factory=PDFImportSettings)
    body_size: float = 0.0

    def is_pdf(self) -> bool:
        return is_pdf_path(self.path)


def is_pdf_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".pdf"


def preview_placeholder_text(name: str, is_pdf: bool) -> str:
    """Text shown before a file has been converted."""
    if is_pdf:
        hint = "Adjust settings, then click  **▶ Preview**  or  **Import All**."
    else:
        hint = "Click  **Import All**  to convert."
    return f"# {name}\n\n*Not yet converted.*\n\n{hint}"


def can_keep_detection_state(old: PDFImportSettings, new: PDFImportSettings) -> bool:
    """Whether auto-detect runtime output can be kept across settings changes."""
    checks = [
        old.auto_hf_detect == new.auto_hf_detect,
        old.hf_min_pages == new.hf_min_pages,
        abs(old.hf_threshold - new.hf_threshold) < 1e-9,
        old.hf_max_pairs == new.hf_max_pairs,
        abs(old.hf_top_zone - new.hf_top_zone) < 1e-9,
        abs(old.hf_bottom_zone - new.hf_bottom_zone) < 1e-9,
    ]
    return all(checks)


def copy_runtime_state(
    src: PDFImportSettings,
    dst: PDFImportSettings,
    *,
    keep_detection: bool,
):
    """Copy worker-produced runtime fields between settings instances."""
    dst.font_info = src.font_info
    if not keep_detection:
        return
    dst.detected_top = src.detected_top
    dst.detected_bottom = src.detected_bottom
    dst.detected_info = src.detected_info
    dst.detected_top_by_page = dict(src.detected_top_by_page)
    dst.detected_bottom_by_page = dict(src.detected_bottom_by_page)
    dst.detected_hf_rects_by_page = dict(src.detected_hf_rects_by_page)


def converted_results(entries: dict[str, ImportEntry]) -> list[tuple[str, str, str]]:
    """Return files_imported payload for successfully converted entries."""
    return [
        (entry.name, path, entry.markdown)
        for path, entry in entries.items()
        if entry.status == _STATUS_DONE
    ]
