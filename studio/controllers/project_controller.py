"""Project save/load coordination extracted from MainWindow."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QWidget

from shared.services.project.project_archive import ensure_archive_extension

if TYPE_CHECKING:
    from studio.app_context import AppContext


class ProjectController:
    """Coordinates project dialogs with autosave/runtime hooks."""

    def __init__(
        self,
        *,
        window: QWidget,
        app_context: AppContext,
    ):
        self._window = window
        self._context = app_context

    def save_project(self) -> bool:
        folder = QFileDialog.getExistingDirectory(
            self._window,
            "Save Project — choose or create a folder",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return False
        self._context.flush_autosave_pending_preview_edits()
        if not self._context.save_project(folder):
            self._show_project_error(
                "Save Project Failed",
                action="save",
                path=folder,
                location_label="Folder",
            )
            return False
        self._context.show_status(f"Project saved to: {folder}", 5000)
        self._context.schedule_autosave(250)
        return True

    def export_project_archive(self) -> bool:
        archive_path, _filter = QFileDialog.getSaveFileName(
            self._window,
            "Export Project (.d2c)",
            "",
            "draft2craift Project (*.d2c)",
        )
        if not archive_path:
            return False
        archive_path = str(ensure_archive_extension(archive_path))
        self._context.flush_autosave_pending_preview_edits()
        if not self._context.export_project_archive(archive_path):
            self._show_project_error(
                "Export Project Failed",
                action="export",
                path=archive_path,
                location_label="File",
            )
            return False
        self._context.show_status(f"Project exported to: {archive_path}", 5000)
        self._context.schedule_autosave(250)
        return True

    def load_project(self) -> bool:
        folder = QFileDialog.getExistingDirectory(
            self._window,
            "Load Project — select project folder",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return False

        loaded, load_exception = self._run_load_with_autosave_guard(
            lambda: bool(self._context.load_project(folder))
        )
        if not loaded:
            self._show_project_error(
                "Load Project Failed",
                action="load",
                path=folder,
                location_label="Folder",
                exception=load_exception,
            )
            return False
        self._context.rewire_autosave_editors()
        self._context.schedule_autosave(250)
        self._context.show_status(f"Project loaded from: {folder}", 5000)
        return True

    def import_project_archive(self) -> bool:
        archive_path, _filter = QFileDialog.getOpenFileName(
            self._window,
            "Import Project (.d2c)",
            "",
            "draft2craift Project (*.d2c);;ZIP Archive (*.zip);;All Files (*)",
        )
        if not archive_path:
            return False

        loaded, load_exception = self._run_load_with_autosave_guard(
            lambda: bool(self._context.import_project_archive(archive_path))
        )
        if not loaded:
            self._show_project_error(
                "Import Project Failed",
                action="import",
                path=archive_path,
                location_label="File",
                exception=load_exception,
            )
            return False
        self._context.rewire_autosave_editors()
        self._context.schedule_autosave(250)
        self._context.show_status(f"Project imported from: {archive_path}", 5000)
        return True

    def open_project_variables_dialog(self) -> bool:
        from studio.project.variables_dialog import ProjectVariablesDialog

        getter = getattr(self._window, "get_project_variables", None)
        current_variables = getter() if callable(getter) else {}
        dialog = ProjectVariablesDialog(
            variables=current_variables,
            user_mode=self._context.get_user_mode(),
            parent=self._window,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        setter = getattr(self._window, "set_project_variables", None)
        if callable(setter):
            setter(dialog.variables(), notify=False)
        self._context.show_status("Project variables updated.", 3500)
        self._context.schedule_autosave(250)
        return True

    def _run_load_with_autosave_guard(
        self,
        load_action: Callable[[], bool],
    ) -> tuple[bool, Exception | None]:
        previous_suspended = bool(self._context.get_autosave_suspended())
        self._context.set_autosave_suspended(True)
        load_exception: Exception | None = None
        try:
            loaded = bool(load_action())
        except Exception as exc:  # defensive: keep UI feedback path consistent
            loaded = False
            load_exception = exc
        finally:
            self._context.set_autosave_suspended(previous_suspended)
        return loaded, load_exception

    def _show_project_error(
        self,
        title: str,
        *,
        action: str,
        path: str,
        location_label: str = "Path",
        exception: Exception | None = None,
    ) -> None:
        message = str(getattr(self._context.project_manager, "last_error", "") or "").strip()
        if not message:
            message = (
                f"Could not {action} project.\n"
                f"{location_label}: {path}"
            )
            if exception is not None:
                message = f"{message}\nReason: {exception}"
        logger = getattr(self._context, "app_logger", None)
        if logger is not None and hasattr(logger, "error"):
            logger.error("SYS", message)
        self._context.show_status(f"Project {action} failed.", 6000)
        QMessageBox.warning(self._window, title, message)
