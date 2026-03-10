"""Central registry of persisted application setting keys."""
from __future__ import annotations

from typing import Final


class AutosaveSettingsKeys:
    ENABLED: Final[str] = "autosave/enabled"


class ThemeSettingsKeys:
    UI_THEME: Final[str] = "ui/theme"
    PREVIEW_PAGE_MARGIN_ENABLED: Final[str] = "preview/page_margin_enabled"
    PREVIEW_PAGE_MARGIN_EM: Final[str] = "preview/page_margin_em"
    PREVIEW_MARKDOWN_THEME: Final[str] = "preview/markdown_theme"


class FeedbackSettingsKeys:
    UI_ENABLED: Final[str] = "feedback/ui_enabled"
    CAPTURE_PAYLOAD_ENABLED: Final[str] = "feedback/capture_payload_enabled"
    STORAGE_DIR: Final[str] = "feedback/storage_dir"


class SpeechSettingsKeys:
    STT_BACKEND: Final[str] = "stt_backend"
    STT_INPUT_DEVICE: Final[str] = "stt_input_device"
    STT_MODEL_SIZE: Final[str] = "stt_model_size"
    STT_LANGUAGE: Final[str] = "stt_language"
    STT_COMPUTE_TYPE: Final[str] = "stt_compute_type"
    STT_CPU_THREADS: Final[str] = "stt_cpu_threads"
    TTS_ENGINE: Final[str] = "tts_engine"
    TTS_LANGUAGE: Final[str] = "tts_language"
    TTS_MODEL_PATH: Final[str] = "tts_model_path"
    TTS_SPEAKER_ID: Final[str] = "tts_speaker_id"
    TTS_OUTPUT_DEVICE: Final[str] = "tts_output_device"
    TTS_VOICE: Final[str] = "tts_voice"
    TTS_RATE: Final[str] = "tts_rate"
    TTS_VOLUME: Final[str] = "tts_volume"
    TTS_PAUSE_MS: Final[str] = "tts_pause_ms"
    TTS_TRIGGER_PAUSE_MS: Final[str] = "tts_trigger_pause_ms"
    TTS_LEAD_IN_MS: Final[str] = "tts_lead_in_ms"
    TTS_START_TRIGGER: Final[str] = "tts_start_trigger"
    TTS_PAUSE_TRIGGERS: Final[str] = "tts_pause_triggers"
    CHAT_TTS_MODE: Final[str] = "chat_tts_mode"


class PromptTemplateKeys:
    CHAT_SYSTEM: Final[str] = "chat_system"
    CHAT_SECTION_GROUNDING_TITLE: Final[str] = "chat_section_grounding_title"
    CHAT_SECTION_REWRITE_TITLE: Final[str] = "chat_section_rewrite_title"
    CHAT_SECTION_CONTEXT_TITLE: Final[str] = "chat_section_context_title"
    CHAT_SECTION_CONTEXT_END: Final[str] = "chat_section_context_end"
    CHAT_SECTION_FILES_TITLE: Final[str] = "chat_section_files_title"
    CHAT_SECTION_RAG_TITLE: Final[str] = "chat_section_rag_title"
    CHAT_SECTION_SELECTED_TITLE: Final[str] = "chat_section_selected_title"
    CHAT_CITATION_RULE_ANSWER: Final[str] = "chat_citation_rule_answer"
    CHAT_CITATION_RULE_REWRITE: Final[str] = "chat_citation_rule_rewrite"
    CHAT_GROUNDING_NOTE_REWRITE: Final[str] = "chat_grounding_note_rewrite"
    CHAT_GROUNDING_RULES: Final[str] = "chat_grounding_rules"
    CHAT_CANVAS_REWRITE_RULES: Final[str] = "chat_canvas_rewrite_rules"
    CLAIM_EXTRACT_SYSTEM: Final[str] = "claim_extract_system"
    CLAIM_EXTRACT_USER: Final[str] = "claim_extract_user"
    FACT_VERIFY_SYSTEM: Final[str] = "fact_verify_system"
    FACT_VERIFY_USER: Final[str] = "fact_verify_user"
    FACT_VERIFY_CHUNK_SYSTEM: Final[str] = "fact_verify_chunk_system"
    FACT_VERIFY_CHUNK_USER: Final[str] = "fact_verify_chunk_user"
    NLI_VERIFY_SYSTEM: Final[str] = "nli_verify_system"
    NLI_VERIFY_USER: Final[str] = "nli_verify_user"
    FACT_CHECK_SYSTEM: Final[str] = "fact_check_system"
    HYDE_TFIDF_SYSTEM: Final[str] = "hyde_tfidf_system"
    HYDE_TFIDF_USER: Final[str] = "hyde_tfidf_user"
    HYDE_ST_SINGLE_SYSTEM: Final[str] = "hyde_st_single_system"
    HYDE_ST_SINGLE_USER: Final[str] = "hyde_st_single_user"
    HYDE_ST_MULTI_SYSTEM: Final[str] = "hyde_st_multi_system"
    HYDE_ST_MULTI_USER: Final[str] = "hyde_st_multi_user"
    LITERAL_TERMS_SYSTEM: Final[str] = "literal_terms_system"
    LITERAL_TERMS_USER: Final[str] = "literal_terms_user"
    RAG_RERANK_SYSTEM: Final[str] = "rag_rerank_system"
    RAG_RERANK_USER: Final[str] = "rag_rerank_user"
    MINDMAP_SYSTEM: Final[str] = "mindmap_system"
    MINDMAP_USER: Final[str] = "mindmap_user"
    GRAPH_SYSTEM: Final[str] = "graph_system"
    GRAPH_USER: Final[str] = "graph_user"
    GLOSSARY_SYSTEM: Final[str] = "glossary_system"
    GLOSSARY_USER: Final[str] = "glossary_user"

    ALL: Final[tuple[str, ...]] = (
        CHAT_SYSTEM,
        CHAT_SECTION_GROUNDING_TITLE,
        CHAT_SECTION_REWRITE_TITLE,
        CHAT_SECTION_CONTEXT_TITLE,
        CHAT_SECTION_CONTEXT_END,
        CHAT_SECTION_FILES_TITLE,
        CHAT_SECTION_RAG_TITLE,
        CHAT_SECTION_SELECTED_TITLE,
        CHAT_CITATION_RULE_ANSWER,
        CHAT_CITATION_RULE_REWRITE,
        CHAT_GROUNDING_NOTE_REWRITE,
        CHAT_GROUNDING_RULES,
        CHAT_CANVAS_REWRITE_RULES,
        CLAIM_EXTRACT_SYSTEM,
        CLAIM_EXTRACT_USER,
        FACT_VERIFY_SYSTEM,
        FACT_VERIFY_USER,
        FACT_VERIFY_CHUNK_SYSTEM,
        FACT_VERIFY_CHUNK_USER,
        NLI_VERIFY_SYSTEM,
        NLI_VERIFY_USER,
        FACT_CHECK_SYSTEM,
        HYDE_TFIDF_SYSTEM,
        HYDE_TFIDF_USER,
        HYDE_ST_SINGLE_SYSTEM,
        HYDE_ST_SINGLE_USER,
        HYDE_ST_MULTI_SYSTEM,
        HYDE_ST_MULTI_USER,
        LITERAL_TERMS_SYSTEM,
        LITERAL_TERMS_USER,
        RAG_RERANK_SYSTEM,
        RAG_RERANK_USER,
        MINDMAP_SYSTEM,
        MINDMAP_USER,
        GRAPH_SYSTEM,
        GRAPH_USER,
        GLOSSARY_SYSTEM,
        GLOSSARY_USER,
    )


class RAGSettingsKeys:
    CHUNKING_STRATEGY: Final[str] = "rag/chunking_strategy"
    CHUNK_SIZE: Final[str] = "rag/chunk_size"
    CHUNK_OVERLAP: Final[str] = "rag/chunk_overlap"
    HYDE_ENABLED: Final[str] = "rag/hyde_enabled"
    HYDE_MIN_WORDS: Final[str] = "rag/hyde_min_words"
    ST_MODEL_NAME: Final[str] = "rag/st_model_name"
    TOP_K: Final[str] = "rag/top_k"
    SCORE_THRESHOLD: Final[str] = "rag/score_threshold"
