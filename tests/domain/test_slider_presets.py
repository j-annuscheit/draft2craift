from __future__ import annotations

from pathlib import Path

import shared.domain.slider_presets as slider_presets


def test_default_slider_presets_are_available() -> None:
    gen = slider_presets.chat_generation_style_presets()
    ctx = slider_presets.chat_context_length_presets()
    scope = slider_presets.rag_scope_presets()
    speed = slider_presets.rag_speed_quality_presets()

    assert len(gen) == 3
    assert len(ctx) == 3
    assert len(scope) == 3
    assert len(speed) == 3
    assert gen[1]["temperature"] == 0.70
    assert ctx[1] == 4096
    assert scope[2]["selection_mode"] == "top_k"
    assert speed[0]["llm_rerank_enabled"] is False


def test_slider_presets_can_be_reloaded_from_custom_file(tmp_path: Path) -> None:
    custom = tmp_path / "slider_presets.toml"
    custom.write_text(
        """
[[chat.generation_style]]
temperature = 0.10
top_p = 0.70
repeat_penalty = 1.30

[[chat.generation_style]]
temperature = 0.20
top_p = 0.80
repeat_penalty = 1.20

[[chat.generation_style]]
temperature = 0.30
top_p = 0.90
repeat_penalty = 1.10

[[chat.context_length]]
context_tokens = 1024

[[chat.context_length]]
context_tokens = 2048

[[chat.context_length]]
context_tokens = 3072

[[rag.scope]]
extended_context = false
ext_before = 111
ext_after = 111
selection_mode = "top_k_threshold"
top_k = 2
threshold = 0.20
regex_max = 1

[[rag.scope]]
extended_context = false
ext_before = 222
ext_after = 222
selection_mode = "top_k_threshold"
top_k = 4
threshold = 0.10
regex_max = 2

[[rag.scope]]
extended_context = true
ext_before = 333
ext_after = 333
selection_mode = "top_k"
top_k = 6
threshold = 0.0
regex_max = 3

[[rag.speed_quality]]
use_hyde = false
hyde_min_words = 8
hyde_tfidf_mode = "keywords"
hyde_st_mode = "passage"
hyde_st_hypotheses = 2
hyde_use_doc_context = false
literal_use_llm_terms = false
literal_llm_max_terms = 4
llm_rerank_enabled = false
llm_rerank_min_score = 0.60
llm_rerank_max_candidates = 5

[[rag.speed_quality]]
use_hyde = true
hyde_min_words = 6
hyde_tfidf_mode = "keywords"
hyde_st_mode = "passage"
hyde_st_hypotheses = 3
hyde_use_doc_context = false
literal_use_llm_terms = false
literal_llm_max_terms = 6
llm_rerank_enabled = false
llm_rerank_min_score = 0.50
llm_rerank_max_candidates = 6

[[rag.speed_quality]]
use_hyde = true
hyde_min_words = 4
hyde_tfidf_mode = "passage"
hyde_st_mode = "multi_passage"
hyde_st_hypotheses = 5
hyde_use_doc_context = true
literal_use_llm_terms = true
literal_llm_max_terms = 10
llm_rerank_enabled = true
llm_rerank_min_score = 0.30
llm_rerank_max_candidates = 12
""".strip(),
        encoding="utf-8",
    )

    try:
        slider_presets.reload_slider_preset_config(custom)
        assert slider_presets.chat_context_length_presets() == (1024, 2048, 3072)
        assert slider_presets.chat_generation_style_presets()[0]["temperature"] == 0.10
        assert slider_presets.rag_scope_presets()[1]["top_k"] == 4
        assert slider_presets.rag_speed_quality_presets()[2]["llm_rerank_enabled"] is True
        assert slider_presets.rag_speed_quality_presets()[2]["llm_rerank_max_candidates"] == 12
    finally:
        slider_presets.reload_slider_preset_config(slider_presets.SLIDER_PRESET_CONFIG_PATH)


def test_slider_presets_fallback_when_step_count_is_invalid(tmp_path: Path) -> None:
    invalid = tmp_path / "slider_presets.toml"
    invalid.write_text(
        """
[[chat.generation_style]]
temperature = 0.5
top_p = 0.5
repeat_penalty = 1.0
""".strip(),
        encoding="utf-8",
    )

    try:
        slider_presets.reload_slider_preset_config(invalid)
        assert slider_presets.chat_context_length_presets() == (2048, 4096, 8192)
        assert slider_presets.chat_generation_style_presets()[1]["temperature"] == 0.70
        assert slider_presets.rag_scope_presets()[2]["regex_max"] == 6
        assert slider_presets.rag_speed_quality_presets()[0]["use_hyde"] is False
    finally:
        slider_presets.reload_slider_preset_config(slider_presets.SLIDER_PRESET_CONFIG_PATH)
