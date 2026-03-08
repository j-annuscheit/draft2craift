from __future__ import annotations

import os
import re

from .pdf_reflow import (
    _header_looks_like_data_row,
    _limit_dot_leaders,
    _replace_html_br_with_space,
)

_MD_TABLE_ROW = re.compile(r"^\|")
_MD_SECTION_NUM_HEADING = re.compile(r"^#{1,6}\s+(\d+)\)")
_PDF_SECTION_NUM_HEADING = re.compile(r"^\s*(\d+)\)\s+(.+)$")
_TABLEISH_HEADING_RE = re.compile(r"(table|tabelle|tabellen|longtable|grid|matrix|summenlinie)", re.IGNORECASE)
_GENERIC_COL_RE = re.compile(r"^col\d+$", re.IGNORECASE)
_CURRENCY_ONLY_RE = re.compile(r"^[€$£¥₹]+$")
_TABLE_MENTION_RE = re.compile(r"\b(?:tabelle|tabellen|table|tables)\b", re.IGNORECASE)
_RISKY_TABLE_DETECTION_ENABLED = str(
    os.getenv("D2C_ENABLE_RISKY_PYMUPDF_TABLES", "")
).strip().lower() in {"1", "true", "yes", "on"}


def _safe_find_tables(page, **kwargs):
    """
    Wrapper for PyMuPDF ``find_tables``.

    Disabled by default because some PDFs trigger hard native crashes inside
    PyMuPDF table detection (not catchable via Python exceptions).
    Re-enable explicitly via:
      D2C_ENABLE_RISKY_PYMUPDF_TABLES=1
    """
    if not _RISKY_TABLE_DETECTION_ENABLED:
        return None
    return page.find_tables(**kwargs)


def _rect_intersection_ratio(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(1.0, (ax1 - ax0) * (ay1 - ay0))
    return inter / area_a


def _extract_table_bboxes(page, clip: tuple[float, float, float, float] | None = None) -> list[tuple[float, float, float, float]]:
    if not _RISKY_TABLE_DETECTION_ENABLED:
        return []
    rects: list[tuple[float, float, float, float]] = []
    for strategy in ("lines_strict", "lines"):
        try:
            tabs = _safe_find_tables(page, strategy=strategy, clip=clip)
        except Exception:
            continue
        if tabs is None:
            continue
        for t in getattr(tabs, "tables", []):
            if int(getattr(t, "row_count", 0) or 0) < 2 or int(getattr(t, "col_count", 0) or 0) < 2:
                continue
            bx0, by0, bx1, by1 = [float(v) for v in t.bbox]
            rects.append((bx0, by0, bx1, by1))
    return rects


def _markdown_section_ranges(lines: list[str]) -> dict[int, tuple[int, int]]:
    heads: list[tuple[int, int]] = []
    for i, ln in enumerate(lines):
        m = _MD_SECTION_NUM_HEADING.match(ln.strip())
        if m:
            heads.append((i, int(m.group(1))))

    out: dict[int, tuple[int, int]] = {}
    for idx, (start, sec) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        out[sec] = (start, end)
    return out


def _pdf_tableish_section_regions(
    page,
    top_m: float,
    bottom_m: float,
) -> list[tuple[int, tuple[float, float, float, float]]]:
    h = float(page.rect.height or 0.0)
    w = float(page.rect.width or 0.0)
    if h <= 0 or w <= 0:
        return []

    body_y0 = max(0.0, top_m)
    body_y1 = min(h, h - max(0.0, bottom_m))
    if body_y1 - body_y0 < 20:
        return []

    headings: list[tuple[int, float, float, str, bool]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            ly0 = float(line.get("bbox", (0.0, 0.0, 0.0, 0.0))[1])
            ly1 = float(line.get("bbox", (0.0, 0.0, 0.0, 0.0))[3])
            if ly1 <= body_y0 or ly0 >= body_y1:
                continue
            text = "".join((s.get("text") or "") for s in line.get("spans", [])).strip()
            m = _PDF_SECTION_NUM_HEADING.match(text)
            if not m:
                continue
            sec = int(m.group(1))
            title = m.group(2).strip()
            is_tableish = bool(_TABLEISH_HEADING_RE.search(title))
            headings.append((sec, ly0, ly1, title, is_tableish))

    headings.sort(key=lambda x: x[1])
    out: list[tuple[int, tuple[float, float, float, float]]] = []
    x0 = 40.0
    x1 = max(x0 + 50.0, w - 40.0)
    for i, (sec, _hy0, hy1, _title, is_tableish) in enumerate(headings):
        if not is_tableish:
            continue
        next_y = headings[i + 1][1] if i + 1 < len(headings) else body_y1
        ry0 = max(body_y0, hy1 + 4.0)
        ry1 = min(body_y1, next_y - 4.0)
        if ry1 - ry0 < 36.0:
            continue
        out.append((sec, (x0, ry0, x1, ry1)))
    return out


def _normalize_table_rows(rows: list[list[object]]) -> list[list[str]]:
    mat = [
        [re.sub(r"\s+", " ", str(c or "").replace("\n", " ").strip()) for c in r]
        for r in rows
    ]
    mat = [r for r in mat if any(c for c in r)]
    if not mat:
        return []

    ncols = max(len(r) for r in mat)
    mat = [r + [""] * (ncols - len(r)) for r in mat]

    # Move semantic headers like "Price"/"Total" onto the first populated data column to the right.
    for c in range(ncols):
        header = mat[0][c].strip()
        if not header:
            continue
        if any(mat[r][c].strip() for r in range(1, len(mat))):
            continue
        for cc in range(c + 1, ncols):
            if mat[0][cc].strip():
                break
            if any(mat[r][cc].strip() for r in range(1, len(mat))):
                mat[0][cc] = header
                mat[0][c] = ""
                break

    # Merge currency-only columns into their left numeric/text columns.
    for c in range(1, ncols):
        vals = [mat[r][c].strip() for r in range(1, len(mat)) if mat[r][c].strip()]
        if not vals:
            continue
        if all(_CURRENCY_ONLY_RE.match(v) for v in vals):
            for r in range(1, len(mat)):
                cur = mat[r][c].strip()
                if not cur:
                    continue
                left = mat[r][c - 1].strip()
                mat[r][c - 1] = (f"{left} {cur}".strip() if left else cur)
                mat[r][c] = ""

    # Drop empty placeholder rows.
    mat = [r for r in mat if any(c.strip() for c in r)]
    if not mat:
        return []

    # Merge continuation rows that only continue right-side cells.
    out: list[list[str]] = [mat[0]]
    for row in mat[1:]:
        nz = [i for i, c in enumerate(row) if c.strip()]
        # Wrapped row fragment: starts with lowercase in col0 and has only
        # very few populated cells -> append to previous row's last content cell.
        if nz and out and 0 in nz and len(nz) <= 2 and row[0] and row[0][0].islower():
            prev = out[-1]
            target = max((i for i, c in enumerate(prev) if c.strip()), default=len(prev) - 1)
            frag = " ".join(row[i].strip() for i in nz if row[i].strip())
            prev[target] = f"{prev[target]}<br>{frag}".strip("<br>") if prev[target] else frag
            continue
        if nz and out and len(nz) <= 2 and nz[0] > 0 and all(not row[i].strip() for i in range(nz[0])):
            prev = out[-1]
            for i in nz:
                prev[i] = f"{prev[i]}<br>{row[i]}".strip("<br>") if prev[i] else row[i]
            continue
        out.append(row)
    mat = out

    ncols = len(mat[0])
    counts = [sum(1 for r in mat if r[c].strip()) for c in range(ncols)]
    data_rows = max(1, len(mat) - 1)
    keep_idx: list[int] = []
    for c in range(ncols):
        hdr = mat[0][c].strip()
        cnt_data = sum(1 for r in mat[1:] if r[c].strip())
        if cnt_data > 0:
            keep_idx.append(c)
            continue
        if hdr and not _GENERIC_COL_RE.match(hdr):
            keep_idx.append(c)
            continue
        if hdr and _GENERIC_COL_RE.match(hdr) and counts[c] >= max(2, int(data_rows * 0.35)):
            keep_idx.append(c)

    if not keep_idx:
        return []

    mat = [[row[c] for c in keep_idx] for row in mat]
    return mat


def _table_markdown_from_rows(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    first = [c.strip() for c in rows[0]]

    def _row_looks_like_data_row(cells: list[str]) -> bool:
        vals = [c.strip().strip("`").strip() for c in cells if c.strip()]
        if len(vals) < 2:
            return False
        first_is_index = bool(re.match(r"^\d+$", vals[0]))
        numericish = sum(
            1
            for v in vals
            if re.match(r"^[+-]?\d+(?:[.,]\d+)?%?$", v) or re.match(r"^[+-]?\d+\s*(?:€|\$|£|¥|₹)$", v)
        )
        return first_is_index or numericish >= 2

    if _row_looks_like_data_row(first):
        # Headerless table: synthesize stable markdown headers.
        header = [f"Col{i + 1}" for i in range(ncols)]
        body = rows
    else:
        header = first
        body = rows[1:]

    # Fallback header names for remaining empty columns.
    for i, c in enumerate(header):
        if not c:
            header[i] = f"Col{i + 1}"

    out = [
        "|" + "|".join(header) + "|",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    for r in body:
        out.append(
            "|" + "|".join(
                _limit_dot_leaders(_replace_html_br_with_space(c.strip()))
                for c in r
            ) + "|"
        )
    return "\n".join(out)


def _best_text_table_in_clip(page, clip: tuple[float, float, float, float]) -> str:
    if not _RISKY_TABLE_DETECTION_ENABLED:
        return ""
    best_score = -1.0
    best_md = ""
    clip_area = max(1.0, (clip[2] - clip[0]) * (clip[3] - clip[1]))

    for mwv in (1, 2):
        try:
            tabs = _safe_find_tables(
                page,
                strategy="text",
                clip=clip,
                min_words_vertical=mwv,
                min_words_horizontal=1,
            )
        except Exception:
            continue
        if tabs is None:
            continue
        for t in getattr(tabs, "tables", []):
            mat = _normalize_table_rows(t.extract())
            if not mat:
                continue
            rows = len(mat)
            cols = len(mat[0])
            if rows < 3 or cols < 2 or cols > 8:
                continue
            header_nonempty = sum(1 for c in mat[0] if c.strip())
            if header_nonempty < 2:
                continue
            nonempty = sum(1 for r in mat for c in r if c.strip())
            density = nonempty / max(1, rows * cols)
            if density < 0.30:
                continue
            bx0, by0, bx1, by1 = [float(v) for v in t.bbox]
            area_ratio = ((bx1 - bx0) * (by1 - by0)) / clip_area
            score = density + (rows * 0.02) + (header_nonempty * 0.06) + (area_ratio * 0.3)
            md = _table_markdown_from_rows(mat)
            if not md:
                continue
            if score > best_score:
                best_score = score
                best_md = md
    return best_md


def _normalize_table_match_text(text: str) -> str:
    if not text:
        return ""
    t = _replace_html_br_with_space(text)
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = re.sub(r"(?<=\D)\d+(?=\D)", " ", t)
    t = re.sub(r"[*_`]", " ", t)
    t = re.sub(r"[^\wäöüß]+", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip().casefold()
    return t


def _row_anchor_text(row: list[str]) -> str:
    best = ""
    for cell in row:
        n = _normalize_table_match_text(cell)
        if not n:
            continue
        if len(n.split()) >= 3:
            return n
        if len(n) > len(best):
            best = n
    if best:
        return best
    joined = _normalize_table_match_text(" ".join(row))
    if not joined:
        return ""
    return " ".join(joined.split()[:8])


def _best_lines_table_candidate(
    page,
    top_m: float,
    bottom_m: float,
) -> tuple[str, list[list[str]]]:
    if not _RISKY_TABLE_DETECTION_ENABLED:
        return "", []
    h = float(page.rect.height or 0.0)
    w = float(page.rect.width or 0.0)
    if h <= 0 or w <= 0:
        return "", []

    clip = (40.0, max(0.0, top_m), max(90.0, w - 40.0), max(0.0, h - max(0.0, bottom_m)))
    clip_area = max(1.0, (clip[2] - clip[0]) * (clip[3] - clip[1]))

    best_score = -1.0
    best_md = ""
    best_mat: list[list[str]] = []
    seen_boxes: set[tuple[float, float, float, float]] = set()

    for strategy in ("lines_strict", "lines"):
        try:
            tabs = _safe_find_tables(page, strategy=strategy, clip=clip)
        except Exception:
            continue
        if tabs is None:
            continue
        for t in getattr(tabs, "tables", []):
            rows = int(getattr(t, "row_count", 0) or 0)
            cols = int(getattr(t, "col_count", 0) or 0)
            if rows < 3 or cols < 2:
                continue

            bx0, by0, bx1, by1 = [float(v) for v in t.bbox]
            box_key = (round(bx0, 1), round(by0, 1), round(bx1, 1), round(by1, 1))
            if box_key in seen_boxes:
                continue
            seen_boxes.add(box_key)

            mat = _normalize_table_rows(t.extract())
            if len(mat) < 3 or len(mat[0]) < 2:
                continue

            md = _table_markdown_from_rows(mat)
            if not md:
                continue

            nonempty = sum(1 for r in mat for c in r if c.strip())
            density = nonempty / max(1, len(mat) * len(mat[0]))
            if density < 0.35:
                continue

            area_ratio = ((bx1 - bx0) * (by1 - by0)) / clip_area
            score = (len(mat) * len(mat[0])) + (density * 2.0) + (area_ratio * 18.0)
            if score > best_score:
                best_score = score
                best_md = md
                best_mat = mat

    return best_md, best_mat


def _inject_lines_table_markdown(
    page,
    page_text: str,
    top_m: float,
    bottom_m: float,
) -> str:
    table_md, table_rows = _best_lines_table_candidate(page, top_m, bottom_m)
    if not table_md or len(table_rows) < 3:
        return page_text

    has_md_table = bool(re.search(r"(?m)^\|.+\|$", page_text))
    lines = page_text.splitlines()
    if not lines:
        return page_text

    norm_lines = [_normalize_table_match_text(ln) for ln in lines]
    header_is_data = _header_looks_like_data_row(table_rows[0])
    data_rows = table_rows if header_is_data else table_rows[1:]
    anchors = []
    seen_anchor = set()
    for row in data_rows:
        anchor = _row_anchor_text(row)
        if not anchor or len(anchor.split()) < 2:
            continue
        if anchor in seen_anchor:
            continue
        seen_anchor.add(anchor)
        anchors.append(anchor)

    match_idx: list[int] = []
    line_token_cache = [set(n.split()) for n in norm_lines]
    for anchor in anchors:
        anchor_tokens = set(anchor.split())
        if not anchor_tokens:
            continue
        best_i = -1
        best_ratio = 0.0
        for i, ln_norm in enumerate(norm_lines):
            if not ln_norm or lines[i].lstrip().startswith("|"):
                continue
            if anchor in ln_norm:
                best_i = i
                best_ratio = 1.0
                break
            ratio = len(anchor_tokens & line_token_cache[i]) / max(1, len(anchor_tokens))
            if ratio > best_ratio:
                best_i = i
                best_ratio = ratio
        if best_i >= 0 and best_ratio >= 0.60:
            match_idx.append(best_i)

    unique_matches = sorted(set(match_idx))
    min_needed = max(2, min(4, max(2, len(anchors) // 2)))

    start = end = -1
    if len(unique_matches) >= min_needed:
        start = unique_matches[0]
        end = unique_matches[-1]
        if end - start > max(24, len(anchors) * 4 + 8):
            start = end = -1

    if start >= 0 and end >= start:
        header_words = {
            tok
            for tok in _normalize_table_match_text(" ".join(table_rows[0])).split()
            if len(tok) >= 6
        }
        i = start - 1
        while i >= 0 and start - i <= 8:
            ln = lines[i]
            if not ln.strip():
                i -= 1
                continue
            ln_norm = norm_lines[i]
            ln_tokens = line_token_cache[i]
            if (header_words and bool(header_words & ln_tokens)) or ("prozent" in ln_norm and len(ln_tokens) <= 12):
                start = i
                i -= 1
                continue
            break

        out = lines[:start]
        if out and out[-1].strip():
            out.append("")
        out.extend(table_md.splitlines())
        if end + 1 < len(lines) and lines[end + 1].strip():
            out.append("")
        out.extend(lines[end + 1:])
        merged = "\n".join(out)
        return re.sub(r"\n{3,}", "\n\n", merged).strip()

    # If markdown tables already exist, avoid duplicate injection when anchors
    # are weak / ambiguous.
    if has_md_table:
        return page_text

    # Fallback: table found geometrically, but plain-text anchors were weak.
    # Insert after the nearest explicit table mention (or append at end).
    insert_at = -1
    for i, ln in enumerate(lines):
        if _TABLE_MENTION_RE.search(ln):
            insert_at = i + 1
    if insert_at < 0:
        insert_at = len(lines)

    out = lines[:insert_at]
    if out and out[-1].strip():
        out.append("")
    out.extend(table_md.splitlines())
    if insert_at < len(lines) and lines[insert_at].strip():
        out.append("")
    out.extend(lines[insert_at:])
    merged = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", merged).strip()


def _inject_recovered_section_tables(
    page,
    page_text: str,
    top_m: float,
    bottom_m: float,
) -> str:
    if not page_text.strip():
        return page_text

    lines = page_text.splitlines()
    sections = _markdown_section_ranges(lines)
    if not sections:
        return page_text

    recovered: dict[int, str] = {}
    for sec, clip in _pdf_tableish_section_regions(page, top_m, bottom_m):
        md = _best_text_table_in_clip(page, clip).strip()
        if md:
            recovered[sec] = md

    if not recovered:
        return page_text

    for sec in sorted(recovered.keys(), reverse=True):
        if sec not in sections:
            continue
        start, end = sections[sec]
        section_body = "\n".join(lines[start + 1:end])
        if re.search(r"(?m)^\|.+\|$", section_body):
            continue
        table_lines = recovered[sec].splitlines()
        lines = lines[: start + 1] + [""] + table_lines + [""] + lines[end:]
    joined = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


def _recover_dominant_lines_table(
    page,
    page_text: str,
    top_m: float,
    bottom_m: float,
) -> str:
    if not _RISKY_TABLE_DETECTION_ENABLED:
        return page_text
    if re.search(r"(?m)^\|.+\|$", page_text):
        return page_text

    h = float(page.rect.height or 0.0)
    w = float(page.rect.width or 0.0)
    if h <= 0 or w <= 0:
        return page_text

    clip = (40.0, max(0.0, top_m), max(90.0, w - 40.0), max(0.0, h - max(0.0, bottom_m)))
    body_area = max(1.0, (clip[2] - clip[0]) * (clip[3] - clip[1]))

    best = None
    best_ratio = 0.0
    for strategy in ("lines_strict", "lines"):
        try:
            tabs = _safe_find_tables(page, strategy=strategy, clip=clip)
        except Exception:
            continue
        if tabs is None:
            continue
        for t in getattr(tabs, "tables", []):
            rows = int(getattr(t, "row_count", 0) or 0)
            cols = int(getattr(t, "col_count", 0) or 0)
            if rows < 8 or cols < 3:
                continue
            bx0, by0, bx1, by1 = [float(v) for v in t.bbox]
            ratio = ((bx1 - bx0) * (by1 - by0)) / body_area
            if ratio > best_ratio:
                best_ratio = ratio
                best = t

    if best is None or best_ratio < 0.55:
        return page_text

    try:
        md = best.to_markdown().strip()
    except Exception:
        return page_text
    if not md:
        return page_text
    return md


def _recover_tables_in_page_markdown(
    page,
    page_text: str,
    top_m: float,
    bottom_m: float,
) -> str:
    updated = _inject_recovered_section_tables(page, page_text, top_m, bottom_m)
    updated = _recover_dominant_lines_table(page, updated, top_m, bottom_m)
    updated = _inject_lines_table_markdown(page, updated, top_m, bottom_m)
    return updated.strip()
