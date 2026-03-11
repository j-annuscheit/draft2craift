"""Shared modeless-window manager for long-lived app dialogs."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QDialog, QWidget


class DialogWindowManager(QObject):
    """Keeps long-lived dialogs singleton and non-modal across the app."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._dialogs: dict[str, QDialog] = {}

    def get(self, key: str) -> QDialog | None:
        return self._dialogs.get(str(key or "").strip())

    def show_dialog(
        self,
        key: str,
        factory: Callable[[], QDialog],
        *,
        on_accept: Callable[[QDialog], None] | None = None,
        on_reopen: Callable[[QDialog], None] | None = None,
    ) -> QDialog:
        dialog_key = str(key or "").strip()
        if not dialog_key:
            raise ValueError("Dialog key must not be empty.")

        existing = self._dialogs.get(dialog_key)
        if existing is not None:
            if callable(on_reopen):
                on_reopen(existing)
            self._focus(existing)
            return existing

        dialog = factory()
        if not isinstance(dialog, QDialog):
            raise TypeError("Dialog factory must return a QDialog instance.")

        self._prepare(dialog)
        self._dialogs[dialog_key] = dialog
        dialog.destroyed.connect(
            lambda *_args, dlg_key=dialog_key: self._dialogs.pop(dlg_key, None)
        )
        if callable(on_accept):
            dialog.accepted.connect(lambda dlg=dialog: on_accept(dlg))
        self._focus(dialog)
        return dialog

    def close_all(self) -> None:
        for dialog in list(self._dialogs.values()):
            try:
                dialog.close()
            except Exception:
                pass

    @staticmethod
    def _prepare(dialog: QDialog) -> None:
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    @staticmethod
    def _focus(dialog: QDialog) -> None:
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()


def find_dialog_manager(widget: object) -> DialogWindowManager | None:
    current = widget
    while current is not None:
        manager = getattr(current, "dialog_manager", None)
        if isinstance(manager, DialogWindowManager):
            return manager
        parent_fn = getattr(current, "parent", None)
        current = parent_fn() if callable(parent_fn) else None
    return None
