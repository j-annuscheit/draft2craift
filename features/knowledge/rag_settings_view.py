"""Top-level dialog view composition for RAG settings."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from services.rag.system import RAGConfig

from .rag_settings_sections import (
    build_backends_section,
    build_chunking_section,
    build_extended_context_section,
    build_hyde_section,
    build_literal_section,
    build_selection_section,
)
from .rag_settings_types import RAGSettingsView


__all__ = ["RAGSettingsView", "build_rag_settings_view"]


def _build_buttons() -> tuple[QDialogButtonBox, QPushButton, QPushButton]:
    buttons = QDialogButtonBox.StandardButton.Ok
    buttons |= QDialogButtonBox.StandardButton.Cancel
    buttons |= QDialogButtonBox.StandardButton.RestoreDefaults
    button_box = QDialogButtonBox(buttons)

    ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
    reset_button = button_box.button(QDialogButtonBox.StandardButton.RestoreDefaults)
    if ok_button is None or reset_button is None:
        raise RuntimeError("Failed to create RAG settings dialog buttons")

    return button_box, ok_button, reset_button


def _build_mode_hint() -> QLabel:
    mode_hint = QLabel("")
    mode_hint.setWordWrap(True)
    mode_hint.setStyleSheet("color: #6C7086; font-size: 10px;")
    return mode_hint


def build_rag_settings_view(dialog: QDialog, cfg: RAGConfig) -> RAGSettingsView:
    root = QVBoxLayout(dialog)
    root.setSpacing(10)
    root.setContentsMargins(14, 14, 14, 14)

    mode_hint = _build_mode_hint()
    root.addWidget(mode_hint)

    backends = build_backends_section(cfg)
    root.addWidget(backends.group)

    hyde = build_hyde_section(cfg)
    root.addWidget(hyde.group)

    chunking = build_chunking_section(cfg)
    root.addWidget(chunking.group)

    extended_context = build_extended_context_section(cfg)
    root.addWidget(extended_context.group)

    selection = build_selection_section(cfg)
    root.addWidget(selection.group)

    literal = build_literal_section(cfg)
    root.addWidget(literal.group)

    button_box, ok_button, reset_button = _build_buttons()
    root.addWidget(button_box)

    return RAGSettingsView(
        mode_hint=mode_hint,
        backends=backends,
        hyde=hyde,
        chunking=chunking,
        extended_context=extended_context,
        selection=selection,
        literal=literal,
        button_box=button_box,
        ok_button=ok_button,
        reset_button=reset_button,
    )
