from __future__ import annotations

import pytest

from shared.services.rag.config import RAGConfig
from studio.knowledge.rag_settings.dialog import RAGSettingsDialog


def test_bm25_controls_are_enabled_only_for_bm25_mode(qt_app):
    _ = qt_app
    cfg = RAGConfig()
    cfg.backend.use_tfidf = True
    cfg.backend.lexical_mode = "tfidf"

    dialog = RAGSettingsDialog(cfg, user_mode="expert")
    try:
        w = dialog._controls.widgets

        assert w["bm25_k1"].isHidden()  # type: ignore[attr-defined]
        assert w["bm25_b"].isHidden()  # type: ignore[attr-defined]
        assert not w["bm25_k1"].isEnabled()  # type: ignore[attr-defined]
        assert not w["bm25_b"].isEnabled()  # type: ignore[attr-defined]

        w["lexical_mode"].setCurrentText("bm25")  # type: ignore[attr-defined]
        qt_app.processEvents()
        assert not w["bm25_k1"].isHidden()  # type: ignore[attr-defined]
        assert not w["bm25_b"].isHidden()  # type: ignore[attr-defined]
        assert w["bm25_k1"].isEnabled()  # type: ignore[attr-defined]
        assert w["bm25_b"].isEnabled()  # type: ignore[attr-defined]

        w["lexical_mode"].setCurrentText("tfidf")  # type: ignore[attr-defined]
        qt_app.processEvents()
        assert w["bm25_k1"].isHidden()  # type: ignore[attr-defined]
        assert w["bm25_b"].isHidden()  # type: ignore[attr-defined]
        assert not w["bm25_k1"].isEnabled()  # type: ignore[attr-defined]
        assert not w["bm25_b"].isEnabled()  # type: ignore[attr-defined]

        w["use_tfidf"].setChecked(False)  # type: ignore[attr-defined]
        qt_app.processEvents()
        assert w["bm25_k1"].isHidden()  # type: ignore[attr-defined]
        assert w["bm25_b"].isHidden()  # type: ignore[attr-defined]
        assert not w["bm25_k1"].isEnabled()  # type: ignore[attr-defined]
        assert not w["bm25_b"].isEnabled()  # type: ignore[attr-defined]
    finally:
        dialog.deleteLater()


def test_bm25_controls_start_enabled_when_mode_is_bm25(qt_app):
    _ = qt_app
    cfg = RAGConfig()
    cfg.backend.use_tfidf = True
    cfg.backend.lexical_mode = "bm25"

    dialog = RAGSettingsDialog(cfg, user_mode="expert")
    try:
        w = dialog._controls.widgets
        assert not w["bm25_k1"].isHidden()  # type: ignore[attr-defined]
        assert not w["bm25_b"].isHidden()  # type: ignore[attr-defined]
        assert w["bm25_k1"].isEnabled()  # type: ignore[attr-defined]
        assert w["bm25_b"].isEnabled()  # type: ignore[attr-defined]
    finally:
        dialog.deleteLater()


def test_rag_scope_slider_applies_presets(qt_app):
    _ = qt_app
    dialog = RAGSettingsDialog(RAGConfig(), user_mode="expert")
    try:
        w = dialog._controls.widgets

        w["scope_profile_slider"].setValue(0)  # type: ignore[attr-defined]
        qt_app.processEvents()
        assert str(w["selection_mode"].currentText()) == "top_k_threshold"  # type: ignore[attr-defined]
        assert int(w["top_k"].value()) == 3  # type: ignore[attr-defined]
        assert float(w["threshold"].value()) == pytest.approx(0.10)  # type: ignore[attr-defined]
        assert not bool(w["extended_context"].isChecked())  # type: ignore[attr-defined]
        assert int(w["ext_before"].value()) == 300  # type: ignore[attr-defined]
        assert int(w["regex_max"].value()) == 2  # type: ignore[attr-defined]

        w["scope_profile_slider"].setValue(2)  # type: ignore[attr-defined]
        qt_app.processEvents()
        assert str(w["selection_mode"].currentText()) == "top_k"  # type: ignore[attr-defined]
        assert int(w["top_k"].value()) == 8  # type: ignore[attr-defined]
        assert float(w["threshold"].value()) == pytest.approx(0.0)  # type: ignore[attr-defined]
        assert bool(w["extended_context"].isChecked())  # type: ignore[attr-defined]
        assert int(w["ext_before"].value()) == 800  # type: ignore[attr-defined]
        assert int(w["regex_max"].value()) == 6  # type: ignore[attr-defined]
    finally:
        dialog.deleteLater()


def test_rag_speed_quality_slider_applies_presets(qt_app):
    _ = qt_app
    dialog = RAGSettingsDialog(RAGConfig(), user_mode="expert")
    try:
        w = dialog._controls.widgets

        w["speed_profile_slider"].setValue(0)  # type: ignore[attr-defined]
        qt_app.processEvents()
        assert not bool(w["use_hyde"].isChecked())  # type: ignore[attr-defined]
        assert not bool(w["llm_rerank_enabled"].isChecked())  # type: ignore[attr-defined]
        assert not bool(w["literal_use_llm_terms"].isChecked())  # type: ignore[attr-defined]
        assert int(w["llm_rerank_max_candidates"].value()) == 8  # type: ignore[attr-defined]

        w["speed_profile_slider"].setValue(2)  # type: ignore[attr-defined]
        qt_app.processEvents()
        assert bool(w["use_hyde"].isChecked())  # type: ignore[attr-defined]
        assert str(w["hyde_tfidf_mode"].currentText()) == "passage"  # type: ignore[attr-defined]
        assert str(w["hyde_st_mode"].currentText()) == "multi_passage"  # type: ignore[attr-defined]
        assert bool(w["hyde_use_doc_context"].isChecked())  # type: ignore[attr-defined]
        assert bool(w["llm_rerank_enabled"].isChecked())  # type: ignore[attr-defined]
        assert bool(w["literal_use_llm_terms"].isChecked())  # type: ignore[attr-defined]
        assert int(w["llm_rerank_max_candidates"].value()) == 16  # type: ignore[attr-defined]
    finally:
        dialog.deleteLater()


def test_rag_scope_slider_syncs_from_manual_control_changes(qt_app):
    _ = qt_app
    dialog = RAGSettingsDialog(RAGConfig(), user_mode="expert")
    try:
        w = dialog._controls.widgets
        w["extended_context"].setChecked(True)  # type: ignore[attr-defined]
        w["ext_before"].setValue(800)  # type: ignore[attr-defined]
        w["ext_after"].setValue(800)  # type: ignore[attr-defined]
        w["selection_mode"].setCurrentText("top_k")  # type: ignore[attr-defined]
        w["top_k"].setValue(8)  # type: ignore[attr-defined]
        w["threshold"].setValue(0.0)  # type: ignore[attr-defined]
        w["regex_max"].setValue(6)  # type: ignore[attr-defined]
        qt_app.processEvents()

        assert int(w["scope_profile_slider"].value()) == 2  # type: ignore[attr-defined]
    finally:
        dialog.deleteLater()


def test_rag_speed_slider_syncs_from_manual_control_changes(qt_app):
    _ = qt_app
    dialog = RAGSettingsDialog(RAGConfig(), user_mode="expert")
    try:
        w = dialog._controls.widgets
        w["use_hyde"].setChecked(True)  # type: ignore[attr-defined]
        w["hyde_min_words"].setValue(3)  # type: ignore[attr-defined]
        w["hyde_tfidf_mode"].setCurrentText("passage")  # type: ignore[attr-defined]
        w["hyde_st_mode"].setCurrentText("multi_passage")  # type: ignore[attr-defined]
        w["hyde_st_hypotheses"].setValue(4)  # type: ignore[attr-defined]
        w["hyde_use_doc_context"].setChecked(True)  # type: ignore[attr-defined]
        w["literal_use_llm_terms"].setChecked(True)  # type: ignore[attr-defined]
        w["literal_llm_max_terms"].setValue(12)  # type: ignore[attr-defined]
        w["llm_rerank_enabled"].setChecked(True)  # type: ignore[attr-defined]
        w["llm_rerank_min_score"].setValue(0.35)  # type: ignore[attr-defined]
        w["llm_rerank_max_candidates"].setValue(16)  # type: ignore[attr-defined]
        qt_app.processEvents()

        assert int(w["speed_profile_slider"].value()) == 2  # type: ignore[attr-defined]
    finally:
        dialog.deleteLater()


def test_rag_simple_sliders_user_mode_texts_and_gating(qt_app, monkeypatch):
    _ = qt_app
    import studio.knowledge.rag_settings.dialog as rag_dialog

    original_is_feature_visible = rag_dialog.is_feature_visible

    def _patched_visibility(mode: object, feature_key: str, default: bool = True) -> bool:
        if str(feature_key) in {
            "rag.settings.selection.scope_profile",
            "rag.settings.selection.speed_profile",
        }:
            return str(mode) == "expert"
        return bool(original_is_feature_visible(mode, feature_key, default=default))

    monkeypatch.setattr(rag_dialog, "is_feature_visible", _patched_visibility)

    dialog = rag_dialog.RAGSettingsDialog(RAGConfig(), user_mode="easy_eng")
    try:
        w = dialog._controls.widgets
        selection_form = dialog._controls.forms["selection"]
        scope_label = selection_form.labelForField(w["scope_profile_widget"])  # type: ignore[arg-type]
        speed_label = selection_form.labelForField(w["speed_profile_widget"])  # type: ignore[arg-type]
        assert scope_label is not None and scope_label.text() == "Result scope:"
        assert speed_label is not None and speed_label.text() == "Speed vs quality:"
        assert str(w["scope_profile_mark_compact"].text()) == "Compact"  # type: ignore[attr-defined]
        assert str(w["scope_profile_mark_balanced"].text()) == "Balanced"  # type: ignore[attr-defined]
        assert str(w["scope_profile_mark_extensive"].text()) == "Extensive"  # type: ignore[attr-defined]
        assert str(w["speed_profile_mark_fast"].text()) == "Fast"  # type: ignore[attr-defined]
        assert str(w["speed_profile_mark_balanced"].text()) == "Balanced"  # type: ignore[attr-defined]
        assert str(w["speed_profile_mark_quality"].text()) == "Quality"  # type: ignore[attr-defined]
        assert w["scope_profile_widget"].isHidden()  # type: ignore[attr-defined]
        assert w["speed_profile_widget"].isHidden()  # type: ignore[attr-defined]

        dialog.set_user_mode("expert")
        assert not w["scope_profile_widget"].isHidden()  # type: ignore[attr-defined]
        assert not w["speed_profile_widget"].isHidden()  # type: ignore[attr-defined]
    finally:
        dialog.deleteLater()
