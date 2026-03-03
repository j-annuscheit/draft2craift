"""Section-level widget builders for the RAG settings dialog."""
from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
)

from services.rag.system import RAGConfig

from .rag_settings_types import (
    BackendSection,
    ChunkingSection,
    ExtendedContextSection,
    HyDESection,
    LiteralSection,
    SelectionSection,
)


def _new_form(group: QGroupBox) -> QFormLayout:
    form = QFormLayout(group)
    form.setSpacing(6)
    return form


def build_backends_section(cfg: RAGConfig) -> BackendSection:
    group = QGroupBox("Backends")
    form = _new_form(group)

    use_tfidf = QCheckBox("TF-IDF  (always available)")
    use_tfidf.setChecked(cfg.use_tfidf)
    form.addRow(use_tfidf)

    use_st = QCheckBox("Sentence-Transformers")
    use_st.setChecked(cfg.use_st)
    form.addRow(use_st)

    use_regex = QCheckBox("Literal Search (Regex/Substrings)")
    use_regex.setChecked(cfg.use_regex_search)
    form.addRow(use_regex)

    st_model = QLineEdit(cfg.st_model_name)
    form.addRow("  Model name:", st_model)

    st_n_threads = QSpinBox()
    st_n_threads.setRange(0, 256)
    st_n_threads.setValue(cfg.st_n_threads)
    st_n_threads.setSpecialValueText(f"Auto ({os.cpu_count() or '?'} cores)")
    st_n_threads.setToolTip(
        "CPU threads used by PyTorch/sentence-transformers.\n"
        "0 = use all available cores (recommended)."
    )
    form.addRow("  CPU threads (ST):", st_n_threads)

    hint = QLabel("At least one backend must be active (TF-IDF, ST or Literal).")
    hint.setStyleSheet("color: #F38BA8; font-size: 10px;")
    form.addRow(hint)

    return BackendSection(
        group=group,
        form=form,
        use_tfidf=use_tfidf,
        use_st=use_st,
        use_regex=use_regex,
        st_model=st_model,
        st_n_threads=st_n_threads,
        hint=hint,
    )


def build_hyde_section(cfg: RAGConfig) -> HyDESection:
    group = QGroupBox("HyDE (Query Expansion)")
    form = _new_form(group)

    use_hyde = QCheckBox("HyDE aktivieren")
    use_hyde.setChecked(cfg.use_hyde)
    form.addRow(use_hyde)

    hyde_min_words = QSpinBox()
    hyde_min_words.setRange(1, 20)
    hyde_min_words.setValue(cfg.hyde_min_words)
    form.addRow("Expand wenn ≤ N Wörter:", hyde_min_words)

    hyde_tfidf_mode = QComboBox()
    hyde_tfidf_mode.addItems(["keywords", "passage"])
    hyde_tfidf_mode.setCurrentText(cfg.hyde_tfidf_mode)
    form.addRow("TF-IDF-Modus:", hyde_tfidf_mode)

    hyde_st_mode = QComboBox()
    hyde_st_mode.addItems(["passage", "multi_passage"])
    hyde_st_mode.setCurrentText(cfg.hyde_st_mode)
    form.addRow("ST-Modus:", hyde_st_mode)

    hyde_st_hypotheses = QSpinBox()
    hyde_st_hypotheses.setRange(2, 10)
    hyde_st_hypotheses.setValue(cfg.hyde_st_hypotheses)
    hyde_hypotheses_label = QLabel("Hypothesen:")
    form.addRow(hyde_hypotheses_label, hyde_st_hypotheses)

    hyde_use_doc_context = QCheckBox("Dokumentstruktur als HyDE-Kontext (TOC)")
    hyde_use_doc_context.setChecked(cfg.hyde_use_doc_context)
    form.addRow(hyde_use_doc_context)

    return HyDESection(
        group=group,
        form=form,
        use_hyde=use_hyde,
        hyde_min_words=hyde_min_words,
        hyde_tfidf_mode=hyde_tfidf_mode,
        hyde_st_mode=hyde_st_mode,
        hyde_st_hypotheses=hyde_st_hypotheses,
        hyde_hypotheses_label=hyde_hypotheses_label,
        hyde_use_doc_context=hyde_use_doc_context,
    )


def build_chunking_section(cfg: RAGConfig) -> ChunkingSection:
    group = QGroupBox("Chunking")
    form = _new_form(group)

    chunk_size = QSpinBox()
    chunk_size.setRange(100, 20_000)
    chunk_size.setSingleStep(100)
    chunk_size.setValue(cfg.chunk_size)
    chunk_size.setSuffix(" chars")
    form.addRow("Chunk-Größe:", chunk_size)

    chunk_overlap = QSpinBox()
    chunk_overlap.setRange(0, 5_000)
    chunk_overlap.setSingleStep(50)
    chunk_overlap.setValue(cfg.chunk_overlap)
    chunk_overlap.setSuffix(" chars")
    form.addRow("Sliding-Window-Overlap:", chunk_overlap)

    chunking_strategy = QComboBox()
    chunking_strategy.addItems(["sliding_window", "section", "recursive"])
    chunking_strategy.setCurrentText(cfg.chunking_strategy)
    form.addRow("Strategie:", chunking_strategy)

    include_headings = QCheckBox("Heading-Breadcrumb einbetten")
    include_headings.setChecked(cfg.include_headings)
    form.addRow(include_headings)

    include_filename = QCheckBox("Dateiname einbetten")
    include_filename.setChecked(cfg.include_filename)
    form.addRow(include_filename)

    return ChunkingSection(
        group=group,
        form=form,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        chunking_strategy=chunking_strategy,
        include_headings=include_headings,
        include_filename=include_filename,
    )


def build_extended_context_section(cfg: RAGConfig) -> ExtendedContextSection:
    group = QGroupBox("Erweiterter Kontext")
    form = _new_form(group)

    extended_context = QCheckBox("Erweitertes Kontext-Fenster aktivieren")
    extended_context.setChecked(cfg.extended_context)
    form.addRow(extended_context)

    hint = QLabel("Expandiert jeden Treffer um ±N Zeichen im Originaldokument.")
    hint.setStyleSheet("color: #6C7086; font-size: 10px;")
    form.addRow(hint)

    ext_before = QSpinBox()
    ext_before.setRange(0, 5_000)
    ext_before.setSingleStep(100)
    ext_before.setValue(cfg.extended_context_before)
    ext_before.setSuffix(" chars")
    form.addRow("Vor dem Chunk:", ext_before)

    ext_after = QSpinBox()
    ext_after.setRange(0, 5_000)
    ext_after.setSingleStep(100)
    ext_after.setValue(cfg.extended_context_after)
    ext_after.setSuffix(" chars")
    form.addRow("Nach dem Chunk:", ext_after)

    return ExtendedContextSection(
        group=group,
        form=form,
        extended_context=extended_context,
        hint=hint,
        ext_before=ext_before,
        ext_after=ext_after,
    )


def build_selection_section(cfg: RAGConfig) -> SelectionSection:
    group = QGroupBox("Result Selection")
    form = _new_form(group)

    selection_mode = QComboBox()
    selection_mode.addItems(["top_k", "threshold", "top_k_threshold"])
    selection_mode.setCurrentText(cfg.selection_mode)
    form.addRow("Mode:", selection_mode)

    hint = QLabel(
        "top_k: return best N results\n"
        "threshold: return all above score\n"
        "top_k_threshold: best N above score\n"
        "Applied to all backends (TF-IDF, ST, Literal)."
    )
    hint.setStyleSheet("color: #6C7086; font-size: 10px;")
    form.addRow(hint)

    top_k = QSpinBox()
    top_k.setRange(1, 100)
    top_k.setValue(cfg.top_k)
    form.addRow("Top-K (N):", top_k)

    threshold = QDoubleSpinBox()
    threshold.setRange(0.0, 2.0)
    threshold.setSingleStep(0.05)
    threshold.setDecimals(3)
    threshold.setValue(cfg.score_threshold)
    form.addRow("Score threshold:", threshold)

    llm_rerank_enabled = QCheckBox("LLM rerank + filter before display")
    llm_rerank_enabled.setChecked(cfg.llm_rerank_enabled)
    form.addRow(llm_rerank_enabled)

    llm_rerank_min_score = QDoubleSpinBox()
    llm_rerank_min_score.setRange(0.0, 1.0)
    llm_rerank_min_score.setSingleStep(0.05)
    llm_rerank_min_score.setDecimals(2)
    llm_rerank_min_score.setValue(cfg.llm_rerank_min_score)
    llm_rerank_min_score.setToolTip(
        "Used only as fallback when a reranker output does not contain class labels."
    )
    form.addRow("LLM min relevance (fallback):", llm_rerank_min_score)

    llm_rerank_max_candidates = QSpinBox()
    llm_rerank_max_candidates.setRange(1, 50)
    llm_rerank_max_candidates.setValue(cfg.llm_rerank_max_candidates)
    llm_rerank_max_candidates.setToolTip(
        "Legacy compatibility value. Per-hit reranking currently evaluates all hits."
    )
    form.addRow("LLM max candidates (legacy):", llm_rerank_max_candidates)

    rerank_hint = QLabel(
        "Requires a loaded LLM. Hits are classified as 'sinnvoll' or 'nicht_sinnvoll'."
    )
    rerank_hint.setStyleSheet("color: #6C7086; font-size: 10px;")
    form.addRow(rerank_hint)

    return SelectionSection(
        group=group,
        form=form,
        selection_mode=selection_mode,
        hint=hint,
        top_k=top_k,
        threshold=threshold,
        llm_rerank_enabled=llm_rerank_enabled,
        llm_rerank_min_score=llm_rerank_min_score,
        llm_rerank_max_candidates=llm_rerank_max_candidates,
        rerank_hint=rerank_hint,
    )


def build_literal_section(cfg: RAGConfig) -> LiteralSection:
    group = QGroupBox("Direct Match (Literal Search)")
    form = _new_form(group)

    hint = QLabel("Details for the Literal backend (configured above).")
    hint.setStyleSheet("color: #6C7086; font-size: 10px;")
    form.addRow(hint)

    regex_max = QSpinBox()
    regex_max.setRange(0, 20)
    regex_max.setValue(cfg.regex_max_results)
    form.addRow("Max literal results:", regex_max)

    literal_use_llm_terms = QCheckBox()
    literal_use_llm_terms.setChecked(cfg.literal_use_llm_terms)
    form.addRow("Ask LLM for literal terms:", literal_use_llm_terms)

    literal_llm_max_terms = QSpinBox()
    literal_llm_max_terms.setRange(1, 30)
    literal_llm_max_terms.setValue(cfg.literal_llm_max_terms)
    form.addRow("Max LLM terms:", literal_llm_max_terms)

    return LiteralSection(
        group=group,
        form=form,
        hint=hint,
        regex_max=regex_max,
        literal_use_llm_terms=literal_use_llm_terms,
        literal_llm_max_terms=literal_llm_max_terms,
    )
