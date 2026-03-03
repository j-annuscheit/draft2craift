"""Mapping between RAGConfig and the RAG settings view widgets."""
from __future__ import annotations

from services.rag.system import RAGConfig

from .rag_settings_types import RAGSettingsView

_DEFAULT_ST_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def load_config_into_view(view: RAGSettingsView, cfg: RAGConfig) -> None:
    """Populate all widgets from *cfg*."""
    view.backends.use_tfidf.setChecked(cfg.use_tfidf)
    view.backends.use_st.setChecked(cfg.use_st)
    view.backends.st_model.setText(cfg.st_model_name)
    view.backends.st_n_threads.setValue(cfg.st_n_threads)
    view.backends.use_regex.setChecked(cfg.use_regex_search)

    view.hyde.use_hyde.setChecked(cfg.use_hyde)
    view.hyde.hyde_min_words.setValue(cfg.hyde_min_words)
    view.hyde.hyde_tfidf_mode.setCurrentText(cfg.hyde_tfidf_mode)
    view.hyde.hyde_st_mode.setCurrentText(cfg.hyde_st_mode)
    view.hyde.hyde_st_hypotheses.setValue(cfg.hyde_st_hypotheses)
    view.hyde.hyde_use_doc_context.setChecked(cfg.hyde_use_doc_context)

    view.chunking.chunk_size.setValue(cfg.chunk_size)
    view.chunking.chunk_overlap.setValue(cfg.chunk_overlap)
    view.chunking.chunking_strategy.setCurrentText(cfg.chunking_strategy)
    view.chunking.include_headings.setChecked(cfg.include_headings)
    view.chunking.include_filename.setChecked(cfg.include_filename)

    view.extended_context.extended_context.setChecked(cfg.extended_context)
    view.extended_context.ext_before.setValue(cfg.extended_context_before)
    view.extended_context.ext_after.setValue(cfg.extended_context_after)

    view.selection.selection_mode.setCurrentText(cfg.selection_mode)
    view.selection.top_k.setValue(cfg.top_k)
    view.selection.threshold.setValue(cfg.score_threshold)
    view.selection.llm_rerank_enabled.setChecked(cfg.llm_rerank_enabled)
    view.selection.llm_rerank_min_score.setValue(cfg.llm_rerank_min_score)
    view.selection.llm_rerank_max_candidates.setValue(cfg.llm_rerank_max_candidates)

    view.literal.regex_max.setValue(cfg.regex_max_results)
    view.literal.literal_use_llm_terms.setChecked(cfg.literal_use_llm_terms)
    view.literal.literal_llm_max_terms.setValue(cfg.literal_llm_max_terms)


def build_config_from_view(view: RAGSettingsView) -> RAGConfig:
    """Build a new RAGConfig from current widget values."""
    st_model_name = view.backends.st_model.text().strip() or _DEFAULT_ST_MODEL
    return RAGConfig(
        use_tfidf=view.backends.use_tfidf.isChecked(),
        use_st=view.backends.use_st.isChecked(),
        st_model_name=st_model_name,
        st_n_threads=view.backends.st_n_threads.value(),
        use_hyde=view.hyde.use_hyde.isChecked(),
        hyde_min_words=view.hyde.hyde_min_words.value(),
        hyde_tfidf_mode=view.hyde.hyde_tfidf_mode.currentText(),
        hyde_st_mode=view.hyde.hyde_st_mode.currentText(),
        hyde_st_hypotheses=view.hyde.hyde_st_hypotheses.value(),
        hyde_use_doc_context=view.hyde.hyde_use_doc_context.isChecked(),
        chunk_size=view.chunking.chunk_size.value(),
        chunk_overlap=view.chunking.chunk_overlap.value(),
        chunking_strategy=view.chunking.chunking_strategy.currentText(),
        include_headings=view.chunking.include_headings.isChecked(),
        include_filename=view.chunking.include_filename.isChecked(),
        extended_context=view.extended_context.extended_context.isChecked(),
        extended_context_before=view.extended_context.ext_before.value(),
        extended_context_after=view.extended_context.ext_after.value(),
        selection_mode=view.selection.selection_mode.currentText(),
        top_k=view.selection.top_k.value(),
        score_threshold=view.selection.threshold.value(),
        llm_rerank_enabled=view.selection.llm_rerank_enabled.isChecked(),
        llm_rerank_min_score=view.selection.llm_rerank_min_score.value(),
        llm_rerank_max_candidates=view.selection.llm_rerank_max_candidates.value(),
        use_regex_search=view.backends.use_regex.isChecked(),
        regex_max_results=view.literal.regex_max.value(),
        literal_use_llm_terms=view.literal.literal_use_llm_terms.isChecked(),
        literal_llm_max_terms=view.literal.literal_llm_max_terms.value(),
    )
