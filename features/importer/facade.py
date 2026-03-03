"""Public facade for the file importer subsystem.

The importer is split into focused modules.
This facade provides one stable import surface for shell-level code.
"""
from __future__ import annotations

from .convert import convert_file
from .dialog import FileImportDialog
from .models import PDFImportSettings, _CODE_EXTENSIONS, _SUPPORTED_FILTER
from .panel import PDFSettingsPanel
from .pdf import (
    analyze_pdf_fonts,
    convert_pdf_with_settings,
    detect_pdf_hf_margins,
    extract_markdown_headings_by_page,
)
from .ui_constants import (
    _DIALOG_STYLE,
    _ICON,
    _STATUS_DONE,
    _STATUS_ERROR,
    _STATUS_PENDING,
)
from .viewer import PDFPageView, PDFViewerPanel
from .workers import (
    ConversionWorker,
    DetectWorker,
    FontAnalysisWorker,
    SingleConversionWorker,
)

__all__ = [
    "PDFImportSettings",
    "convert_pdf_with_settings",
    "convert_file",
    "detect_pdf_hf_margins",
    "analyze_pdf_fonts",
    "extract_markdown_headings_by_page",
    "ConversionWorker",
    "SingleConversionWorker",
    "DetectWorker",
    "FontAnalysisWorker",
    "PDFPageView",
    "PDFViewerPanel",
    "PDFSettingsPanel",
    "FileImportDialog",
    "_CODE_EXTENSIONS",
    "_SUPPORTED_FILTER",
    "_DIALOG_STYLE",
    "_STATUS_PENDING",
    "_STATUS_DONE",
    "_STATUS_ERROR",
    "_ICON",
]
