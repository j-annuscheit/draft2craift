from __future__ import annotations

from PySide6.QtWidgets import QDialog, QWidget

from studio.dialogs.window_manager import DialogWindowManager, find_dialog_manager


def test_show_dialog_reuses_existing_instance(qt_app) -> None:
    parent = QWidget()
    manager = DialogWindowManager(parent)
    created: list[QDialog] = []

    def _factory() -> QDialog:
        dialog = QDialog(parent)
        created.append(dialog)
        return dialog

    first = manager.show_dialog("sample", _factory)
    second = manager.show_dialog("sample", _factory)
    qt_app.processEvents()

    assert first is second
    assert created == [first]

    first.close()
    qt_app.processEvents()


def test_show_dialog_runs_accept_callback(qt_app) -> None:
    parent = QWidget()
    manager = DialogWindowManager(parent)
    accepted: list[QDialog] = []

    dialog = manager.show_dialog(
        "accept-test",
        lambda: QDialog(parent),
        on_accept=lambda dlg: accepted.append(dlg),
    )
    dialog.accept()
    qt_app.processEvents()

    assert accepted == [dialog]


def test_find_dialog_manager_walks_parent_chain(qt_app) -> None:
    parent = QWidget()
    manager = DialogWindowManager(parent)
    setattr(parent, "dialog_manager", manager)
    child = QWidget(parent)

    assert find_dialog_manager(child) is manager
