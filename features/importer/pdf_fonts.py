"""Font-size analysis helpers for PDF importer."""
from __future__ import annotations

from collections import Counter, defaultdict

from .models import PDFImportSettings


def _compute_body_font_size(
    doc,
    top_zone: float = 0.10,
    bottom_zone: float = 0.10,
) -> float:
    """Return median body-text font size, skipping margin zones."""
    sizes: list[float] = []
    for page in doc:
        height = page.rect.height or 1.0
        top_limit = height * top_zone
        bottom_limit = height * (1.0 - bottom_zone)
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            by0 = block["bbox"][1]
            by1 = block["bbox"][3]
            if by1 <= top_limit or by0 >= bottom_limit:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    size = span.get("size", 0)
                    if size > 0:
                        sizes.append(size)
    if not sizes:
        return 11.0
    sizes.sort()
    return sizes[len(sizes) // 2]


def analyze_pdf_fonts(path: str, settings: PDFImportSettings) -> dict:
    """
    Inspect all text spans in a PDF and compute font-size statistics.

    Returns keys:
    - body_size
    - clusters
    - body_fonts
    - heading_fonts
    - suggested_h1/suggested_h2/suggested_h3
    - info
    """
    try:
        import fitz  # type: ignore
    except ImportError:
        return {
            "info": "PyMuPDF (fitz) not available.",
            "body_size": 11.0,
            "clusters": [],
            "body_fonts": [],
            "heading_fonts": [],
            "suggested_h1": 1.40,
            "suggested_h2": 1.20,
            "suggested_h3": 1.05,
        }

    doc = fitz.open(path)
    n_pages = len(doc)
    top_limit_frac = settings.hf_top_zone
    bottom_limit_frac = settings.hf_bottom_zone

    body_sizes: list[float] = []
    body_fonts: Counter = Counter()
    all_sizes: list[float] = []
    all_fonts_by_size: dict[float, Counter] = defaultdict(Counter)

    for pi, page in enumerate(doc):
        height = page.rect.height or 1.0
        top_limit = height * top_limit_frac
        bottom_limit = height * (1.0 - bottom_limit_frac)

        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            by0 = block["bbox"][1]
            by1 = block["bbox"][3]
            in_body = by1 > top_limit and by0 < bottom_limit

            for line in block["lines"]:
                for span in line["spans"]:
                    size = round(span.get("size", 0) * 2) / 2
                    font = span.get("font", "")
                    text = (span.get("text") or "").strip()
                    if size <= 0 or not text:
                        continue
                    all_sizes.append(size)
                    all_fonts_by_size[size][font] += len(text)
                    if in_body and (pi > 0 or n_pages == 1):
                        body_sizes.append(size)
                        body_fonts[font] += len(text)

    doc.close()

    if not body_sizes:
        body_sizes = all_sizes or [11.0]

    body_sizes.sort()
    body_size = body_sizes[len(body_sizes) // 2]

    size_counter = Counter(round(value * 2) / 2 for value in all_sizes)
    raw_items = sorted(size_counter.items())
    clusters: list[list] = []
    for size, count in raw_items:
        if clusters and abs(size - clusters[-1][0]) <= 0.5:
            clusters[-1][1] += count
            if count > 0:
                clusters[-1][0] = (
                    size if count >= clusters[-1][1] // 2 else clusters[-1][0]
                )
        else:
            clusters.append([size, count])

    heading_fonts: set[str] = set()
    for size, font_counter in all_fonts_by_size.items():
        if size > body_size * 1.05:
            for font in font_counter:
                if font not in body_fonts:
                    heading_fonts.add(font)

    larger = [(size, count) for size, count in clusters if size > body_size * 1.03]

    def _ratio(size: float) -> float:
        if body_size <= 0:
            return 1.0
        return round(size / body_size, 3)

    suggested_h1 = _ratio(larger[0][0]) if len(larger) >= 1 else 1.40
    suggested_h2 = _ratio(larger[1][0]) if len(larger) >= 2 else 1.20
    suggested_h3 = min(
        (_ratio(size) for size, _ in larger if _ratio(size) > 1.03),
        default=1.05,
    )

    ratios = sorted([suggested_h1, suggested_h2, suggested_h3], reverse=True)
    suggested_h1, suggested_h2, suggested_h3 = ratios

    top_body = [font for font, _ in body_fonts.most_common(3)]
    top_heading = sorted(heading_fonts)[:4]

    info_lines = [
        f"PDF:  {n_pages} pages  |  Median body font size: {body_size:.1f} pt",
        "",
        "Font size clusters (size → page count):",
    ]
    for size, count in clusters:
        marker = "  ← body" if abs(size - body_size) < 0.6 else ""
        ratio = _ratio(size)
        info_lines.append(f"  {size:5.1f} pt  ×{ratio:.3f}  ({count} spans){marker}")

    info_lines += [
        "",
        f"Body fonts:    {', '.join(top_body) or '—'}",
        f"Heading fonts: {', '.join(top_heading) or '—'}",
        "",
        "Suggested heading ratios  (relative to body size):",
        f"  H1 ratio: {suggested_h1:.3f}   (≥ {body_size * suggested_h1:.1f} pt)",
        f"  H2 ratio: {suggested_h2:.3f}   (≥ {body_size * suggested_h2:.1f} pt)",
        f"  H3 ratio: {suggested_h3:.3f}   (≥ {body_size * suggested_h3:.1f} pt)",
        "",
        "Use 'Analyze Fonts + Apply' to compute and apply these values.",
    ]

    return {
        "body_size": body_size,
        "clusters": [(size, count) for size, count in clusters],
        "body_fonts": top_body,
        "heading_fonts": top_heading,
        "suggested_h1": suggested_h1,
        "suggested_h2": suggested_h2,
        "suggested_h3": suggested_h3,
        "info": "\n".join(info_lines),
    }

