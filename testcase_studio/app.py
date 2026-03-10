"""Testcase Studio main dialog and entry point."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from testcase_studio.case_dialog import CaseDraftDialog
from testcase_studio.controller import TestcaseStudioController
from testcase_studio.draft_builder import (
    build_case_draft_from_event,
    event_payload,
    extract_observed_output,
    extract_prompt_from_event,
    manual_case_template,
)
from testcase_studio.feedback_formatter import format_feedback_fields
from testcase_studio.suite_schema import SUITE_BY_ID
from testcase_studio.text_utils import coerce_int_list, safe_str, truncate
from testcase_studio.ui_style import BLUE, GREEN, MUTED, OVERLAY, PURPLE, RED, STYLE, SURFACE, YELLOW
from testcase_studio.views import CasesTabView, FeedbackTabView


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text or ""))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class TestcaseStudio(QDialog):
    def __init__(self, storage_dir: str | Path | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Testcase Studio")
        self.resize(1340, 860)
        self.setStyleSheet(STYLE)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)

        self._controller = TestcaseStudioController(storage_dir)
        self._selected_event_id = ""
        self._selected_case_no = 0

        self._build_ui()
        self._connect_signals()
        self._reload_all()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(42)
        header.setStyleSheet(f"background: {SURFACE}; border-bottom: 1px solid {OVERLAY};")
        hdr = QHBoxLayout(header)
        hdr.setContentsMargins(12, 4, 12, 4)
        title = QLabel("Testcase Studio")
        title.setStyleSheet(f"color: {PURPLE}; font-weight: bold; font-size: 14px;")
        self._path_lbl = QLabel(str(self._controller.storage_dir))
        self._path_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        reload_button = QWidget()
        reload_layout = QHBoxLayout(reload_button)
        reload_layout.setContentsMargins(0, 0, 0, 0)
        self._btn_reload = QPushButton("Aktualisieren")
        self._btn_close = QPushButton("Schliessen")
        reload_layout.addWidget(self._btn_reload)
        reload_layout.addWidget(self._btn_close)

        hdr.addWidget(title)
        hdr.addWidget(self._path_lbl)
        hdr.addStretch()
        hdr.addWidget(reload_button)
        root.addWidget(header)

        self._tabs = QTabWidget()
        self.feedback_view = FeedbackTabView()
        self.cases_view = CasesTabView(str(self._controller.storage_dir / "generated"))
        self._tabs.addTab(self.feedback_view, "Feedback")
        self._tabs.addTab(self.cases_view, "Testcases")
        root.addWidget(self._tabs, 1)

        status = QWidget()
        status.setFixedHeight(24)
        status.setStyleSheet(f"background: {SURFACE}; border-top: 1px solid {OVERLAY};")
        bar = QHBoxLayout(status)
        bar.setContentsMargins(12, 2, 12, 2)
        self._status_lbl = QLabel("Bereit")
        self._status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 10px;")
        bar.addWidget(self._status_lbl)
        bar.addStretch()
        root.addWidget(status)

    def _connect_signals(self) -> None:
        self._btn_reload.clicked.connect(self._reload_all)
        self._btn_close.clicked.connect(self.reject)

        self.feedback_view.filter_edit.textChanged.connect(self._refresh_feedback_table)
        self.feedback_view.sent_combo.currentIndexChanged.connect(self._refresh_feedback_table)
        self.feedback_view.target_suite_combo.currentIndexChanged.connect(self._refresh_feedback_suite_hint)
        self.feedback_view.table.itemSelectionChanged.connect(self._on_feedback_selected)
        self.feedback_view.create_btn.clicked.connect(self._create_case_from_feedback)
        self.feedback_view.delete_btn.clicked.connect(self._delete_selected_feedback)

        self.cases_view.filter_edit.textChanged.connect(self._refresh_cases_table)
        self.cases_view.suite_combo.currentIndexChanged.connect(self._refresh_cases_table)
        self.cases_view.status_combo.currentIndexChanged.connect(self._refresh_cases_table)
        self.cases_view.table.itemSelectionChanged.connect(self._on_case_selected)
        self.cases_view.new_btn.clicked.connect(self._new_manual_case)
        self.cases_view.edit_btn.clicked.connect(self._edit_selected_case)
        self.cases_view.delete_btn.clicked.connect(self._delete_selected_case)
        self.cases_view.export_pick_btn.clicked.connect(self._pick_export_dir)
        self.cases_view.export_btn.clicked.connect(self._export_suites)

    def _status(self, text: str) -> None:
        self._status_lbl.setText(text)

    def _reload_all(self) -> None:
        self._controller.reload()
        self._refresh_feedback_suite_hint()
        self._refresh_feedback_table()
        self._refresh_cases_table()
        self._status(f"Geladen: {len(self._controller.events)} Feedback-Events, {len(self._controller.cases)} Testcases")

    def _refresh_feedback_suite_hint(self) -> None:
        suite_id = str(self.feedback_view.target_suite_combo.currentData() or "")
        spec = SUITE_BY_ID.get(suite_id)
        self.feedback_view.hint_lbl.setText(spec.description if spec else "")

    def _refresh_feedback_table(self) -> None:
        visible = self._controller.filtered_events(
            self.feedback_view.filter_edit.text(),
            str(self.feedback_view.sent_combo.currentData() or "all"),
        )
        case_index = {int(case.get("case_no", 0) or 0): case for case in self._controller.cases}

        table = self.feedback_view.table
        table.setRowCount(len(visible))
        for row, event in enumerate(visible):
            event_id = safe_str(event.get("event_id"))
            linked_nos = [no for no in coerce_int_list(event.get("linked_testcases")) if no > 0]
            linked_titles = [safe_str(case_index[no].get("case_id")) for no in linked_nos[:3] if no in case_index]
            linked_text = str(len(linked_nos)) + (f" ({', '.join(linked_titles)})" if linked_titles else "")
            values = [
                safe_str(event.get("timestamp"))[:19].replace("T", " "),
                event_id,
                safe_str(event.get("use_case")),
                safe_str(event.get("sentiment")),
                linked_text,
                truncate(safe_str(event.get("note")), 80),
            ]
            for col, value in enumerate(values):
                item = _cell(value)
                item.setData(Qt.ItemDataRole.UserRole, event_id)
                if col == 3:
                    color = RED if value == "negative" else GREEN if value == "positive" else MUTED
                    item.setForeground(QColor(color))
                table.setItem(row, col, item)

        for col in range(5):
            table.resizeColumnToContents(col)

    def _refresh_cases_table(self) -> None:
        visible = self._controller.filtered_cases(
            self.cases_view.filter_edit.text(),
            str(self.cases_view.suite_combo.currentData() or "all"),
            str(self.cases_view.status_combo.currentData() or "all"),
        )

        table = self.cases_view.table
        table.setRowCount(len(visible))
        for row, entry in enumerate(visible):
            case_no = int(entry.get("case_no", 0) or 0)
            suite_id = safe_str(entry.get("suite_type"))
            suite_label = SUITE_BY_ID.get(suite_id).label if suite_id in SUITE_BY_ID else suite_id
            status = "accepted" if bool(entry.get("accepted", False)) else "draft"
            values = [
                str(case_no),
                safe_str(entry.get("case_id")),
                suite_label,
                status,
                safe_str(entry.get("source_event_id")),
                safe_str(entry.get("updated_at")),
                truncate(safe_str(entry.get("title")), 140),
                "",
            ]
            for col, value in enumerate(values):
                item = _cell(value)
                item.setData(Qt.ItemDataRole.UserRole, case_no)
                if col == 3:
                    item.setForeground(QColor(GREEN if status == "accepted" else YELLOW))
                table.setItem(row, col, item)
        for col in range(6):
            table.resizeColumnToContents(col)

    def _on_feedback_selected(self) -> None:
        items = self.feedback_view.table.selectedItems()
        if not items:
            return
        event_id = safe_str(items[0].data(Qt.ItemDataRole.UserRole))
        event = self._controller.find_event(event_id)
        if event is None:
            return
        self._selected_event_id = event_id

        self.feedback_view.meta_lbl.setText(
            f"{event_id} | {safe_str(event.get('use_case'))} | {safe_str(event.get('sentiment'))} | {safe_str(event.get('timestamp'))}"
        )
        self.feedback_view.prompt_lbl.setText(f"Prompt: {truncate(extract_prompt_from_event(event), 220) or '-'}")
        self.feedback_view.observed_lbl.setText(f"Observed: {truncate(extract_observed_output(event), 220) or '-'}")
        self.feedback_view.payload_edit.setPlainText(json.dumps(event_payload(event), ensure_ascii=False, indent=2))
        self.feedback_view.fields_edit.setPlainText(format_feedback_fields(event))

        lines: list[str] = []
        for case_no in coerce_int_list(event.get("linked_testcases")):
            case = self._controller.find_case(case_no)
            if case is None:
                lines.append(f"#{case_no}: (nicht gefunden)")
            else:
                lines.append(f"#{case_no} {safe_str(case.get('case_id'))} [{safe_str(case.get('suite_type'))}] {'accepted' if case.get('accepted') else 'draft'}")
        self.feedback_view.linked_cases_edit.setPlainText("\n".join(lines) if lines else "(keine)")

    def _on_case_selected(self) -> None:
        items = self.cases_view.table.selectedItems()
        if not items:
            return
        case_no = int(items[0].data(Qt.ItemDataRole.UserRole) or 0)
        case = self._controller.find_case(case_no)
        if case is None:
            return
        self._selected_case_no = case_no
        self.cases_view.meta_lbl.setText(
            f"#{case_no} {safe_str(case.get('case_id'))} [{safe_str(case.get('suite_type'))}] {'accepted' if case.get('accepted') else 'draft'}"
        )
        self.cases_view.json_preview.setPlainText(json.dumps(case.get("case", {}), ensure_ascii=False, indent=2))

    def _open_case_editor(self, *, suite_id: str, payload: dict[str, Any], accepted: bool, title: str):
        dialog = CaseDraftDialog(
            suite_id=suite_id,
            payload=payload,
            accepted_default=accepted,
            title=title,
            existing_labels=self._controller.known_labels(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.suite_id(), dialog.payload(), dialog.accepted()

    def _create_case_from_feedback(self) -> None:
        event = self._controller.find_event(self._selected_event_id)
        if event is None:
            QMessageBox.information(self, "Kein Feedback", "Bitte zuerst ein Feedback-Event auswaehlen.")
            return
        suite_id = str(self.feedback_view.target_suite_combo.currentData() or "")
        result = self._open_case_editor(
            suite_id=suite_id,
            payload=build_case_draft_from_event(event, suite_id),
            accepted=True,
            title=f"Testcase aus Feedback {self._selected_event_id}",
        )
        if result is None:
            return
        final_suite_id, payload, accepted = result
        entry = self._controller.create_case_from_feedback(event_id=self._selected_event_id, suite_id=final_suite_id, payload=payload, accepted=accepted)
        self._reload_all()
        self._selected_case_no = int(entry.get("case_no", 0) or 0)
        self._tabs.setCurrentIndex(1)
        self._status(f"Testcase erstellt: #{entry.get('case_no')} ({entry.get('case_id')})")

    def _new_manual_case(self) -> None:
        suite_id = str(self.cases_view.new_suite_combo.currentData() or "rag")
        result = self._open_case_editor(suite_id=suite_id, payload=manual_case_template(suite_id), accepted=False, title="Neuer manueller Testcase")
        if result is None:
            return
        final_suite_id, payload, accepted = result
        entry = self._controller.create_manual_case(suite_id=final_suite_id, payload=payload, accepted=accepted)
        self._selected_case_no = int(entry.get("case_no", 0) or 0)
        self._reload_all()
        self._status(f"Manueller Testcase erstellt: #{entry.get('case_no')}")

    def _edit_selected_case(self) -> None:
        case = self._controller.find_case(self._selected_case_no)
        if case is None:
            QMessageBox.information(self, "Kein Testcase", "Bitte zuerst einen Testcase auswaehlen.")
            return
        result = self._open_case_editor(
            suite_id=safe_str(case.get("suite_type")),
            payload=dict(case.get("case") or {}),
            accepted=bool(case.get("accepted", False)),
            title=f"Testcase bearbeiten #{case.get('case_no', 0)}",
        )
        if result is None:
            return
        suite_id, payload, accepted = result
        updated = self._controller.update_case(case_no=int(case.get("case_no", 0) or 0), suite_id=suite_id, payload=payload, accepted=accepted)
        if updated:
            self._reload_all()
            self._status(f"Testcase aktualisiert: #{updated.get('case_no')}")

    def _delete_selected_feedback(self) -> None:
        event_id = self._selected_event_id
        if not event_id:
            return
        answer = QMessageBox.question(self, "Feedback loeschen", f"Feedback {event_id} wirklich loeschen?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes and self._controller.delete_feedback(event_id):
            self._selected_event_id = ""
            self._reload_all()
            self._status(f"Feedback geloescht: {event_id}")

    def _delete_selected_case(self) -> None:
        case = self._controller.find_case(self._selected_case_no)
        if case is None:
            return
        case_no = int(case.get("case_no", 0) or 0)
        answer = QMessageBox.question(self, "Testcase loeschen", f"Testcase #{case_no} ({safe_str(case.get('case_id'))}) wirklich loeschen?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes and self._controller.delete_case(case_no):
            self._selected_case_no = 0
            self._reload_all()
            self._status(f"Testcase geloescht: #{case_no}")

    def _pick_export_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export-Ordner waehlen", self.cases_view.export_output_edit.text())
        if folder:
            self.cases_view.export_output_edit.setText(folder)

    def _export_suites(self) -> None:
        output_dir = Path(self.cases_view.export_output_edit.text().strip() or str(self._controller.storage_dir / "generated")).expanduser()
        if not output_dir.is_absolute():
            output_dir = (Path.cwd() / output_dir).resolve()
        try:
            summary, written = self._controller.export_suites(
                output_dir=output_dir,
                run_name=self.cases_view.export_run_name_edit.text().strip(),
                include_drafts=bool(self.cases_view.export_include_drafts_cb.isChecked()),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Export", f"Export fehlgeschlagen:\n{exc}")
            return

        lines = [
            f"run_name={summary.get('run_name', '')}",
            f"include_unaccepted={summary.get('include_unaccepted', False)}",
            f"exported_cases={summary.get('exported_cases', 0)}",
            "written:",
        ]
        lines.extend(f"  - {path}" for path in written)
        self.cases_view.export_log.setPlainText("\n".join(lines))
        self._status("Suite-Export abgeschlossen")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Testcase Studio")
    parser.add_argument("--storage-dir", default="runs/feedback", help="Feedback/Testcase Speicherordner (default: runs/feedback)")
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Testcase Studio")
    dialog = TestcaseStudio(storage_dir=args.storage_dir)
    dialog.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.WindowMaximizeButtonHint
        | Qt.WindowType.WindowMinimizeButtonHint
        | Qt.WindowType.WindowCloseButtonHint
    )
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
