"""Bridge between RAGConfig and dialog controls."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from shared.services.rag.config import RAGConfig

_DEFAULT_ST_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


@dataclass(frozen=True)
class RAGSettingsControls:
    mode_hint: QLabel
    groups: dict[str, QGroupBox]
    forms: dict[str, QFormLayout]
    widgets: dict[str, QWidget]
    button_box: QDialogButtonBox
    ok_button: QPushButton
    reset_button: QPushButton


def add_group(
    root: QVBoxLayout,
    groups: dict[str, QGroupBox],
    forms: dict[str, QFormLayout],
    group_key: str,
    title: str,
) -> QFormLayout:
    """Create a group with a form layout and register it."""
    group = QGroupBox(title)
    form = QFormLayout(group)
    form.setSpacing(6)
    groups[group_key] = group
    forms[group_key] = form
    root.addWidget(group)
    return form


def add_chunking_controls(
    root: QVBoxLayout,
    groups: dict[str, QGroupBox],
    forms: dict[str, QFormLayout],
    widgets: dict[str, QWidget],
) -> None:
    """Add chunking controls to the dialog."""
    form = add_group(root, groups, forms, "chunking", "Chunking")

    chunk_size = QSpinBox()
    chunk_size.setRange(100, 20_000)
    chunk_size.setSingleStep(100)
    chunk_size.setSuffix(" chars")
    form.addRow("Chunk-Größe:", chunk_size)
    widgets["chunk_size"] = chunk_size

    chunk_overlap = QSpinBox()
    chunk_overlap.setRange(0, 5_000)
    chunk_overlap.setSingleStep(50)
    chunk_overlap.setSuffix(" chars")
    form.addRow("Sliding-Window-Overlap:", chunk_overlap)
    widgets["chunk_overlap"] = chunk_overlap

    chunking_strategy = QComboBox()
    chunking_strategy.addItems(["sliding_window", "section", "recursive"])
    form.addRow("Strategie:", chunking_strategy)
    widgets["chunking_strategy"] = chunking_strategy

    include_headings = QCheckBox("Heading-Breadcrumb einbetten")
    include_filename = QCheckBox("Dateiname einbetten")
    form.addRow(include_headings)
    form.addRow(include_filename)
    widgets["include_headings"] = include_headings
    widgets["include_filename"] = include_filename


def add_extended_context_controls(
    root: QVBoxLayout,
    groups: dict[str, QGroupBox],
    forms: dict[str, QFormLayout],
    widgets: dict[str, QWidget],
) -> None:
    """Add extended-context controls to the dialog."""
    form = add_group(root, groups, forms, "extended", "Erweiterter Kontext")

    extended_context = QCheckBox("Erweitertes Kontext-Fenster aktivieren")
    form.addRow(extended_context)
    widgets["extended_context"] = extended_context

    hint = QLabel("Expandiert jeden Treffer um ±N Zeichen im Originaldokument.")
    hint.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
    form.addRow(hint)
    widgets["extended_hint"] = hint

    ext_before = QSpinBox()
    ext_before.setRange(0, 5_000)
    ext_before.setSingleStep(100)
    ext_before.setSuffix(" chars")
    form.addRow("Vor dem Chunk:", ext_before)
    widgets["ext_before"] = ext_before

    ext_after = QSpinBox()
    ext_after.setRange(0, 5_000)
    ext_after.setSingleStep(100)
    ext_after.setSuffix(" chars")
    form.addRow("Nach dem Chunk:", ext_after)
    widgets["ext_after"] = ext_after


def _widget(controls: RAGSettingsControls, key: str) -> QWidget:
    widget = controls.widgets.get(key)
    if widget is None:
        raise KeyError(f"Missing RAG settings widget: {key}")
    return widget


def _set_combo_text(combo: QComboBox, value: str) -> None:
    index = combo.findText(str(value or ""))
    if index >= 0:
        combo.setCurrentIndex(index)


def load_config_into_controls(controls: RAGSettingsControls, cfg: RAGConfig) -> None:
    """Populate all controls from a RAGConfig."""
    box = controls.widgets

    box["use_tfidf"].setChecked(cfg.backend.use_tfidf)  # type: ignore[attr-defined]
    _set_combo_text(box["lexical_mode"], cfg.backend.lexical_mode)  # type: ignore[arg-type]
    box["bm25_k1"].setValue(cfg.backend.bm25_k1)  # type: ignore[attr-defined]
    box["bm25_b"].setValue(cfg.backend.bm25_b)  # type: ignore[attr-defined]
    box["use_st"].setChecked(cfg.backend.use_st)  # type: ignore[attr-defined]
    box["use_regex"].setChecked(cfg.backend.use_regex_search)  # type: ignore[attr-defined]
    box["st_model"].setText(cfg.backend.st_model_name)  # type: ignore[attr-defined]
    box["st_n_threads"].setValue(cfg.backend.st_n_threads)  # type: ignore[attr-defined]

    box["use_hyde"].setChecked(cfg.hyde.use_hyde)  # type: ignore[attr-defined]
    box["hyde_min_words"].setValue(cfg.hyde.min_words)  # type: ignore[attr-defined]
    _set_combo_text(box["hyde_tfidf_mode"], cfg.hyde.tfidf_mode)  # type: ignore[arg-type]
    _set_combo_text(box["hyde_st_mode"], cfg.hyde.st_mode)  # type: ignore[arg-type]
    box["hyde_st_hypotheses"].setValue(cfg.hyde.st_hypotheses)  # type: ignore[attr-defined]
    box["hyde_use_doc_context"].setChecked(cfg.hyde.use_doc_context)  # type: ignore[attr-defined]

    box["chunk_size"].setValue(cfg.chunking.chunk_size)  # type: ignore[attr-defined]
    box["chunk_overlap"].setValue(cfg.chunking.chunk_overlap)  # type: ignore[attr-defined]
    _set_combo_text(box["chunking_strategy"], cfg.chunking.strategy)  # type: ignore[arg-type]
    box["include_headings"].setChecked(cfg.chunking.include_headings)  # type: ignore[attr-defined]
    box["include_filename"].setChecked(cfg.chunking.include_filename)  # type: ignore[attr-defined]

    box["extended_context"].setChecked(cfg.context.enabled)  # type: ignore[attr-defined]
    box["ext_before"].setValue(cfg.context.before_chars)  # type: ignore[attr-defined]
    box["ext_after"].setValue(cfg.context.after_chars)  # type: ignore[attr-defined]

    _set_combo_text(box["selection_mode"], cfg.selection.mode)  # type: ignore[arg-type]
    box["top_k"].setValue(cfg.selection.top_k)  # type: ignore[attr-defined]
    box["threshold"].setValue(cfg.selection.score_threshold)  # type: ignore[attr-defined]
    box["llm_rerank_enabled"].setChecked(cfg.rerank.enabled)  # type: ignore[attr-defined]
    box["llm_rerank_min_score"].setValue(cfg.rerank.min_score)  # type: ignore[attr-defined]
    box["llm_rerank_max_candidates"].setValue(cfg.rerank.max_candidates)  # type: ignore[attr-defined]

    box["regex_max"].setValue(cfg.literal.max_results)  # type: ignore[attr-defined]
    box["literal_use_llm_terms"].setChecked(cfg.literal.use_llm_terms)  # type: ignore[attr-defined]
    box["literal_llm_max_terms"].setValue(cfg.literal.max_llm_terms)  # type: ignore[attr-defined]


def build_config_from_controls(controls: RAGSettingsControls) -> RAGConfig:
    """Create a RAGConfig from current control values."""
    use_tfidf = _widget(controls, "use_tfidf")
    use_st = _widget(controls, "use_st")
    use_regex = _widget(controls, "use_regex")

    st_model = str(_widget(controls, "st_model").text() or "").strip()  # type: ignore[attr-defined]
    if not st_model:
        st_model = _DEFAULT_ST_MODEL

    return RAGConfig.from_dict(
        {
            "backend": {
                "use_tfidf": bool(use_tfidf.isChecked()),  # type: ignore[attr-defined]
                "lexical_mode": str(_widget(controls, "lexical_mode").currentText()),  # type: ignore[attr-defined]
                "bm25_k1": float(_widget(controls, "bm25_k1").value()),  # type: ignore[attr-defined]
                "bm25_b": float(_widget(controls, "bm25_b").value()),  # type: ignore[attr-defined]
                "use_st": bool(use_st.isChecked()),  # type: ignore[attr-defined]
                "use_regex_search": bool(use_regex.isChecked()),  # type: ignore[attr-defined]
                "st_model_name": st_model,
                "st_n_threads": int(_widget(controls, "st_n_threads").value()),  # type: ignore[attr-defined]
            },
            "hyde": {
                "use_hyde": bool(_widget(controls, "use_hyde").isChecked()),  # type: ignore[attr-defined]
                "min_words": int(_widget(controls, "hyde_min_words").value()),  # type: ignore[attr-defined]
                "tfidf_mode": str(_widget(controls, "hyde_tfidf_mode").currentText()),  # type: ignore[attr-defined]
                "st_mode": str(_widget(controls, "hyde_st_mode").currentText()),  # type: ignore[attr-defined]
                "st_hypotheses": int(_widget(controls, "hyde_st_hypotheses").value()),  # type: ignore[attr-defined]
                "use_doc_context": bool(_widget(controls, "hyde_use_doc_context").isChecked()),  # type: ignore[attr-defined]
            },
            "chunking": {
                "chunk_size": int(_widget(controls, "chunk_size").value()),  # type: ignore[attr-defined]
                "chunk_overlap": int(_widget(controls, "chunk_overlap").value()),  # type: ignore[attr-defined]
                "strategy": str(_widget(controls, "chunking_strategy").currentText()),  # type: ignore[attr-defined]
                "include_headings": bool(_widget(controls, "include_headings").isChecked()),  # type: ignore[attr-defined]
                "include_filename": bool(_widget(controls, "include_filename").isChecked()),  # type: ignore[attr-defined]
            },
            "context": {
                "enabled": bool(_widget(controls, "extended_context").isChecked()),  # type: ignore[attr-defined]
                "before_chars": int(_widget(controls, "ext_before").value()),  # type: ignore[attr-defined]
                "after_chars": int(_widget(controls, "ext_after").value()),  # type: ignore[attr-defined]
            },
            "selection": {
                "mode": str(_widget(controls, "selection_mode").currentText()),  # type: ignore[attr-defined]
                "top_k": int(_widget(controls, "top_k").value()),  # type: ignore[attr-defined]
                "score_threshold": float(_widget(controls, "threshold").value()),  # type: ignore[attr-defined]
            },
            "rerank": {
                "enabled": bool(_widget(controls, "llm_rerank_enabled").isChecked()),  # type: ignore[attr-defined]
                "min_score": float(_widget(controls, "llm_rerank_min_score").value()),  # type: ignore[attr-defined]
                "max_candidates": int(_widget(controls, "llm_rerank_max_candidates").value()),  # type: ignore[attr-defined]
            },
            "literal": {
                "max_results": int(_widget(controls, "regex_max").value()),  # type: ignore[attr-defined]
                "use_llm_terms": bool(_widget(controls, "literal_use_llm_terms").isChecked()),  # type: ignore[attr-defined]
                "max_llm_terms": int(_widget(controls, "literal_llm_max_terms").value()),  # type: ignore[attr-defined]
            },
        }
    )
