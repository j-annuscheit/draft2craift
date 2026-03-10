"""Service wiring for :mod:`studio.window`."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings

from shared.domain.user_mode import USER_MODE_PLUS
from shared.services.llm.manager import LLMManager
from shared.services.project.manager import ProjectManager
from shared.services.rag.orchestrator import RAGSystem
from studio.app_context import AppContext
from studio.logger import AppLogger

@dataclass(slots=True)
class ServiceBundle:
    """Services and settings required by the runtime setup pipeline."""

    app_logger: AppLogger
    rag_system: RAGSystem
    llm_manager: LLMManager
    project_manager: ProjectManager
    file_registry: dict[str, tuple[str, str]]
    user_mode: str
    app_settings: QSettings
    context: AppContext


def init_services(window) -> ServiceBundle:
    """Create long-lived services and the shared AppContext."""
    app_logger = AppLogger(enabled=True)
    rag_system = RAGSystem(logger=app_logger)
    llm_manager = LLMManager(logger=app_logger)
    file_registry: dict[str, tuple[str, str]] = {}
    project_manager = ProjectManager()
    user_mode = USER_MODE_PLUS
    app_settings = QSettings("draft2craift", "draft2craift")
    context = AppContext(
        window=window,
        app_logger=app_logger,
        rag_system=rag_system,
        llm_manager=llm_manager,
        project_manager=project_manager,
        app_settings=app_settings,
        file_registry=file_registry,
        user_mode=user_mode,
    )
    return ServiceBundle(
        app_logger=app_logger,
        rag_system=rag_system,
        llm_manager=llm_manager,
        project_manager=project_manager,
        file_registry=file_registry,
        user_mode=user_mode,
        app_settings=app_settings,
        context=context,
    )
