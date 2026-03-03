"""Dialog exposing all RAGConfig parameters as editable widgets."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog

from core.user_modes import USER_MODE_PLUS, normalize_user_mode
from services.rag.system import RAGConfig

from .rag_settings_config import build_config_from_view, load_config_into_view
from .rag_settings_mode import (
    apply_user_mode,
    update_hyde_visibility,
    update_literal_visibility,
    update_rerank_visibility,
    validate_backends,
)
from .rag_settings_style import RAG_SETTINGS_STYLE
from .rag_settings_types import RAGSettingsView
from .rag_settings_view import build_rag_settings_view


class RAGSettingsDialog(QDialog):
    """Dialog for editing all parameters of a RAGConfig."""

    def __init__(self, config: RAGConfig, parent=None, user_mode: str = USER_MODE_PLUS):
        super().__init__(parent)
        self.setWindowTitle("RAG Settings")
        self.setStyleSheet(RAG_SETTINGS_STYLE)
        self.setMinimumWidth(440)

        self._user_mode = normalize_user_mode(user_mode)
        self._view: RAGSettingsView = build_rag_settings_view(self, config)

        self._connect_buttons()
        self._connect_dynamic_signals()
        self.set_user_mode(self._user_mode)

    def _connect_buttons(self) -> None:
        self._view.button_box.accepted.connect(self.accept)
        self._view.button_box.rejected.connect(self.reject)
        self._view.reset_button.clicked.connect(lambda: self._load(RAGConfig()))

    def _connect_dynamic_signals(self) -> None:
        self._view.backends.use_tfidf.toggled.connect(self._validate_backends)
        self._view.backends.use_st.toggled.connect(self._validate_backends)
        self._view.backends.use_regex.toggled.connect(self._validate_backends)
        self._view.backends.use_regex.toggled.connect(self._update_literal_visibility)

        self._view.hyde.hyde_st_mode.currentTextChanged.connect(
            lambda _text: self._update_hyde_visibility()
        )
        self._view.literal.literal_use_llm_terms.toggled.connect(
            self._update_literal_visibility
        )
        self._view.selection.llm_rerank_enabled.toggled.connect(
            self._update_rerank_visibility
        )

    def _sync_dynamic_state(self) -> None:
        self._update_literal_visibility()
        self._update_rerank_visibility()
        self._update_hyde_visibility()
        self._validate_backends()

    def _validate_backends(self) -> None:
        self._view.ok_button.setEnabled(validate_backends(self._view))

    def _update_hyde_visibility(self) -> None:
        update_hyde_visibility(self._view, self._user_mode)

    def _update_literal_visibility(self) -> None:
        update_literal_visibility(self._view)

    def _update_rerank_visibility(self) -> None:
        update_rerank_visibility(self._view, self._user_mode)

    def _load(self, cfg: RAGConfig) -> None:
        """Populate all widgets from *cfg* (used by Restore Defaults)."""
        load_config_into_view(self._view, cfg)
        self.set_user_mode(self._user_mode)

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = apply_user_mode(self._view, mode)
        self._sync_dynamic_state()

    def get_config(self) -> RAGConfig:
        """Return a RAGConfig built from the current widget values."""
        return build_config_from_view(self._view)
