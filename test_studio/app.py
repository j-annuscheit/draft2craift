#!/usr/bin/env python3
"""Test Studio dashboard for suite runs, pipeline execution, and run comparison."""
from __future__ import annotations

import argparse
import pathlib
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from test_studio.components.controller import TestStudioController
from test_studio.components.runner import RunnerController
from test_studio.view.cases_tab import CasesTab
from test_studio.view.comparison_tab import ComparisonTab
from test_studio.view.labels_tab import LabelsTab
from test_studio.view.run_table import RunTableView
from test_studio.view.visuals_tab import VisualsTab
from test_studio.view.widgets import MetricCard

_THIS_FILE = pathlib.Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[1]

_STYLE = """
QMainWindow, QDialog { background: #11131A; }
QWidget { color: #CDD6F4; font-family: 'Noto Sans', 'Segoe UI', sans-serif; }
QFrame#MetricCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1A1D2A, stop:1 #141723);
    border: 1px solid #313244;
    border-radius: 10px;
}
QLineEdit, QComboBox {
    background: #181B28;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 5px 8px;
}
QPushButton {
    background: #313244;
    border: none;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 600;
}
QPushButton:hover { background: #45475A; }
QTableWidget {
    background: #171A25;
    gridline-color: #2A2E3D;
    border: 1px solid #2A2E3D;
    border-radius: 8px;
}
QHeaderView::section {
    background: #222638;
    color: #BAC2DE;
    border: none;
    border-right: 1px solid #2A2E3D;
    border-bottom: 1px solid #2A2E3D;
    padding: 6px;
    font-size: 11px;
}
QTabWidget::pane { border: 1px solid #2A2E3D; border-radius: 8px; }
QTabBar::tab {
    background: #1A1D2A;
    color: #7F849C;
    border: 1px solid #2A2E3D;
    padding: 6px 10px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected { color: #CDD6F4; background: #222638; }
QPlainTextEdit {
    background: #171A25;
    border: 1px solid #2A2E3D;
    border-radius: 8px;
}
"""


class TestStudioDashboard(QMainWindow):
    def __init__(self, root_dir: pathlib.Path):
        super().__init__()
        self.setWindowTitle(
            "Test Studio Dashboard (RAG + PDF + Glossary + Fact-Check + Judge + LLM-Compare)"
        )
        self.resize(1680, 980)
        self.setStyleSheet(_STYLE)

        self._controller = TestStudioController()

        self._root_edit = QLineEdit(str(root_dir))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by run name or suite path…")
        self._type_selector = QComboBox()
        self._type_selector.addItem("All", "all")
        self._type_selector.addItem("RAG", "rag")
        self._type_selector.addItem("PDF", "pdf")
        self._type_selector.addItem("Glossary", "glossary")
        self._type_selector.addItem("Fact-Check", "factcheck")
        self._type_selector.addItem("Judge", "judge")
        self._type_selector.addItem("LLM Compare", "llmcompare")
        self._common_case_cb = QCheckBox("Nur gemeinsame Case-Nummern")
        self._status_lbl = QLabel("")

        self._run_table_widget = QTableWidget(0, 10)
        self._run_table = RunTableView(self._run_table_widget)

        self._visuals_tab = VisualsTab()
        self._comparison_tab = ComparisonTab()
        self._cases_tab = CasesTab()
        self._labels_tab = LabelsTab()

        self._card_loaded = MetricCard("Loaded Runs", "#89B4FA")
        self._card_visible = MetricCard("Visible Runs", "#B4BEFE")
        self._card_selected = MetricCard("Selected Runs", "#CBA6F7")
        self._card_macro = MetricCard("Mean Primary Score", "#A6E3A1")
        self._card_hit = MetricCard("Mean Structure Score", "#F9E2AF")
        self._card_fail = MetricCard("Mean Failure Rate", "#F38BA8")

        self._runner = RunnerController(
            project_root=_PROJECT_ROOT,
            style_sheet=self.styleSheet(),
            on_runs_changed=self.reload_runs,
        )

        self._build_ui()
        self.reload_runs()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        browse_btn = QPushButton("Browse…")
        reload_btn = QPushButton("Reload")
        open_tests_btn = QPushButton("Tests…")
        run_all_toolbar_btn = QPushButton("Run All-Tests")
        toolbar.addWidget(QLabel("Runs root:"))
        toolbar.addWidget(self._root_edit, 1)
        toolbar.addWidget(browse_btn)
        toolbar.addWidget(reload_btn)
        toolbar.addWidget(open_tests_btn)
        toolbar.addWidget(run_all_toolbar_btn)
        layout.addLayout(toolbar)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Run filter:"))
        filter_row.addWidget(self._filter_edit, 1)
        filter_row.addWidget(QLabel("Type:"))
        filter_row.addWidget(self._type_selector)
        filter_row.addWidget(self._common_case_cb)
        layout.addLayout(filter_row)

        self._status_lbl.setStyleSheet("color: #7F849C; font-size: 11px;")
        layout.addWidget(self._status_lbl)

        card_row = QHBoxLayout()
        card_row.setSpacing(8)
        for card in (
            self._card_loaded,
            self._card_visible,
            self._card_selected,
            self._card_macro,
            self._card_hit,
            self._card_fail,
        ):
            card_row.addWidget(card, 1)
        layout.addLayout(card_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._run_table_widget)

        tabs = QTabWidget()
        tabs.addTab(self._visuals_tab, "Visuals")
        tabs.addTab(self._comparison_tab, "Vergleich")
        tabs.addTab(self._cases_tab, "Case View")
        tabs.addTab(self._labels_tab, "Label Analyse")
        splitter.addWidget(tabs)
        splitter.setSizes([620, 1050])
        layout.addWidget(splitter, 1)

        browse_btn.clicked.connect(self._browse_root)
        reload_btn.clicked.connect(self.reload_runs)
        open_tests_btn.clicked.connect(self._runner.open_dialog)
        run_all_toolbar_btn.clicked.connect(self._runner.open_and_run_all)

        self._filter_edit.textChanged.connect(self._apply_filter)
        self._type_selector.currentIndexChanged.connect(self._apply_filter)
        self._common_case_cb.stateChanged.connect(self._refresh_views)
        self._run_table_widget.itemSelectionChanged.connect(self._refresh_views)
        self._labels_tab.connect_refresh(self._refresh_views)

    def _browse_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose runs directory",
            self._root_edit.text(),
        )
        if selected:
            self._root_edit.setText(selected)
            self.reload_runs()

    def reload_runs(self) -> None:
        root = pathlib.Path(self._root_edit.text()).expanduser().resolve()
        self._controller.reload_runs(root)
        self._apply_filter()

    def _apply_filter(self) -> None:
        self._controller.apply_filter(
            self._filter_edit.text(),
            str(self._type_selector.currentData() or "all"),
        )
        self._render_run_table()
        self._refresh_views()

    def _requested_mode(self) -> str:
        return self._controller.requested_type_mode(
            str(self._type_selector.currentData() or "all")
        )

    def _render_run_table(self) -> None:
        mode = self._controller.runs_mode(self._controller.visible_runs)
        if not self._controller.visible_runs:
            mode = self._requested_mode()
        self._run_table.render(self._controller.visible_runs, mode)

    def _selected_runs(self):
        return self._controller.selected_runs_from_paths(self._run_table.selected_paths())

    def _refresh_views(self) -> None:
        selected = self._selected_runs()
        runs_scope = self._controller.runs_for_scope(
            selected,
            self._common_case_cb.isChecked(),
        )

        self._status_lbl.setText(
            self._controller.status_text(
                selected_runs=selected,
                runs_scope=runs_scope,
                requested_type_filter=str(self._type_selector.currentData() or "all"),
                use_common_cases=self._common_case_cb.isChecked(),
            )
        )

        cards = self._controller.cards_text(
            self._controller.all_runs,
            self._controller.visible_runs,
            selected,
            runs_scope,
        )
        self._card_loaded.set_value(*cards["loaded"])
        self._card_visible.set_value(*cards["visible"])
        self._card_selected.set_value(*cards["selected"])
        self._card_macro.set_value(*cards["macro"])
        self._card_hit.set_value(*cards["hit"])
        self._card_fail.set_value(*cards["fail"])

        scoped_mode = self._controller.runs_mode(runs_scope)
        if not runs_scope:
            scoped_mode = self._requested_mode()

        self._visuals_tab.refresh(runs_scope)
        self._comparison_tab.refresh(runs_scope, scoped_mode)
        self._cases_tab.set_runs_scope(runs_scope, self._controller.runs_by_path)

        label_scope = str(self._labels_tab.scope_selector.currentData() or "selected")
        label_runs = selected if label_scope == "selected" and selected else self._controller.visible_runs
        label_mode = self._controller.runs_mode(label_runs)
        if not label_runs:
            label_mode = self._requested_mode()
        self._labels_tab.refresh(
            visible_runs=self._controller.visible_runs,
            selected_runs=selected,
            mode=label_mode,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open Test Studio dashboard for suite run artifacts"
    )
    parser.add_argument(
        "--root",
        default="runs",
        help="Directory scanned recursively for *.summary.json files",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = QApplication(sys.argv)
    window = TestStudioDashboard(pathlib.Path(args.root).expanduser().resolve())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
