"""Dialog exposing all RAGConfig parameters as editable widgets."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import (
    default_user_mode,
    is_feature_visible,
    normalize_user_mode,
    resolve_feature_label,
)
from shared.domain.slider_presets import rag_scope_presets, rag_speed_quality_presets
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


_MODE_HINT_DEFAULTS = {
    "simple": "Einfach-Modus: nur Kernoptionen. Erweiterte Werte bleiben gespeichert.",
    "plus": "Plus-Modus: zusätzliche, aber überschaubare Einstellungen.",
    "expert": "Experte-Modus: vollständige Kontrolle über alle RAG-Parameter.",
}
_GREEN_SLIDER_STYLE = """
QSlider::groove:horizontal {
    height: 6px;
    background: palette(midlight);
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #2ea043;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #2ea043;
    border: 1px solid #1f7a33;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background: #3fb950;
}
"""

_RAG_SCOPE_PRESETS: tuple[dict[str, object], ...] = rag_scope_presets()
_RAG_SPEED_QUALITY_PRESETS: tuple[dict[str, object], ...] = rag_speed_quality_presets()

_RAG_SCOPE_FIELDS = tuple(_RAG_SCOPE_PRESETS[0].keys())
_RAG_SPEED_QUALITY_FIELDS = tuple(_RAG_SPEED_QUALITY_PRESETS[0].keys())


class RAGSettingsDialog(QDialog):
    """Dialog for editing all parameters of a RAGConfig."""

    def __init__(self, config: RAGConfig, parent=None, user_mode: str | None = None):
        super().__init__(parent)
        self.setStyleSheet(RAG_SETTINGS_STYLE)
        self.setMinimumWidth(440)
        self._user_mode = normalize_user_mode(default_user_mode() if user_mode is None else user_mode)
        self._show_hyde_hypotheses = False
        self._show_rerank_min_score = False
        self._show_bm25_k1 = True
        self._show_bm25_b = True
        self._syncing_simple_profiles = False
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
        mode_hint.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
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

        use_tfidf = QCheckBox("Lexical Search (TF-IDF/BM25)")
        use_st = QCheckBox("Sentence-Transformers")
        use_regex = QCheckBox("Regex Search")
        form.addRow(use_tfidf)
        form.addRow(use_st)
        form.addRow(use_regex)
        widgets["use_tfidf"] = use_tfidf
        widgets["use_st"] = use_st
        widgets["use_regex"] = use_regex

        lexical_mode = QComboBox()
        lexical_mode.addItems(["tfidf", "bm25"])
        lexical_mode.setToolTip(
            "Select lexical ranking backend.\n"
            "tfidf = weighted term relevance, bm25 = Okapi BM25."
        )
        form.addRow("  Lexical mode:", lexical_mode)
        widgets["lexical_mode"] = lexical_mode

        bm25_k1 = QDoubleSpinBox()
        bm25_k1.setRange(0.20, 3.00)
        bm25_k1.setDecimals(2)
        bm25_k1.setSingleStep(0.05)
        bm25_k1.setToolTip(
            "BM25 TF saturation parameter.\n"
            "Higher values increase term-frequency influence."
        )
        form.addRow("  BM25 k1:", bm25_k1)
        widgets["bm25_k1"] = bm25_k1

        bm25_b = QDoubleSpinBox()
        bm25_b.setRange(0.00, 1.00)
        bm25_b.setDecimals(2)
        bm25_b.setSingleStep(0.05)
        bm25_b.setToolTip(
            "BM25 document-length normalization.\n"
            "0 disables length norm, 1 applies full normalization."
        )
        form.addRow("  BM25 b:", bm25_b)
        widgets["bm25_b"] = bm25_b

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

        hint = QLabel("At least one backend must be active (TF-IDF, ST or Regex).")
        hint.setStyleSheet("color: palette(bright-text); font-size: 10px;")
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

        scope_slider = QSlider(Qt.Orientation.Horizontal)
        scope_slider.setRange(0, 2)
        scope_slider.setSingleStep(1)
        scope_slider.setPageStep(1)
        scope_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        scope_slider.setTickInterval(1)
        scope_slider.setValue(1)
        scope_slider.setStyleSheet(_GREEN_SLIDER_STYLE)
        scope_slider.setToolTip(
            "Steuert, wie umfangreich die gefundenen Ergebnisse ausfallen.\n"
            "Setzt Auswahlgrenzen und Kontextumfang automatisch."
        )
        scope_mark_compact = QLabel("Kompakt")
        scope_mark_balanced = QLabel("Ausgewogen")
        scope_mark_extensive = QLabel("Umfangreich")
        for mark in (
            scope_mark_compact,
            scope_mark_balanced,
            scope_mark_extensive,
        ):
            mark.setStyleSheet("color: palette(placeholder-text); font-size: 9px;")

        scope_marks_row = QHBoxLayout()
        scope_marks_row.setContentsMargins(0, 0, 0, 0)
        scope_marks_row.setSpacing(4)
        scope_marks_row.addWidget(
            scope_mark_compact,
            1,
            Qt.AlignmentFlag.AlignLeft,
        )
        scope_marks_row.addWidget(
            scope_mark_balanced,
            1,
            Qt.AlignmentFlag.AlignHCenter,
        )
        scope_marks_row.addWidget(
            scope_mark_extensive,
            1,
            Qt.AlignmentFlag.AlignRight,
        )

        scope_widget = QWidget()
        scope_layout = QVBoxLayout(scope_widget)
        scope_layout.setContentsMargins(0, 0, 0, 0)
        scope_layout.setSpacing(1)
        scope_layout.addWidget(scope_slider)
        scope_layout.addLayout(scope_marks_row)
        form.addRow("Ergebnisumfang:", scope_widget)
        widgets["scope_profile_widget"] = scope_widget
        widgets["scope_profile_slider"] = scope_slider
        widgets["scope_profile_mark_compact"] = scope_mark_compact
        widgets["scope_profile_mark_balanced"] = scope_mark_balanced
        widgets["scope_profile_mark_extensive"] = scope_mark_extensive

        speed_slider = QSlider(Qt.Orientation.Horizontal)
        speed_slider.setRange(0, 2)
        speed_slider.setSingleStep(1)
        speed_slider.setPageStep(1)
        speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        speed_slider.setTickInterval(1)
        speed_slider.setValue(1)
        speed_slider.setStyleSheet(_GREEN_SLIDER_STYLE)
        speed_slider.setToolTip(
            "Steuert den Fokus zwischen Antwortgeschwindigkeit und Antwortqualitaet.\n"
            "Setzt HyDE und Reranking automatisch."
        )
        speed_mark_fast = QLabel("Schnell")
        speed_mark_balanced = QLabel("Ausgewogen")
        speed_mark_quality = QLabel("Qualitaet")
        for mark in (
            speed_mark_fast,
            speed_mark_balanced,
            speed_mark_quality,
        ):
            mark.setStyleSheet("color: palette(placeholder-text); font-size: 9px;")

        speed_marks_row = QHBoxLayout()
        speed_marks_row.setContentsMargins(0, 0, 0, 0)
        speed_marks_row.setSpacing(4)
        speed_marks_row.addWidget(
            speed_mark_fast,
            1,
            Qt.AlignmentFlag.AlignLeft,
        )
        speed_marks_row.addWidget(
            speed_mark_balanced,
            1,
            Qt.AlignmentFlag.AlignHCenter,
        )
        speed_marks_row.addWidget(
            speed_mark_quality,
            1,
            Qt.AlignmentFlag.AlignRight,
        )

        speed_widget = QWidget()
        speed_layout = QVBoxLayout(speed_widget)
        speed_layout.setContentsMargins(0, 0, 0, 0)
        speed_layout.setSpacing(1)
        speed_layout.addWidget(speed_slider)
        speed_layout.addLayout(speed_marks_row)
        form.addRow("Geschwindigkeit vs Qualitaet:", speed_widget)
        widgets["speed_profile_widget"] = speed_widget
        widgets["speed_profile_slider"] = speed_slider
        widgets["speed_profile_mark_fast"] = speed_mark_fast
        widgets["speed_profile_mark_balanced"] = speed_mark_balanced
        widgets["speed_profile_mark_quality"] = speed_mark_quality

        selection_mode = QComboBox()
        selection_mode.addItems(["top_k", "threshold", "top_k_threshold"])
        form.addRow("Mode:", selection_mode)
        widgets["selection_mode"] = selection_mode

        hint = QLabel(
            "top_k: return best N results\n"
            "threshold: return all above score\n"
            "top_k_threshold: best N above score\n"
            "Applied to all backends (TF-IDF, ST, Regex)."
        )
        hint.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
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
            "Reserved setting. Current per-hit reranking evaluates all hits."
        )
        form.addRow("LLM max candidates:", llm_rerank_max_candidates)
        widgets["llm_rerank_max_candidates"] = llm_rerank_max_candidates

        rerank_hint = QLabel(
            "Requires a loaded LLM. Hits are classified as 'sinnvoll' or 'nicht_sinnvoll'."
        )
        rerank_hint.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
        form.addRow(rerank_hint)
        widgets["rerank_hint"] = rerank_hint

    def _build_literal_group(self, root, groups, forms, widgets) -> None:
        form = add_group(root, groups, forms, "literal", "Direct Match (Regex Search)")

        hint = QLabel("Details for the Regex backend (configured above).")
        hint.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
        form.addRow(hint)
        widgets["literal_hint"] = hint

        regex_max = QSpinBox()
        regex_max.setRange(0, 20)
        form.addRow("Max regex results:", regex_max)
        widgets["regex_max"] = regex_max

        literal_use_llm_terms = QCheckBox("Ask LLM for regex patterns:")
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
        widgets["use_tfidf"].toggled.connect(self._update_lexical_visibility)  # type: ignore[attr-defined]
        widgets["lexical_mode"].currentTextChanged.connect(  # type: ignore[attr-defined]
            lambda _text: self._update_lexical_visibility()
        )
        widgets["use_st"].toggled.connect(self._validate_backends)  # type: ignore[attr-defined]
        widgets["use_regex"].toggled.connect(self._validate_backends)  # type: ignore[attr-defined]
        widgets["use_regex"].toggled.connect(self._update_literal_visibility)  # type: ignore[attr-defined]
        widgets["hyde_st_mode"].currentTextChanged.connect(  # type: ignore[attr-defined]
            lambda _text: self._update_hyde_visibility()
        )
        widgets["literal_use_llm_terms"].toggled.connect(self._update_literal_visibility)  # type: ignore[attr-defined]
        widgets["llm_rerank_enabled"].toggled.connect(self._update_rerank_visibility)  # type: ignore[attr-defined]
        widgets["scope_profile_slider"].valueChanged.connect(  # type: ignore[attr-defined]
            self._on_scope_profile_slider_changed
        )
        widgets["speed_profile_slider"].valueChanged.connect(  # type: ignore[attr-defined]
            self._on_speed_profile_slider_changed
        )
        self._connect_scope_profile_sync_signals()
        self._connect_speed_profile_sync_signals()

    def _sync_dynamic_state(self) -> None:
        self._update_lexical_visibility()
        self._update_literal_visibility()
        self._update_rerank_visibility()
        self._update_hyde_visibility()
        self._validate_backends()
        self._sync_scope_profile_from_controls()
        self._sync_speed_profile_from_controls()

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

    def _update_lexical_visibility(self) -> None:
        w = self._controls.widgets
        f = self._controls.forms
        lexical_enabled = w["use_tfidf"].isChecked()  # type: ignore[attr-defined]
        mode = str(w["lexical_mode"].currentText()).strip().lower()  # type: ignore[attr-defined]
        use_bm25 = lexical_enabled and mode == "bm25"
        w["lexical_mode"].setEnabled(lexical_enabled)

        show_k1_row = bool(self._show_bm25_k1 and use_bm25)
        show_b_row = bool(self._show_bm25_b and use_bm25)
        _set_form_row_visible(f["backends"], w["bm25_k1"], show_k1_row)
        _set_form_row_visible(f["backends"], w["bm25_b"], show_b_row)
        w["bm25_k1"].setEnabled(show_k1_row)
        w["bm25_b"].setEnabled(show_b_row)

    def _update_hyde_visibility(self) -> None:
        w = self._controls.widgets
        visible = (
            bool(self._show_hyde_hypotheses)
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
        enabled = w["llm_rerank_enabled"].isChecked()  # type: ignore[attr-defined]
        w["llm_rerank_min_score"].setEnabled(enabled and bool(self._show_rerank_min_score))
        w["llm_rerank_max_candidates"].setEnabled(False)

    def _connect_slider_sync_signals(
        self,
        fields: tuple[str, ...],
        sync_callback,
    ) -> None:
        w = self._controls.widgets
        for key in fields:
            widget = w.get(key)
            if widget is None:
                continue
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(lambda _checked: sync_callback())
                continue
            if isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(lambda _text: sync_callback())
                continue
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.valueChanged.connect(lambda _value: sync_callback())

    def _connect_scope_profile_sync_signals(self) -> None:
        self._connect_slider_sync_signals(
            _RAG_SCOPE_FIELDS,
            self._sync_scope_profile_from_controls,
        )

    def _connect_speed_profile_sync_signals(self) -> None:
        self._connect_slider_sync_signals(
            _RAG_SPEED_QUALITY_FIELDS,
            self._sync_speed_profile_from_controls,
        )

    def _set_widget_value(self, key: str, value: object) -> None:
        widget = self._controls.widgets.get(key)
        if widget is None:
            return
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
            return
        if isinstance(widget, QComboBox):
            target = str(value or "")
            index = widget.findText(target)
            if index >= 0:
                widget.setCurrentIndex(index)
            return
        if isinstance(widget, QSpinBox):
            widget.setValue(int(value))
            return
        if isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(value))

    def _apply_preset(self, preset: dict[str, object]) -> None:
        if self._syncing_simple_profiles:
            return
        self._syncing_simple_profiles = True
        try:
            for key, value in preset.items():
                self._set_widget_value(key, value)
            self._sync_dynamic_state()
        finally:
            self._syncing_simple_profiles = False

    def _on_scope_profile_slider_changed(self, profile_index: int) -> None:
        idx = max(0, min(2, int(profile_index)))
        self._apply_preset(_RAG_SCOPE_PRESETS[idx])

    def _on_speed_profile_slider_changed(self, profile_index: int) -> None:
        idx = max(0, min(2, int(profile_index)))
        self._apply_preset(_RAG_SPEED_QUALITY_PRESETS[idx])

    def _profile_distance(self, preset: dict[str, object], fields: tuple[str, ...]) -> float:
        distance = 0.0
        for key in fields:
            if key not in preset:
                continue
            expected = preset[key]
            widget = self._controls.widgets.get(key)
            if widget is None:
                continue
            if isinstance(widget, QCheckBox):
                distance += 0.0 if widget.isChecked() == bool(expected) else 1.0
                continue
            if isinstance(widget, QComboBox):
                distance += 0.0 if str(widget.currentText()) == str(expected) else 1.0
                continue
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                span = max(float(widget.maximum() - widget.minimum()), 1.0)
                current = float(widget.value())
                target = float(expected)
                distance += abs(current - target) / span
        return distance

    def _nearest_profile_index(
        self,
        presets: tuple[dict[str, object], ...],
        fields: tuple[str, ...],
    ) -> int:
        distances: list[tuple[float, int]] = []
        for idx, preset in enumerate(presets):
            distances.append((self._profile_distance(preset, fields), idx))
        distances.sort(key=lambda item: (item[0], item[1]))
        return int(distances[0][1])

    def _sync_scope_profile_from_controls(self) -> None:
        if self._syncing_simple_profiles:
            return
        slider = self._controls.widgets.get("scope_profile_slider")
        if not isinstance(slider, QSlider):
            return
        idx = self._nearest_profile_index(_RAG_SCOPE_PRESETS, _RAG_SCOPE_FIELDS)
        self._syncing_simple_profiles = True
        try:
            slider.setValue(idx)
        finally:
            self._syncing_simple_profiles = False

    def _sync_speed_profile_from_controls(self) -> None:
        if self._syncing_simple_profiles:
            return
        slider = self._controls.widgets.get("speed_profile_slider")
        if not isinstance(slider, QSlider):
            return
        idx = self._nearest_profile_index(_RAG_SPEED_QUALITY_PRESETS, _RAG_SPEED_QUALITY_FIELDS)
        self._syncing_simple_profiles = True
        try:
            slider.setValue(idx)
        finally:
            self._syncing_simple_profiles = False

    def _load(self, cfg: RAGConfig) -> None:
        load_config_into_controls(self._controls, cfg)
        self._sync_dynamic_state()

    def _set_form_row_label(
        self,
        form_key: str,
        field_key: str,
        label_key: str,
        fallback: str,
    ) -> None:
        form = self._controls.forms.get(form_key)
        field = self._controls.widgets.get(field_key)
        if form is None or field is None:
            return
        label = form.labelForField(field)
        if label is None:
            return
        label.setText(
            resolve_feature_label(
                self._user_mode,
                label_key,
                fallback,
            )
        )

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self.setWindowTitle(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.window_title",
                "RAG Settings",
            )
        )
        w = self._controls.widgets
        f = self._controls.forms
        g = self._controls.groups

        g["backends"].setTitle(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.group.backends.title",
                "Backends",
            )
        )
        g["hyde"].setTitle(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.group.hyde.title",
                "HyDE (Query Expansion)",
            )
        )
        g["chunking"].setTitle(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.group.chunking.title",
                "Chunking",
            )
        )
        g["extended"].setTitle(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.group.extended.title",
                "Erweiterter Kontext",
            )
        )
        g["selection"].setTitle(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.group.selection.title",
                "Result Selection",
            )
        )
        g["literal"].setTitle(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.group.literal.title",
                "Direct Match (Regex Search)",
            )
        )

        w["use_tfidf"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.backends.use_tfidf.label",
                "Lexical Search (TF-IDF/BM25)",
            )
        )
        self._set_form_row_label(
            "backends",
            "lexical_mode",
            "rag.settings.backends.lexical_mode.label",
            "  Lexical mode:",
        )
        w["lexical_mode"].setToolTip(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.backends.lexical_mode.tooltip",
                "Select lexical ranking backend.\n"
                "tfidf = weighted term relevance, bm25 = Okapi BM25.",
            )
        )
        self._set_form_row_label(
            "backends",
            "bm25_k1",
            "rag.settings.backends.bm25_k1.label",
            "  BM25 k1:",
        )
        self._set_form_row_label(
            "backends",
            "bm25_b",
            "rag.settings.backends.bm25_b.label",
            "  BM25 b:",
        )
        w["bm25_k1"].setToolTip(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.backends.bm25_k1.tooltip",
                "BM25 TF saturation parameter.\n"
                "Higher values increase term-frequency influence.",
            )
        )
        w["bm25_b"].setToolTip(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.backends.bm25_b.tooltip",
                "BM25 document-length normalization.\n"
                "0 disables length norm, 1 applies full normalization.",
            )
        )
        w["use_st"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.backends.use_st.label",
                "Sentence-Transformers",
            )
        )
        w["use_regex"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.backends.use_regex.label",
                "Regex Search",
            )
        )
        self._set_form_row_label(
            "backends",
            "st_model",
            "rag.settings.backends.st_model.label",
            "  Model name:",
        )
        self._set_form_row_label(
            "backends",
            "st_n_threads",
            "rag.settings.backends.st_n_threads.label",
            "  CPU threads (ST):",
        )
        w["st_n_threads"].setToolTip(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.backends.st_n_threads.tooltip",
                "CPU threads used by PyTorch/sentence-transformers.\n"
                "0 = use all available cores (recommended).",
            )
        )
        w["backends_hint"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.backends.hint.text",
                "At least one backend must be active (TF-IDF, ST or Regex).",
            )
        )

        w["use_hyde"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.hyde.use_hyde.label",
                "HyDE aktivieren",
            )
        )
        self._set_form_row_label(
            "hyde",
            "hyde_min_words",
            "rag.settings.hyde.min_words.label",
            "Expand wenn ≤ N Wörter:",
        )
        self._set_form_row_label(
            "hyde",
            "hyde_tfidf_mode",
            "rag.settings.hyde.tfidf_mode.label",
            "TF-IDF-Modus:",
        )
        self._set_form_row_label(
            "hyde",
            "hyde_st_mode",
            "rag.settings.hyde.st_mode.label",
            "ST-Modus:",
        )
        w["hyde_hypotheses_label"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.hyde.hypotheses.label",
                "Hypothesen:",
            )
        )
        w["hyde_use_doc_context"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.hyde.use_doc_context.label",
                "Dokumentstruktur als HyDE-Kontext (TOC)",
            )
        )

        self._set_form_row_label(
            "chunking",
            "chunk_size",
            "rag.settings.chunking.chunk_size.label",
            "Chunk-Größe:",
        )
        self._set_form_row_label(
            "chunking",
            "chunk_overlap",
            "rag.settings.chunking.overlap.label",
            "Sliding-Window-Overlap:",
        )
        self._set_form_row_label(
            "chunking",
            "chunking_strategy",
            "rag.settings.chunking.strategy.label",
            "Strategie:",
        )
        w["include_headings"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.chunking.include_headings.label",
                "Heading-Breadcrumb einbetten",
            )
        )
        w["include_filename"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.chunking.include_filename.label",
                "Dateiname einbetten",
            )
        )

        w["extended_context"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.extended.enabled.label",
                "Erweitertes Kontext-Fenster aktivieren",
            )
        )
        w["extended_hint"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.extended.hint.text",
                "Expandiert jeden Treffer um ±N Zeichen im Originaldokument.",
            )
        )
        self._set_form_row_label(
            "extended",
            "ext_before",
            "rag.settings.extended.before.label",
            "Vor dem Chunk:",
        )
        self._set_form_row_label(
            "extended",
            "ext_after",
            "rag.settings.extended.after.label",
            "Nach dem Chunk:",
        )

        self._set_form_row_label(
            "selection",
            "scope_profile_widget",
            "rag.settings.selection.scope_profile.label",
            "Ergebnisumfang:",
        )
        w["scope_profile_slider"].setToolTip(  # type: ignore[attr-defined]
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.scope_profile.tooltip",
                "Steuert, wie umfangreich die gefundenen Ergebnisse ausfallen.\n"
                "Setzt Auswahlgrenzen und Kontextumfang automatisch.",
            )
        )
        w["scope_profile_mark_compact"].setText(  # type: ignore[attr-defined]
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.scope_profile.compact",
                "Kompakt",
            )
        )
        w["scope_profile_mark_balanced"].setText(  # type: ignore[attr-defined]
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.scope_profile.balanced",
                "Ausgewogen",
            )
        )
        w["scope_profile_mark_extensive"].setText(  # type: ignore[attr-defined]
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.scope_profile.extensive",
                "Umfangreich",
            )
        )
        self._set_form_row_label(
            "selection",
            "speed_profile_widget",
            "rag.settings.selection.speed_profile.label",
            "Geschwindigkeit vs Qualitaet:",
        )
        w["speed_profile_slider"].setToolTip(  # type: ignore[attr-defined]
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.speed_profile.tooltip",
                "Steuert den Fokus zwischen Antwortgeschwindigkeit und Antwortqualitaet.\n"
                "Setzt HyDE und Reranking automatisch.",
            )
        )
        w["speed_profile_mark_fast"].setText(  # type: ignore[attr-defined]
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.speed_profile.fast",
                "Schnell",
            )
        )
        w["speed_profile_mark_balanced"].setText(  # type: ignore[attr-defined]
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.speed_profile.balanced",
                "Ausgewogen",
            )
        )
        w["speed_profile_mark_quality"].setText(  # type: ignore[attr-defined]
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.speed_profile.quality",
                "Qualitaet",
            )
        )
        self._set_form_row_label(
            "selection",
            "selection_mode",
            "rag.settings.selection.mode.label",
            "Mode:",
        )
        w["selection_hint"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.hint.text",
                "top_k: return best N results\n"
                "threshold: return all above score\n"
                "top_k_threshold: best N above score\n"
                "Applied to all backends (TF-IDF, ST, Regex).",
            )
        )
        self._set_form_row_label(
            "selection",
            "top_k",
            "rag.settings.selection.top_k.label",
            "Top-K (N):",
        )
        self._set_form_row_label(
            "selection",
            "threshold",
            "rag.settings.selection.threshold.label",
            "Score threshold:",
        )
        w["llm_rerank_enabled"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.llm_rerank_enabled.label",
                "LLM rerank + filter before display",
            )
        )
        self._set_form_row_label(
            "selection",
            "llm_rerank_min_score",
            "rag.settings.selection.llm_rerank_min_score.label",
            "LLM min relevance (fallback):",
        )
        w["llm_rerank_min_score"].setToolTip(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.llm_rerank_min_score.tooltip",
                "Used only as fallback when a reranker output does not contain class labels.",
            )
        )
        self._set_form_row_label(
            "selection",
            "llm_rerank_max_candidates",
            "rag.settings.selection.llm_rerank_max_candidates.label",
            "LLM max candidates:",
        )
        w["llm_rerank_max_candidates"].setToolTip(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.llm_rerank_max_candidates.tooltip",
                "Reserved setting. Current per-hit reranking evaluates all hits.",
            )
        )
        w["rerank_hint"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.selection.rerank_hint.text",
                "Requires a loaded LLM. Hits are classified as 'sinnvoll' or 'nicht_sinnvoll'.",
            )
        )

        w["literal_hint"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.literal.hint.text",
                "Details for the Regex backend (configured above).",
            )
        )
        self._set_form_row_label(
            "literal",
            "regex_max",
            "rag.settings.literal.max_results.label",
            "Max regex results:",
        )
        w["literal_use_llm_terms"].setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.literal.use_llm_terms.label",
                "Ask LLM for regex patterns:",
            )
        )
        self._set_form_row_label(
            "literal",
            "literal_llm_max_terms",
            "rag.settings.literal.max_llm_terms.label",
            "Max LLM terms:",
        )

        self._controls.ok_button.setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.button.ok",
                "OK",
            )
        )
        cancel_button = self._controls.button_box.button(
            QDialogButtonBox.StandardButton.Cancel
        )
        if cancel_button is not None:
            cancel_button.setText(
                resolve_feature_label(
                    self._user_mode,
                    "rag.settings.button.cancel",
                    "Cancel",
                )
            )
        self._controls.reset_button.setText(
            resolve_feature_label(
                self._user_mode,
                "rag.settings.button.restore_defaults",
                "Restore Defaults",
            )
        )

        mode_hint_simple = bool(
            is_feature_visible(self._user_mode, "rag.settings.mode_hint.simple", default=False)
        )
        mode_hint_plus = bool(
            is_feature_visible(self._user_mode, "rag.settings.mode_hint.plus", default=False)
        )
        mode_hint_expert = bool(
            is_feature_visible(self._user_mode, "rag.settings.mode_hint.expert", default=False)
        )
        if mode_hint_simple:
            hint_key = "simple"
        elif mode_hint_plus:
            hint_key = "plus"
        elif mode_hint_expert:
            hint_key = "expert"
        else:
            hint_key = "plus"
        self._controls.mode_hint.setText(
            resolve_feature_label(
                self._user_mode,
                f"rag.settings.mode_hint.{hint_key}.text",
                _MODE_HINT_DEFAULTS[hint_key],
            )
        )
        self._controls.mode_hint.setVisible(bool(mode_hint_simple or mode_hint_plus or mode_hint_expert))

        show_group_backends = bool(
            is_feature_visible(self._user_mode, "rag.settings.group.backends", default=True)
        )
        show_group_hyde = bool(
            is_feature_visible(self._user_mode, "rag.settings.group.hyde", default=True)
        )
        show_group_chunking = bool(
            is_feature_visible(self._user_mode, "rag.settings.group.chunking", default=True)
        )
        show_group_extended = bool(
            is_feature_visible(self._user_mode, "rag.settings.group.extended", default=True)
        )
        show_group_selection = bool(
            is_feature_visible(self._user_mode, "rag.settings.group.selection", default=True)
        )
        show_group_literal = bool(
            is_feature_visible(self._user_mode, "rag.settings.group.literal", default=True)
        )

        g["backends"].setVisible(show_group_backends)
        g["hyde"].setVisible(show_group_hyde)
        g["chunking"].setVisible(show_group_chunking)
        g["extended"].setVisible(show_group_extended)
        g["selection"].setVisible(show_group_selection)
        g["literal"].setVisible(show_group_literal)

        show_use_tfidf = bool(
            is_feature_visible(self._user_mode, "rag.settings.backends.use_tfidf", default=True)
        )
        show_lexical_mode = bool(
            is_feature_visible(self._user_mode, "rag.settings.backends.lexical_mode", default=True)
        )
        show_bm25_k1 = bool(
            is_feature_visible(self._user_mode, "rag.settings.backends.bm25_k1", default=True)
        )
        show_bm25_b = bool(
            is_feature_visible(self._user_mode, "rag.settings.backends.bm25_b", default=True)
        )
        self._show_bm25_k1 = show_bm25_k1
        self._show_bm25_b = show_bm25_b
        show_st_model = bool(
            is_feature_visible(self._user_mode, "rag.settings.backends.st_model", default=True)
        )
        show_st_n_threads = bool(
            is_feature_visible(self._user_mode, "rag.settings.backends.st_n_threads", default=True)
        )
        show_backends_hint = bool(
            is_feature_visible(self._user_mode, "rag.settings.backends.hint", default=True)
        )

        if not show_use_tfidf:
            w["use_tfidf"].setChecked(True)  # type: ignore[attr-defined]

        _set_form_row_visible(f["backends"], w["use_tfidf"], show_use_tfidf)
        _set_form_row_visible(f["backends"], w["lexical_mode"], show_lexical_mode)
        _set_form_row_visible(f["backends"], w["bm25_k1"], show_bm25_k1)
        _set_form_row_visible(f["backends"], w["bm25_b"], show_bm25_b)
        _set_form_row_visible(f["backends"], w["st_model"], show_st_model)
        _set_form_row_visible(f["backends"], w["st_n_threads"], show_st_n_threads)
        w["backends_hint"].setVisible(show_backends_hint)

        _set_form_row_visible(
            f["hyde"],
            w["hyde_tfidf_mode"],
            is_feature_visible(self._user_mode, "rag.settings.hyde.tfidf_mode", default=True),
        )
        _set_form_row_visible(
            f["hyde"],
            w["hyde_st_mode"],
            is_feature_visible(self._user_mode, "rag.settings.hyde.st_mode", default=True),
        )
        _set_form_row_visible(
            f["hyde"],
            w["hyde_use_doc_context"],
            is_feature_visible(self._user_mode, "rag.settings.hyde.use_doc_context", default=True),
        )
        self._show_hyde_hypotheses = bool(
            is_feature_visible(self._user_mode, "rag.settings.hyde.hypotheses", default=False)
        )

        _set_form_row_visible(
            f["chunking"],
            w["chunk_overlap"],
            is_feature_visible(self._user_mode, "rag.settings.chunking.overlap", default=True),
        )
        _set_form_row_visible(
            f["chunking"],
            w["chunking_strategy"],
            is_feature_visible(self._user_mode, "rag.settings.chunking.strategy", default=True),
        )
        _set_form_row_visible(
            f["chunking"],
            w["include_headings"],
            is_feature_visible(self._user_mode, "rag.settings.chunking.include_headings", default=True),
        )
        _set_form_row_visible(
            f["chunking"],
            w["include_filename"],
            is_feature_visible(self._user_mode, "rag.settings.chunking.include_filename", default=True),
        )

        w["extended_hint"].setVisible(
            bool(is_feature_visible(self._user_mode, "rag.settings.extended.hint", default=True))
        )
        _set_form_row_visible(
            f["extended"],
            w["ext_before"],
            is_feature_visible(self._user_mode, "rag.settings.extended.before", default=True),
        )
        _set_form_row_visible(
            f["extended"],
            w["ext_after"],
            is_feature_visible(self._user_mode, "rag.settings.extended.after", default=True),
        )

        _set_form_row_visible(
            f["selection"],
            w["scope_profile_widget"],
            is_feature_visible(self._user_mode, "rag.settings.selection.scope_profile", default=True),
        )
        _set_form_row_visible(
            f["selection"],
            w["speed_profile_widget"],
            is_feature_visible(self._user_mode, "rag.settings.selection.speed_profile", default=True),
        )
        _set_form_row_visible(
            f["selection"],
            w["selection_mode"],
            is_feature_visible(self._user_mode, "rag.settings.selection.mode", default=True),
        )
        w["selection_hint"].setVisible(
            bool(is_feature_visible(self._user_mode, "rag.settings.selection.hint", default=True))
        )
        _set_form_row_visible(
            f["selection"],
            w["threshold"],
            is_feature_visible(self._user_mode, "rag.settings.selection.threshold", default=True),
        )
        _set_form_row_visible(
            f["selection"],
            w["llm_rerank_enabled"],
            is_feature_visible(
                self._user_mode,
                "rag.settings.selection.llm_rerank_enabled",
                default=True,
            ),
        )
        self._show_rerank_min_score = bool(
            is_feature_visible(
                self._user_mode,
                "rag.settings.selection.llm_rerank_min_score",
                default=False,
            )
        )
        _set_form_row_visible(
            f["selection"],
            w["llm_rerank_min_score"],
            self._show_rerank_min_score,
        )
        _set_form_row_visible(
            f["selection"],
            w["llm_rerank_max_candidates"],
            is_feature_visible(
                self._user_mode,
                "rag.settings.selection.llm_rerank_max_candidates",
                default=False,
            ),
        )
        w["rerank_hint"].setVisible(
            bool(is_feature_visible(self._user_mode, "rag.settings.selection.rerank_hint", default=True))
        )
        self._sync_dynamic_state()

    def get_config(self) -> RAGConfig:
        return build_config_from_controls(self._controls)
