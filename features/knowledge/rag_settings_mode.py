"""User mode and visibility logic for the RAG settings dialog."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QWidget

from core.user_modes import (
    USER_MODE_EXPERT,
    USER_MODE_PLUS,
    USER_MODE_SIMPLE,
    mode_rank,
    normalize_user_mode,
)

from .rag_settings_types import RAGSettingsView


def _set_form_row_visible(form: QFormLayout, field: QWidget, visible: bool) -> None:
    label = form.labelForField(field)
    if label is not None:
        label.setVisible(visible)
    field.setVisible(visible)


def validate_backends(view: RAGSettingsView) -> bool:
    """Return True when at least one backend is enabled."""
    return any(
        (
            view.backends.use_tfidf.isChecked(),
            view.backends.use_st.isChecked(),
            view.backends.use_regex.isChecked(),
        )
    )


def update_hyde_visibility(view: RAGSettingsView, user_mode: str) -> None:
    """Show hypothesis count only in expert mode and multi_passage ST mode."""
    is_multi_passage = view.hyde.hyde_st_mode.currentText() == "multi_passage"
    is_expert = mode_rank(user_mode) >= mode_rank(USER_MODE_EXPERT)
    visible = is_multi_passage and is_expert
    view.hyde.hyde_hypotheses_label.setVisible(visible)
    view.hyde.hyde_st_hypotheses.setVisible(visible)


def update_literal_visibility(view: RAGSettingsView) -> None:
    """Enable literal settings only when literal backend is active."""
    use_literal = view.backends.use_regex.isChecked()
    view.literal.regex_max.setEnabled(use_literal)
    view.literal.literal_use_llm_terms.setEnabled(use_literal)
    view.literal.literal_llm_max_terms.setEnabled(
        use_literal and view.literal.literal_use_llm_terms.isChecked()
    )


def update_rerank_visibility(view: RAGSettingsView, user_mode: str) -> None:
    """Expert-only threshold editing for rerank fallback score."""
    enabled = view.selection.llm_rerank_enabled.isChecked()
    expert = mode_rank(user_mode) >= mode_rank(USER_MODE_EXPERT)
    view.selection.llm_rerank_min_score.setEnabled(enabled and expert)
    view.selection.llm_rerank_max_candidates.setEnabled(False)


def apply_user_mode(view: RAGSettingsView, mode: str) -> str:
    """Apply user mode visibility and return normalized mode."""
    user_mode = normalize_user_mode(mode)
    rank = mode_rank(user_mode)
    plus_or_higher = rank >= mode_rank(USER_MODE_PLUS)
    expert_only = rank >= mode_rank(USER_MODE_EXPERT)

    if user_mode == USER_MODE_SIMPLE:
        view.mode_hint.setText(
            "Einfach-Modus: nur Kernoptionen. "
            "Erweiterte Werte bleiben unverändert gespeichert."
        )
    elif user_mode == USER_MODE_PLUS:
        view.mode_hint.setText(
            "Plus-Modus: zusätzliche, aber überschaubare Einstellungen."
        )
    else:
        view.mode_hint.setText(
            "Experte-Modus: vollständige Kontrolle über alle RAG-Parameter."
        )

    view.backends.group.setVisible(plus_or_higher)
    view.hyde.group.setVisible(plus_or_higher)
    view.chunking.group.setVisible(plus_or_higher)
    view.extended_context.group.setVisible(plus_or_higher)
    view.selection.group.setVisible(True)
    view.literal.group.setVisible(expert_only)

    if not expert_only:
        view.backends.use_tfidf.setChecked(True)

    _set_form_row_visible(view.backends.form, view.backends.use_tfidf, expert_only)
    _set_form_row_visible(view.backends.form, view.backends.st_model, expert_only)
    _set_form_row_visible(view.backends.form, view.backends.st_n_threads, expert_only)
    view.backends.hint.setVisible(plus_or_higher)

    _set_form_row_visible(view.hyde.form, view.hyde.hyde_tfidf_mode, expert_only)
    _set_form_row_visible(view.hyde.form, view.hyde.hyde_st_mode, expert_only)
    _set_form_row_visible(view.hyde.form, view.hyde.hyde_use_doc_context, expert_only)

    _set_form_row_visible(view.chunking.form, view.chunking.chunk_overlap, expert_only)
    _set_form_row_visible(view.chunking.form, view.chunking.chunking_strategy, expert_only)
    _set_form_row_visible(view.chunking.form, view.chunking.include_headings, expert_only)
    _set_form_row_visible(view.chunking.form, view.chunking.include_filename, expert_only)

    view.extended_context.hint.setVisible(expert_only)
    _set_form_row_visible(view.extended_context.form, view.extended_context.ext_before, expert_only)
    _set_form_row_visible(view.extended_context.form, view.extended_context.ext_after, expert_only)

    _set_form_row_visible(view.selection.form, view.selection.selection_mode, plus_or_higher)
    view.selection.hint.setVisible(plus_or_higher)
    _set_form_row_visible(view.selection.form, view.selection.threshold, plus_or_higher)
    _set_form_row_visible(
        view.selection.form,
        view.selection.llm_rerank_enabled,
        plus_or_higher,
    )
    _set_form_row_visible(
        view.selection.form,
        view.selection.llm_rerank_min_score,
        expert_only,
    )
    _set_form_row_visible(
        view.selection.form,
        view.selection.llm_rerank_max_candidates,
        expert_only,
    )
    view.selection.rerank_hint.setVisible(plus_or_higher)

    return user_mode
