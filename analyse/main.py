#!/usr/bin/env python3
"""Agentic Run Analyser — PySide6 viewer for agentic run JSON files.

Usage:
    python main.py [path/to/run.json]
"""

import sys
import json
import math
import re
import tomllib
from pathlib import Path
from typing import Optional, Any

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QGroupBox,
    QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QFileDialog, QPushButton, QLabel, QToolBar, QGraphicsView,
    QGraphicsScene, QHeaderView, QTextEdit, QComboBox,
    QAbstractItemView, QStatusBar, QTabWidget, QCompleter,
    QColorDialog,
)
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QStringListModel
from PySide6.QtGui import (
    QPen, QBrush, QColor, QFont, QPainterPath, QPainter, QPolygonF,
)

# ─── Layout constants ──────────────────────────────────────────────────────────
NODE_W, NODE_H = 185, 56
COL_GAP, ROW_GAP = 84, 38
MARGIN = 28

# ─── Colors ────────────────────────────────────────────────────────────────────
C_GREEN       = QColor("#27ae60")
C_ORANGE      = QColor("#e67e22")
C_RED         = QColor("#c0392b")
C_NODE_BG     = QColor("#f8f9fa")
C_NODE_SEL_BG = QColor("#dceefb")
C_BORDER      = QColor("#ced4da")
C_BORDER_SEL  = QColor("#2980b9")
C_TEXT        = QColor("#212529")
C_SUBDUED     = QColor("#6c757d")


# ─── Data model ────────────────────────────────────────────────────────────────
class RunData:
    def __init__(self, raw: dict):
        self.raw      = raw
        self.run_id   = raw.get("run_id", "")
        self.ok       = raw.get("ok", False)
        self.workflow = raw.get("workflow", {})
        self.profile  = raw.get("profile", {})
        self.policy   = raw.get("policy", {})
        self.wiring   = raw.get("wiring", {})
        self.metrics  = raw.get("metrics", {})
        self.request  = raw.get("request", {})
        self.state    = raw.get("state", {})
        self.trace    = raw.get("trace", [])
        self.errors   = raw.get("errors", [])

    def settings_rows(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        rows.append(("run_id",      self.run_id))
        rows.append(("ok",          "✓ ja" if self.ok else "✗ nein"))
        rows.append(("created_at",  self.raw.get("created_at_utc", "")))
        if self.errors:
            rows.append(("errors", " | ".join(self.errors)))
        for k, v in self.workflow.items():
            rows.append((f"workflow.{k}", str(v)))
        for k, v in self.profile.items():
            val = ", ".join(v) if isinstance(v, list) else str(v)
            rows.append((f"profile.{k}", val))
        for k, v in self.metrics.items():
            val = json.dumps(v) if isinstance(v, dict) else str(v)
            rows.append((f"metrics.{k}", val))
        for k, v in self.policy.items():
            val = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            rows.append((f"policy.{k}", val))
        for k, v in self.wiring.items():
            rows.append((f"wiring.{k}", str(v)))
        return rows

    def cumulative_state(self, up_to: int) -> dict:
        """Accumulated state after trace[up_to] (all changes from step 0 to up_to)."""
        acc: dict = {}
        for i, step in enumerate(self.trace):
            if i > up_to:
                break
            acc.update(step.get("state_after", {}))
        return acc

    def all_state_keys(self) -> list[str]:
        keys: set[str] = set()
        for step in self.trace:
            keys.update(step.get("state_after", {}).keys())
        return sorted(keys)

    def edge_color(self, i: int) -> QColor:
        """Color for the edge FROM trace[i] → trace[i+1].

        Uses the authoritative ``transition.kind`` field when present.
        Falls back to output heuristics for legacy traces without it.

        Green  = normal success (edge condition met, sequential flow)
        Orange = condition not met / explicit jump / max_visits
        Red    = error, stop, budget exceeded, no edge matched
        """
        step       = self.trace[i]
        transition = step.get("transition", {})
        kind       = transition.get("kind", "")

        if kind:
            if kind in ("stop", "error", "budget_exceeded", "no_edge_matched", "terminal"):
                return C_RED
            if kind in ("jump", "max_visits"):
                return C_ORANGE
            if kind == "edge":
                # Custom color from TOML definition takes precedence
                color_str = transition.get("color", "")
                if color_str:
                    try:
                        return QColor(color_str)
                    except Exception:
                        pass
                # Orange when the decisive condition indicates failure
                cond = transition.get("condition", "")
                if "== False" in cond or "== false" in cond or "is False" in cond:
                    return C_ORANGE
                return C_GREEN
            return C_GREEN  # unknown kind → green

        # ── legacy fallback (no transition field) ────────────────────────
        output = step.get("output", {})
        if step.get("status") == "error":
            return C_RED
        if output.get("stop"):
            return C_RED
        if output.get("jump"):
            return C_ORANGE
        val = output.get("value")
        if isinstance(val, dict) and val.get("ok") is False:
            return C_ORANGE
        return C_GREEN


# ─── Settings Table ────────────────────────────────────────────────────────────
class SettingsTable(QTableWidget):
    def __init__(self):
        super().__init__()
        self.setColumnCount(2)
        self.setHorizontalHeaderLabels(["Schlüssel", "Wert"])
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.setFont(QFont("Monospace", 9))

    def load(self, run: RunData):
        rows = run.settings_rows()
        self.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            ki = QTableWidgetItem(k)
            vi = QTableWidgetItem(v)
            ki.setForeground(QBrush(C_SUBDUED))
            self.setItem(r, 0, ki)
            self.setItem(r, 1, vi)
        self.resizeRowsToContents()


# ─── Trace Table ───────────────────────────────────────────────────────────────
_TRACE_COLS = ["#", "step_id", "runner", "status", "ms", "visit",
               "transition", "next_step", "decisive_param",
               "stop", "jump", "→ state", "reason"]


class TraceTable(QTableWidget):
    step_selected = Signal(int)

    def __init__(self):
        super().__init__()
        self.setColumnCount(len(_TRACE_COLS))
        self.setHorizontalHeaderLabels(_TRACE_COLS)
        hh = self.horizontalHeader()
        for c in range(len(_TRACE_COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setFont(QFont("Monospace", 9))
        self.currentCellChanged.connect(
            lambda row, _col, _pr, _pc: self._emit(row)
        )

    def _emit(self, row: int):
        self.step_selected.emit(row)

    def load(self, run: RunData):
        trace = run.trace
        self.setRowCount(len(trace))
        for i, step in enumerate(trace):
            out  = step.get("output", {})
            tr   = step.get("transition", {})
            stop = out.get("stop", False)
            kind = tr.get("kind", "")
            vals = [
                str(i),
                step.get("step_id", ""),
                step.get("runner", ""),
                step.get("status", ""),
                f"{step.get('duration_ms', 0):.1f}",
                str(step.get("visit_index", 1)),
                kind,
                tr.get("next_step", ""),
                tr.get("decisive_param", ""),
                "■" if stop else "",
                out.get("jump", ""),
                out.get("write_to", ""),
                step.get("reason", ""),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if c == 3:   # status
                    item.setForeground(QBrush(C_GREEN if v == "ok" else C_RED))
                elif c == 6 and v:  # transition kind
                    if v in ("stop", "error", "budget_exceeded", "no_edge_matched"):
                        item.setForeground(QBrush(C_RED))
                    elif v in ("jump", "max_visits"):
                        item.setForeground(QBrush(C_ORANGE))
                    else:
                        item.setForeground(QBrush(C_GREEN))
                elif c == 9 and v:  # stop
                    item.setForeground(QBrush(C_RED))
                self.setItem(i, c, item)
        self.resizeColumnsToContents()


# ─── Graph View ────────────────────────────────────────────────────────────────
class GraphView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self._sc = QGraphicsScene()
        self.setScene(self._sc)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._run: Optional[RunData] = None
        self._sel = -1

    def wheelEvent(self, ev):
        f = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)

    def load(self, run: RunData, sel: int = -1):
        self._run = run
        self._sel = sel
        self._rebuild(fit=True)

    def select(self, idx: int):
        if self._sel == idx:
            return
        self._sel = idx
        self._rebuild(fit=False)

    def fit(self):
        self.fitInView(self._sc.sceneRect(), Qt.KeepAspectRatio)

    # ── internal ──

    def _node_rect(self, col: int, row: int) -> QRectF:
        x = MARGIN + col * (NODE_W + COL_GAP)
        y = MARGIN + row * (NODE_H + ROW_GAP)
        return QRectF(x, y, NODE_W, NODE_H)

    def _rebuild(self, fit: bool):
        self._sc.clear()
        run = self._run
        if not run or not run.trace:
            return
        trace = run.trace

        # Column: first appearance order
        col_map: dict[str, int] = {}
        for s in trace:
            sid = s["step_id"]
            if sid not in col_map:
                col_map[sid] = len(col_map)

        # Row assignment: once we drop to a new row, we never go back up.
        # New (never-seen) steps are placed at the current row floor.
        current_floor = 0
        first_row: dict[str, int] = {}
        node_rows: list[int] = []
        for s in trace:
            sid   = s["step_id"]
            visit = s.get("visit_index", 1)
            if visit == 1:
                row = current_floor
                first_row[sid] = current_floor
            else:
                row = first_row.get(sid, 0) + (visit - 1)
                current_floor = max(current_floor, row)
            node_rows.append(row)

        rects: list[QRectF] = [
            self._node_rect(col_map[trace[i]["step_id"]], node_rows[i])
            for i in range(len(trace))
        ]

        # Edges (drawn first, behind nodes)
        for i in range(len(trace) - 1):
            self._draw_edge(rects[i], rects[i + 1], run.edge_color(i))

        # Nodes
        fn_main = QFont("Monospace", 8, QFont.Bold)
        fn_small = QFont("Monospace", 7)

        for i, s in enumerate(trace):
            r      = rects[i]
            is_sel = (i == self._sel)
            bg     = C_NODE_SEL_BG if is_sel else C_NODE_BG
            brd    = C_BORDER_SEL  if is_sel else C_BORDER
            bw     = 2.5           if is_sel else 1.0

            # Background rect
            self._sc.addRect(r, QPen(brd, bw), QBrush(bg))

            # Left status stripe
            sc = C_GREEN if s.get("status") == "ok" else C_RED
            self._sc.addRect(
                QRectF(r.x(), r.y(), 5, r.height()),
                QPen(Qt.NoPen), QBrush(sc),
            )

            # Step ID label
            label = s["step_id"]
            if s.get("visit_index", 1) > 1:
                label += f"  [{s['visit_index']}]"
            t = self._sc.addText(label, fn_main)
            t.setDefaultTextColor(C_TEXT)
            t.setPos(r.x() + 10, r.y() + 5)

            # Runner (truncated, bottom-left)
            runner = s.get("runner", "")
            if runner:
                rs = runner if len(runner) <= 27 else runner[:26] + "…"
                t2 = self._sc.addText(rs, fn_small)
                t2.setDefaultTextColor(C_SUBDUED)
                t2.setPos(r.x() + 10, r.y() + r.height() - 20)

            # Duration (top-right)
            dur = s.get("duration_ms", 0)
            ds  = f"{dur:.0f}ms" if dur >= 1 else f"{dur * 1000:.0f}μs"
            t3  = self._sc.addText(ds, fn_small)
            t3.setDefaultTextColor(C_SUBDUED)
            t3.setPos(r.right() - t3.boundingRect().width() - 6, r.y() + 5)

        self._sc.setSceneRect(
            self._sc.itemsBoundingRect().adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN)
        )
        if fit:
            self.fitInView(self._sc.sceneRect(), Qt.KeepAspectRatio)

    def _draw_edge(self, r1: QRectF, r2: QRectF, color: QColor):
        pen = QPen(color, 2.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)

        p1 = QPointF(r1.right(), r1.center().y())
        p2 = QPointF(r2.left(),  r2.center().y())

        path = QPainterPath()
        forward = r2.left() >= r1.right() - 10
        # "going to a lower row" = target top is clearly below source bottom
        drops_row = r2.top() >= r1.bottom() - 5

        if forward:
            # Normal flow: smooth bezier left→right
            dx = max((p2.x() - p1.x()) * 0.45, 28)
            path.moveTo(p1)
            path.cubicTo(
                QPointF(p1.x() + dx, p1.y()),
                QPointF(p2.x() - dx, p2.y()),
                p2,
            )
        elif drops_row:
            # Backward column but dropping to a new row:
            # Down to midpoint between the two rows → left → down to target row → right into node.
            # The horizontal segment sits between rows → no overlap with any node.
            mid_y = (r1.bottom() + r2.top()) / 2
            path.moveTo(p1)
            path.lineTo(QPointF(p1.x(),       mid_y))    # ↓ half-way down
            path.lineTo(QPointF(p2.x() - 12,  mid_y))    # ← left
            path.lineTo(QPointF(p2.x() - 12,  p2.y()))   # ↓ to target row
            path.lineTo(p2)                               # → into node
        else:
            # Backward column, same or higher row: route above all nodes
            above = min(r1.top(), r2.top()) - ROW_GAP * 0.65
            path.moveTo(p1)
            path.lineTo(QPointF(p1.x() + 18, p1.y()))
            path.lineTo(QPointF(p1.x() + 18, above))
            path.lineTo(QPointF(p2.x() - 18, above))
            path.lineTo(QPointF(p2.x() - 18, p2.y()))
            path.lineTo(p2)

        self._sc.addPath(path, pen)
        # Arrow head: use point near end of path for direction
        self._arrowhead(p2, path.pointAtPercent(0.98), color)

    def _arrowhead(self, tip: QPointF, prev: QPointF, color: QColor):
        angle = math.atan2(tip.y() - prev.y(), tip.x() - prev.x())
        sz = 9
        a1 = angle + math.radians(148)
        a2 = angle - math.radians(148)
        p1 = QPointF(tip.x() + sz * math.cos(a1), tip.y() + sz * math.sin(a1))
        p2 = QPointF(tip.x() + sz * math.cos(a2), tip.y() + sz * math.sin(a2))
        self._sc.addPolygon(
            QPolygonF([tip, p1, p2]),
            QPen(Qt.NoPen), QBrush(color),
        )


# ─── State Viewer ──────────────────────────────────────────────────────────────
def _clip(v: Any, n: int = 400) -> Any:
    """Truncate long strings for readable display."""
    if isinstance(v, str):
        return v[:n] + f"…[{len(v)} Z.]" if len(v) > n else v
    if isinstance(v, dict):
        return {k: _clip(vv, n) for k, vv in v.items()}
    if isinstance(v, list):
        return [_clip(x, n) for x in v]
    return v


def _json(obj: Any) -> str:
    return json.dumps(_clip(obj), indent=2, ensure_ascii=False)


class StateViewer(QWidget):
    def __init__(self):
        super().__init__()
        self._run: Optional[RunData] = None
        self._sel = -1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # ── Tab 1: Accumulated state ──
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        l1.setContentsMargins(4, 4, 4, 4)
        hl = QHBoxLayout()
        hl.addWidget(QLabel("Schlüssel:"))
        self._combo = QComboBox()
        self._combo.currentTextChanged.connect(self._refresh_state)
        hl.addWidget(self._combo, 1)
        l1.addLayout(hl)
        self._state_edit = _make_text_edit()
        l1.addWidget(self._state_edit)
        self._tabs.addTab(w1, "State")

        # ── Tab 2: Changes in this step ──
        self._diff_edit = _make_text_edit()
        self._tabs.addTab(self._diff_edit, "Änderungen")

        # ── Tab 3: Input ──
        self._input_edit = _make_text_edit()
        self._tabs.addTab(self._input_edit, "Input")

        # ── Tab 4: Output ──
        self._output_edit = _make_text_edit()
        self._tabs.addTab(self._output_edit, "Output")

        # ── Tab 5: Runner variable inspector ──
        self._runner_var = RunnerVarTab()
        self._tabs.addTab(self._runner_var, "Runner-Variable")

    def load(self, run: RunData, sel: int = -1):
        self._run = run
        self._sel = sel
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItem("— Vollständig —")
        for k in run.all_state_keys():
            self._combo.addItem(k)
        self._combo.blockSignals(False)
        self._runner_var.load(run, sel)
        self._refresh_all()

    def select(self, idx: int):
        self._sel = idx
        self._runner_var.select(idx)
        self._refresh_all()

    # ── refresh helpers ──

    def _refresh_all(self):
        self._refresh_state()
        self._refresh_diff()
        self._refresh_io()

    def _refresh_state(self):
        run = self._run
        if run is None or self._sel < 0:
            self._state_edit.clear()
            return
        state = run.cumulative_state(self._sel)
        key = self._combo.currentText()
        if key == "— Vollständig —":
            self._state_edit.setPlainText(_json(state))
        else:
            val = state.get(key)
            if val is None:
                self._state_edit.setPlainText(f"(kein Eintrag für »{key}«)")
            else:
                self._state_edit.setPlainText(_json(val))

    def _refresh_diff(self):
        run = self._run
        if run is None or self._sel < 0:
            self._diff_edit.clear()
            return
        after = run.trace[self._sel].get("state_after", {})
        self._diff_edit.setPlainText(_json(after))

    def _refresh_io(self):
        run = self._run
        if run is None or self._sel < 0:
            self._input_edit.clear()
            self._output_edit.clear()
            return
        step = run.trace[self._sel]
        self._input_edit.setPlainText(_json(step.get("input", {})))
        self._output_edit.setPlainText(_json(step.get("output", {})))


def _resolve_path(obj: Any, path: str) -> tuple[bool, Any]:
    """Traverse a dot-separated path, correctly handling keys that themselves
    contain dots (e.g. state_after keys like 'state._runtime.last_step_id').

    Uses greedy matching: at each level tries the longest possible key first,
    so dotted key names are preferred over multi-level traversal.
    """
    parts = [p for p in path.split(".") if p]

    def _go(cur: Any, remaining: list[str]) -> tuple[bool, Any]:
        if not remaining:
            return True, cur
        if not isinstance(cur, dict):
            return False, None
        # Try longest key first so dotted keys win over deeper traversal
        for n in range(len(remaining), 0, -1):
            key = ".".join(remaining[:n])
            if key in cur:
                ok, val = _go(cur[key], remaining[n:])
                if ok:
                    return True, val
        return False, None

    return _go(obj, parts)


def _path_suggestions(step: dict, max_depth: int = 6, max_items: int = 300) -> list[str]:
    """Build flat dot-path suggestions by recursively walking the step dict."""
    suggestions: list[str] = []

    def _walk(obj: Any, prefix: str, depth: int) -> None:
        if depth > max_depth or len(suggestions) >= max_items:
            return
        if not isinstance(obj, dict):
            return
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            suggestions.append(path)
            if len(suggestions) >= max_items:
                return
            _walk(v, path, depth + 1)

    _walk(step, "", 0)
    return suggestions


class RunnerVarTab(QWidget):
    """Tab 5 — per-runner variable inspector.

    Runner is set automatically from the trace selection.
    Type any dot-path (e.g. output.value.markdown) — the dropdown filters
    live as you type (contains-match).  The chosen path is remembered per
    runner so it is restored when you return to the same runner.
    Values are shown untruncated with full line breaks.
    """

    def __init__(self):
        super().__init__()
        self._run: Optional[RunData] = None
        self._sel = -1
        self._memory: dict[str, str] = {}        # runner → remembered path
        self._all_suggestions: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Runner label (read-only)
        hl1 = QHBoxLayout()
        hl1.addWidget(QLabel("Runner:"))
        self._runner_lbl = QLabel("–")
        self._runner_lbl.setStyleSheet("font: bold 9pt monospace; color: #2c3e50;")
        hl1.addWidget(self._runner_lbl, 1)
        layout.addLayout(hl1)

        # Path combo — editable + live-filter completer
        hl2 = QHBoxLayout()
        hl2.addWidget(QLabel("Pfad:"))
        self._path_cb = QComboBox()
        self._path_cb.setEditable(True)
        self._path_cb.setInsertPolicy(QComboBox.NoInsert)

        # QCompleter with contains-filter for live filtering while typing
        self._completer_model = QStringListModel()
        self._completer = QCompleter(self._completer_model, self._path_cb)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setMaxVisibleItems(20)
        self._path_cb.setCompleter(self._completer)

        # activated fires when user selects from dropdown or completer popup
        self._path_cb.activated.connect(self._on_activated)
        # textEdited fires only on user keystrokes (not programmatic changes)
        self._path_cb.lineEdit().textEdited.connect(self._on_text_edited)
        # editingFinished fires on Enter/Tab/focus-out
        self._path_cb.lineEdit().editingFinished.connect(self._on_editing_finished)

        hl2.addWidget(self._path_cb, 1)
        layout.addLayout(hl2)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Monospace", 9))
        self._text.setLineWrapMode(QTextEdit.WidgetWidth)
        layout.addWidget(self._text)

    # ── public API ──

    def load(self, run: RunData, sel: int = -1):
        self._run = run
        self._sel = sel
        self._sync_to_step()

    def select(self, idx: int):
        self._sel = idx
        self._sync_to_step()

    # ── internals ──

    def _sync_to_step(self):
        run = self._run
        if run is None or self._sel < 0:
            return
        step   = run.trace[self._sel]
        runner = step.get("runner", "")
        self._runner_lbl.setText(runner or "–")

        suggestions = _path_suggestions(step)
        self._all_suggestions = suggestions
        remembered  = self._memory.get(runner, "")

        # Populate combo + completer model
        self._path_cb.blockSignals(True)
        self._path_cb.clear()
        self._path_cb.addItems(suggestions)
        self._completer_model.setStringList(suggestions)
        if remembered:
            idx = self._path_cb.findText(remembered)
            if idx >= 0:
                self._path_cb.setCurrentIndex(idx)
            else:
                self._path_cb.setCurrentText(remembered)
        self._path_cb.blockSignals(False)

        self._refresh()

    def _on_text_edited(self, text: str):
        """Re-filter the combo dropdown items as the user types."""
        t = text.lower()
        filtered = (
            [s for s in self._all_suggestions if t in s.lower()]
            if t else self._all_suggestions
        )
        self._path_cb.blockSignals(True)
        self._path_cb.clear()
        self._path_cb.addItems(filtered[:200])
        self._path_cb.blockSignals(False)
        # Keep typed text in the edit field (clear/addItems resets it)
        self._path_cb.lineEdit().blockSignals(True)
        self._path_cb.lineEdit().setText(text)
        self._path_cb.lineEdit().blockSignals(False)

    def _on_activated(self, _index: int = 0):
        """User selected an item from the dropdown or completer popup."""
        self._save_and_refresh()

    def _on_editing_finished(self):
        """User pressed Enter or left the field."""
        self._save_and_refresh()

    def _save_and_refresh(self):
        run = self._run
        if run is None or self._sel < 0:
            return
        path   = self._path_cb.currentText().strip()
        runner = run.trace[self._sel].get("runner", "")
        if runner and path:
            self._memory[runner] = path
        self._refresh()

    def _refresh(self):
        run = self._run
        if run is None or self._sel < 0:
            self._text.clear()
            return
        path = self._path_cb.currentText().strip()
        if not path:
            self._text.clear()
            return
        step    = run.trace[self._sel]
        ok, val = _resolve_path(step, path)
        if not ok:
            self._text.setPlainText(f"(Pfad »{path}« nicht gefunden)")
            return
        if isinstance(val, str):
            self._text.setPlainText(val)
        else:
            self._text.setPlainText(json.dumps(val, indent=2, ensure_ascii=False))


def _make_text_edit() -> QTextEdit:
    te = QTextEdit()
    te.setReadOnly(True)
    te.setFont(QFont("Monospace", 9))
    return te


# ─── TOML helpers ──────────────────────────────────────────────────────────────

def _toml_inject_colors(text: str, color_map: dict) -> str:
    """Add/update ``color = "..."`` in ``[[edges]]`` blocks of a TOML string.

    *color_map* maps ``(from_step, to_step) → hex_color``.
    An empty hex string removes an existing color line.
    All other lines are left untouched.
    """
    if not color_map:
        return text
    lines  = text.splitlines(keepends=True)
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'^\s*\[\[edges\]\]\s*$', line):
            # Collect this edges block (until next [ header or EOF)
            block: list[str] = [line]
            i += 1
            while i < len(lines) and not re.match(r'^\s*\[', lines[i]):
                block.append(lines[i])
                i += 1
            # Extract from/to; locate existing color line
            from_val = to_val = ""
            color_line_idx: Optional[int] = None
            for j, bl in enumerate(block):
                m = re.match(r'^\s*from\s*=\s*"([^"]*)"', bl)
                if m:
                    from_val = m.group(1)
                m = re.match(r'^\s*to\s*=\s*"([^"]*)"', bl)
                if m:
                    to_val = m.group(1)
                if re.match(r'^\s*color\s*=', bl):
                    color_line_idx = j
            key = (from_val, to_val)
            if key in color_map:
                color = color_map[key]
                if color_line_idx is not None:
                    if color:
                        block[color_line_idx] = f'color = "{color}"\n'
                    else:
                        del block[color_line_idx]
                elif color:
                    # Insert after the last non-blank content line
                    insert_at = len(block)
                    for j in range(len(block) - 1, 0, -1):
                        if block[j].strip():
                            insert_at = j + 1
                            break
                    block.insert(insert_at, f'color = "{color}"\n')
            result.extend(block)
        else:
            result.append(line)
            i += 1
    return "".join(result)


def _wf_bfs_layout(
    step_ids: list[str],
    edges: list[tuple[str, str]],
    entry_step: str,
) -> dict[str, tuple[int, int]]:
    """BFS column assignment from *entry_step*.  Returns {step_id: (col, row)}."""
    from collections import deque, defaultdict
    steps_set = set(step_ids)
    adj: dict[str, list[str]] = {s: [] for s in step_ids}
    for f, t in edges:
        if f in steps_set and t in steps_set:
            adj[f].append(t)

    col_map: dict[str, int] = {}
    start = entry_step if entry_step in steps_set else (step_ids[0] if step_ids else "")
    if not start:
        return {}
    q: deque[tuple[str, int]] = deque([(start, 0)])
    col_map[start] = 0
    while q:
        node, c = q.popleft()
        for nxt in adj.get(node, []):
            if nxt not in col_map:
                col_map[nxt] = c + 1
                q.append((nxt, c + 1))

    # Unreachable steps appended at the end
    max_col = max(col_map.values()) if col_map else 0
    for s in step_ids:
        if s not in col_map:
            max_col += 1
            col_map[s] = max_col

    # Rows: steps sharing a column get sequential rows (order = step_ids order)
    rows_by_col: dict[int, list[str]] = defaultdict(list)
    for s in step_ids:
        rows_by_col[col_map[s]].append(s)
    layout: dict[str, tuple[int, int]] = {}
    for c_idx, col_steps in rows_by_col.items():
        for r_idx, s in enumerate(col_steps):
            layout[s] = (c_idx, r_idx)
    return layout


# ─── Workflow Graph View ────────────────────────────────────────────────────────
_C_DEFAULT_EDGE = QColor("#7f8c8d")
_C_ENTRY_BORDER = QColor("#27ae60")
_C_TERM_BORDER  = QColor("#c0392b")


class WorkflowGraphView(QGraphicsView):
    """Static graph of a workflow TOML definition (no run context)."""

    def __init__(self):
        super().__init__()
        self._sc = QGraphicsScene()
        self.setScene(self._sc)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._wf: dict = {}

    def wheelEvent(self, ev):
        f = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)

    def fit(self):
        self.fitInView(self._sc.sceneRect(), Qt.KeepAspectRatio)

    def load(self, wf: dict):
        self._wf = wf
        self._rebuild()

    def _node_rect(self, col: int, row: int) -> QRectF:
        x = MARGIN + col * (NODE_W + COL_GAP)
        y = MARGIN + row * (NODE_H + ROW_GAP)
        return QRectF(x, y, NODE_W, NODE_H)

    def _rebuild(self):
        self._sc.clear()
        wf = self._wf
        if not wf:
            return
        raw_steps = wf.get("steps", [])
        step_ids  = [s.get("id", "") for s in raw_steps if s.get("id")]
        raw_edges = wf.get("edges", [])
        entry     = wf.get("entry_step", "")
        terminals = set(wf.get("terminal_steps", []))

        edge_pairs = [(e.get("from", ""), e.get("to", "")) for e in raw_edges]
        layout = _wf_bfs_layout(step_ids, edge_pairs, entry)
        step_info = {s.get("id", ""): s for s in raw_steps}
        rects: dict[str, QRectF] = {
            s: self._node_rect(*layout[s]) for s in step_ids if s in layout
        }

        fn_main  = QFont("Monospace", 8, QFont.Bold)
        fn_small = QFont("Monospace", 7)

        # Draw edges first
        for e in raw_edges:
            from_s = e.get("from", ""); to_s = e.get("to", "")
            if from_s not in rects or to_s not in rects:
                continue
            color_str = e.get("color", "")
            color = QColor(color_str) if color_str else _C_DEFAULT_EDGE
            self._draw_edge(rects[from_s], rects[to_s], color, e.get("when", ""))

        # Draw nodes
        for s in step_ids:
            if s not in rects:
                continue
            r   = rects[s]
            inf = step_info.get(s, {})
            is_entry    = (s == entry)
            is_terminal = (s in terminals)
            brd = _C_ENTRY_BORDER if is_entry else (_C_TERM_BORDER if is_terminal else C_BORDER)
            bw  = 2.5 if (is_entry or is_terminal) else 1.0
            self._sc.addRect(r, QPen(brd, bw), QBrush(C_NODE_BG))
            t = self._sc.addText(s, fn_main)
            t.setDefaultTextColor(C_TEXT)
            t.setPos(r.x() + 10, r.y() + 5)
            runner = inf.get("runner", "")
            if runner:
                rs = runner if len(runner) <= 27 else runner[:26] + "…"
                t2 = self._sc.addText(rs, fn_small)
                t2.setDefaultTextColor(C_SUBDUED)
                t2.setPos(r.x() + 10, r.y() + r.height() - 20)

        self._sc.setSceneRect(
            self._sc.itemsBoundingRect().adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN)
        )
        self.fitInView(self._sc.sceneRect(), Qt.KeepAspectRatio)

    def _draw_edge(self, r1: QRectF, r2: QRectF, color: QColor, label: str = ""):
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p1 = QPointF(r1.right(), r1.center().y())
        p2 = QPointF(r2.left(),  r2.center().y())
        path = QPainterPath()
        forward   = r2.left()  >= r1.right()  - 10
        drops_row = r2.top()   >= r1.bottom() - 5
        if forward:
            dx = max((p2.x() - p1.x()) * 0.45, 28)
            path.moveTo(p1)
            path.cubicTo(
                QPointF(p1.x() + dx, p1.y()),
                QPointF(p2.x() - dx, p2.y()),
                p2,
            )
        elif drops_row:
            mid_y = (r1.bottom() + r2.top()) / 2
            path.moveTo(p1)
            path.lineTo(QPointF(p1.x(),       mid_y))
            path.lineTo(QPointF(p2.x() - 12,  mid_y))
            path.lineTo(QPointF(p2.x() - 12,  p2.y()))
            path.lineTo(p2)
        else:
            above = min(r1.top(), r2.top()) - ROW_GAP * 0.65
            path.moveTo(p1)
            path.lineTo(QPointF(p1.x() + 18, p1.y()))
            path.lineTo(QPointF(p1.x() + 18, above))
            path.lineTo(QPointF(p2.x() - 18, above))
            path.lineTo(QPointF(p2.x() - 18, p2.y()))
            path.lineTo(p2)
        self._sc.addPath(path, pen)
        self._arrowhead(p2, path.pointAtPercent(0.98), color)
        if label:
            mid   = path.pointAtPercent(0.5)
            short = label[:28] + "…" if len(label) > 28 else label
            t     = self._sc.addText(short, QFont("Monospace", 6))
            t.setDefaultTextColor(color.darker(130))
            t.setPos(mid.x() - t.boundingRect().width() / 2, mid.y() - 10)

    def _arrowhead(self, tip: QPointF, prev: QPointF, color: QColor):
        angle = math.atan2(tip.y() - prev.y(), tip.x() - prev.x())
        sz = 9
        a1 = angle + math.radians(148)
        a2 = angle - math.radians(148)
        p1 = QPointF(tip.x() + sz * math.cos(a1), tip.y() + sz * math.sin(a1))
        p2 = QPointF(tip.x() + sz * math.cos(a2), tip.y() + sz * math.sin(a2))
        self._sc.addPolygon(
            QPolygonF([tip, p1, p2]),
            QPen(Qt.NoPen), QBrush(color),
        )


# ─── Profile View ──────────────────────────────────────────────────────────────
class ProfileView(QWidget):
    """Read-only viewer for a workflow profile TOML (policy, routing, wiring, cache)."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._meta_lbl = QLabel("  –")
        self._meta_lbl.setStyleSheet("font:bold 9pt monospace; color:#2c3e50; padding:4px;")
        layout.addWidget(self._meta_lbl)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, 1)

        self._policy_tbl  = self._make_kv_table()
        self._routing_tbl = self._make_kv_table()
        self._wiring_tbl  = self._make_kv_table()
        self._cache_tbl   = self._make_kv_table()

        self._tabs.addTab(self._policy_tbl,  "Policy")
        self._tabs.addTab(self._routing_tbl, "Model-Routing")
        self._tabs.addTab(self._wiring_tbl,  "Wiring")
        self._tabs.addTab(self._cache_tbl,   "Cache-Policy")

    def _make_kv_table(self) -> QTableWidget:
        t = QTableWidget()
        t.setColumnCount(2)
        t.setHorizontalHeaderLabels(["Schlüssel", "Wert"])
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setAlternatingRowColors(True)
        t.setFont(QFont("Monospace", 9))
        return t

    def _fill_table(self, table: QTableWidget, data: dict):
        rows = [
            (str(k), json.dumps(v) if isinstance(v, (dict, list, bool)) else str(v))
            for k, v in data.items()
        ]
        table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            ki = QTableWidgetItem(k); ki.setForeground(QBrush(C_SUBDUED))
            table.setItem(r, 0, ki)
            table.setItem(r, 1, QTableWidgetItem(v))
        table.resizeColumnsToContents()

    def load(self, path: str):
        try:
            raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            self._meta_lbl.setText(f"Fehler: {e}")
            return
        pid  = raw.get("profile_id", ""); wid = raw.get("workflow_id", "")
        ver  = raw.get("profile_version", ""); desc = raw.get("description", "")
        self._meta_lbl.setText(
            f"{pid}  v{ver}  →  Workflow: {wid}" + (f"  |  {desc}" if desc else "")
        )
        self._fill_table(self._policy_tbl,  dict(raw.get("policy", {})))
        self._fill_table(self._routing_tbl, dict(raw.get("model_routing", {})))
        self._fill_table(self._wiring_tbl,  dict(raw.get("wiring", {})))
        self._fill_table(self._cache_tbl,   dict(raw.get("cache_policy", {})))


# ─── Workflow View ──────────────────────────────────────────────────────────────
class WorkflowView(QWidget):
    """Second surface: workflow definition (edge colors) + profile viewer."""

    def __init__(self):
        super().__init__()
        self._def_path: Optional[Path] = None
        self._raw:      dict = {}
        self._color_map: dict[tuple[str, str], str] = {}   # (from, to) → "#rrggbb"
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Toolbar ──
        tb = QHBoxLayout()
        btn_def = QPushButton("Definition öffnen…")
        btn_def.clicked.connect(self._open_def_dialog)
        tb.addWidget(btn_def)
        btn_save = QPushButton("Speichern")
        btn_save.clicked.connect(self._save)
        tb.addWidget(btn_save)
        btn_prof = QPushButton("Profil öffnen…")
        btn_prof.clicked.connect(self._open_prof_dialog)
        tb.addWidget(btn_prof)
        btn_fit = QPushButton("Graph einpassen")
        btn_fit.clicked.connect(lambda: self._graph.fit())
        tb.addWidget(btn_fit)
        self._wf_lbl = QLabel("  –")
        self._wf_lbl.setStyleSheet("color:#555; font:9pt monospace;")
        tb.addWidget(self._wf_lbl, 1)
        layout.addLayout(tb)

        # ── Inner tab widget (Definition | Profil) ──
        self._inner_tabs = QTabWidget()
        layout.addWidget(self._inner_tabs, 1)

        # ── Tab A: Definition ──
        def_widget = QWidget()
        def_layout = QVBoxLayout(def_widget)
        def_layout.setContentsMargins(0, 2, 0, 0)

        main_split = QSplitter(Qt.Horizontal)
        def_layout.addWidget(main_split)

        left_split = QSplitter(Qt.Vertical)
        main_split.addWidget(left_split)

        g_steps = QGroupBox("Schritte")
        v_steps = QVBoxLayout(g_steps)
        v_steps.setContentsMargins(4, 8, 4, 4)
        self._steps_tbl = QTableWidget()
        self._steps_tbl.setColumnCount(4)
        self._steps_tbl.setHorizontalHeaderLabels(["id", "runner", "on_error", "max_visits"])
        hh = self._steps_tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self._steps_tbl.verticalHeader().setVisible(False)
        self._steps_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._steps_tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._steps_tbl.setAlternatingRowColors(True)
        self._steps_tbl.setFont(QFont("Monospace", 9))
        v_steps.addWidget(self._steps_tbl)
        left_split.addWidget(g_steps)

        g_edges = QGroupBox("Edges  (Doppelklick → Farbe wählen)")
        v_edges = QVBoxLayout(g_edges)
        v_edges.setContentsMargins(4, 8, 4, 4)
        self._edges_tbl = QTableWidget()
        self._edges_tbl.setColumnCount(4)
        self._edges_tbl.setHorizontalHeaderLabels(["von", "nach", "Bedingung", "Farbe"])
        hh2 = self._edges_tbl.horizontalHeader()
        hh2.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh2.setSectionResizeMode(2, QHeaderView.Stretch)
        self._edges_tbl.verticalHeader().setVisible(False)
        self._edges_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._edges_tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._edges_tbl.setAlternatingRowColors(True)
        self._edges_tbl.setFont(QFont("Monospace", 9))
        self._edges_tbl.cellDoubleClicked.connect(self._on_edge_dbl)
        v_edges.addWidget(self._edges_tbl)
        left_split.addWidget(g_edges)

        left_split.setSizes([280, 420])

        g_graph = QGroupBox("Workflow-Graph")
        v_graph = QVBoxLayout(g_graph)
        v_graph.setContentsMargins(4, 8, 4, 4)
        self._graph = WorkflowGraphView()
        v_graph.addWidget(self._graph)
        main_split.addWidget(g_graph)

        main_split.setSizes([460, 1240])
        self._inner_tabs.addTab(def_widget, "Definition")

        # ── Tab B: Profil ──
        self._profile_view = ProfileView()
        self._inner_tabs.addTab(self._profile_view, "Profil")

        # ── Status ──
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color:#555; font:8pt monospace; padding:2px;")
        layout.addWidget(self._status_lbl)

    # ── public API ──

    def load_path(self, path: str):
        self._do_load_def(path)

    # ── internals ──

    def _open_def_dialog(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Workflow-Definition öffnen", "",
            "TOML-Dateien (*.toml);;Alle Dateien (*)",
        )
        if p:
            self._do_load_def(p)

    def _open_prof_dialog(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Workflow-Profil öffnen", "",
            "TOML-Dateien (*.toml);;Alle Dateien (*)",
        )
        if p:
            self._profile_view.load(p)
            self._inner_tabs.setCurrentIndex(1)
            self._status_lbl.setText(f"Profil geladen: {p}")

    def _do_load_def(self, path: str):
        try:
            raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            self._status_lbl.setText(f"Fehler: {e}")
            return
        self._def_path = Path(path)
        self._raw      = raw
        self._wf_lbl.setText(f"  {path}")
        # Seed color_map from existing color fields
        self._color_map = {}
        for e in raw.get("edges", []):
            f = e.get("from", ""); t = e.get("to", ""); c = e.get("color", "")
            if f and t and c:
                self._color_map[(f, t)] = c
        self._reload_tables()
        self._graph.load(self._effective_wf())
        self._inner_tabs.setCurrentIndex(0)
        self._status_lbl.setText(
            f"Geladen: {raw.get('workflow_id', '')}  "
            f"v{raw.get('workflow_version', '')}  |  "
            f"{len(raw.get('steps', []))} Schritte  "
            f"{len(raw.get('edges', []))} Edges"
        )

    def _effective_wf(self) -> dict:
        import copy
        raw = copy.deepcopy(self._raw)
        for e in raw.get("edges", []):
            key = (e.get("from", ""), e.get("to", ""))
            if key in self._color_map:
                e["color"] = self._color_map[key]
        return raw

    def _reload_tables(self):
        raw       = self._raw
        entry     = raw.get("entry_step", "")
        terminals = set(raw.get("terminal_steps", []))

        # Steps
        steps = raw.get("steps", [])
        self._steps_tbl.setRowCount(len(steps))
        for r, s in enumerate(steps):
            sid  = s.get("id", "")
            vals = [sid, s.get("runner", ""), s.get("on_error", "fail_hard"),
                    str(s.get("max_visits", 0) or 0)]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 0:
                    if sid == entry:   item.setForeground(QBrush(C_GREEN))
                    elif sid in terminals: item.setForeground(QBrush(C_RED))
                self._steps_tbl.setItem(r, c, item)
        self._steps_tbl.resizeColumnsToContents()

        # Edges
        edges = raw.get("edges", [])
        self._edges_tbl.setRowCount(len(edges))
        for r, e in enumerate(edges):
            from_s = e.get("from", ""); to_s = e.get("to", "")
            when   = e.get("when", "")
            color  = self._color_map.get((from_s, to_s), e.get("color", ""))
            for c, v in enumerate([from_s, to_s, when, color]):
                item = QTableWidgetItem(v)
                if c == 3 and color:
                    try:
                        qc  = QColor(color)
                        lum = 0.299 * qc.red() + 0.587 * qc.green() + 0.114 * qc.blue()
                        item.setBackground(QBrush(qc))
                        item.setForeground(QBrush(
                            QColor("#000000") if lum > 128 else QColor("#ffffff")
                        ))
                    except Exception:
                        pass
                self._edges_tbl.setItem(r, c, item)
        self._edges_tbl.resizeColumnsToContents()

    def _on_edge_dbl(self, row: int, _col: int):
        edges = self._raw.get("edges", [])
        if row >= len(edges):
            return
        e      = edges[row]
        from_s = e.get("from", ""); to_s = e.get("to", "")
        current = self._color_map.get((from_s, to_s), e.get("color", ""))
        initial = QColor(current) if current else QColor("#27ae60")
        picked  = QColorDialog.getColor(initial, self, f"Farbe: {from_s} → {to_s}")
        if not picked.isValid():
            return
        self._color_map[(from_s, to_s)] = picked.name()
        self._reload_tables()
        self._graph.load(self._effective_wf())

    def _save(self):
        if self._def_path is None or not self._raw:
            self._status_lbl.setText("Keine Definition geladen.")
            return
        try:
            text = self._def_path.read_text(encoding="utf-8")
            text = _toml_inject_colors(text, self._color_map)
            self._def_path.write_text(text, encoding="utf-8")
            self._status_lbl.setText(f"Gespeichert: {self._def_path}")
        except Exception as e:
            self._status_lbl.setText(f"Fehler beim Speichern: {e}")


# ─── Main Window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, path: Optional[str] = None):
        super().__init__()
        self.setWindowTitle("Agentic Run Analyser")
        self.resize(1700, 960)
        self._run: Optional[RunData] = None
        self._build_ui()
        if path:
            self._load(path)

    def _build_ui(self):
        self._outer_tabs = QTabWidget()
        self.setCentralWidget(self._outer_tabs)

        # ── Tab 1: Run Analyser ──
        run_page   = QWidget()
        run_layout = QVBoxLayout(run_page)
        run_layout.setContentsMargins(2, 2, 2, 2)

        # Toolbar row
        tb_layout = QHBoxLayout()
        btn_open = QPushButton("Run öffnen…")
        btn_open.clicked.connect(self._open_dialog)
        tb_layout.addWidget(btn_open)
        btn_fit = QPushButton("Graph einpassen")
        btn_fit.clicked.connect(lambda: self._graph.fit())
        tb_layout.addWidget(btn_fit)
        self._lbl = QLabel("  –")
        self._lbl.setStyleSheet("color:#555; font:9pt monospace;")
        tb_layout.addWidget(self._lbl, 1)
        run_layout.addLayout(tb_layout)

        # Outer splitter (top | bottom)
        outer = QSplitter(Qt.Vertical)
        run_layout.addWidget(outer)

        # Top: Settings + Trace
        top = QSplitter(Qt.Horizontal)
        outer.addWidget(top)

        g1 = QGroupBox("① Einstellungen")
        v1 = QVBoxLayout(g1)
        v1.setContentsMargins(4, 8, 4, 4)
        self._settings = SettingsTable()
        v1.addWidget(self._settings)
        top.addWidget(g1)

        g2 = QGroupBox("② Trace")
        v2 = QVBoxLayout(g2)
        v2.setContentsMargins(4, 8, 4, 4)
        self._trace = TraceTable()
        self._trace.step_selected.connect(self._on_select)
        v2.addWidget(self._trace)
        top.addWidget(g2)

        top.setSizes([460, 1040])

        # Bottom: Graph + State
        bot = QSplitter(Qt.Horizontal)
        outer.addWidget(bot)

        g3 = QGroupBox("③ Ablaufgraph")
        v3 = QVBoxLayout(g3)
        v3.setContentsMargins(4, 8, 4, 4)
        self._graph = GraphView()
        v3.addWidget(self._graph)
        bot.addWidget(g3)

        g4 = QGroupBox("④ State-Inspektor")
        v4 = QVBoxLayout(g4)
        v4.setContentsMargins(4, 8, 4, 4)
        self._state = StateViewer()
        v4.addWidget(self._state)
        bot.addWidget(g4)

        bot.setSizes([1050, 650])
        outer.setSizes([340, 620])

        self._outer_tabs.addTab(run_page, "Run-Analyse")

        # ── Tab 2: Workflow-Definition ──
        self._wf_view = WorkflowView()
        self._outer_tabs.addTab(self._wf_view, "Workflow-Definition")

        self.setStatusBar(QStatusBar())

    def _open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Run-Datei öffnen", "",
            "JSON-Dateien (*.json);;Alle Dateien (*)",
        )
        if p:
            self._load(p)

    def _load(self, path: str):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.statusBar().showMessage(f"Ladefehler: {e}")
            return

        run = RunData(data)
        self._run = run
        self._lbl.setText(f"  {path}")

        self._settings.load(run)
        self._trace.load(run)
        self._graph.load(run, -1)
        self._state.load(run, -1)

        if run.trace:
            self._trace.selectRow(0)

        ok_s = "✓ OK" if run.ok else "✗ Fehler"
        self.statusBar().showMessage(
            f"{run.run_id}  |  {ok_s}  |  {len(run.trace)} Schritte  |  "
            f"{run.metrics.get('elapsed_ms', 0):.1f} ms gesamt"
        )

    def _on_select(self, idx: int):
        if idx < 0:
            return
        self._graph.select(idx)
        self._state.select(idx)


# ─── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    path = sys.argv[1] if len(sys.argv) > 1 else None
    win = MainWindow(path)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
