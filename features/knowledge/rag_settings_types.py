"""Typed section containers for the RAG settings dialog view."""
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
)


@dataclass(frozen=True)
class BackendSection:
    group: QGroupBox
    form: QFormLayout
    use_tfidf: QCheckBox
    use_st: QCheckBox
    use_regex: QCheckBox
    st_model: QLineEdit
    st_n_threads: QSpinBox
    hint: QLabel


@dataclass(frozen=True)
class HyDESection:
    group: QGroupBox
    form: QFormLayout
    use_hyde: QCheckBox
    hyde_min_words: QSpinBox
    hyde_tfidf_mode: QComboBox
    hyde_st_mode: QComboBox
    hyde_st_hypotheses: QSpinBox
    hyde_hypotheses_label: QLabel
    hyde_use_doc_context: QCheckBox


@dataclass(frozen=True)
class ChunkingSection:
    group: QGroupBox
    form: QFormLayout
    chunk_size: QSpinBox
    chunk_overlap: QSpinBox
    chunking_strategy: QComboBox
    include_headings: QCheckBox
    include_filename: QCheckBox


@dataclass(frozen=True)
class ExtendedContextSection:
    group: QGroupBox
    form: QFormLayout
    extended_context: QCheckBox
    hint: QLabel
    ext_before: QSpinBox
    ext_after: QSpinBox


@dataclass(frozen=True)
class SelectionSection:
    group: QGroupBox
    form: QFormLayout
    selection_mode: QComboBox
    hint: QLabel
    top_k: QSpinBox
    threshold: QDoubleSpinBox
    llm_rerank_enabled: QCheckBox
    llm_rerank_min_score: QDoubleSpinBox
    llm_rerank_max_candidates: QSpinBox
    rerank_hint: QLabel


@dataclass(frozen=True)
class LiteralSection:
    group: QGroupBox
    form: QFormLayout
    hint: QLabel
    regex_max: QSpinBox
    literal_use_llm_terms: QCheckBox
    literal_llm_max_terms: QSpinBox


@dataclass(frozen=True)
class RAGSettingsView:
    mode_hint: QLabel
    backends: BackendSection
    hyde: HyDESection
    chunking: ChunkingSection
    extended_context: ExtendedContextSection
    selection: SelectionSection
    literal: LiteralSection
    button_box: QDialogButtonBox
    ok_button: QPushButton
    reset_button: QPushButton
