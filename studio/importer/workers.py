from __future__ import annotations

from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)
from difflib import SequenceMatcher
import multiprocessing
import os
import re
from typing import Any

from PySide6.QtCore import QThread, Signal

from shared.services.importer.convert import convert_file
from shared.services.importer.models import PDFImportSettings
from shared.services.importer.pdf.extract import convert_pdf_with_settings
from shared.services.importer.pdf.fonts import analyze_pdf_fonts
from shared.services.importer.pdf.layout import detect_pdf_hf_layout

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
        has_pdf_jobs = any(
            os.path.splitext(path)[1].lower() == ".pdf"
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

    @staticmethod
    def _split_markdown_chunks(
        text: str,
        *,
        target_chars: int = 1400,
        max_chars: int = 2200,
    ) -> list[str]:
        source = str(text or "")
        if not source:
            return []
        chunks: list[str] = []
        buf: list[str] = []
        buf_len = 0
        lines = source.splitlines(keepends=True)
        for line in lines:
            buf.append(line)
            buf_len += len(line)
            at_soft_boundary = (not line.strip()) and (buf_len >= target_chars)
            at_hard_boundary = buf_len >= max_chars
            if at_soft_boundary or at_hard_boundary:
                chunks.append("".join(buf))
                buf = []
                buf_len = 0
        if buf:
            chunks.append("".join(buf))
        return chunks

    @staticmethod
    def _numbers_signature(text: str) -> tuple[str, ...]:
        return tuple(re.findall(r"\d+(?:[.,]\d+)?", str(text or "")))

    @staticmethod
    def _page_marker_signature(text: str) -> tuple[str, ...]:
        matches = re.findall(
            r"\[\s*Seite\s+(\d+)\s*\]",
            str(text or ""),
            flags=re.IGNORECASE,
        )
        return tuple(str(int(num)) for num in matches)

    @classmethod
    def _accept_candidate(cls, original: str, candidate: str) -> bool:
        orig = str(original or "")
        cand = str(candidate or "")
        if not cand.strip():
            return False
        if cls._page_marker_signature(orig) != cls._page_marker_signature(cand):
            return False
        if cls._numbers_signature(orig) != cls._numbers_signature(cand):
            return False
        ratio = SequenceMatcher(None, orig, cand).ratio()
        if ratio < 0.86:
            return False
        max_delta = max(120, int(len(orig) * 0.45))
        if abs(len(cand) - len(orig)) > max_delta:
            return False
        return True

    @staticmethod
    def _extract_markdown_payload(raw: str) -> str:
        text = str(raw or "")
        if not text.strip():
            return ""
        fence = re.search(
            r"```(?:markdown|md)?\s*([\s\S]*?)```",
            text,
            flags=re.IGNORECASE,
        )
        if fence:
            return str(fence.group(1) or "")
        return text

    @staticmethod
    def _source_has_xml_tag(text: str, tag_name: str) -> bool:
        return bool(
            re.search(
                rf"</?\s*{re.escape(str(tag_name or '').strip())}\s*>",
                str(text or ""),
                flags=re.IGNORECASE,
            )
        )

    @classmethod
    def _remove_leaked_prompt_tags(cls, original: str, candidate: str) -> str:
        src = str(original or "")
        out = str(candidate or "")
        if not out:
            return out

        if not cls._source_has_xml_tag(src, "fixed_md"):
            out = re.sub(r"</?\s*fixed_md\s*>", "", out, flags=re.IGNORECASE)
        if not cls._source_has_xml_tag(src, "markdown_input"):
            out = re.sub(r"</?\s*markdown_input\s*>", "", out, flags=re.IGNORECASE)
        if "<|" not in src:
            out = re.sub(r"<\|[^|>\n]{1,120}\|>", "", out)
        return out

    @staticmethod
    def _restore_percent_signs(original: str, candidate: str) -> str:
        src = str(original or "")
        out = str(candidate or "")
        if "%" not in src:
            return out
        return re.sub(
            r"(\d+(?:[.,]\d+)?)\s*(?:Prozent|prozent)\b",
            r"\1 %",
            out,
        )

    @classmethod
    def _restore_page_markers(cls, original: str, candidate: str) -> str:
        """
        Preserve generated page markers in canonical form: ``[Seite N]``.
        """
        src = str(original or "")
        out = str(candidate or "")
        src_signature = cls._page_marker_signature(src)
        if not src_signature:
            return out

        # Normalize already bracketed variants to canonical spelling/spacing.
        out = re.sub(
            r"\[\s*Seite\s+(\d+)\s*\]",
            lambda m: f"[Seite {int(m.group(1))}]",
            out,
            flags=re.IGNORECASE,
        )

        allowed = {str(int(num)) for num in src_signature}

        # Repair line-only degradations like "Seite 12" -> "[Seite 12]".
        def _line_marker_repl(m: re.Match[str]) -> str:
            num = str(int(m.group(1)))
            if num in allowed:
                return f"[Seite {num}]"
            return str(m.group(0) or "")

        out = re.sub(
            r"(?im)^\s*Seite\s+(\d+)\s*$",
            _line_marker_repl,
            out,
        )
        return out

    @staticmethod
    def _escape_internal_word_asterisks(text: str) -> str:
        return re.sub(
            r"(?<=[^\W\d_])\*(?=[^\W\d_])",
            r"\\*",
            str(text or ""),
            flags=re.UNICODE,
        )

    @staticmethod
    def _strip_new_single_emphasis_markup(original: str, candidate: str) -> str:
        """
        Remove newly introduced single-emphasis spans (*...* / _..._) that
        often appear as correction annotations rather than source formatting.
        """
        orig = str(original or "")
        out = str(candidate or "")
        if not out:
            return out

        def unwrap_if_new(match: re.Match[str]) -> str:
            token = str(match.group(0) or "")
            inner = str(match.group(1) or "")
            if not inner.strip():
                return token
            # Keep emphasis only if this exact span already existed in source.
            return token if token in orig else inner

        out = re.sub(
            r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)",
            unwrap_if_new,
            out,
        )
        out = re.sub(
            r"(?<!_)_(?!_)([^_\n]+?)_(?!_)",
            unwrap_if_new,
            out,
        )
        return out

    @staticmethod
    def _count_leading_newlines(text: str) -> int:
        m = re.match(r"^\n*", str(text or ""))
        return len(str(m.group(0) if m else ""))

    @staticmethod
    def _count_trailing_newlines(text: str) -> int:
        m = re.search(r"\n*$", str(text or ""))
        return len(str(m.group(0) if m else ""))

    @classmethod
    def _preserve_chunk_edge_newlines(cls, original: str, candidate: str) -> str:
        orig = str(original or "")
        cand = str(candidate or "")
        need_head = cls._count_leading_newlines(orig)
        need_tail = cls._count_trailing_newlines(orig)
        have_head = cls._count_leading_newlines(cand)
        have_tail = cls._count_trailing_newlines(cand)
        if have_head < need_head:
            cand = ("\n" * (need_head - have_head)) + cand
        if have_tail < need_tail:
            cand = cand + ("\n" * (need_tail - have_tail))
        return cand

    @staticmethod
    def _extract_heading_specs(text: str) -> list[tuple[str, str]]:
        specs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for raw_line in str(text or "").splitlines():
            line = str(raw_line or "").rstrip()
            m = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
            if not m:
                continue
            level = str(m.group(1) or "")
            title = re.sub(r"\s+", " ", str(m.group(2) or "").strip())
            if not level or not title:
                continue
            key = (level, title)
            if key in seen:
                continue
            seen.add(key)
            specs.append(key)
        return specs

    @staticmethod
    def _title_regex(title: str) -> str:
        tokens = [t for t in re.split(r"\s+", str(title or "").strip()) if t]
        if not tokens:
            return ""
        return r"\s+".join(re.escape(token) for token in tokens)

    @classmethod
    def _restore_heading_boundaries(cls, original: str, candidate: str) -> str:
        out = str(candidate or "")
        specs = cls._extract_heading_specs(original)
        if not specs:
            return out
        for level, title in specs:
            title_pat = cls._title_regex(title)
            if not title_pat:
                continue
            heading_pat = rf"\s{{0,3}}{re.escape(level)}\s+{title_pat}"
            # Prevent heading from being glued to previous paragraph text.
            out = re.sub(
                rf"([^\n])({heading_pat})(?=\s|$)",
                r"\1\n\2",
                out,
            )
            # Prevent heading from sharing a line with following paragraph text.
            out = re.sub(
                rf"({heading_pat})([ \t]+)(?=[^\n])",
                r"\1\n",
                out,
            )
        return out

    @staticmethod
    def _parse_numbered_heading_depth(text: str) -> int | None:
        title = str(text or "").strip()
        if not title:
            return None
        m = re.match(r"^(\d+(?:\.\d+){0,7})(?:[.)])?(?:\s+|$)", title)
        if not m:
            return None
        raw = str(m.group(1) or "").strip().strip(".")
        if not raw:
            return None
        parts = [p for p in raw.split(".") if p]
        if not parts:
            return None
        return int(len(parts))

    @staticmethod
    def _is_score_like_title(text: str) -> bool:
        title = re.sub(r"\s+", " ", str(text or "").strip())
        if not title:
            return False
        compact = title.replace(" ", "")
        if re.fullmatch(
            r"\d+(?:[.,]\d+)?(?:%|[Pp](?:unkte|unkt|kt)?\.?)",
            compact,
        ):
            return True
        token_pat = r"\d+(?:[.,]\d+)?\s*(?:%|[Pp](?:unkte|unkt|kt)?\.?)"
        tokens = re.findall(token_pat, title)
        if len(tokens) < 2:
            return False
        rest = re.sub(token_pat, " ", title)
        rest = re.sub(r"[\s,;:|/\\-]+", "", rest)
        return not bool(rest)

    @classmethod
    def _infer_numbered_heading_offset(cls, text: str, default: int = 1) -> int:
        counts: dict[int, int] = {}
        for raw_line in str(text or "").splitlines():
            m = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", str(raw_line or ""))
            if not m:
                continue
            level = int(len(str(m.group(1) or "")))
            title = str(m.group(2) or "")
            if cls._is_score_like_title(title):
                continue
            depth = cls._parse_numbered_heading_depth(title)
            if depth is None:
                continue
            offset = int(level - depth)
            if -2 <= offset <= 3:
                counts[offset] = counts.get(offset, 0) + 1
        if not counts:
            return int(default)
        best_offset = sorted(
            counts.items(),
            key=lambda item: (-int(item[1]), abs(int(item[0]) - int(default))),
        )[0][0]
        return int(best_offset)

    @staticmethod
    def _heading_level_from_depth(depth: int, offset: int) -> int:
        value = int(depth) + int(offset)
        return max(1, min(6, value))

    @classmethod
    def _promote_bold_numbered_headings(cls, text: str, offset: int) -> str:
        lines = str(text or "").splitlines()
        out_lines: list[str] = []
        for raw in lines:
            line = str(raw or "")
            bold_spans = re.findall(r"\*\*[^*\n]+?\*\*", line)
            if len(bold_spans) != 1:
                out_lines.append(line)
                continue
            m = re.match(r"^\s{0,3}\*\*(.+?)\*\*(.*)$", line)
            if not m:
                out_lines.append(line)
                continue
            title = re.sub(r"\s+", " ", str(m.group(1) or "").strip())
            if cls._is_score_like_title(title):
                out_lines.append(line)
                continue
            depth = cls._parse_numbered_heading_depth(title)
            if depth is None:
                out_lines.append(line)
                continue
            level = cls._heading_level_from_depth(depth, offset)
            heading = f"{'#' * level} {title}"
            tail = str(m.group(2) or "").strip()
            if re.search(r"\*\*[^*\n]+?\*\*", tail):
                out_lines.append(line)
                continue
            if tail.startswith(":"):
                tail = tail[1:].lstrip()
            out_lines.append(heading)
            if tail:
                out_lines.append("")
                out_lines.append(tail)
            continue
        return "\n".join(out_lines)

    @classmethod
    def _normalize_numbered_heading_levels(cls, text: str, offset: int) -> str:
        lines = str(text or "").splitlines()
        out_lines: list[str] = []
        for raw in lines:
            line = str(raw or "")
            m = re.match(r"^(\s{0,3})(#{1,6})(\s+)(.+?)\s*$", line)
            if not m:
                out_lines.append(line)
                continue
            prefix = str(m.group(1) or "")
            title = str(m.group(4) or "").strip()
            if cls._is_score_like_title(title):
                out_lines.append(line)
                continue
            depth = cls._parse_numbered_heading_depth(title)
            if depth is None:
                out_lines.append(line)
                continue
            level = cls._heading_level_from_depth(depth, offset)
            out_lines.append(f"{prefix}{'#' * level} {title}")
        return "\n".join(out_lines)

    @classmethod
    def _harmonize_numbered_headings(cls, text: str, offset: int) -> str:
        source = str(text or "")
        out = source
        out = cls._promote_bold_numbered_headings(out, offset)
        out = cls._normalize_numbered_heading_levels(out, offset)
        return cls._preserve_chunk_edge_newlines(source, out)

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
                fixed_raw, meta = manager.fix_markdown_chunk_sync(chunk)
            except Exception as exc:
                fixed_raw = chunk
                meta = {"applied": False, "reason": f"exception:{exc}"}

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
