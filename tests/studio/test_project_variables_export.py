from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from PySide6.QtWidgets import QWidget

from studio.canvas.exporting import ExportOptions
from studio.canvas.file_actions import CanvasFileActions


pytestmark = pytest.mark.usefixtures("qt_app")


class _StatusBarStub:
    def __init__(self) -> None:
        self.messages: list[tuple[str, int]] = []

    def showMessage(self, message: str, timeout: int = 0) -> None:
        self.messages.append((str(message), int(timeout)))


class _ParentStub(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._status_bar = _StatusBarStub()
        self._project_variables: dict[str, str] = {}
        self.user_mode = "easy_eng"

    def statusBar(self) -> _StatusBarStub:
        return self._status_bar

    def get_project_variables(self) -> dict[str, str]:
        return dict(self._project_variables)

    def set_project_variables(self, variables: dict[str, str]) -> None:
        self._project_variables = dict(variables or {})


def test_export_replaces_project_variables_before_pdf_write(tmp_path):
    parent = _ParentStub()
    parent.set_project_variables({"Applicant Name": "Alice"})

    panel = QWidget()
    panel.editor = Mock()
    panel.editor.toPlainText.return_value = "Applicant: ${applicant_name}"
    panel.file_path = ""

    tabs = Mock()
    tabs.tab_widget = Mock()
    tabs.tab_widget.count.return_value = 0

    actions = CanvasFileActions(parent=parent, tabs=tabs)
    options = ExportOptions(output_format="pdf")

    with (
        patch.object(actions, "_ask_export_options", return_value=options),
        patch(
            "studio.canvas.file_actions.QFileDialog.getSaveFileName",
            return_value=(str(tmp_path / "out.pdf"), "PDF (*.pdf)"),
        ),
        patch("studio.canvas.file_actions.write_pdf") as write_pdf,
    ):
        ok = actions.export_specific_panel(
            panel,
            default_format="pdf",
            panel_scope="draft",
            tab_name="Draft A",
        )

    assert ok is True
    write_pdf.assert_called_once()
    assert write_pdf.call_args.args[0] == "Applicant: Alice"


def test_export_keeps_unknown_variables_and_shows_mild_status_warning(tmp_path):
    parent = _ParentStub()
    parent.set_project_variables({"known": "yes"})

    panel = QWidget()
    panel.editor = Mock()
    panel.editor.toPlainText.return_value = "Known ${known}, unknown ${missing}"
    panel.file_path = ""

    tabs = Mock()
    tabs.tab_widget = Mock()
    tabs.tab_widget.count.return_value = 0

    actions = CanvasFileActions(parent=parent, tabs=tabs)
    options = ExportOptions(output_format="pdf")

    with (
        patch.object(actions, "_ask_export_options", return_value=options),
        patch(
            "studio.canvas.file_actions.QFileDialog.getSaveFileName",
            return_value=(str(tmp_path / "out.pdf"), "PDF (*.pdf)"),
        ),
        patch("studio.canvas.file_actions.write_pdf") as write_pdf,
    ):
        ok = actions.export_specific_panel(
            panel,
            default_format="pdf",
            panel_scope="draft",
            tab_name="Draft A",
        )

    assert ok is True
    write_pdf.assert_called_once()
    assert write_pdf.call_args.args[0] == "Known yes, unknown ${missing}"
    assert any("missing" in message for message, _timeout in parent.statusBar().messages)
