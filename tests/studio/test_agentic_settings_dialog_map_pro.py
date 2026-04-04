from __future__ import annotations

from shared.services.agentic.settings import AgenticRuntimeSettings
from studio.agentic.settings_dialog import AgenticSettingsDialog


def test_agentic_settings_dialog_roundtrip_map_pro_fields(qt_app):
    _ = qt_app
    base = AgenticRuntimeSettings.from_dict(
        {
            "mindmap_retrieval_strategy": "agent",
            "mindmap_agent_max_iterations": 7,
            "mindmap_factcheck": True,
            "mindmap_max_nodes": 48,
            "mindmap_max_refinement_rounds": 2,
            "graph_retrieval_strategy": "none",
            "graph_agent_max_iterations": 5,
            "graph_factcheck": False,
            "graph_max_nodes": 28,
        }
    )
    dialog = AgenticSettingsDialog(base, user_mode="expert")
    try:
        assert dialog._mindmap_retrieval_combo is not None
        assert dialog._mindmap_agent_iter_spin is not None
        assert dialog._graph_retrieval_combo is not None
        assert dialog._graph_agent_iter_spin is not None

        assert str(dialog._mindmap_retrieval_combo.currentData() or "") == "agent"
        assert int(dialog._mindmap_agent_iter_spin.value()) == 7
        assert str(dialog._graph_retrieval_combo.currentData() or "") == "none"
        assert int(dialog._graph_agent_iter_spin.value()) == 5

        dialog._graph_retrieval_combo.setCurrentIndex(
            dialog._graph_retrieval_combo.findData("agent")
        )
        qt_app.processEvents()
        assert bool(dialog._graph_agent_iter_spin.isEnabled())

        dialog._mindmap_retrieval_combo.setCurrentIndex(
            dialog._mindmap_retrieval_combo.findData("rag")
        )
        qt_app.processEvents()
        assert not bool(dialog._mindmap_agent_iter_spin.isEnabled())

        out = dialog.get_settings()
        assert out.mindmap_retrieval_strategy == "rag"
        assert out.graph_retrieval_strategy == "agent"
    finally:
        dialog.deleteLater()
