from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from .pdf_settings import PDFSettingsPanel


def build_general_group(panel: "PDFSettingsPanel") -> QGroupBox:
    group = QGroupBox("General")
    panel._general_form = QFormLayout(group)
    panel._general_form.setSpacing(6)

    panel._backend = QComboBox()
    panel._backend.addItems(["PyMuPDF  (manuell konfigurierbar)", "Docling  (KI-basiert)"])
    panel._backend.setToolTip(
        "PyMuPDF   Klassische Pipeline mit vollständiger manueller Kontrolle über\n"
        "          Header/Footer-Erkennung, Überschriften, Tabellen und Reflow.\n\n"
        "Docling   KI-basierte Pipeline (IBM). Erkennt Layout, Tabellen und\n"
        "          Überschriften automatisch — keine manuelle Konfiguration nötig."
    )
    panel._general_form.addRow("Backend:", panel._backend)

    panel._page_range = QLineEdit("all")
    panel._page_range.setPlaceholderText("all   or   1-5,7,10-")
    panel._page_range.setToolTip(
        "Page range (1-indexed, inclusive).\n"
        "  all   → all pages\n"
        "  1-10  → pages 1–10\n"
        "  1-5,8,12-  → pages 1-5, 8, 12 to end"
    )
    panel._general_form.addRow("Pages:", panel._page_range)

    panel._show_markers = QCheckBox("Insert [Seite N] page markers")
    panel._show_markers.setChecked(True)
    panel._show_markers.setToolTip(
        "Adds page marker lines to the generated Markdown.\n"
        "Heading overlays in the PDF viewer remain global and do not depend on markers."
    )
    panel._general_form.addRow("", panel._show_markers)
    return group


def build_tbl_img_group(panel: "PDFSettingsPanel") -> QGroupBox:
    group = QGroupBox("Tables & Images")
    panel._tbl_img_form = QFormLayout(group)
    panel._tbl_img_form.setSpacing(6)

    panel._table_strategy = QComboBox()
    panel._table_strategy.addItems(["lines_strict", "lines", "text", "none"])
    panel._table_strategy.setToolTip(
        "lines_strict  Strict line-based (default)\n"
        "lines          Flexible line-based\n"
        "text           Text-flow based\n"
        "none           Disable table extraction"
    )
    panel._tbl_img_form.addRow("Table strategy:", panel._table_strategy)

    panel._write_images = QCheckBox("Extract images to disk")
    panel._tbl_img_form.addRow("", panel._write_images)

    panel._image_format = QComboBox()
    panel._image_format.addItems(["png", "jpeg"])
    panel._tbl_img_form.addRow("Image format:", panel._image_format)

    panel._dpi = QSpinBox()
    panel._dpi.setRange(72, 600)
    panel._dpi.setValue(150)
    panel._dpi.setSuffix(" DPI")
    panel._tbl_img_form.addRow("DPI:", panel._dpi)

    panel._graphics_limit = QSpinBox()
    panel._graphics_limit.setRange(0, 2000)
    panel._graphics_limit.setValue(50)
    panel._graphics_limit.setSpecialValueText("unlimited")
    panel._graphics_limit.setToolTip("Max graphics per page  (0 = unlimited)")
    panel._tbl_img_form.addRow("Graphics limit:", panel._graphics_limit)
    return group


def _make_separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    return sep


def build_docling_group(panel: "PDFSettingsPanel") -> QGroupBox:
    """Options shown only when the Docling backend is selected."""
    group = QGroupBox("Docling-Optionen")
    layout = QVBoxLayout(group)
    layout.setSpacing(6)

    # ── Content extraction ────────────────────────────────────────────────
    panel._docling_images = QCheckBox("Bilder extrahieren")
    panel._docling_images.setChecked(True)
    panel._docling_images.setToolTip(
        "Extrahierte Bilder werden als Dateien gespeichert und im Markdown\n"
        "über Dateipfade referenziert (keine base64-Blöcke im Markdown)."
    )
    layout.addWidget(panel._docling_images)

    # Image scale (only shown when images are active + user mode allows)
    panel._docling_scale_widget = QWidget()
    scale_form = QFormLayout(panel._docling_scale_widget)
    scale_form.setContentsMargins(16, 0, 0, 0)
    scale_form.setSpacing(4)
    panel._docling_images_scale = QDoubleSpinBox()
    panel._docling_images_scale.setRange(0.5, 4.0)
    panel._docling_images_scale.setSingleStep(0.5)
    panel._docling_images_scale.setDecimals(1)
    panel._docling_images_scale.setValue(2.0)
    panel._docling_images_scale.setToolTip(
        "Skalierungsfaktor für extrahierte Bilder.\n"
        "1.0 × = Entwurfsqualität  |  2.0 × = Standard  |  3.0 × = Hohe Auflösung\n"
        "Höhere Werte erhöhen die Dateigröße und Konvertierungszeit."
    )
    scale_form.addRow("Bildqualität:", panel._docling_images_scale)
    layout.addWidget(panel._docling_scale_widget)

    panel._docling_formulas = QCheckBox("Formelerkennung (LaTeX)  ⚠ ~1 GB Modell-Download")
    panel._docling_formulas.setChecked(False)
    panel._docling_formulas.setToolTip(
        "Aktiviert Doclings CodeFormulaV2-Modell:\n"
        "Formeln werden als LaTeX erkannt und als gerenderte Bilder angezeigt.\n\n"
        "Beim ersten Start wird das Modell (~1 GB) von HuggingFace heruntergeladen.\n"
        "Erhöht die Konvertierungszeit deutlich."
    )
    layout.addWidget(panel._docling_formulas)

    panel._docling_code = QCheckBox("Code-Blöcke erkennen  ⚠ ~0.5 GB Modell-Download")
    panel._docling_code.setChecked(False)
    panel._docling_code.setToolTip(
        "Aktiviert Doclings Code-Enrichment-Modell:\n"
        "Code-Fragmente im Dokument werden als Blöcke erkannt und formatiert.\n\n"
        "Nützlich für technische Dokumente und wissenschaftliche Arbeiten."
    )
    layout.addWidget(panel._docling_code)

    # ── Table structure ───────────────────────────────────────────────────
    layout.addWidget(_make_separator())

    panel._docling_table_widget = QWidget()
    table_form = QFormLayout(panel._docling_table_widget)
    table_form.setContentsMargins(0, 0, 0, 0)
    table_form.setSpacing(5)
    panel._docling_table_mode = QComboBox()
    panel._docling_table_mode.addItems(["Genau (Standard)", "Schnell"])
    panel._docling_table_mode.setToolTip(
        "Genau   TableFormerMode.ACCURATE — höhere Qualität, langsamer.\n"
        "          Empfohlen für komplexe Tabellen mit Zell-Spans.\n\n"
        "Schnell  TableFormerMode.FAST — schneller, für einfache Tabellen."
    )
    table_form.addRow("Tabellen-Modus:", panel._docling_table_mode)
    layout.addWidget(panel._docling_table_widget)

    # ── OCR ───────────────────────────────────────────────────────────────
    layout.addWidget(_make_separator())

    panel._docling_ocr_widget = QWidget()
    ocr_outer = QVBoxLayout(panel._docling_ocr_widget)
    ocr_outer.setContentsMargins(0, 0, 0, 0)
    ocr_outer.setSpacing(4)

    panel._docling_ocr = QCheckBox("OCR aktivieren (für gescannte PDFs)")
    panel._docling_ocr.setChecked(True)
    panel._docling_ocr.setToolTip(
        "Wendet OCR auf Seiten an, die Bitmap-Inhalte enthalten.\n"
        "Für native PDF-Textdokumente kann OCR deaktiviert werden,\n"
        "um die Konvertierung zu beschleunigen."
    )
    ocr_outer.addWidget(panel._docling_ocr)

    panel._docling_ocr_advanced_widget = QWidget()
    ocr_adv_form = QFormLayout(panel._docling_ocr_advanced_widget)
    ocr_adv_form.setContentsMargins(16, 0, 0, 0)
    ocr_adv_form.setSpacing(4)

    panel._docling_ocr_force_full_page = QCheckBox("Ganzseitige OCR erzwingen")
    panel._docling_ocr_force_full_page.setChecked(False)
    panel._docling_ocr_force_full_page.setToolTip(
        "OCR auf jede Seite anwenden, auch wenn native PDF-Texte vorhanden sind.\n"
        "Nützlich wenn der extrahierte Text fehlerhaft/leer erscheint."
    )
    ocr_adv_form.addRow("", panel._docling_ocr_force_full_page)

    panel._docling_ocr_lang = QLineEdit()
    panel._docling_ocr_lang.setPlaceholderText("leer = automatisch")
    panel._docling_ocr_lang.setToolTip(
        "Kommagetrennte OCR-Sprachcodes, z. B.: de,en\n"
        "Leer lassen für automatische Spracherkennung.\n"
        "Unterstützte Codes: de, en, fr, es, it, ja, zh, ar, ..."
    )
    ocr_adv_form.addRow("Sprachen:", panel._docling_ocr_lang)
    ocr_outer.addWidget(panel._docling_ocr_advanced_widget)
    layout.addWidget(panel._docling_ocr_widget)

    # ── Performance / Erweitert ───────────────────────────────────────────
    layout.addWidget(_make_separator())

    panel._docling_perf_widget = QWidget()
    perf_form = QFormLayout(panel._docling_perf_widget)
    perf_form.setContentsMargins(0, 0, 0, 0)
    perf_form.setSpacing(5)

    panel._docling_force_backend_text = QCheckBox("PDF-Nativtext bevorzugen")
    panel._docling_force_backend_text.setChecked(False)
    panel._docling_force_backend_text.setToolTip(
        "Verwendet den nativen PDF-Text anstelle der Layout-Modell-Vorhersagen.\n"
        "Schneller und zuverlässiger für gut strukturierte, native PDF-Dokumente.\n"
        "Deaktiviert Layout-Analyse für Text-Elemente."
    )
    perf_form.addRow("", panel._docling_force_backend_text)

    panel._docling_timeout = QDoubleSpinBox()
    panel._docling_timeout.setRange(0.0, 3600.0)
    panel._docling_timeout.setSingleStep(30.0)
    panel._docling_timeout.setDecimals(0)
    panel._docling_timeout.setValue(0.0)
    panel._docling_timeout.setSpecialValueText("unbegrenzt")
    panel._docling_timeout.setSuffix(" s")
    panel._docling_timeout.setToolTip(
        "Maximale Verarbeitungszeit pro Dokument in Sekunden.\n"
        "0 = kein Limit. Nützlich für sehr große PDFs um Hänger zu verhindern."
    )
    perf_form.addRow("Timeout:", panel._docling_timeout)

    panel._docling_num_threads = QSpinBox()
    panel._docling_num_threads.setRange(0, 64)
    panel._docling_num_threads.setValue(0)
    panel._docling_num_threads.setSpecialValueText("auto")
    panel._docling_num_threads.setToolTip(
        "Anzahl CPU-Threads für die Docling-Pipeline.\n"
        "0 = automatisch (alle verfügbaren Kerne)."
    )
    perf_form.addRow("CPU-Threads:", panel._docling_num_threads)
    layout.addWidget(panel._docling_perf_widget)

    return group


def build_hf_group(panel: "PDFSettingsPanel") -> QGroupBox:
    group = QGroupBox("Header / Footer Removal")
    layout = QVBoxLayout(group)
    layout.setSpacing(6)

    panel._hf_mode_form = QFormLayout()
    panel._hf_mode_form.setSpacing(5)
    panel._hf_mode = QComboBox()
    panel._hf_mode.addItems([
        "Auto-Detect (per page)",
        "Manual scan zones (all pages)",
    ])
    panel._hf_mode.setToolTip(
        "Auto-Detect: finds repeating headers/footers per page (supports merged PDFs).\n"
        "Manual: apply one fixed top/bottom scan zone for all pages."
    )
    panel._hf_mode_form.addRow("Mode:", panel._hf_mode)
    layout.addLayout(panel._hf_mode_form)

    panel._hf_auto_form = QFormLayout()
    panel._hf_auto_form.setSpacing(5)

    panel._hf_min_pages = QSpinBox()
    panel._hf_min_pages.setRange(2, 200)
    panel._hf_min_pages.setValue(3)
    panel._hf_min_pages.setToolTip(
        "Min. pages where a line must repeat to be classified\n"
        "as running element. Keep low (2-3) for merged PDFs."
    )
    panel._hf_auto_form.addRow("Min. repeats:", panel._hf_min_pages)

    panel._hf_threshold = QDoubleSpinBox()
    panel._hf_threshold.setRange(1.0, 100.0)
    panel._hf_threshold.setValue(10.0)
    panel._hf_threshold.setSuffix(" % of doc")
    panel._hf_threshold.setDecimals(1)
    panel._hf_threshold.setToolTip(
        "Alternative minimum: fraction of total pages.\n"
        "Effective threshold = max(min_repeats, pages × this%)."
    )
    panel._hf_auto_form.addRow("Min. fraction:", panel._hf_threshold)

    panel._hf_max_pairs = QSpinBox()
    panel._hf_max_pairs.setRange(1, 12)
    panel._hf_max_pairs.setValue(3)
    panel._hf_max_pairs.setToolTip(
        "Maximum number of header/footer combinations across the document.\n"
        "Each page is assigned to one of these combinations."
    )
    panel._hf_auto_form.addRow("Max pairs:", panel._hf_max_pairs)

    panel._hf_auto_widget = QWidget()
    panel._hf_auto_widget.setLayout(panel._hf_auto_form)
    layout.addWidget(panel._hf_auto_widget)

    button_row = QHBoxLayout()
    panel._btn_detect = QPushButton("🔍  Run Auto-Detect")
    panel._btn_detect.setToolTip("Scan the PDF and show which H/F would be removed")
    panel._btn_detect.clicked.connect(panel.detect_requested)
    button_row.addWidget(panel._btn_detect)
    panel._btn_detect_debug = QPushButton("Debug Info…")
    panel._btn_detect_debug.setToolTip(
        "Open Header/Footer detection details in a separate window."
    )
    panel._btn_detect_debug.clicked.connect(panel._show_detect_debug)
    panel._btn_detect_debug.setEnabled(False)
    button_row.addWidget(panel._btn_detect_debug)
    button_row.addStretch()
    layout.addLayout(button_row)

    panel._hf_manual_form = QFormLayout()
    panel._hf_manual_form.setSpacing(5)

    panel._hf_top_zone = QDoubleSpinBox()
    panel._hf_top_zone.setRange(1.0, 49.0)
    panel._hf_top_zone.setValue(10.0)
    panel._hf_top_zone.setSuffix(" % from top")
    panel._hf_top_zone.setDecimals(1)
    panel._hf_manual_form.addRow("Top scan zone:", panel._hf_top_zone)

    panel._hf_bottom_zone = QDoubleSpinBox()
    panel._hf_bottom_zone.setRange(1.0, 49.0)
    panel._hf_bottom_zone.setValue(10.0)
    panel._hf_bottom_zone.setSuffix(" % from bottom")
    panel._hf_bottom_zone.setDecimals(1)
    panel._hf_manual_form.addRow("Bottom scan zone:", panel._hf_bottom_zone)

    panel._manual_widget = QWidget()
    panel._manual_widget.setLayout(panel._hf_manual_form)
    layout.addWidget(panel._manual_widget)

    panel._sync_hf_widgets()
    return group


def build_heading_group(panel: "PDFSettingsPanel") -> QGroupBox:
    group = QGroupBox("Heading Detection")
    layout = QVBoxLayout(group)
    layout.setSpacing(6)

    panel._heading_mode_form = QFormLayout()
    panel._heading_mode_form.setSpacing(5)

    panel._heading_mode = QComboBox()
    panel._heading_mode.addItems(["pymupdf4llm  (default)", "custom", "none  (off)"])
    panel._heading_mode.setToolTip(
        "pymupdf4llm  Use the library's built-in detection\n"
        "custom        Apply the size ratios / bold / color rules below\n"
        "none          Disable heading detection entirely"
    )
    panel._heading_mode_form.addRow("Mode:", panel._heading_mode)
    layout.addLayout(panel._heading_mode_form)

    panel._hdg_custom_widget = QWidget()
    custom_layout = QVBoxLayout(panel._hdg_custom_widget)
    custom_layout.setContentsMargins(0, 0, 0, 0)
    custom_layout.setSpacing(6)

    panel._heading_ratio_form = QFormLayout()
    panel._heading_ratio_form.setSpacing(5)

    controls = [
        (
            "_hdg_h1_ratio",
            "H1 size ratio:",
            "size ≥ body × ratio → H1  (e.g. 1.40 = 40% larger)",
        ),
        ("_hdg_h2_ratio", "H2 size ratio:", "size ≥ body × ratio → H2"),
        ("_hdg_h3_ratio", "H3 size ratio:", "size ≥ body × ratio → H3"),
    ]
    for attr, label, tip in controls:
        spin_box = QDoubleSpinBox()
        spin_box.setRange(1.00, 5.00)
        spin_box.setDecimals(3)
        spin_box.setSingleStep(0.05)
        spin_box.setToolTip(tip)
        setattr(panel, attr, spin_box)
        panel._heading_ratio_form.addRow(label, spin_box)

    panel._hdg_h1_ratio.setValue(1.400)
    panel._hdg_h2_ratio.setValue(1.200)
    panel._hdg_h3_ratio.setValue(1.050)

    panel._hdg_max_chars = QSpinBox()
    panel._hdg_max_chars.setRange(20, 500)
    panel._hdg_max_chars.setValue(120)
    panel._hdg_max_chars.setToolTip(
        "Lines longer than this character count are never classified as headings."
    )
    panel._heading_ratio_form.addRow("Max heading chars:", panel._hdg_max_chars)

    custom_layout.addLayout(panel._heading_ratio_form)

    panel._hdg_bold = QCheckBox("Bold at body size → H3")
    panel._hdg_bold.setChecked(True)
    panel._hdg_bold.setToolTip("Promote bold text that is ≈ body-font size to H3")
    custom_layout.addWidget(panel._hdg_bold)

    panel._hdg_color = QCheckBox("Colored text → H3")
    panel._hdg_color.setChecked(True)
    panel._hdg_color.setToolTip("Promote non-black/grey colored text at ≈ body size to H3")
    custom_layout.addWidget(panel._hdg_color)

    layout.addWidget(panel._hdg_custom_widget)

    button_row = QHBoxLayout()
    panel._btn_analyze = QPushButton("🔬  Analyze Fonts + Apply")
    panel._btn_analyze.setToolTip(
        "Inspect all font sizes in the PDF.\n"
        "Automatically applies suggested H1/H2/H3 ratios."
    )
    panel._btn_analyze.clicked.connect(panel.analyze_requested)
    button_row.addWidget(panel._btn_analyze)

    panel._btn_font_debug = QPushButton("Debug Info…")
    panel._btn_font_debug.setToolTip("Open font-analysis details in a separate window.")
    panel._btn_font_debug.clicked.connect(panel._show_font_debug)
    panel._btn_font_debug.setEnabled(False)
    button_row.addWidget(panel._btn_font_debug)
    button_row.addStretch()
    layout.addLayout(button_row)

    panel._heading_mode.currentIndexChanged.connect(panel._on_heading_mode_changed)
    panel._sync_heading_mode()
    return group


def build_para_group(panel: "PDFSettingsPanel") -> QGroupBox:
    group = QGroupBox("Paragraph Reflow")
    layout = QVBoxLayout(group)
    layout.setSpacing(6)

    panel._para_mode_form = QFormLayout()
    panel._para_mode_form.setSpacing(5)

    panel._para_mode = QComboBox()
    panel._para_mode.addItems(["smart", "join", "none"])
    panel._para_mode.setToolTip(
        "smart  Apply heuristic rules (recommended)\n"
        "join   Simply join all consecutive non-blank lines\n"
        "none   Pass pymupdf4llm output through unchanged"
    )
    panel._para_mode_form.addRow("Mode:", panel._para_mode)
    layout.addLayout(panel._para_mode_form)

    panel._para_smart_widget = QWidget()
    smart_layout = QVBoxLayout(panel._para_smart_widget)
    smart_layout.setContentsMargins(0, 0, 0, 0)
    smart_layout.setSpacing(5)

    panel._para_sentence_end = QCheckBox("Line ending with  . ! ?  → paragraph boundary")
    panel._para_sentence_end.setChecked(True)
    panel._para_sentence_end.setToolTip(
        "When a line ends with a sentence-ending character and is 'short'\n"
        "(or the next line starts with a capital letter), insert a paragraph break."
    )
    smart_layout.addWidget(panel._para_sentence_end)

    panel._para_join_hyphen = QCheckBox("Line ending with  -  → join and dehyphenate")
    panel._para_join_hyphen.setChecked(True)
    panel._para_join_hyphen.setToolTip(
        "When a line ends with a hyphen (word-wrap artefact), join it with the\n"
        "next line and remove the hyphen.  Never treated as a paragraph end."
    )
    smart_layout.addWidget(panel._para_join_hyphen)

    panel._para_fill_form = QFormLayout()
    panel._para_fill_form.setSpacing(5)
    panel._para_min_fill = QDoubleSpinBox()
    panel._para_min_fill.setRange(0.10, 1.00)
    panel._para_min_fill.setDecimals(2)
    panel._para_min_fill.setSingleStep(0.05)
    panel._para_min_fill.setValue(0.75)
    panel._para_min_fill.setToolTip(
        "A line is considered 'short' when its fill ratio is less than\n"
        "this fraction × the text-box width estimate (derived from fuller lines).\n\n"
        "Short lines at sentence end trigger a paragraph break.\n"
        "Lower → more sensitive to short lines (more paragraph splits)."
    )
    panel._para_fill_form.addRow("Short-line threshold:", panel._para_min_fill)
    smart_layout.addLayout(panel._para_fill_form)

    layout.addWidget(panel._para_smart_widget)

    panel._para_mode.currentTextChanged.connect(panel._on_para_mode_changed)
    panel._sync_para_mode()
    return group
