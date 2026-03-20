from __future__ import annotations

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
