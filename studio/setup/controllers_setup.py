"""Controller wiring for :mod:`studio.window`."""
from __future__ import annotations

from dataclasses import dataclass

from studio.app_context import AppContext
from studio.chat.runtime_ports import (
    ChatDockActionPorts,
    ChatDockContextPorts,
)
from studio.controllers.autosave import AutosaveController
from studio.controllers.canvas_controller import CanvasController
from studio.controllers.chat_controller import ChatController
from studio.controllers.find_replace_ctrl import FindReplaceController
from studio.controllers.knowledge_controller import KnowledgeController
from studio.controllers.llm_task_context import LLMTaskContext
from studio.controllers.llm_tasks import LLMSideTaskController
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
    llm_tasks_ctrl: LLMSideTaskController
    find_replace_ctrl: FindReplaceController


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
    user_mode_ctrl = getattr(window, "_user_mode_ctrl", None)
    if user_mode_ctrl is None:
        raise RuntimeError("Controller setup requires user_mode controller to be bound.")

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
    chat_dock.bind_context_ports(
        ChatDockContextPorts(
            build_context=chat_controller.build_llm_context,
            canvas_selection_text=chat_controller.canvas_selection_text,
        )
    )
    ctx.bind_chat_controller(chat_controller)

    speech_ctrl = SpeechController(
        parent=window,
        canvas=canvas,
        knowledge_dock=knowledge_dock,
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

    theme_ctrl = ctx.theme_controller
    if theme_ctrl is None:
        raise RuntimeError("Controller setup requires theme_controller to be bound.")
    glossary_bar = ctx.glossary_feedback_bar
    if glossary_bar is None:
        raise RuntimeError("Controller setup requires glossary_feedback_bar to be bound.")

    llm_tasks_ctrl = LLMSideTaskController(
        parent=window,
        ctx=LLMTaskContext(
            llm_manager=ctx.llm_manager,
            rag_system=ctx.rag_system,
            canvas=canvas,
            chat_dock=chat_dock,
            glossary_feedback_bar=glossary_bar,
            app_logger=ctx.app_logger,
            show_status=ctx.show_status,
            resolve_imported_doc_content=ctx.resolve_imported_doc_content,
            set_status_feedback_payload=user_mode_ctrl.set_status_feedback_payload,
            refresh_preview_overlays=theme_ctrl.refresh_all_preview_overlays,
            autosave_schedule_fn=ctx.schedule_autosave,
            build_llm_context=chat_controller.build_llm_context,
            get_user_mode=ctx.get_user_mode,
            is_prompt_editor_allowed=user_mode_ctrl.is_prompt_editor_allowed,
            dialog_manager=window.dialog_manager,
        ),
    )
    chat_dock.bind_action_ports(
        ChatDockActionPorts(
            apply_selection_rewrite=canvas.replace_selected_text,
            open_fact_result=canvas_controller.open_fact_check_canvas,
            generate_glossary=llm_tasks_ctrl.generate_glossary_from_llm_context,
            generate_mindmap=llm_tasks_ctrl.generate_mindmap_from_llm_context,
        )
    )
    find_replace_ctrl = FindReplaceController(
        parent_window=window,
        canvas=canvas,
        knowledge_dock=knowledge_dock,
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
        llm_tasks_ctrl=llm_tasks_ctrl,
        find_replace_ctrl=find_replace_ctrl,
    )
