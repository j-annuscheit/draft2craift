"""Model load and generation-parameter panel for chat dock."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from shared.services.llm.backends import (
    BACKEND_AUTO,
    BACKEND_LLAMA_CPP,
    BACKEND_TRANSFORMERS,
)
from shared.domain.user_mode import (
    default_user_mode,
    normalize_user_mode,
    resolve_feature_label,
)
from shared.domain.slider_presets import (
    chat_context_length_presets,
    chat_generation_style_presets,
)
from studio.user_mode_bindings import (
    apply_form_row_labels,
    apply_form_row_visibility,
    apply_widget_texts,
    apply_widget_tooltips,
    feature_visible,
    set_form_row_visible,
)

from .styles import BTN_NEUTRAL, BTN_PRIMARY

_GENERATION_STYLE_PRESETS: tuple[dict[str, float], ...] = chat_generation_style_presets()
_CONTEXT_LENGTH_PRESETS: tuple[int, ...] = chat_context_length_presets()
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


class ModelLoadPanel(QWidget):
    """Panel for loading text models and editing generation parameters."""

    load_requested = Signal(str, dict)
    nli_load_requested = Signal(str, dict)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._user_mode = default_user_mode()
        self._show_ctx_tokens = True
        self._show_context_profile = True
        self._show_gpu_layers = True
        self._show_threads = False
        self._show_trust_remote_code = False
        self._syncing_context_profile = False
        self._syncing_generation_style = False
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(
            """
            QWidget  { background: palette(alternate-base); }
            QLabel   { color: palette(text); font-size: 10px; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background: palette(base); color: palette(text);
                border: 1px solid palette(mid); border-radius: 3px;
                padding: 3px 6px; font-size: 11px;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: palette(highlight); }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(5)

        self.model_section_lbl = QLabel("Model Load")
        self.model_section_lbl.setStyleSheet(
            "color: palette(highlight); font-size: 10px; font-weight: bold;"
        )
        layout.addWidget(self.model_section_lbl)
        self.model_hint = QLabel("Changes here require clicking 'Load Model'.")
        self.model_hint.setStyleSheet("color: palette(placeholder-text); font-size: 9px;")
        layout.addWidget(self.model_hint)

        self.backend_combo = QComboBox()
        self.backend_combo.addItem("Auto", BACKEND_AUTO)
        self.backend_combo.addItem("GGUF (llama.cpp)", BACKEND_LLAMA_CPP)
        self.backend_combo.addItem("Transformers (HF)", BACKEND_TRANSFORMERS)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        backend_row = QHBoxLayout()
        backend_row.setContentsMargins(0, 0, 0, 0)
        backend_row.setSpacing(6)
        self.backend_label = QLabel("Backend:")
        backend_row.addWidget(self.backend_label)
        backend_row.addWidget(self.backend_combo, 1)
        layout.addLayout(backend_row)

        path_row = QHBoxLayout()
        self.model_path = QLineEdit()
        self.model_path.setPlaceholderText(
            "Model path (.gguf) or Hugging Face model id / URL…"
        )
        self.browse_btn = QPushButton("…")
        self.browse_btn.setFixedWidth(28)
        self.browse_btn.setStyleSheet(BTN_NEUTRAL)
        self.browse_btn.clicked.connect(self._browse)
        path_row.addWidget(self.model_path)
        path_row.addWidget(self.browse_btn)
        layout.addLayout(path_row)

        self._model_form = QFormLayout()
        self._model_form.setSpacing(4)
        self._model_form.setContentsMargins(0, 0, 0, 0)

        self.ctx_spin = QSpinBox()
        self.ctx_spin.setRange(512, 131072)
        self.ctx_spin.setValue(4096)
        self.ctx_spin.setSingleStep(512)
        self.context_profile_slider = QSlider(Qt.Orientation.Horizontal)
        self.context_profile_slider.setRange(0, 2)
        self.context_profile_slider.setSingleStep(1)
        self.context_profile_slider.setPageStep(1)
        self.context_profile_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.context_profile_slider.setTickInterval(1)
        self.context_profile_slider.setValue(1)
        self.context_profile_slider.setStyleSheet(_GREEN_SLIDER_STYLE)
        self.context_profile_mark_short = QLabel("Kurz")
        self.context_profile_mark_standard = QLabel("Standard")
        self.context_profile_mark_long = QLabel("Lang")
        for mark in (
            self.context_profile_mark_short,
            self.context_profile_mark_standard,
            self.context_profile_mark_long,
        ):
            mark.setStyleSheet("color: palette(placeholder-text); font-size: 9px;")

        self.context_profile_marks_row = QHBoxLayout()
        self.context_profile_marks_row.setContentsMargins(0, 0, 0, 0)
        self.context_profile_marks_row.setSpacing(4)
        self.context_profile_marks_row.addWidget(
            self.context_profile_mark_short,
            1,
            Qt.AlignmentFlag.AlignLeft,
        )
        self.context_profile_marks_row.addWidget(
            self.context_profile_mark_standard,
            1,
            Qt.AlignmentFlag.AlignHCenter,
        )
        self.context_profile_marks_row.addWidget(
            self.context_profile_mark_long,
            1,
            Qt.AlignmentFlag.AlignRight,
        )

        self.context_profile_widget = QWidget()
        self.context_profile_layout = QVBoxLayout(self.context_profile_widget)
        self.context_profile_layout.setContentsMargins(0, 0, 0, 0)
        self.context_profile_layout.setSpacing(1)
        self.context_profile_layout.addWidget(self.context_profile_slider)
        self.context_profile_layout.addLayout(self.context_profile_marks_row)
        self._model_form.addRow("Kontextlaenge:", self.context_profile_widget)
        self._model_form.addRow("Context (tokens):", self.ctx_spin)

        self.gpu_spin = QSpinBox()
        self.gpu_spin.setRange(0, 200)
        self.gpu_spin.setValue(0)
        self.gpu_spin.setToolTip("0 = CPU only")
        self._model_form.addRow("GPU Layers:", self.gpu_spin)

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 64)
        self.threads_spin.setValue(min(os.cpu_count() or 4, 8))
        self._model_form.addRow("Threads:", self.threads_spin)

        self.trust_remote_code_cb = QCheckBox()
        self.trust_remote_code_cb.setChecked(False)
        self.trust_remote_code_cb.setToolTip(
            "Allows execution of custom Python code from the model repository "
            "(transformers trust_remote_code). Only enable for trusted models."
        )
        self._model_form.addRow("Trust remote code:", self.trust_remote_code_cb)

        layout.addLayout(self._model_form)

        self.load_btn = QPushButton("⚡ Load Model")
        self.load_btn.setStyleSheet(BTN_PRIMARY)
        self.load_btn.clicked.connect(self._request_load)
        layout.addWidget(self.load_btn)

        self.status_lbl = QLabel("No model loaded")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_lbl)

        self.nli_section_lbl = QLabel("NLI Model (Fact-Check)")
        self.nli_section_lbl.setStyleSheet(
            "color: palette(highlight); font-size: 10px; font-weight: bold;"
        )
        layout.addWidget(self.nli_section_lbl)
        nli_hint = QLabel(
            "Optional: separates Transformers-NLI-Modell fuer "
            "Claim-vs-Chunk-Faktencheck."
        )
        nli_hint.setStyleSheet("color: palette(placeholder-text); font-size: 9px;")
        layout.addWidget(nli_hint)

        self.nli_model_id = QLineEdit()
        self.nli_model_id.setPlaceholderText("HuggingFace model id (e.g. cross-encoder/nli-deberta-v3-xsmall)")
        self.nli_model_id.setText("cross-encoder/nli-deberta-v3-xsmall")
        layout.addWidget(self.nli_model_id)

        self.nli_load_btn = QPushButton("Load NLI")
        self.nli_load_btn.setStyleSheet(BTN_NEUTRAL)
        self.nli_load_btn.clicked.connect(self._request_nli_load)
        layout.addWidget(self.nli_load_btn)

        self.nli_status_lbl = QLabel("No NLI model loaded")
        self.nli_status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.nli_status_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: palette(mid); margin: 4px 0;")
        layout.addWidget(sep)

        self.generation_section_lbl = QLabel("Generation")
        self.generation_section_lbl.setStyleSheet(
            "color: palette(highlight); font-size: 10px; font-weight: bold;"
        )
        layout.addWidget(self.generation_section_lbl)
        gen_hint = QLabel("Applied immediately for next message (no model reload).")
        gen_hint.setStyleSheet("color: palette(placeholder-text); font-size: 9px;")
        layout.addWidget(gen_hint)

        self._gen_form = QFormLayout()
        self._gen_form.setSpacing(4)
        self._gen_form.setContentsMargins(0, 0, 0, 0)

        self.generation_style_slider = QSlider(Qt.Orientation.Horizontal)
        self.generation_style_slider.setRange(0, 2)
        self.generation_style_slider.setSingleStep(1)
        self.generation_style_slider.setPageStep(1)
        self.generation_style_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.generation_style_slider.setTickInterval(1)
        self.generation_style_slider.setValue(1)
        self.generation_style_slider.setStyleSheet(_GREEN_SLIDER_STYLE)

        self.generation_style_mark_precise = QLabel("Präzise")
        self.generation_style_mark_balanced = QLabel("Ausgewogen")
        self.generation_style_mark_creative = QLabel("Kreativ")
        for mark in (
            self.generation_style_mark_precise,
            self.generation_style_mark_balanced,
            self.generation_style_mark_creative,
        ):
            mark.setStyleSheet("color: palette(placeholder-text); font-size: 9px;")

        self.generation_style_marks_row = QHBoxLayout()
        self.generation_style_marks_row.setContentsMargins(0, 0, 0, 0)
        self.generation_style_marks_row.setSpacing(4)
        self.generation_style_marks_row.addWidget(
            self.generation_style_mark_precise,
            1,
            Qt.AlignmentFlag.AlignLeft,
        )
        self.generation_style_marks_row.addWidget(
            self.generation_style_mark_balanced,
            1,
            Qt.AlignmentFlag.AlignHCenter,
        )
        self.generation_style_marks_row.addWidget(
            self.generation_style_mark_creative,
            1,
            Qt.AlignmentFlag.AlignRight,
        )

        self.generation_style_widget = QWidget()
        self.generation_style_layout = QVBoxLayout(self.generation_style_widget)
        self.generation_style_layout.setContentsMargins(0, 0, 0, 0)
        self.generation_style_layout.setSpacing(1)
        self.generation_style_layout.addWidget(self.generation_style_slider)
        self.generation_style_layout.addLayout(self.generation_style_marks_row)
        self._gen_form.addRow("Antwortstil:", self.generation_style_widget)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(16, 32768)
        self.max_tokens_spin.setSingleStep(64)
        self.max_tokens_spin.setValue(1024)
        self._gen_form.addRow("Max tokens:", self.max_tokens_spin)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setDecimals(2)
        self.temp_spin.setSingleStep(0.05)
        self.temp_spin.setValue(0.7)
        self._gen_form.addRow("Temperature:", self.temp_spin)

        self.top_p_spin = QDoubleSpinBox()
        self.top_p_spin.setRange(0.0, 1.0)
        self.top_p_spin.setDecimals(2)
        self.top_p_spin.setSingleStep(0.05)
        self.top_p_spin.setValue(0.9)
        self._gen_form.addRow("Top p:", self.top_p_spin)

        self.repeat_penalty_spin = QDoubleSpinBox()
        self.repeat_penalty_spin.setRange(0.5, 2.0)
        self.repeat_penalty_spin.setDecimals(2)
        self.repeat_penalty_spin.setSingleStep(0.05)
        self.repeat_penalty_spin.setValue(1.1)
        self._gen_form.addRow("Repeat penalty:", self.repeat_penalty_spin)

        self.forbidden_chars_edit = QLineEdit()
        self.forbidden_chars_edit.setText(
            "\\u00A0,\\u2007,\\u2009,\\u202F,\\u2060,emdash,endash,‒,―,;"
        )
        self.forbidden_chars_edit.setToolTip(
            "Comma-separated forbidden characters.\n"
            "Supports direct chars and escapes like \\u00A0.\n"
            "Default includes special spaces, dash variants and semicolon."
        )
        self._gen_form.addRow("Forbidden chars:", self.forbidden_chars_edit)

        self.generation_style_slider.valueChanged.connect(
            self._on_generation_style_changed
        )
        self.context_profile_slider.valueChanged.connect(
            self._on_context_profile_changed
        )
        self.ctx_spin.valueChanged.connect(
            lambda _value: self._sync_context_profile_from_controls()
        )
        self.temp_spin.valueChanged.connect(
            lambda _value: self._sync_generation_style_from_controls()
        )
        self.top_p_spin.valueChanged.connect(
            lambda _value: self._sync_generation_style_from_controls()
        )
        self.repeat_penalty_spin.valueChanged.connect(
            lambda _value: self._sync_generation_style_from_controls()
        )

        layout.addLayout(self._gen_form)
        self.set_user_mode(self._user_mode)
        self._refresh_model_row_visibility()
        self._sync_context_profile_from_controls()
        self._sync_generation_style_from_controls()

    def _on_backend_changed(self, _index: int):
        self._refresh_model_row_visibility()

    def _apply_backend_ui(self):
        backend = self.get_model_backend()
        if backend == BACKEND_LLAMA_CPP:
            default_hint = resolve_feature_label(
                self._user_mode,
                "chat.model.hint",
                "Use local GGUF model files and click 'Load Model'.",
            )
            default_placeholder = resolve_feature_label(
                self._user_mode,
                "chat.model.path.placeholder",
                "Path to local GGUF model (.gguf/.bin)…",
            )
            default_browse_tip = resolve_feature_label(
                self._user_mode,
                "chat.model.button.browse.tooltip",
                "Choose a local GGUF model file.",
            )
            self.model_hint.setText(
                resolve_feature_label(
                    self._user_mode,
                    "chat.model.hint.llama_cpp",
                    default_hint,
                )
            )
            self.model_path.setPlaceholderText(
                resolve_feature_label(
                    self._user_mode,
                    "chat.model.path.placeholder.llama_cpp",
                    default_placeholder,
                )
            )
            self.browse_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "chat.model.button.browse.tooltip.llama_cpp",
                    default_browse_tip,
                )
            )
        elif backend == BACKEND_TRANSFORMERS:
            default_hint = resolve_feature_label(
                self._user_mode,
                "chat.model.hint",
                "Use a Hugging Face model id/URL or a local model directory.",
            )
            default_placeholder = resolve_feature_label(
                self._user_mode,
                "chat.model.path.placeholder",
                "Hugging Face model id / URL or local model directory…",
            )
            default_browse_tip = resolve_feature_label(
                self._user_mode,
                "chat.model.button.browse.tooltip",
                "Choose a local transformers model directory.",
            )
            self.model_hint.setText(
                resolve_feature_label(
                    self._user_mode,
                    "chat.model.hint.transformers",
                    default_hint,
                )
            )
            self.model_path.setPlaceholderText(
                resolve_feature_label(
                    self._user_mode,
                    "chat.model.path.placeholder.transformers",
                    default_placeholder,
                )
            )
            self.browse_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "chat.model.button.browse.tooltip.transformers",
                    default_browse_tip,
                )
            )
        else:
            default_hint = resolve_feature_label(
                self._user_mode,
                "chat.model.hint",
                "Changes here require clicking 'Load Model'.",
            )
            default_placeholder = resolve_feature_label(
                self._user_mode,
                "chat.model.path.placeholder",
                "Model path (.gguf) or Hugging Face model id / URL…",
            )
            default_browse_tip = resolve_feature_label(
                self._user_mode,
                "chat.model.button.browse.tooltip",
                "Choose a local GGUF file, or enter a transformers id/URL.",
            )
            self.model_hint.setText(
                resolve_feature_label(
                    self._user_mode,
                    "chat.model.hint.auto",
                    default_hint,
                )
            )
            self.model_path.setPlaceholderText(
                resolve_feature_label(
                    self._user_mode,
                    "chat.model.path.placeholder.auto",
                    default_placeholder,
                )
            )
            self.browse_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "chat.model.button.browse.tooltip.auto",
                    default_browse_tip,
                )
            )
        self._refresh_model_row_visibility()

    def _refresh_model_row_visibility(self):
        backend = self.get_model_backend()
        show_context_profile = bool(self._show_context_profile)
        show_ctx = bool(self._show_ctx_tokens)
        show_gpu = bool(self._show_gpu_layers) and backend in {
            BACKEND_AUTO,
            BACKEND_LLAMA_CPP,
        }
        show_threads = bool(self._show_threads)
        show_trust_remote_code = bool(self._show_trust_remote_code) and backend in {
            BACKEND_AUTO,
            BACKEND_TRANSFORMERS,
        }
        set_form_row_visible(self._model_form, self.context_profile_widget, show_context_profile)
        set_form_row_visible(self._model_form, self.ctx_spin, show_ctx)
        set_form_row_visible(self._model_form, self.gpu_spin, show_gpu)
        set_form_row_visible(self._model_form, self.threads_spin, show_threads)
        set_form_row_visible(
            self._model_form,
            self.trust_remote_code_cb,
            show_trust_remote_code,
        )

    def _browse(self):
        backend = self.get_model_backend()
        if backend == BACKEND_TRANSFORMERS:
            directory = QFileDialog.getExistingDirectory(
                self,
                "Select Transformers Model Directory",
                "",
            )
            if directory:
                self.model_path.setText(directory)
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select GGUF Model File",
            "",
            "GGUF Models (*.gguf *.bin);;All Files (*)",
        )
        if path:
            self.model_path.setText(path)

    def _request_load(self):
        path = self.model_path.text().strip()
        if not path:
            return
        params = {
            "n_ctx": self.ctx_spin.value(),
            "n_gpu_layers": self.gpu_spin.value(),
            "n_threads": self.threads_spin.value(),
            "trust_remote_code": bool(self.trust_remote_code_cb.isChecked()),
            "backend": self.get_model_backend(),
        }
        self.load_btn.setEnabled(False)
        self.status_lbl.setText("⏳ Loading…")
        color = QColor(self.palette().color(QPalette.ColorRole.Highlight))
        self.status_lbl.setStyleSheet(
            f"color: {color.name(QColor.NameFormat.HexRgb)}; font-size: 10px;"
        )
        self.load_requested.emit(path, params)

    def _request_nli_load(self):
        model_id = self.nli_model_id.text().strip()
        if not model_id:
            return
        params = {
            "n_threads": self.threads_spin.value(),
        }
        self.nli_load_btn.setEnabled(False)
        self.nli_status_lbl.setText("⏳ Loading NLI…")
        color = QColor(self.palette().color(QPalette.ColorRole.Highlight))
        self.nli_status_lbl.setStyleSheet(
            f"color: {color.name(QColor.NameFormat.HexRgb)}; font-size: 10px;"
        )
        self.nli_load_requested.emit(model_id, params)

    def on_model_loaded(self, success: bool, message: str):
        self.load_btn.setEnabled(True)
        self.status_lbl.setText(message)
        role = (
            QPalette.ColorRole.Link
            if success
            else QPalette.ColorRole.BrightText
        )
        color = QColor(self.palette().color(role))
        self.status_lbl.setStyleSheet(
            f"color: {color.name(QColor.NameFormat.HexRgb)}; font-size: 10px;"
        )

    def on_nli_model_loaded(self, success: bool, message: str):
        self.nli_load_btn.setEnabled(True)
        self.nli_status_lbl.setText(message)
        role = (
            QPalette.ColorRole.Link
            if success
            else QPalette.ColorRole.BrightText
        )
        color = QColor(self.palette().color(role))
        self.nli_status_lbl.setStyleSheet(
            f"color: {color.name(QColor.NameFormat.HexRgb)}; font-size: 10px;"
        )

    def get_generation_params(self) -> dict:
        return {
            "max_tokens": int(self.max_tokens_spin.value()),
            "temperature": float(self.temp_spin.value()),
            "top_p": float(self.top_p_spin.value()),
            "repeat_penalty": float(self.repeat_penalty_spin.value()),
            "forbidden_chars": self.forbidden_chars_edit.text(),
        }

    def get_model_backend(self) -> str:
        combo = self.backend_combo
        if combo is None:
            return BACKEND_AUTO
        value = str(combo.currentData() or BACKEND_AUTO).strip().casefold()
        if value in {BACKEND_AUTO, BACKEND_LLAMA_CPP, BACKEND_TRANSFORMERS}:
            return value
        return BACKEND_AUTO

    def set_model_backend(self, backend: str) -> None:
        combo = self.backend_combo
        if combo is None:
            return
        target = str(backend or BACKEND_AUTO).strip().casefold()
        for idx in range(combo.count()):
            if str(combo.itemData(idx) or "").strip().casefold() == target:
                combo.setCurrentIndex(idx)
                self._apply_backend_ui()
                return
        combo.setCurrentIndex(0)
        self._apply_backend_ui()

    def _on_generation_style_changed(self, style_index: int) -> None:
        index = max(0, min(2, int(style_index)))
        if self._syncing_generation_style:
            return
        preset = _GENERATION_STYLE_PRESETS[index]
        self._syncing_generation_style = True
        try:
            self.temp_spin.setValue(float(preset["temperature"]))
            self.top_p_spin.setValue(float(preset["top_p"]))
            self.repeat_penalty_spin.setValue(float(preset["repeat_penalty"]))
        finally:
            self._syncing_generation_style = False

    def _nearest_generation_style_index(self) -> int:
        current_temp = float(self.temp_spin.value())
        current_top_p = float(self.top_p_spin.value())
        current_repeat = float(self.repeat_penalty_spin.value())
        distances: list[tuple[float, int]] = []
        for idx, preset in enumerate(_GENERATION_STYLE_PRESETS):
            distance = (
                abs(current_temp - float(preset["temperature"]))
                + abs(current_top_p - float(preset["top_p"]))
                + abs(current_repeat - float(preset["repeat_penalty"]))
            )
            distances.append((distance, idx))
        distances.sort(key=lambda item: (item[0], item[1]))
        return int(distances[0][1])

    def _sync_generation_style_from_controls(self) -> None:
        if self._syncing_generation_style:
            return
        target_idx = self._nearest_generation_style_index()
        self._syncing_generation_style = True
        try:
            self.generation_style_slider.setValue(target_idx)
        finally:
            self._syncing_generation_style = False

    def _on_context_profile_changed(self, profile_index: int) -> None:
        idx = max(0, min(2, int(profile_index)))
        if self._syncing_context_profile:
            return
        target_ctx = int(_CONTEXT_LENGTH_PRESETS[idx])
        self._syncing_context_profile = True
        try:
            self.ctx_spin.setValue(target_ctx)
        finally:
            self._syncing_context_profile = False

    def _nearest_context_profile_index(self) -> int:
        current_ctx = int(self.ctx_spin.value())
        distances: list[tuple[int, int]] = []
        for idx, target_ctx in enumerate(_CONTEXT_LENGTH_PRESETS):
            distances.append((abs(current_ctx - int(target_ctx)), idx))
        distances.sort(key=lambda item: (item[0], item[1]))
        return int(distances[0][1])

    def _sync_context_profile_from_controls(self) -> None:
        if self._syncing_context_profile:
            return
        target_idx = self._nearest_context_profile_index()
        self._syncing_context_profile = True
        try:
            self.context_profile_slider.setValue(target_idx)
        finally:
            self._syncing_context_profile = False

    def set_user_mode(self, mode: str):
        self._user_mode = normalize_user_mode(mode)
        self._show_context_profile = feature_visible(
            self._user_mode,
            "chat.model.load.context_profile",
            default=True,
        )
        self._show_ctx_tokens = feature_visible(
            self._user_mode,
            "chat.model.load.context_tokens",
            default=True,
        )
        self._show_gpu_layers = feature_visible(
            self._user_mode,
            "chat.model.load.gpu_layers",
            default=True,
        )
        self._show_threads = feature_visible(
            self._user_mode,
            "chat.model.load.threads",
            default=False,
        )
        self._show_trust_remote_code = feature_visible(
            self._user_mode,
            "chat.model.load.trust_remote_code",
            default=False,
        )

        apply_form_row_visibility(
            self._user_mode,
            self._gen_form,
            (
                (
                    self.generation_style_widget,
                    "chat.model.generation.style",
                    True,
                ),
                (
                    self.temp_spin,
                    "chat.model.generation.temperature",
                    True,
                ),
                (
                    self.top_p_spin,
                    "chat.model.generation.top_p",
                    True,
                ),
                (
                    self.repeat_penalty_spin,
                    "chat.model.generation.repeat_penalty",
                    True,
                ),
                (
                    self.forbidden_chars_edit,
                    "chat.model.generation.forbidden_chars",
                    False,
                ),
            ),
        )

        apply_widget_texts(
            self._user_mode,
            (
                (self.model_section_lbl, "chat.model.section.load", "Model Load"),
                (self.backend_label, "chat.model.backend_label", "Backend:"),
                (
                    self.load_btn,
                    "chat.model.button.load_model",
                    "⚡ Load Model",
                ),
                (
                    self.nli_section_lbl,
                    "chat.model.section.nli",
                    "NLI Model (Fact-Check)",
                ),
                (
                    self.nli_load_btn,
                    "chat.model.button.load_nli",
                    "Load NLI",
                ),
                (
                    self.generation_section_lbl,
                    "chat.model.section.generation",
                    "Generation",
                ),
                (
                    self.context_profile_mark_short,
                    "chat.model.load.context_profile.short",
                    "Kurz",
                ),
                (
                    self.context_profile_mark_standard,
                    "chat.model.load.context_profile.standard",
                    "Standard",
                ),
                (
                    self.context_profile_mark_long,
                    "chat.model.load.context_profile.long",
                    "Lang",
                ),
            ),
        )
        apply_widget_tooltips(
            self._user_mode,
            (
                (
                    self.browse_btn,
                    "chat.model.button.browse.tooltip",
                    "Choose model path",
                ),
                (
                    self.load_btn,
                    "chat.model.button.load_model.tooltip",
                    "Load model with current backend and settings.",
                ),
                (
                    self.nli_load_btn,
                    "chat.model.button.load_nli.tooltip",
                    "Load NLI model for fact-check classification.",
                ),
                (
                    self.generation_style_slider,
                    "chat.model.generation.style.tooltip",
                    "Simple output style: precise, balanced or creative. "
                    "This automatically updates temperature, top-p and repeat penalty.",
                ),
                (
                    self.context_profile_slider,
                    "chat.model.load.context_profile.tooltip",
                    "Simple context length: short, standard or long. "
                    "This automatically updates context tokens.",
                ),
            ),
        )
        apply_widget_texts(
            self._user_mode,
            (
                (
                    self.generation_style_mark_precise,
                    "chat.model.generation.style.precise",
                    "Präzise",
                ),
                (
                    self.generation_style_mark_balanced,
                    "chat.model.generation.style.balanced",
                    "Ausgewogen",
                ),
                (
                    self.generation_style_mark_creative,
                    "chat.model.generation.style.creative",
                    "Kreativ",
                ),
            ),
        )
        apply_form_row_labels(
            self._user_mode,
            self._model_form,
            (
                (
                    self.context_profile_widget,
                    "chat.model.load.context_profile",
                    "Kontextlaenge:",
                ),
                (
                    self.ctx_spin,
                    "chat.model.load.context_tokens",
                    "Context (tokens):",
                ),
                (
                    self.gpu_spin,
                    "chat.model.load.gpu_layers",
                    "GPU Layers:",
                ),
                (
                    self.threads_spin,
                    "chat.model.load.threads",
                    "Threads:",
                ),
                (
                    self.trust_remote_code_cb,
                    "chat.model.load.trust_remote_code",
                    "Trust remote code:",
                ),
            ),
        )
        apply_form_row_labels(
            self._user_mode,
            self._gen_form,
            (
                (
                    self.generation_style_widget,
                    "chat.model.generation.style",
                    "Antwortstil:",
                ),
                (
                    self.max_tokens_spin,
                    "chat.model.generation.max_tokens",
                    "Max tokens:",
                ),
                (
                    self.temp_spin,
                    "chat.model.generation.temperature",
                    "Temperature:",
                ),
                (
                    self.top_p_spin,
                    "chat.model.generation.top_p",
                    "Top p:",
                ),
                (
                    self.repeat_penalty_spin,
                    "chat.model.generation.repeat_penalty",
                    "Repeat penalty:",
                ),
                (
                    self.forbidden_chars_edit,
                    "chat.model.generation.forbidden_chars",
                    "Forbidden chars:",
                ),
            ),
        )
        self._apply_backend_ui()
        self._sync_context_profile_from_controls()
        self._sync_generation_style_from_controls()
