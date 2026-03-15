"""Global signal wiring for :mod:`studio.window`."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QTimer


def connect_global_signals(window: Any) -> None:
    """Connect runtime-wide signals after all controllers are initialized."""
    window.llm_manager.model_loaded.connect(window._on_model_loaded)
    window._speech_ctrl.tts_manager.speaking_changed.connect(window._on_tts_speaking_changed)
    window.rag_system.backend_changed.connect(window._on_backend_changed)
    window._backend_lbl.setText(f"backend: {window.rag_system.current_backend()}")
    window.knowledge_dock.rag_settings_requested.connect(
        window._knowledge_controller.open_rag_settings_dialog
    )
    window.knowledge_dock.rag_status_changed.connect(window._on_rag_status)
    window.knowledge_dock.document_remove_requested.connect(window._remove_imported_document)
    window.knowledge_dock.document_rename_requested.connect(window._rename_imported_document)
    window.knowledge_dock.rag_worker.index_complete.connect(window._on_rag_index_complete)
    window.chat_dock.tts_mode_changed.connect(window._speech_ctrl.on_chat_tts_mode_changed)
    window.canvas.tabs.read_aloud_requested.connect(window._speak_selection_text)
    window.knowledge_dock.doc_viewer.tabs.read_aloud_requested.connect(window._speak_selection_text)
    window.knowledge_dock.rag_panel.tabs.read_aloud_requested.connect(window._speak_selection_text)

    try:
        window.chat_dock.history.content_changed.connect(window._on_chat_history_content_changed)
    except Exception as exc:
        window.app_logger.warning(
            "SYS",
            f"Failed to connect chat history autosave hook: {exc}",
        )

    window._speech_ctrl.apply_tts_speaking_state(
        window._speech_ctrl.tts_manager.is_speaking()
    )
    window._speech_ctrl._apply_runtime_settings()
    window._ctx_timer = QTimer(window)
    window._ctx_timer.timeout.connect(window._refresh_context_bar)
    window._ctx_timer.start(1000)
