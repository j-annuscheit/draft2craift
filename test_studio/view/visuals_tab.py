"""Visual analytics tab for Test Studio."""
from __future__ import annotations

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QStackedBarSeries,
    QValueAxis,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHeaderView, QLabel, QSplitter, QTableWidget, QVBoxLayout, QWidget

from test_studio.components.metrics import (
    aggregate_labels,
    failure_count,
    set_numeric_item,
    set_text_item,
    short_name,
)
from test_studio.models import LabelStat, RunEntry


class VisualsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.run_metric_chart = self._prepare_chart_view(QChartView())
        self.failure_chart = self._prepare_chart_view(QChartView())
        self.label_chart = self._prepare_chart_view(QChartView())
        self.strength_table = self._new_insight_table()
        self.weakness_table = self._new_insight_table()

        layout = QVBoxLayout(self)
        chart_split = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(chart_split, 1)

        top_row = QSplitter(Qt.Orientation.Horizontal)
        top_row.addWidget(self.run_metric_chart)
        top_row.addWidget(self.failure_chart)
        top_row.setSizes([500, 500])
        chart_split.addWidget(top_row)

        bottom_row = QSplitter(Qt.Orientation.Horizontal)
        bottom_row.addWidget(self.label_chart)

        insight_wrap = QWidget()
        insight_layout = QVBoxLayout(insight_wrap)
        insight_layout.setContentsMargins(0, 0, 0, 0)
        insight_layout.setSpacing(6)
        insight_layout.addWidget(QLabel("Top labels (works)"))
        insight_layout.addWidget(self.strength_table, 1)
        insight_layout.addWidget(QLabel("Weak labels (needs work)"))
        insight_layout.addWidget(self.weakness_table, 1)
        bottom_row.addWidget(insight_wrap)
        bottom_row.setSizes([540, 440])

        chart_split.addWidget(bottom_row)
        chart_split.setSizes([360, 420])

    def refresh(self, runs_scope: list[RunEntry]) -> None:
        self._refresh_run_metric_chart(runs_scope)
        self._refresh_failure_chart(runs_scope)
        self._refresh_label_chart(runs_scope)
        self._refresh_strength_weakness_tables(runs_scope)

    @staticmethod
    def _new_insight_table() -> QTableWidget:
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Label", "Cases", "Primary", "Fail%"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setSortingEnabled(True)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        return table

    def _prepare_chart_view(self, view: QChartView) -> QChartView:
        view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        view.setMinimumHeight(220)
        self._set_empty_chart(view, "Waiting for data", "Select runs to populate chart")
        return view

    @staticmethod
    def _set_empty_chart(view: QChartView, title: str, message: str) -> None:
        chart = QChart()
        chart.setTitle(f"{title}\n{message}")
        chart.legend().hide()
        chart.setBackgroundVisible(False)
        view.setChart(chart)

    def _refresh_run_metric_chart(self, runs_scope: list[RunEntry]) -> None:
        runs = runs_scope[:10]
        if not runs:
            self._set_empty_chart(self.run_metric_chart, "Run Scoreboard", "No runs in current scope")
            return

        categories = [short_name(run.run_name, 16) for run in runs]
        macro_set = QBarSet("Primary")
        macro_set.setColor(QColor("#89B4FA"))
        macro_set.append([run.macro_f1 for run in runs])

        hit_set = QBarSet("Structure")
        hit_set.setColor(QColor("#F9E2AF"))
        hit_set.append([run.hit_at_k for run in runs])

        map_set = QBarSet("Secondary")
        map_set.setColor(QColor("#A6E3A1"))
        map_set.append([run.map_value for run in runs])

        series = QBarSeries()
        series.append(macro_set)
        series.append(hit_set)
        series.append(map_set)

        chart = QChart()
        chart.setTitle("Run Scoreboard: primary vs structure vs secondary")
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.setBackgroundVisible(False)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_y = QValueAxis()
        axis_y.setRange(0.0, 1.0)
        axis_y.setLabelFormat("%.2f")

        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.legend().setVisible(True)

        self.run_metric_chart.setChart(chart)

    def _refresh_failure_chart(self, runs_scope: list[RunEntry]) -> None:
        runs = runs_scope[:12]
        if not runs:
            self._set_empty_chart(self.failure_chart, "Failure Pressure", "No runs in current scope")
            return

        categories = [short_name(run.run_name, 16) for run in runs]

        fail_set = QBarSet("Failed cases")
        fail_set.setColor(QColor("#F38BA8"))
        fail_set.append([float(failure_count(run)) for run in runs])

        success_set = QBarSet("Passing cases")
        success_set.setColor(QColor("#94E2D5"))
        success_set.append([float(max(0, run.cases_count - failure_count(run))) for run in runs])

        series = QStackedBarSeries()
        series.append(success_set)
        series.append(fail_set)

        max_cases = max((run.cases_count for run in runs), default=1)
        chart = QChart()
        chart.setTitle("Failure Pressure: failing-case share per run")
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.setBackgroundVisible(False)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_y = QValueAxis()
        axis_y.setRange(0.0, float(max_cases))
        axis_y.setLabelFormat("%.0f")

        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.legend().setVisible(True)

        self.failure_chart.setChart(chart)

    def _refresh_label_chart(self, runs_scope: list[RunEntry]) -> None:
        stats = aggregate_labels(case for run in runs_scope for case in run.cases)
        if not stats:
            self._set_empty_chart(self.label_chart, "Label Intelligence", "No labeled cases in current scope")
            return

        top = sorted(stats, key=lambda s: s.macro_f1, reverse=True)[:6]
        weak = sorted(stats, key=lambda s: (s.macro_f1, -s.failure_rate))[:6]

        categories: list[str] = []
        top_values: dict[str, float] = {}
        weak_values: dict[str, float] = {}

        for item in top:
            if item.label not in categories:
                categories.append(item.label)
            top_values[item.label] = item.macro_f1

        for item in weak:
            if item.label not in categories:
                categories.append(item.label)
            weak_values[item.label] = item.macro_f1

        top_set = QBarSet("Strong labels")
        top_set.setColor(QColor("#A6E3A1"))
        top_set.append([float(top_values.get(label, 0.0)) for label in categories])

        weak_set = QBarSet("Weak labels")
        weak_set.setColor(QColor("#F38BA8"))
        weak_set.append([float(weak_values.get(label, 0.0)) for label in categories])

        series = QBarSeries()
        series.append(top_set)
        series.append(weak_set)

        chart = QChart()
        chart.setTitle("Label Intelligence: what works vs what breaks")
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.setBackgroundVisible(False)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append([short_name(label, 14) for label in categories])
        axis_y = QValueAxis()
        axis_y.setRange(0.0, 1.0)
        axis_y.setLabelFormat("%.2f")

        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.legend().setVisible(True)

        self.label_chart.setChart(chart)

    def _refresh_strength_weakness_tables(self, runs_scope: list[RunEntry]) -> None:
        stats = aggregate_labels(case for run in runs_scope for case in run.cases)
        strengths = sorted(stats, key=lambda s: (s.macro_f1, -s.failure_rate), reverse=True)[:8]
        weaknesses = sorted(stats, key=lambda s: (s.macro_f1, -s.failure_rate))[:8]

        self._fill_insight_table(self.strength_table, strengths)
        self._fill_insight_table(self.weakness_table, weaknesses)

    @staticmethod
    def _fill_insight_table(table: QTableWidget, rows: list[LabelStat]) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for row_idx, stat in enumerate(rows):
            table.insertRow(row_idx)
            set_text_item(table, row_idx, 0, stat.label)
            set_text_item(table, row_idx, 1, str(stat.cases))
            set_numeric_item(table, row_idx, 2, stat.macro_f1, heatmap=True)
            set_numeric_item(table, row_idx, 3, stat.failure_rate, heatmap=True)
        table.setSortingEnabled(True)
