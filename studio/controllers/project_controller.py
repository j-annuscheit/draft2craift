"""Project save/load coordination extracted from MainWindow."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

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
                folder=folder,
            )
            return False
        self._context.show_status(f"Project saved to: {folder}", 5000)
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

        previous_suspended = bool(self._context.get_autosave_suspended())
        self._context.set_autosave_suspended(True)
        load_exception: Exception | None = None
        try:
            loaded = bool(self._context.load_project(folder))
        except Exception as exc:  # defensive: keep UI feedback path consistent
            loaded = False
            load_exception = exc
        finally:
            self._context.set_autosave_suspended(previous_suspended)
        if not loaded:
            self._show_project_error(
                "Load Project Failed",
                action="load",
                folder=folder,
                exception=load_exception,
            )
            return False
        self._context.rewire_autosave_editors()
        self._context.schedule_autosave(250)
        self._context.show_status(f"Project loaded from: {folder}", 5000)
        return True

    def _show_project_error(
        self,
        title: str,
        *,
        action: str,
        folder: str,
        exception: Exception | None = None,
    ) -> None:
        message = str(getattr(self._context.project_manager, "last_error", "") or "").strip()
        if not message:
            message = (
                f"Could not {action} project.\n"
                f"Folder: {folder}"
            )
            if exception is not None:
                message = f"{message}\nReason: {exception}"
        logger = getattr(self._context, "app_logger", None)
        if logger is not None and hasattr(logger, "error"):
            logger.error("SYS", message)
        self._context.show_status(f"Project {action} failed.", 6000)
        QMessageBox.warning(self._window, title, message)
