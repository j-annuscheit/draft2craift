"""Dialog exposing all RAGConfig parameters as editable widgets."""
from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import (
    USER_MODE_EXPERT,
    USER_MODE_PLUS,
    USER_MODE_SIMPLE,
    mode_rank,
    normalize_user_mode,
)
from shared.services.rag.config import RAGConfig

from .config_bridge import (
    RAGSettingsControls,
    add_chunking_controls,
    add_extended_context_controls,
    add_group,
    build_config_from_controls,
    load_config_into_controls,
)
from .styles import RAG_SETTINGS_STYLE


def _set_form_row_visible(form: QFormLayout, field: QWidget, visible: bool) -> None:
    label = form.labelForField(field)
    if label is not None:
        label.setVisible(visible)
    field.setVisible(visible)


class RAGSettingsDialog(QDialog):
    """Dialog for editing all parameters of a RAGConfig."""

    def __init__(self, config: RAGConfig, parent=None, user_mode: str = USER_MODE_PLUS):
        super().__init__(parent)
        self.setWindowTitle("RAG Settings")
        self.setStyleSheet(RAG_SETTINGS_STYLE)
        self.setMinimumWidth(440)
        self._user_mode = normalize_user_mode(user_mode)
        self._controls = self._build_ui()
        self._connect_signals()
        self._load(config)
        self.set_user_mode(self._user_mode)

    def _build_ui(self) -> RAGSettingsControls:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        mode_hint = QLabel("")
        mode_hint.setWordWrap(True)
        mode_hint.setStyleSheet("color: #6C7086; font-size: 10px;")
        root.addWidget(mode_hint)

        groups: dict[str, QGroupBox] = {}
        forms: dict[str, QFormLayout] = {}
        widgets: dict[str, QWidget] = {}

        self._build_backends_group(root, groups, forms, widgets)
        self._build_hyde_group(root, groups, forms, widgets)
        add_chunking_controls(root, groups, forms, widgets)
        add_extended_context_controls(root, groups, forms, widgets)
        self._build_selection_group(root, groups, forms, widgets)
        self._build_literal_group(root, groups, forms, widgets)

        buttons = QDialogButtonBox.StandardButton.Ok
        buttons |= QDialogButtonBox.StandardButton.Cancel
        buttons |= QDialogButtonBox.StandardButton.RestoreDefaults
        button_box = QDialogButtonBox(buttons)
        root.addWidget(button_box)

        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        reset_button = button_box.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        if ok_button is None or reset_button is None:
            raise RuntimeError("Failed to create RAG settings dialog buttons")

        return RAGSettingsControls(
            mode_hint=mode_hint,
            groups=groups,
            forms=forms,
            widgets=widgets,
            button_box=button_box,
            ok_button=ok_button,
            reset_button=reset_button,
        )

    def _build_backends_group(self, root, groups, forms, widgets) -> None:
        form = add_group(root, groups, forms, "backends", "Backends")

        use_tfidf = QCheckBox("TF-IDF  (always available)")
        use_st = QCheckBox("Sentence-Transformers")
        use_regex = QCheckBox("Literal Search (Regex/Substrings)")
        form.addRow(use_tfidf)
        form.addRow(use_st)
        form.addRow(use_regex)
        widgets["use_tfidf"] = use_tfidf
        widgets["use_st"] = use_st
        widgets["use_regex"] = use_regex

        st_model = QLineEdit()
        form.addRow("  Model name:", st_model)
        widgets["st_model"] = st_model

        st_n_threads = QSpinBox()
        st_n_threads.setRange(0, 256)
        st_n_threads.setSpecialValueText(f"Auto ({os.cpu_count() or '?'} cores)")
        st_n_threads.setToolTip(
            "CPU threads used by PyTorch/sentence-transformers.\n"
            "0 = use all available cores (recommended)."
        )
        form.addRow("  CPU threads (ST):", st_n_threads)
        widgets["st_n_threads"] = st_n_threads

        hint = QLabel("At least one backend must be active (TF-IDF, ST or Literal).")
        hint.setStyleSheet("color: #F38BA8; font-size: 10px;")
        form.addRow(hint)
        widgets["backends_hint"] = hint

    def _build_hyde_group(self, root, groups, forms, widgets) -> None:
        form = add_group(root, groups, forms, "hyde", "HyDE (Query Expansion)")

        use_hyde = QCheckBox("HyDE aktivieren")
        form.addRow(use_hyde)
        widgets["use_hyde"] = use_hyde

        hyde_min_words = QSpinBox()
        hyde_min_words.setRange(1, 20)
        form.addRow("Expand wenn ≤ N Wörter:", hyde_min_words)
        widgets["hyde_min_words"] = hyde_min_words

        hyde_tfidf_mode = QComboBox()
        hyde_tfidf_mode.addItems(["keywords", "passage"])
        form.addRow("TF-IDF-Modus:", hyde_tfidf_mode)
        widgets["hyde_tfidf_mode"] = hyde_tfidf_mode

        hyde_st_mode = QComboBox()
        hyde_st_mode.addItems(["passage", "multi_passage"])
        form.addRow("ST-Modus:", hyde_st_mode)
        widgets["hyde_st_mode"] = hyde_st_mode

        hyde_hypotheses_label = QLabel("Hypothesen:")
        hyde_st_hypotheses = QSpinBox()
        hyde_st_hypotheses.setRange(2, 10)
        form.addRow(hyde_hypotheses_label, hyde_st_hypotheses)
        widgets["hyde_hypotheses_label"] = hyde_hypotheses_label
        widgets["hyde_st_hypotheses"] = hyde_st_hypotheses

        hyde_use_doc_context = QCheckBox("Dokumentstruktur als HyDE-Kontext (TOC)")
        form.addRow(hyde_use_doc_context)
        widgets["hyde_use_doc_context"] = hyde_use_doc_context

    def _build_selection_group(self, root, groups, forms, widgets) -> None:
        form = add_group(root, groups, forms, "selection", "Result Selection")

        selection_mode = QComboBox()
        selection_mode.addItems(["top_k", "threshold", "top_k_threshold"])
        form.addRow("Mode:", selection_mode)
        widgets["selection_mode"] = selection_mode

        hint = QLabel(
            "top_k: return best N results\n"
            "threshold: return all above score\n"
            "top_k_threshold: best N above score\n"
            "Applied to all backends (TF-IDF, ST, Literal)."
        )
        hint.setStyleSheet("color: #6C7086; font-size: 10px;")
        form.addRow(hint)
        widgets["selection_hint"] = hint

        top_k = QSpinBox()
        top_k.setRange(1, 100)
        form.addRow("Top-K (N):", top_k)
        widgets["top_k"] = top_k

        threshold = QDoubleSpinBox()
        threshold.setRange(0.0, 2.0)
        threshold.setSingleStep(0.05)
        threshold.setDecimals(3)
        form.addRow("Score threshold:", threshold)
        widgets["threshold"] = threshold

        llm_rerank_enabled = QCheckBox("LLM rerank + filter before display")
        form.addRow(llm_rerank_enabled)
        widgets["llm_rerank_enabled"] = llm_rerank_enabled

        llm_rerank_min_score = QDoubleSpinBox()
        llm_rerank_min_score.setRange(0.0, 1.0)
        llm_rerank_min_score.setSingleStep(0.05)
        llm_rerank_min_score.setDecimals(2)
        llm_rerank_min_score.setToolTip(
            "Used only as fallback when a reranker output does not contain class labels."
        )
        form.addRow("LLM min relevance (fallback):", llm_rerank_min_score)
        widgets["llm_rerank_min_score"] = llm_rerank_min_score

        llm_rerank_max_candidates = QSpinBox()
        llm_rerank_max_candidates.setRange(1, 50)
        llm_rerank_max_candidates.setToolTip(
            "Legacy compatibility value. Per-hit reranking currently evaluates all hits."
        )
        form.addRow("LLM max candidates (legacy):", llm_rerank_max_candidates)
        widgets["llm_rerank_max_candidates"] = llm_rerank_max_candidates

        rerank_hint = QLabel(
            "Requires a loaded LLM. Hits are classified as 'sinnvoll' or 'nicht_sinnvoll'."
        )
        rerank_hint.setStyleSheet("color: #6C7086; font-size: 10px;")
        form.addRow(rerank_hint)
        widgets["rerank_hint"] = rerank_hint

    def _build_literal_group(self, root, groups, forms, widgets) -> None:
        form = add_group(root, groups, forms, "literal", "Direct Match (Literal Search)")

        hint = QLabel("Details for the Literal backend (configured above).")
        hint.setStyleSheet("color: #6C7086; font-size: 10px;")
        form.addRow(hint)
        widgets["literal_hint"] = hint

        regex_max = QSpinBox()
        regex_max.setRange(0, 20)
        form.addRow("Max literal results:", regex_max)
        widgets["regex_max"] = regex_max

        literal_use_llm_terms = QCheckBox("Ask LLM for literal terms:")
        form.addRow(literal_use_llm_terms)
        widgets["literal_use_llm_terms"] = literal_use_llm_terms

        literal_llm_max_terms = QSpinBox()
        literal_llm_max_terms.setRange(1, 30)
        form.addRow("Max LLM terms:", literal_llm_max_terms)
        widgets["literal_llm_max_terms"] = literal_llm_max_terms

    def _connect_signals(self) -> None:
        widgets = self._controls.widgets
        self._controls.button_box.accepted.connect(self.accept)
        self._controls.button_box.rejected.connect(self.reject)
        self._controls.reset_button.clicked.connect(lambda: self._load(RAGConfig()))

        widgets["use_tfidf"].toggled.connect(self._validate_backends)  # type: ignore[attr-defined]
        widgets["use_st"].toggled.connect(self._validate_backends)  # type: ignore[attr-defined]
        widgets["use_regex"].toggled.connect(self._validate_backends)  # type: ignore[attr-defined]
        widgets["use_regex"].toggled.connect(self._update_literal_visibility)  # type: ignore[attr-defined]
        widgets["hyde_st_mode"].currentTextChanged.connect(  # type: ignore[attr-defined]
            lambda _text: self._update_hyde_visibility()
        )
        widgets["literal_use_llm_terms"].toggled.connect(self._update_literal_visibility)  # type: ignore[attr-defined]
        widgets["llm_rerank_enabled"].toggled.connect(self._update_rerank_visibility)  # type: ignore[attr-defined]

    def _sync_dynamic_state(self) -> None:
        self._update_literal_visibility()
        self._update_rerank_visibility()
        self._update_hyde_visibility()
        self._validate_backends()

    def _validate_backends(self) -> None:
        w = self._controls.widgets
        has_backend = any(
            (
                w["use_tfidf"].isChecked(),  # type: ignore[attr-defined]
                w["use_st"].isChecked(),  # type: ignore[attr-defined]
                w["use_regex"].isChecked(),  # type: ignore[attr-defined]
            )
        )
        self._controls.ok_button.setEnabled(has_backend)

    def _update_hyde_visibility(self) -> None:
        w = self._controls.widgets
        visible = (
            mode_rank(self._user_mode) >= mode_rank(USER_MODE_EXPERT)
            and w["hyde_st_mode"].currentText() == "multi_passage"  # type: ignore[attr-defined]
        )
        w["hyde_hypotheses_label"].setVisible(visible)
        w["hyde_st_hypotheses"].setVisible(visible)

    def _update_literal_visibility(self) -> None:
        w = self._controls.widgets
        use_literal = w["use_regex"].isChecked()  # type: ignore[attr-defined]
        w["regex_max"].setEnabled(use_literal)
        w["literal_use_llm_terms"].setEnabled(use_literal)
        w["literal_llm_max_terms"].setEnabled(
            use_literal and w["literal_use_llm_terms"].isChecked()  # type: ignore[attr-defined]
        )

    def _update_rerank_visibility(self) -> None:
        w = self._controls.widgets
        expert = mode_rank(self._user_mode) >= mode_rank(USER_MODE_EXPERT)
        enabled = w["llm_rerank_enabled"].isChecked()  # type: ignore[attr-defined]
        w["llm_rerank_min_score"].setEnabled(enabled and expert)
        w["llm_rerank_max_candidates"].setEnabled(False)

    def _load(self, cfg: RAGConfig) -> None:
        load_config_into_controls(self._controls, cfg)
        self._sync_dynamic_state()

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        rank = mode_rank(self._user_mode)
        plus_or_higher = rank >= mode_rank(USER_MODE_PLUS)
        expert_only = rank >= mode_rank(USER_MODE_EXPERT)
        w = self._controls.widgets
        f = self._controls.forms
        g = self._controls.groups

        if self._user_mode == USER_MODE_SIMPLE:
            self._controls.mode_hint.setText(
                "Einfach-Modus: nur Kernoptionen. Erweiterte Werte bleiben gespeichert."
            )
        elif self._user_mode == USER_MODE_PLUS:
            self._controls.mode_hint.setText(
                "Plus-Modus: zusätzliche, aber überschaubare Einstellungen."
            )
        else:
            self._controls.mode_hint.setText(
                "Experte-Modus: vollständige Kontrolle über alle RAG-Parameter."
            )

        g["backends"].setVisible(plus_or_higher)
        g["hyde"].setVisible(plus_or_higher)
        g["chunking"].setVisible(plus_or_higher)
        g["extended"].setVisible(plus_or_higher)
        g["selection"].setVisible(True)
        g["literal"].setVisible(expert_only)

        if not expert_only:
            w["use_tfidf"].setChecked(True)  # type: ignore[attr-defined]

        _set_form_row_visible(f["backends"], w["use_tfidf"], expert_only)
        _set_form_row_visible(f["backends"], w["st_model"], expert_only)
        _set_form_row_visible(f["backends"], w["st_n_threads"], expert_only)
        w["backends_hint"].setVisible(plus_or_higher)

        _set_form_row_visible(f["hyde"], w["hyde_tfidf_mode"], expert_only)
        _set_form_row_visible(f["hyde"], w["hyde_st_mode"], expert_only)
        _set_form_row_visible(f["hyde"], w["hyde_use_doc_context"], expert_only)

        _set_form_row_visible(f["chunking"], w["chunk_overlap"], expert_only)
        _set_form_row_visible(f["chunking"], w["chunking_strategy"], expert_only)
        _set_form_row_visible(f["chunking"], w["include_headings"], expert_only)
        _set_form_row_visible(f["chunking"], w["include_filename"], expert_only)

        w["extended_hint"].setVisible(expert_only)
        _set_form_row_visible(f["extended"], w["ext_before"], expert_only)
        _set_form_row_visible(f["extended"], w["ext_after"], expert_only)

        _set_form_row_visible(f["selection"], w["selection_mode"], plus_or_higher)
        w["selection_hint"].setVisible(plus_or_higher)
        _set_form_row_visible(f["selection"], w["threshold"], plus_or_higher)
        _set_form_row_visible(f["selection"], w["llm_rerank_enabled"], plus_or_higher)
        _set_form_row_visible(f["selection"], w["llm_rerank_min_score"], expert_only)
        _set_form_row_visible(
            f["selection"],
            w["llm_rerank_max_candidates"],
            expert_only,
        )
        w["rerank_hint"].setVisible(plus_or_higher)
        self._sync_dynamic_state()

    def get_config(self) -> RAGConfig:
        return build_config_from_controls(self._controls)
