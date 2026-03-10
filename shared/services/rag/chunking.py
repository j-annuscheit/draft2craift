"""Chunking primitives and strategies for RAG indexing."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Protocol


class ChunkingConfig(Protocol):
    """Minimal config contract required by chunking strategies."""

    chunk_size: int
    chunk_overlap: int
    strategy: str
    include_headings: bool
    include_filename: bool


@dataclass(slots=True)
class Segment:
    """Normalized markdown paragraph segment with heading context."""

    text: str
    breadcrumb: list[str]
    is_heading: bool
    h_level: int


class SlidingWindowChunker:
    """Overlapping paragraph-aware chunking."""

    def __init__(self, config: ChunkingConfig):
        self._config = config

    def chunk(self, segments: list[Segment], doc_name: str = "") -> list[dict[str, Any]]:
        cfg = self._config
        chunks: list[dict[str, Any]] = []
        i = 0

        while i < len(segments):
            window: list[Segment] = []
            total_chars = 0
            j = i

            while j < len(segments):
                seg = segments[j]
                seg_len = len(seg.text)
                if window and total_chars + seg_len + 2 > cfg.chunk_size:
                    break
                window.append(seg)
                total_chars += seg_len + 2
                j += 1

            if not window:
                i += 1
                continue

            chunks.append(make_chunk_dict(window, cfg, doc_name))

            if cfg.chunk_overlap > 0 and len(window) > 1:
                overlap_chars = 0
                keep = 0
                for seg in reversed(window):
                    overlap_chars += len(seg.text) + 2
                    keep += 1
                    if overlap_chars >= cfg.chunk_overlap:
                        break
                i += max(1, len(window) - keep)
            else:
                i = j

        return chunks


class SectionChunker:
    """One chunk per markdown heading section."""

    def __init__(self, config: ChunkingConfig):
        self._config = config

    def chunk(self, segments: list[Segment], doc_name: str = "") -> list[dict[str, Any]]:
        sections: list[list[Segment]] = []
        current: list[Segment] = []
        section_level = 0

        for seg in segments:
            if seg.is_heading:
                lvl = seg.h_level
                if current and lvl <= section_level:
                    sections.append(current)
                    current = [seg]
                    section_level = lvl
                elif not current:
                    current = [seg]
                    section_level = lvl
                else:
                    current.append(seg)
            else:
                if not current:
                    current = [seg]
                else:
                    current.append(seg)

        if current:
            sections.append(current)

        return [make_chunk_dict(section, self._config, doc_name) for section in sections]


class RecursiveChunker:
    """Hierarchical chunking: H1 -> H2 -> sliding-window leaf chunks."""

    def __init__(self, config: ChunkingConfig):
        self._config = config
        self._sliding = SlidingWindowChunker(config)

    def chunk(self, segments: list[Segment], doc_name: str = "") -> list[dict[str, Any]]:
        all_chunks: list[dict[str, Any]] = []

        for h1_segments in _group_by_level(segments, 1):
            for h2_segments in _group_by_level(h1_segments, 2):
                parent_text = "\n\n".join(segment.text for segment in h2_segments)
                leaf_chunks = self._sliding.chunk(h2_segments, doc_name)
                for chunk in leaf_chunks:
                    chunk["_parent_text"] = parent_text
                    all_chunks.append(chunk)

        return all_chunks


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Simple fixed-size chunking helper used by tests."""
    body = str(text or "")
    if chunk_size <= 0:
        return [body] if body else []

    step = chunk_size - max(0, int(overlap))
    if step <= 0:
        step = chunk_size

    chunks: list[str] = []
    if len(body) <= chunk_size:
        return [body] if body else []

    i = 0
    last_start = max(0, len(body) - chunk_size)
    while i <= last_start:
        part = body[i : i + chunk_size]
        if part:
            chunks.append(part)
        i += step
    return chunks


def parse_segments(content: str) -> list[Segment]:
    """Split markdown into paragraph segments and track heading hierarchy."""
    heading_stack: list[tuple[int, str]] = []
    segments: list[Segment] = []

    for raw in re.split(r"\n{2,}", str(content or "")):
        para = raw.strip()
        if not para:
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)", para)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            heading_stack = [
                (lvl, text)
                for lvl, text in heading_stack
                if lvl < level
            ]
            heading_stack.append((level, title))
            is_heading = True
            h_level = level
        else:
            is_heading = False
            h_level = 0

        segments.append(
            Segment(
                text=para,
                breadcrumb=[title for _, title in heading_stack],
                is_heading=is_heading,
                h_level=h_level,
            )
        )

    return segments


def split_large_segments(segments: list[Segment], max_chars: int) -> list[Segment]:
    """Split any segment larger than max_chars into smaller segments."""
    split: list[Segment] = []
    for segment in segments:
        if len(segment.text) > max_chars:
            split.extend(_split_segment(segment, max_chars))
        else:
            split.append(segment)
    return split


def build_chunks(
    content: str,
    config: ChunkingConfig,
    doc_name: str = "",
    logger: Any = None,
) -> list[dict[str, Any]]:
    """Build chunks using configured chunking strategy."""
    segments = parse_segments(content)
    if not segments:
        return []

    segments = split_large_segments(segments, max(1, int(config.chunk_size)))
    if logger is not None:
        try:
            logger.debug(
                "RAG",
                f"Parsed {len(segments)} segments"
                f"  |  chunk_size={config.chunk_size}"
                f"  |  strategy={config.strategy}",
            )
        except Exception:
            pass

    strategy = str(config.strategy or "sliding_window")
    if strategy == "section":
        return SectionChunker(config).chunk(segments, doc_name)
    if strategy == "recursive":
        return RecursiveChunker(config).chunk(segments, doc_name)
    return SlidingWindowChunker(config).chunk(segments, doc_name)


def make_chunk_dict(segs: list[Segment], config: ChunkingConfig, doc_name: str = "") -> dict[str, Any]:
    """Create indexable chunk payload."""
    raw_text = "\n\n".join(segment.text for segment in segs)
    breadcrumb = segs[-1].breadcrumb if segs else []

    if config.include_filename and doc_name:
        basename = os.path.basename(doc_name)
        prefix_parts = [basename]
        if config.include_headings and breadcrumb:
            prefix_parts.extend(breadcrumb)
        indexed_text = f"[{' › '.join(prefix_parts)}]\n\n{raw_text}"
    elif config.include_headings and breadcrumb:
        indexed_text = f"[{' › '.join(breadcrumb)}]\n\n{raw_text}"
    else:
        indexed_text = raw_text

    return {
        "text": indexed_text,
        "raw_text": raw_text,
        "breadcrumb": breadcrumb,
    }


def _group_by_level(segments: list[Segment], level: int) -> list[list[Segment]]:
    groups: list[list[Segment]] = []
    current: list[Segment] = []
    for seg in segments:
        if seg.is_heading and seg.h_level == level:
            if current:
                groups.append(current)
            current = [seg]
        else:
            current.append(seg)
    if current:
        groups.append(current)
    return groups if groups else [segments]


def _split_segment(segment: Segment, max_chars: int) -> list[Segment]:
    def hard_split(text: str, limit: int) -> list[str]:
        parts: list[str] = []
        body = text
        while len(body) > limit:
            cut = body.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            parts.append(body[:cut].strip())
            body = body[cut:].strip()
        if body:
            parts.append(body)
        return parts

    lines = segment.text.split("\n")
    groups: list[str] = []
    buffer: list[str] = []
    buffer_len = 0

    for line in lines:
        line_len = len(line)
        if line_len > max_chars:
            if buffer:
                groups.append("\n".join(buffer))
                buffer, buffer_len = [], 0
            groups.extend(hard_split(line, max_chars))
        elif buffer and buffer_len + line_len + 1 > max_chars:
            groups.append("\n".join(buffer))
            buffer, buffer_len = [line], line_len
        else:
            buffer.append(line)
            buffer_len += line_len + 1

    if buffer:
        groups.append("\n".join(buffer))

    return [
        Segment(
            text=group,
            breadcrumb=list(segment.breadcrumb),
            is_heading=segment.is_heading,
            h_level=segment.h_level,
        )
        for group in groups
        if group.strip()
    ] or [segment]
