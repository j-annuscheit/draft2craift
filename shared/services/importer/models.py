from __future__ import annotations

from dataclasses import dataclass, field

# ── Code-file extensions ─────────────────────────────────────────────────────

_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
    ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt",
    ".sh", ".bash", ".zsh", ".fish", ".lua", ".r", ".m", ".jl",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".json",
    ".xml", ".sql", ".dockerfile", ".makefile",
}

_SUPPORTED_FILTER = (
    "Supported Files (*.pdf *.docx *.html *.htm *.csv *.txt *.rst *.md *.markdown "
    "*.odt *.py *.js *.ts *.jsx *.tsx *.java *.c *.cpp *.h *.hpp *.cs *.go *.rs "
    "*.rb *.php *.swift *.kt *.sh *.lua *.r *.yaml *.yml *.toml *.json *.xml *.sql);;"
    "All Files (*)"
)


@dataclass
class PDFImportSettings:
    """
    All tunable parameters for PDF → Markdown conversion via pymupdf4llm.
    Stored per file in ``ImportEntry.pdf_settings`` (managed by FileImportDialog).
    """

    # ── Backend ──────────────────────────────────────────────────────────────
    # "pymupdf"  – custom pipeline via pymupdf4llm (full manual control)
    # "docling"  – AI-based pipeline via Docling (automatic layout analysis)
    backend: str = "pymupdf"

    # ── Docling-specific options (only used when backend == "docling") ─────────
    # Extract and embed images as base64 in the HTML preview.
    docling_images: bool = True
    # Scale factor for extracted images (1.0 = draft, 2.0 = standard, 3.0 = high-res).
    docling_images_scale: float = 2.0
    # Recognise formulas and render them as LaTeX → PNG (requires the
    # CodeFormulaV2 model, ~1 GB download on first use).
    docling_formulas: bool = False
    # Recognise code blocks with a specialized enrichment model (~0.5 GB).
    docling_code: bool = False

    # ── Docling OCR ──────────────────────────────────────────────────────────
    # Apply OCR on pages that contain bitmap/scanned content.
    docling_ocr: bool = True
    # Force full-page OCR even on pages with native text.
    docling_ocr_force_full_page: bool = False
    # Comma-separated OCR language codes, e.g. "de,en"  (empty = auto-detect).
    docling_ocr_lang: str = ""

    # ── Docling table structure ───────────────────────────────────────────────
    # "accurate" uses TableFormerMode.ACCURATE (default), "fast" uses FAST.
    docling_table_mode: str = "accurate"

    # ── Docling performance / advanced ───────────────────────────────────────
    # Max. processing time in seconds per document (0 = no limit).
    docling_timeout: float = 0.0
    # CPU threads for the Docling pipeline (0 = auto).
    docling_num_threads: int = 0
    # When True, use native PDF text instead of the layout-model predictions.
    docling_force_backend_text: bool = False

    # ── General ─────────────────────────────────────────────────────────────
    page_range: str = "all"               # "all"  or  "1-5,7,9-"
    show_page_markers: bool = True

    # ── Tables & Images ──────────────────────────────────────────────────────
    dpi: int = 150
    write_images: bool = False
    image_format: str = "png"
    graphics_limit: int = 50             # 0 = unlimited

    # ── Table extraction ─────────────────────────────────────────────────────
    table_strategy: str = "lines_strict"  # "lines_strict"|"lines"|"text"|"none"

    # ── Header / footer auto-detection ──────────────────────────────────────
    auto_hf_detect: bool = True
    hf_top_zone: float = 0.10
    hf_bottom_zone: float = 0.10
    hf_min_pages: int = 3
    hf_threshold: float = 0.10
    hf_max_pairs: int = 3

    # ── Heading detection ────────────────────────────────────────────────────
    # "pymupdf4llm"  – use the library's built-in detection (default)
    # "custom"       – use CustomHeaderDetector with the ratios below
    # "none"         – disable heading detection (hdr_info=False)
    heading_mode: str = "pymupdf4llm"

    # Size ratios relative to the median body font size.
    # A span whose size ≥ body × ratio is classified as that heading level.
    heading_h1_ratio: float = 1.40
    heading_h2_ratio: float = 1.20
    heading_h3_ratio: float = 1.05

    # Additional signals that can promote a line to a heading
    heading_bold_promotes: bool = True   # bold at ≈body size → H3
    heading_color_promotes: bool = True  # non-black/grey color → H3

    # A span with more characters than this is never classified as a heading
    heading_max_chars: int = 120

    # ── Paragraph reflow ─────────────────────────────────────────────────────
    # "none"  – pass pymupdf4llm output through unchanged
    # "join"  – join consecutive non-blank lines within a block (simple)
    # "smart" – apply heuristic rules (sentence ending, hyphen joining, …)
    para_mode: str = "smart"

    # Smart-reflow rules (only used when para_mode == "smart")
    para_sentence_end: bool = True       # line ending .!? → paragraph boundary
    para_join_hyphen: bool = True        # trailing - → join and dehyphenate
    #   A line shorter than  (box_fill_width × para_min_fill_ratio)  is considered
    #   a potential paragraph end (combined with the punctuation check).
    #   box_fill_width is derived per text box from the fullest extracted lines.
    para_min_fill_ratio: float = 0.75

    # ── Runtime state (set by analysis/detection workers) ────────────────────
    detected_top: float = field(default=0.0, repr=False)
    detected_bottom: float = field(default=0.0, repr=False)
    detected_info: str = field(default="", repr=False)
    detected_top_by_page: dict[int, float] = field(default_factory=dict, repr=False)
    detected_bottom_by_page: dict[int, float] = field(default_factory=dict, repr=False)
    detected_hf_rects_by_page: dict[int, dict[str, list[tuple[float, float, float, float]]]] = field(
        default_factory=dict,
        repr=False,
    )
    font_info: str = field(default="", repr=False)
