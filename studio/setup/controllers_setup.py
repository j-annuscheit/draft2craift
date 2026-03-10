"""Controller wiring for :mod:`studio.window`."""
from __future__ import annotations

from dataclasses import dataclass

from studio.app_context import AppContext
from studio.controllers.autosave import AutosaveController
from studio.controllers.canvas_controller import CanvasController
from studio.controllers.chat_controller import ChatController
from studio.controllers.knowledge_controller import KnowledgeController
from studio.controllers.project_controller import ProjectController
from studio.controllers.speech_ctrl import SpeechController
from studio.controllers.zoom_ctrl import ZoomController

@dataclass(slots=True)
class ControllerBundle:
    """Runtime controllers created after docks are available."""

    autosave_ctrl: AutosaveController
    canvas_controller: CanvasController
    knowledge_controller: KnowledgeController
    project_controller: ProjectController
    chat_controller: ChatController
    speech_ctrl: SpeechController
    zoom_ctrl: ZoomController


def init_controllers(ctx: AppContext) -> ControllerBundle:
    """Initialize runtime controllers after docks are available."""
    window = ctx.window
    canvas = getattr(window, "canvas", None)
    knowledge_dock = getattr(window, "knowledge_dock", None)
    chat_dock = getattr(window, "chat_dock", None)
    if canvas is None or knowledge_dock is None or chat_dock is None:
        raise RuntimeError(
            "Controller setup requires initialized canvas and dock widgets."
        )

    autosave_ctrl = AutosaveController(
        parent=window,
        canvas=canvas,
        app_context=ctx,
        app_logger=ctx.app_logger,
        app_settings=ctx.app_settings,
    )
    ctx.bind_autosave_controller(autosave_ctrl)

    canvas_controller = CanvasController(
        parent=window,
        canvas=canvas,
        knowledge_dock=knowledge_dock,
        chat_dock=chat_dock,
        show_status=ctx.show_status,
    )
    knowledge_controller = KnowledgeController(
        file_registry=ctx.file_registry,
        knowledge_dock=knowledge_dock,
        chat_dock=chat_dock,
        app_context=ctx,
        app_logger=ctx.app_logger,
        rag_system=ctx.rag_system,
    )
    ctx.bind_knowledge_controller(knowledge_controller)

    project_controller = ProjectController(
        window=window,
        app_context=ctx,
    )
    chat_controller = ChatController(
        chat_dock=chat_dock,
        canvas=canvas,
        knowledge_dock=knowledge_dock,
        resolve_imported_doc_content=ctx.resolve_imported_doc_content,
    )
    ctx.bind_chat_controller(chat_controller)

    speech_ctrl = SpeechController(
        parent=window,
        canvas=canvas,
        chat_dock=chat_dock,
        app_logger=ctx.app_logger,
        app_settings=ctx.app_settings,
        show_status=ctx.show_status,
        autosave_schedule_fn=ctx.schedule_autosave,
        on_tts_speaking_changed=window._on_tts_speaking_changed,
    )
    zoom_ctrl = ZoomController(
        canvas=canvas,
        show_status=ctx.show_status,
    )
    return ControllerBundle(
        autosave_ctrl=autosave_ctrl,
        canvas_controller=canvas_controller,
        knowledge_controller=knowledge_controller,
        project_controller=project_controller,
        chat_controller=chat_controller,
        speech_ctrl=speech_ctrl,
        zoom_ctrl=zoom_ctrl,
    )
