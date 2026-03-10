"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

@classmethod
def _restore_extra_blank_lines_from_plaintext(
    cls,
    markdown_text: str,
    plain_text: str,
) -> str:
    """
    Restore user-added extra blank paragraphs from HTML editor input.

    Qt's toMarkdown() collapses repeated empty paragraphs. We preserve
    additional blank lines by inserting invisible spacer paragraphs between
    blocks where plain-text block gaps are larger than the markdown gap.
    """
    md = str(markdown_text or "").replace("\r\n", "\n")
    plain = str(plain_text or "").replace("\r\n", "\n")
    if not md or not plain:
        return md

    md_rows = cls._nonempty_normalized_rows(md)
    plain_rows = cls._nonempty_normalized_rows(plain)
    if len(md_rows) < 2 or len(md_rows) != len(plain_rows):
        return md
    if any(md_rows[idx][0] != plain_rows[idx][0] for idx in range(len(md_rows))):
        return md

    lines = md.split("\n")
    offset = 0
    changed = False
    for idx in range(len(md_rows) - 1):
        start = int(md_rows[idx][1]) + offset
        end = int(md_rows[idx + 1][1]) + offset
        if end <= start:
            continue
        region = lines[start + 1:end]
        if not region:
            continue
        if not all(cls._line_is_blank_like(line) for line in region):
            continue

        desired_extra = max(0, int(plain_rows[idx][2]))
        target_region = [""]
        for _ in range(desired_extra):
            target_region.append(cls._BLANK_LINE_SENTINEL)
            target_region.append("")

        if region == target_region:
            continue
        lines[start + 1:end] = target_region
        offset += len(target_region) - len(region)
        changed = True

    if not changed:
        return md
    return "\n".join(lines)
@classmethod
def _restore_blank_like_runs_from_reference(
    cls,
    markdown_text: str,
    reference_markdown: str,
) -> str:
    """
    Restore blank-like separator runs from a markdown reference text.

    Used for preview toolbar formatting actions: Qt may rewrite soft line
    breaks into blank-line-separated blocks during toMarkdown() export.
    When token order is unchanged, we transplant only the inter-row blank
    runs from the reference so original line wrapping is preserved.
    """
    md = str(markdown_text or "").replace("\r\n", "\n")
    ref = str(reference_markdown or "").replace("\r\n", "\n")
    if not md or not ref:
        return md

    md_rows = cls._nonempty_normalized_rows(md)
    ref_rows = cls._nonempty_normalized_rows(ref)
    if len(md_rows) < 2 or len(md_rows) != len(ref_rows):
        return md
    if any(md_rows[idx][0] != ref_rows[idx][0] for idx in range(len(md_rows))):
        return md

    md_lines = md.split("\n")
    ref_lines = ref.split("\n")
    offset = 0
    changed = False
    for idx in range(len(md_rows) - 1):
        md_start = int(md_rows[idx][1]) + offset
        md_end = int(md_rows[idx + 1][1]) + offset
        ref_start = int(ref_rows[idx][1])
        ref_end = int(ref_rows[idx + 1][1])
        if md_end <= md_start:
            continue

        md_region = md_lines[md_start + 1:md_end]
        ref_region = ref_lines[ref_start + 1:ref_end]
        if not all(cls._line_is_blank_like(line) for line in md_region):
            continue
        if not all(cls._line_is_blank_like(line) for line in ref_region):
            continue
        if md_region == ref_region:
            continue

        md_lines[md_start + 1:md_end] = ref_region
        offset += len(ref_region) - len(md_region)
        changed = True

    if not changed:
        return md
    return "\n".join(md_lines)
@classmethod
def _is_plain_paragraph_line_for_wrap_restore(cls, line: str) -> bool:
    raw = str(line or "")
    stripped = raw.strip()
    if not stripped:
        return False
    if cls._line_is_blank_like(raw):
        return False
    if re.match(r"^([`~]{3,})", stripped):
        return False
    if re.match(r"^#{1,6}\s+", stripped):
        return False
    if raw.startswith("    ") or raw.startswith("\t"):
        return False
    if re.match(r"^\s*>", raw):
        return False
    if cls._BULLET_ITEM_RE.match(raw) is not None:
        return False
    if cls._ORDERED_ITEM_RE.match(raw) is not None:
        return False
    if re.match(r"^\s*[-*_]{3,}\s*$", raw):
        return False
    if re.match(r"^\s*\|", raw):
        return False
    if re.match(r"^\s*<[^>]+>\s*$", raw):
        return False
    return True
@classmethod
def _restore_soft_wrapped_plain_lines_from_reference(
    cls,
    markdown_text: str,
    reference_markdown: str,
) -> str:
    """
    Undo Qt soft-wrap artifacts for plain paragraphs.

    QTextDocument.toMarkdown() may rewrite a single long paragraph line
    into multiple hard line breaks. If a non-blank block is plain text in
    both versions and collapses to the same content, restore the original
    block line layout from the markdown reference.
    """
    md = str(markdown_text or "").replace("\r\n", "\n")
    ref = str(reference_markdown or "").replace("\r\n", "\n")
    if not md or not ref:
        return md

    md_lines = md.split("\n")
    ref_lines = ref.split("\n")

    def nonblank_blocks(lines: list[str]) -> list[tuple[int, int]]:
        blocks: list[tuple[int, int]] = []
        idx = 0
        count = len(lines)
        while idx < count:
            while idx < count and cls._line_is_blank_like(lines[idx]):
                idx += 1
            if idx >= count:
                break
            start = idx
            while idx < count and not cls._line_is_blank_like(lines[idx]):
                idx += 1
            blocks.append((start, idx))
        return blocks

    md_blocks = nonblank_blocks(md_lines)
    ref_blocks = nonblank_blocks(ref_lines)
    if not md_blocks or len(md_blocks) != len(ref_blocks):
        return md

    def collapse_block(lines: list[str]) -> str:
        return re.sub(r"\s+", " ", " ".join(lines)).strip()

    changed = False
    offset = 0
    for block_index, (md_start_raw, md_end_raw) in enumerate(md_blocks):
        ref_start, ref_end = ref_blocks[block_index]
        md_start = md_start_raw + offset
        md_end = md_end_raw + offset
        if md_end <= md_start or ref_end <= ref_start:
            continue

        md_block = md_lines[md_start:md_end]
        ref_block = ref_lines[ref_start:ref_end]
        if len(md_block) <= 1 or len(ref_block) != 1:
            continue
        if not all(
            cls._is_plain_paragraph_line_for_wrap_restore(line)
            for line in md_block
        ):
            continue
        if not all(
            cls._is_plain_paragraph_line_for_wrap_restore(line)
            for line in ref_block
        ):
            continue
        if collapse_block(md_block).casefold() != collapse_block(ref_block).casefold():
            continue
        if md_block == ref_block:
            continue

        md_lines[md_start:md_end] = ref_block
        offset += len(ref_block) - len(md_block)
        changed = True

    if not changed:
        return md
    return "\n".join(md_lines)
@staticmethod
def _line_has_explicit_hard_break_marker(line: str) -> bool:
    stripped_right = str(line or "").rstrip()
    if stripped_right.endswith("\\"):
        return True
    if re.search(r"<br\s*/?>\s*$", stripped_right, flags=re.IGNORECASE):
        return True
    # Markdown hard break via two trailing spaces.
    return bool(re.search(r"[ ]{2,}$", str(line or "")))
@classmethod
def _unwrap_soft_wrapped_plain_paragraphs(cls, markdown_text: str) -> str:
    """
    Collapse Qt-introduced soft-wrap line breaks in plain paragraphs.

    QTextDocument.toMarkdown() may hard-wrap long paragraph lines at a
    visual width. Those breaks are not semantic paragraph boundaries and
    should not be persisted back into source markdown.
    """
    md = str(markdown_text or "").replace("\r\n", "\n")
    if not md:
        return md
    lines = md.split("\n")
    out: list[str] = []
    idx = 0
    total = len(lines)
    while idx < total:
        line = lines[idx]
        if cls._line_is_blank_like(line):
            out.append(line)
            idx += 1
            continue

        start = idx
        while idx < total and not cls._line_is_blank_like(lines[idx]):
            idx += 1
        block = lines[start:idx]
        if len(block) <= 1:
            out.extend(block)
            continue
        if not all(
            cls._is_plain_paragraph_line_for_wrap_restore(part)
            for part in block
        ):
            out.extend(block)
            continue
        if any(
            cls._line_has_explicit_hard_break_marker(part)
            for part in block[:-1]
        ):
            out.extend(block)
            continue

        merged = re.sub(r"\s+", " ", " ".join(part.strip() for part in block)).strip()
        out.append(merged)
    return "\n".join(out)

__all__ = [
    "_restore_extra_blank_lines_from_plaintext",
    "_restore_blank_like_runs_from_reference",
    "_is_plain_paragraph_line_for_wrap_restore",
    "_restore_soft_wrapped_plain_lines_from_reference",
    "_line_has_explicit_hard_break_marker",
    "_unwrap_soft_wrapped_plain_paragraphs",
]
