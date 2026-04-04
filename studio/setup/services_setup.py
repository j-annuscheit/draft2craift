"""Service wiring for :mod:`studio.window`."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

from shared.domain.user_mode import default_user_mode
from shared.services.llm.manager import LLMManager
from shared.services.plugins.manager import PluginManager
from shared.services.project.manager import ProjectManager
from shared.services.rag.orchestrator import RAGSystem
from studio.app_context import AppContext
from studio.controllers.user_mode_controller import UserModeController
from studio.logger import AppLogger

@dataclass(slots=True)
class ServiceBundle:
    """Services and settings required by the runtime setup pipeline."""

    app_logger: AppLogger
    rag_system: RAGSystem
    llm_manager: LLMManager
    plugin_manager: PluginManager
    project_manager: ProjectManager
    file_registry: dict[str, tuple[str, str]]
    user_mode_ctrl: UserModeController
    app_settings: QSettings
    context: AppContext


def init_services(window, *, app_settings: QSettings) -> ServiceBundle:
    """Create long-lived services and the shared AppContext."""
    app_logger = AppLogger(enabled=True)
    plugins_root = Path(__file__).resolve().parents[2] / "plugins"
    plugin_manager = PluginManager(root_dir=plugins_root, logger=app_logger)
    plugin_manager.load_all()
    rag_system = RAGSystem(logger=app_logger, plugin_manager=plugin_manager)
    llm_manager = LLMManager(logger=app_logger, plugin_manager=plugin_manager)
    file_registry: dict[str, tuple[str, str]] = {}
    project_manager = ProjectManager()
    user_mode_ctrl = UserModeController(default_user_mode())
    context = AppContext(
        window=window,
        app_logger=app_logger,
        rag_system=rag_system,
        llm_manager=llm_manager,
        plugin_manager=plugin_manager,
        project_manager=project_manager,
        app_settings=app_settings,
        file_registry=file_registry,
        get_user_mode=user_mode_ctrl.get_user_mode,
    )
    return ServiceBundle(
        app_logger=app_logger,
        rag_system=rag_system,
        llm_manager=llm_manager,
        plugin_manager=plugin_manager,
        project_manager=project_manager,
        file_registry=file_registry,
        user_mode_ctrl=user_mode_ctrl,
        app_settings=app_settings,
        context=context,
    )
