"""Model load and generation-parameter panel for chat dock."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.user_modes import (
    USER_MODE_EXPERT,
    USER_MODE_PLUS,
    mode_rank,
    normalize_user_mode,
)

from .styles import BTN_NEUTRAL, BTN_PRIMARY


def _set_form_row_visible(form: QFormLayout, field: QWidget, visible: bool):
    label = form.labelForField(field)
    if label is not None:
        label.setVisible(visible)
    field.setVisible(visible)


class ModelLoadPanel(QWidget):
    """Panel for loading GGUF model and editing generation parameters."""

    load_requested = Signal(str, dict)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._user_mode = USER_MODE_PLUS
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(
            """
            QWidget  { background: #252535; }
            QLabel   { color: #A6ADC8; font-size: 10px; }
            QLineEdit, QSpinBox, QDoubleSpinBox {
                background: #1E1E2E; color: #CDD6F4;
                border: 1px solid #45475A; border-radius: 3px;
                padding: 3px 6px; font-size: 11px;
            }
            QLineEdit:focus, QSpinBox:focus { border-color: #89B4FA; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(5)

        model_lbl = QLabel("Model Load")
        model_lbl.setStyleSheet(
            "color: #89B4FA; font-size: 10px; font-weight: bold;"
        )
        layout.addWidget(model_lbl)
        model_hint = QLabel("Changes here require clicking 'Load Model'.")
        model_hint.setStyleSheet("color: #6C7086; font-size: 9px;")
        layout.addWidget(model_hint)

        path_row = QHBoxLayout()
        self.model_path = QLineEdit()
        self.model_path.setPlaceholderText("Path to .gguf model file…")
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(28)
        browse_btn.setStyleSheet(BTN_NEUTRAL)
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(self.model_path)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        self._model_form = QFormLayout()
        self._model_form.setSpacing(4)
        self._model_form.setContentsMargins(0, 0, 0, 0)

        self.ctx_spin = QSpinBox()
        self.ctx_spin.setRange(512, 131072)
        self.ctx_spin.setValue(4096)
        self.ctx_spin.setSingleStep(512)
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

        layout.addLayout(self._model_form)

        self.load_btn = QPushButton("⚡ Load Model")
        self.load_btn.setStyleSheet(BTN_PRIMARY)
        self.load_btn.clicked.connect(self._request_load)
        layout.addWidget(self.load_btn)

        self.status_lbl = QLabel("No model loaded")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #313244; margin: 4px 0;")
        layout.addWidget(sep)

        gen_lbl = QLabel("Generation")
        gen_lbl.setStyleSheet(
            "color: #89B4FA; font-size: 10px; font-weight: bold;"
        )
        layout.addWidget(gen_lbl)
        gen_hint = QLabel("Applied immediately for next message (no model reload).")
        gen_hint.setStyleSheet("color: #6C7086; font-size: 9px;")
        layout.addWidget(gen_hint)

        self._gen_form = QFormLayout()
        self._gen_form.setSpacing(4)
        self._gen_form.setContentsMargins(0, 0, 0, 0)

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

        layout.addLayout(self._gen_form)
        self.set_user_mode(self._user_mode)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select GGUF Model",
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
        }
        self.load_btn.setEnabled(False)
        self.status_lbl.setText("⏳ Loading…")
        self.status_lbl.setStyleSheet("color: #F9E2AF; font-size: 10px;")
        self.load_requested.emit(path, params)

    def on_model_loaded(self, success: bool, message: str):
        self.load_btn.setEnabled(True)
        self.status_lbl.setText(message)
        color = "#A6E3A1" if success else "#F38BA8"
        self.status_lbl.setStyleSheet(f"color: {color}; font-size: 10px;")

    def get_generation_params(self) -> dict:
        return {
            "max_tokens": int(self.max_tokens_spin.value()),
            "temperature": float(self.temp_spin.value()),
            "top_p": float(self.top_p_spin.value()),
            "repeat_penalty": float(self.repeat_penalty_spin.value()),
            "forbidden_chars": self.forbidden_chars_edit.text(),
        }

    def set_user_mode(self, mode: str):
        self._user_mode = normalize_user_mode(mode)
        rank = mode_rank(self._user_mode)
        plus_rank = mode_rank(USER_MODE_PLUS)
        expert_rank = mode_rank(USER_MODE_EXPERT)

        plus_or_higher = rank >= plus_rank
        expert_only = rank >= expert_rank

        _set_form_row_visible(self._gen_form, self.top_p_spin, plus_or_higher)
        _set_form_row_visible(
            self._gen_form, self.repeat_penalty_spin, plus_or_higher
        )
        _set_form_row_visible(
            self._gen_form, self.forbidden_chars_edit, expert_only
        )

        _set_form_row_visible(self._model_form, self.ctx_spin, plus_or_higher)
        _set_form_row_visible(self._model_form, self.gpu_spin, plus_or_higher)
        _set_form_row_visible(self._model_form, self.threads_spin, expert_only)
