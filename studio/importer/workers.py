"""Background workers for importer conversion and markdown cleanup."""
from __future__ import annotations

from difflib import SequenceMatcher
import os
import re
from typing import Any

from PySide6.QtCore import QThread, Signal

from shared.services.importer.convert import convert_file
from shared.services.importer.models import PDFImportSettings
from shared.services.importer.pdf.extract import convert_pdf_with_settings
from shared.services.importer.pdf.fonts import analyze_pdf_fonts
from shared.services.importer.pdf.layout import detect_pdf_hf_layout


def _convert_one(path: str, settings: PDFImportSettings) -> tuple[str, str]:
    try:
        if os.path.splitext(path)[1].lower() == ".pdf":
            return convert_pdf_with_settings(path, settings), ""
        return convert_file(path), ""
    except Exception as exc:
        return "", str(exc)


class ConversionWorker(QThread):
    file_done = Signal(int, str, str, str, str, object)
    all_done = Signal()

    def __init__(self, paths: list[str], settings_map: dict[str, PDFImportSettings], parent=None):
        super().__init__(parent)
        self._paths = list(paths or [])
        self._settings_map = dict(settings_map or {})
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        for idx, path in enumerate(self._paths):
            if self._stop:
                break
            settings = self._settings_map.get(path, PDFImportSettings())
            markdown, error = _convert_one(path, settings)
            self.file_done.emit(idx, os.path.basename(path), path, markdown, error, settings)
        self.all_done.emit()


class SingleConversionWorker(QThread):
    done = Signal(str, str)

    def __init__(self, path: str, settings: PDFImportSettings, parent=None):
        super().__init__(parent)
        self._path = path
        self._settings = settings

    def run(self) -> None:
        markdown, error = _convert_one(self._path, self._settings)
        self.done.emit(markdown, error)


class DetectWorker(QThread):
    done = Signal(dict)

    def __init__(self, path: str, settings: PDFImportSettings, parent=None):
        super().__init__(parent)
        self._path = path
        self._settings = settings

    def run(self) -> None:
        try:
            self.done.emit(detect_pdf_hf_layout(self._path, self._settings))
        except Exception as exc:
            self.done.emit(
                {
                    "top_margin": 0.0,
                    "bottom_margin": 0.0,
                    "info": f"Detection error: {exc}",
                    "top_by_page": {},
                    "bottom_by_page": {},
                    "hf_rects_by_page": {},
                }
            )


class FontAnalysisWorker(QThread):
    done = Signal(dict)

    def __init__(self, path: str, settings: PDFImportSettings, parent=None):
        super().__init__(parent)
        self._path = path
        self._settings = settings

    def run(self) -> None:
        try:
            result = analyze_pdf_fonts(self._path, self._settings)
        except Exception as exc:
            result = {
                "info": f"Analysis error: {exc}",
                "body_size": 11.0,
                "clusters": [],
                "body_fonts": [],
                "heading_fonts": [],
                "suggested_h1": 1.40,
                "suggested_h2": 1.20,
                "suggested_h3": 1.05,
            }
        self.done.emit(result)


class MarkdownLLMFixWorker(QThread):
    """Chunk-wise markdown cleanup with conservative acceptance checks."""

    progress = Signal(int, int, str)
    done = Signal(str, object)

    def __init__(self, llm_manager: Any, markdown_text: str, parent=None):
        super().__init__(parent)
        self._llm_manager = llm_manager
        self._markdown_text = str(markdown_text or "")
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    @staticmethod
    def _split_markdown_chunks(text: str, target_chars: int = 1400) -> list[str]:
        source = str(text or "")
        if not source.strip():
            return []
        chunks: list[str] = []
        buf: list[str] = []
        size = 0
        for line in source.splitlines(keepends=True):
            buf.append(line)
            size += len(line)
            if size >= target_chars and not line.strip():
                chunks.append("".join(buf))
                buf = []
                size = 0
        if buf:
            chunks.append("".join(buf))
        return chunks

    @staticmethod
    def _numbers_signature(text: str) -> tuple[str, ...]:
        return tuple(re.findall(r"\d+(?:[.,]\d+)?", str(text or "")))

    @staticmethod
    def _page_marker_signature(text: str) -> tuple[str, ...]:
        return tuple(re.findall(r"\[\s*Seite\s+(\d+)\s*\]", str(text or ""), flags=re.IGNORECASE))

    @classmethod
    def _accept_candidate(cls, original: str, candidate: str) -> bool:
        src = str(original or "")
        out = str(candidate or "")
        if not out.strip():
            return False
        if cls._page_marker_signature(src) != cls._page_marker_signature(out):
            return False
        if cls._numbers_signature(src) != cls._numbers_signature(out):
            return False
        if SequenceMatcher(None, src, out).ratio() < 0.86:
            return False
        max_delta = max(120, int(len(src) * 0.45))
        return abs(len(out) - len(src)) <= max_delta

    @staticmethod
    def _extract_markdown_payload(raw: str) -> str:
        text = str(raw or "")
        block = re.search(r"```(?:markdown|md)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
        return str(block.group(1) or "") if block else text

    @staticmethod
    def _escape_internal_word_asterisks(text: str) -> str:
        return re.sub(r"(?<=[^\W\d_])\*(?=[^\W\d_])", r"\\*", str(text or ""), flags=re.UNICODE)

    @staticmethod
    def _strip_new_single_emphasis_markup(original: str, candidate: str) -> str:
        src = str(original or "")
        out = str(candidate or "")

        def _unwrap(match: re.Match[str]) -> str:
            token = str(match.group(0) or "")
            inner = str(match.group(1) or "")
            return token if token in src or not inner.strip() else inner

        out = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)", _unwrap, out)
        out = re.sub(r"(?<!_)_(?!_)([^_\n]+?)_(?!_)", _unwrap, out)
        return out

    @staticmethod
    def _parse_numbered_heading_depth(text: str) -> int | None:
        title = str(text or "").strip()
        m = re.match(r"^(\d+(?:\.\d+){0,7})(?:[.)])?(?:\s+|$)", title)
        if not m:
            return None
        parts = [p for p in str(m.group(1) or "").strip(".").split(".") if p]
        return len(parts) if parts else None

    @staticmethod
    def _is_score_like_title(text: str) -> bool:
        title = re.sub(r"\s+", " ", str(text or "").strip())
        if not title:
            return False
        compact = title.replace(" ", "")
        if re.fullmatch(r"\d+(?:[.,]\d+)?(?:%|[Pp](?:unkte|unkt|kt)?\.?)", compact):
            return True
        token_pat = r"\d+(?:[.,]\d+)?\s*(?:%|[Pp](?:unkte|unkt|kt)?\.?)"
        tokens = re.findall(token_pat, title)
        if len(tokens) < 2:
            return False
        return not bool(re.sub(r"[\s,;:|/\\-]+", "", re.sub(token_pat, " ", title)))

    @classmethod
    def _infer_numbered_heading_offset(cls, text: str, default: int = 1) -> int:
        counts: dict[int, int] = {}
        for raw in str(text or "").splitlines():
            m = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", str(raw or ""))
            if not m:
                continue
            depth = cls._parse_numbered_heading_depth(str(m.group(2) or ""))
            if depth is None or cls._is_score_like_title(str(m.group(2) or "")):
                continue
            offset = int(len(str(m.group(1) or "")) - depth)
            if -2 <= offset <= 3:
                counts[offset] = counts.get(offset, 0) + 1
        if not counts:
            return int(default)
        return int(sorted(counts.items(), key=lambda item: (-item[1], abs(item[0] - int(default))))[0][0])

    @staticmethod
    def _heading_level_from_depth(depth: int, offset: int) -> int:
        return max(1, min(6, int(depth) + int(offset)))

    @classmethod
    def _promote_bold_numbered_headings(cls, text: str, offset: int) -> str:
        out: list[str] = []
        for raw in str(text or "").splitlines():
            line = str(raw or "")
            if len(re.findall(r"\*\*[^*\n]+?\*\*", line)) != 1:
                out.append(line)
                continue
            m = re.match(r"^\s{0,3}\*\*(.+?)\*\*(.*)$", line)
            if not m:
                out.append(line)
                continue
            title = re.sub(r"\s+", " ", str(m.group(1) or "").strip())
            if cls._is_score_like_title(title):
                out.append(line)
                continue
            depth = cls._parse_numbered_heading_depth(title)
            if depth is None:
                out.append(line)
                continue
            tail = str(m.group(2) or "").strip()
            if re.search(r"\*\*[^*\n]+?\*\*", tail):
                out.append(line)
                continue
            out.append(f"{'#' * cls._heading_level_from_depth(depth, offset)} {title}")
            if tail:
                if tail.startswith(":"):
                    tail = tail[1:].lstrip()
                out.append("")
                out.append(tail)
        return "\n".join(out)

    @classmethod
    def _normalize_numbered_heading_levels(cls, text: str, offset: int) -> str:
        out: list[str] = []
        for raw in str(text or "").splitlines():
            line = str(raw or "")
            m = re.match(r"^(\s{0,3})(#{1,6})(\s+)(.+?)\s*$", line)
            if not m:
                out.append(line)
                continue
            title = str(m.group(4) or "").strip()
            if cls._is_score_like_title(title):
                out.append(line)
                continue
            depth = cls._parse_numbered_heading_depth(title)
            if depth is None:
                out.append(line)
                continue
            out.append(f"{str(m.group(1) or '')}{'#' * cls._heading_level_from_depth(depth, offset)} {title}")
        return "\n".join(out)

    def run(self) -> None:
        text = self._markdown_text
        if not text.strip():
            self.done.emit(text, {"applied": False, "reason": "empty_markdown", "chunks": 0})
            return
        manager = self._llm_manager
        chunks = self._split_markdown_chunks(text)
        if not chunks:
            self.done.emit(text, {"applied": False, "reason": "no_chunks", "chunks": 0})
            return
        out_chunks: list[str] = []
        changed = 0
        for idx, chunk in enumerate(chunks, 1):
            if self._stop:
                out_chunks.extend(chunks[idx - 1 :])
                break
            self.progress.emit(idx - 1, len(chunks), f"Block {idx}/{len(chunks)}")
            fixed = chunk
            try:
                if manager is not None:
                    raw, _meta = manager.fix_markdown_chunk_sync(chunk)
                    candidate = self._extract_markdown_payload(str(raw or ""))
                    candidate = self._escape_internal_word_asterisks(candidate)
                    candidate = self._strip_new_single_emphasis_markup(chunk, candidate)
                    if self._accept_candidate(chunk, candidate):
                        fixed = candidate
            except Exception:
                fixed = chunk
            out_chunks.append(fixed)
            if fixed != chunk:
                changed += 1
        merged = "".join(out_chunks) if out_chunks else text
        offset = self._infer_numbered_heading_offset(merged, default=1)
        merged = self._promote_bold_numbered_headings(merged, offset)
        merged = self._normalize_numbered_heading_levels(merged, offset)
        merged = self._escape_internal_word_asterisks(merged)
        self.progress.emit(len(chunks), len(chunks), "Fertig")
        self.done.emit(merged, {"applied": True, "reason": "ok", "chunks": len(chunks), "changed_chunks": changed})
