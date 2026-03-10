"""Overlay helper types for PDF viewer."""
from __future__ import annotations

from dataclasses import dataclass

from shared.services.importer.models import PDFImportSettings


@dataclass(frozen=True, slots=True)
class _HeadingAnchor:
    text: str
    level: int


def _collect_page_lines(_page) -> list[str]:
    return []


def _extract_global_heading_anchors(_markdown: str) -> list[_HeadingAnchor]:
    return []


def _extract_page_overlay_rects(_page, _settings: PDFImportSettings) -> tuple[list, list]:
    return ([], [])


def _find_heading_rects_on_page(_page, _anchors: list[_HeadingAnchor], _body_size: float) -> list:
    return []
