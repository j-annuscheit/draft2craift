from __future__ import annotations

import unittest
from unittest.mock import Mock, call, patch

import pytest
from PySide6.QtWidgets import QDialog, QWidget

from studio.canvas.exporting.annotation_export import (
    AnnotationExportData,
    AnnotationExportEntry,
    AnnotationExportOptions,
)
from studio.controllers.canvas_controller import CanvasController
from studio.controllers.chat_controller import ChatController
from studio.controllers.project_controller import ProjectController


pytestmark = pytest.mark.usefixtures("qt_app")


class _CanvasTabsStub:
    def __init__(self, panel: QWidget, title: str = "Draft Tab"):
        self._panel = panel
        self._title = title
        self.tab_widget = Mock()
        self.tab_widget.currentIndex.return_value = 0
        self.tab_widget.tabText.return_value = title

    def current_panel(self) -> QWidget:
        return self._panel

    def get_tab_full_title(self, _idx: int) -> str:
        return self._title


class _CanvasStub:
    def __init__(self, panel: QWidget):
        self.tabs = _CanvasTabsStub(panel)


class _CanvasContextStub:
    def __init__(
        self,
        *,
        current_text: str,
        selected_text: str,
        selected_span: tuple[int, int] | None,
    ):
        self._current_text = str(current_text)
        self._selected_text = str(selected_text)
        self._selected_span = selected_span
        self.tabs = Mock()
        self.tabs.tab_widget = Mock()
        self.tabs.tab_widget.currentIndex.return_value = 0
        self.tabs.tab_widget.tabText.return_value = "Draft One"

    def get_current_text(self) -> str:
        return self._current_text

    def get_selected_text(
        self,
        *,
        allow_cached: bool = True,
        consume_cached: bool = True,
    ) -> str:
        _ = allow_cached, consume_cached
        return self._selected_text

    def get_selected_span(self, *, allow_cached: bool = True):
        _ = allow_cached
        return self._selected_span


class CanvasControllerIntegrationTests(unittest.TestCase):
    def test_export_uses_chat_scope_when_focus_is_in_chat_dock(self):
        parent = QWidget()
        knowledge_dock = QWidget()
        chat_dock = QWidget()
        chat_panel = QWidget()
        focus_widget = QWidget(chat_dock)
        show_status = Mock()

        chat_dock.history = Mock()
        chat_dock.history.current_panel.return_value = chat_panel
        chat_dock.history.current_tab_title.return_value = "Session A"

        canvas = _CanvasStub(QWidget())
        controller = CanvasController(
            parent=parent,
            canvas=canvas,  # type: ignore[arg-type]
            knowledge_dock=knowledge_dock,  # type: ignore[arg-type]
            chat_dock=chat_dock,  # type: ignore[arg-type]
            show_status=show_status,
        )

        with (
            patch(
                "studio.controllers.canvas_controller.QApplication.focusWidget",
                return_value=focus_widget,
            ),
            patch("studio.controllers.canvas_controller.CanvasFileActions") as export_cls,
        ):
            controller.export_active_canvas_document()

        export_cls.assert_called_once_with(parent=parent, tabs=canvas.tabs)
        exporter = export_cls.return_value
        exporter.export_specific_panel.assert_called_once_with(
            chat_panel,
            default_format="pdf",
            panel_scope="chat",
            tab_name="Session A",
        )
        show_status.assert_not_called()

    def test_export_without_panel_reports_status(self):
        parent = QWidget()
        controller = CanvasController(
            parent=parent,
            canvas=_CanvasStub(QWidget()),  # type: ignore[arg-type]
            knowledge_dock=QWidget(),  # type: ignore[arg-type]
            chat_dock=QWidget(),  # type: ignore[arg-type]
            show_status=Mock(),
        )
        controller.resolve_active_export_target = Mock(return_value={"panel": None})

        controller.export_active_canvas_document()

        controller._show_status.assert_called_once_with(
            "Kein exportierbares Canvas aktiv.",
            2800,
        )

    def test_export_panel_annotations_to_canvas_creates_new_draft_tab(self):
        parent = QWidget()
        canvas = _CanvasStub(QWidget())
        canvas.tabs.add_tab = Mock()
        show_status = Mock()
        controller = CanvasController(
            parent=parent,
            canvas=canvas,  # type: ignore[arg-type]
            knowledge_dock=QWidget(),  # type: ignore[arg-type]
            chat_dock=QWidget(),  # type: ignore[arg-type]
            show_status=show_status,
        )
        panel = Mock()
        panel.annotation_export_text.return_value = "Alpha Beta"
        export_data = AnnotationExportData(
            entries=(
                AnnotationExportEntry(
                    highlight_id="hl_1",
                    kind="user",
                    color="#F9E2AF",
                    text="Alpha",
                    comment="Kommentar",
                    created_at="2026-03-01T10:00:00+00:00",
                    start=0,
                    end=5,
                ),
            ),
            color_counts=(("#F9E2AF", 1),),
            glossary_count=0,
        )

        with (
            patch(
                "studio.controllers.canvas_controller.collect_annotation_export_data",
                return_value=export_data,
            ),
            patch(
                "studio.controllers.canvas_controller.build_annotation_export_markdown",
                return_value="# Export",
            ),
            patch("studio.controllers.canvas_controller.AnnotationExportDialog") as dialog_cls,
        ):
            dialog = dialog_cls.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.options.return_value = AnnotationExportOptions(
                include_colors=("#F9E2AF",),
                include_glossary=False,
                include_comments=True,
                sort_mode="chronological",
                keep_markers=True,
            )
            ok = controller.export_panel_annotations_to_canvas(
                panel=panel,
                panel_scope="draft",
                tab_name="Draft 1",
                user_mode="standard",
            )

        self.assertTrue(ok)
        canvas.tabs.add_tab.assert_called_once_with(
            title="Annotationen: Draft 1",
            content="# Export",
            read_only=False,
            activate=True,
        )
        show_status.assert_called_once_with(
            "Annotationen in neuem Canvas-Tab extrahiert.",
            4200,
        )


class ChatControllerIntegrationTests(unittest.TestCase):
    def test_build_llm_context_combines_docs_draft_and_rag(self):
        chat_dock = Mock()
        chat_dock.get_context_selection.return_value = (
            True,
            True,
            [
                ("Doc A", ""),
                ("Doc B", "Content B"),
                ("", "ignored"),
            ],
        )
        canvas = _CanvasContextStub(
            current_text=" Draft text ",
            selected_text="selected sentence",
            selected_span=(7, 15),
        )
        knowledge_dock = Mock()
        knowledge_dock.get_rag_results_text.return_value = "### 1. Treffer"
        resolver = Mock(side_effect=lambda name: f"Resolved {name}")

        controller = ChatController(
            chat_dock=chat_dock,
            canvas=canvas,  # type: ignore[arg-type]
            knowledge_dock=knowledge_dock,  # type: ignore[arg-type]
            resolve_imported_doc_content=resolver,
        )

        ctx = controller.build_llm_context()

        self.assertEqual(
            ctx["file_contents"],
            [
                ("Doc A", "Resolved Doc A"),
                ("Doc B", "Content B"),
                ("Draft: Draft One", "Draft text"),
            ],
        )
        self.assertEqual(
            ctx["rag_results"],
            [("RAG Results", 1.0, "### 1. Treffer")],
        )
        self.assertEqual(ctx["selected_text"], "selected sentence")
        self.assertEqual(ctx["selected_span"], (7, 15))
        self.assertTrue(ctx["grounding_required"])
        self.assertTrue(ctx["grounding_has_sources"])
        self.assertEqual(ctx["grounding_selected_docs"], 2)
        self.assertTrue(ctx["grounding_rag_selected"])
        self.assertTrue(ctx["grounding_rag_has_data"])

    def test_refresh_context_bar_reports_all_selected_sources(self):
        chat_dock = Mock()
        chat_dock.get_context_selection.return_value = (
            True,
            True,
            [("Doc A", "A")],
        )
        canvas = _CanvasContextStub(
            current_text="some draft",
            selected_text="snippet",
            selected_span=(0, 7),
        )
        knowledge_dock = Mock()
        knowledge_dock.get_rag_results_text.return_value = "RAG summary"

        controller = ChatController(
            chat_dock=chat_dock,
            canvas=canvas,  # type: ignore[arg-type]
            knowledge_dock=knowledge_dock,  # type: ignore[arg-type]
            resolve_imported_doc_content=Mock(return_value=""),
        )

        controller.refresh_context_bar()

        chat_dock.update_context_bar.assert_called_once_with(
            ["canvas", "RAG", "1 doc", "selection"]
        )


class ProjectControllerIntegrationTests(unittest.TestCase):
    def test_export_project_archive_success_flushes_and_schedules_autosave(self):
        window = QWidget()
        context = Mock()
        context.export_project_archive.return_value = True
        context.project_manager = Mock(last_error="")
        controller = ProjectController(window=window, app_context=context)

        with patch(
            "studio.controllers.project_controller.QFileDialog.getSaveFileName",
            return_value=("/tmp/project-out.d2c", "draft2craift Project (*.d2c)"),
        ):
            ok = controller.export_project_archive()

        self.assertTrue(ok)
        context.flush_autosave_pending_preview_edits.assert_called_once_with()
        context.export_project_archive.assert_called_once_with("/tmp/project-out.d2c")
        context.schedule_autosave.assert_called_once_with(250)
        context.show_status.assert_called_once_with(
            "Project exported to: /tmp/project-out.d2c",
            5000,
        )

    def test_load_project_failure_reports_error_and_restores_autosave_state(self):
        window = QWidget()
        context = Mock()
        context.get_autosave_suspended.return_value = False
        context.load_project.return_value = False
        context.project_manager = Mock(last_error="load failed hard")
        controller = ProjectController(window=window, app_context=context)

        with (
            patch(
                "studio.controllers.project_controller.QFileDialog.getExistingDirectory",
                return_value="/tmp/project-a",
            ),
            patch("studio.controllers.project_controller.QMessageBox.warning") as warning,
        ):
            ok = controller.load_project()

        self.assertFalse(ok)
        self.assertEqual(
            context.set_autosave_suspended.call_args_list,
            [call(True), call(False)],
        )
        context.rewire_autosave_editors.assert_not_called()
        context.schedule_autosave.assert_not_called()
        context.show_status.assert_called_with("Project load failed.", 6000)
        warning.assert_called_once()

    def test_load_project_success_rewires_editors_and_schedules_autosave(self):
        window = QWidget()
        context = Mock()
        context.get_autosave_suspended.return_value = False
        context.load_project.return_value = True
        context.project_manager = Mock(last_error="")
        controller = ProjectController(window=window, app_context=context)

        with patch(
            "studio.controllers.project_controller.QFileDialog.getExistingDirectory",
            return_value="/tmp/project-b",
        ):
            ok = controller.load_project()

        self.assertTrue(ok)
        context.rewire_autosave_editors.assert_called_once_with()
        context.schedule_autosave.assert_called_once_with(250)
        context.show_status.assert_called_once_with(
            "Project loaded from: /tmp/project-b",
            5000,
        )

    def test_import_project_archive_failure_reports_error_and_restores_autosave_state(self):
        window = QWidget()
        context = Mock()
        context.get_autosave_suspended.return_value = False
        context.import_project_archive.return_value = False
        context.project_manager = Mock(last_error="invalid archive")
        controller = ProjectController(window=window, app_context=context)

        with (
            patch(
                "studio.controllers.project_controller.QFileDialog.getOpenFileName",
                return_value=("/tmp/project-bad.d2c", "draft2craift Project (*.d2c)"),
            ),
            patch("studio.controllers.project_controller.QMessageBox.warning") as warning,
        ):
            ok = controller.import_project_archive()

        self.assertFalse(ok)
        self.assertEqual(
            context.set_autosave_suspended.call_args_list,
            [call(True), call(False)],
        )
        context.rewire_autosave_editors.assert_not_called()
        context.schedule_autosave.assert_not_called()
        context.show_status.assert_called_with("Project import failed.", 6000)
        warning.assert_called_once()

    def test_import_project_archive_success_rewires_editors_and_schedules_autosave(self):
        window = QWidget()
        context = Mock()
        context.get_autosave_suspended.return_value = False
        context.import_project_archive.return_value = True
        context.project_manager = Mock(last_error="")
        controller = ProjectController(window=window, app_context=context)

        with patch(
            "studio.controllers.project_controller.QFileDialog.getOpenFileName",
            return_value=("/tmp/project-in.d2c", "draft2craift Project (*.d2c)"),
        ):
            ok = controller.import_project_archive()

        self.assertTrue(ok)
        context.rewire_autosave_editors.assert_called_once_with()
        context.schedule_autosave.assert_called_once_with(250)
        context.show_status.assert_called_once_with(
            "Project imported from: /tmp/project-in.d2c",
            5000,
        )


if __name__ == "__main__":
    unittest.main()
