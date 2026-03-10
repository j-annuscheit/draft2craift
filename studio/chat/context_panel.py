"""Context source selection panel for chat requests."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .styles import CTX_CB_STYLE, CTX_DOC_CB_STYLE


class ContextSelectorPanel(QWidget):
    """
    Panel controlling which sources are sent to the LLM.

    Fixed options:
    - Current Draft
    - Current RAG Results

    Dynamic options:
    - One checkbox per imported document.
    """

    preferred_height_changed = Signal(int)
    _HEIGHT_PADDING = 10
    _MAX_VISIBLE_DOC_ROWS = 10

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._docs: dict[str, str] = {}
        self._cbs: dict[str, QCheckBox] = {}
        self._header: QWidget | None = None
        self._scroll: QScrollArea | None = None
        self._body: QWidget | None = None
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QWidget()
        hdr.setFixedHeight(26)
        hdr.setStyleSheet(
            "background: palette(alternate-base); border-bottom: 1px solid palette(mid);"
        )
        self._header = hdr
        hbox = QHBoxLayout(hdr)
        hbox.setContentsMargins(8, 0, 8, 0)
        lbl = QLabel("Context Sources")
        lbl.setStyleSheet(
            "color: palette(highlight); font-size: 10px; "
            "font-weight: bold; background: transparent;"
        )
        hbox.addWidget(lbl)
        root.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: palette(base); border: none; }"
        )
        self._scroll = scroll

        body = QWidget()
        body.setStyleSheet("background: palette(base);")
        self._body = body
        body.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(8, 6, 8, 6)
        self._body_layout.setSpacing(2)

        self._use_canvas = QCheckBox("Current Draft")
        self._use_canvas.setChecked(False)
        self._use_canvas.setStyleSheet(CTX_CB_STYLE)

        self._use_rag = QCheckBox("Current RAG Results")
        self._use_rag.setChecked(False)
        self._use_rag.setStyleSheet(CTX_CB_STYLE)

        self._body_layout.addWidget(self._use_canvas)
        self._body_layout.addWidget(self._use_rag)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: palette(mid); margin: 4px 0;")
        self._body_layout.addWidget(sep)

        self._docs_lbl = QLabel("Imported Documents:")
        self._docs_lbl.setStyleSheet(
            "color: palette(placeholder-text); font-size: 9px; background: transparent;"
        )
        self._body_layout.addWidget(self._docs_lbl)

        scroll.setWidget(body)
        root.addWidget(scroll)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        self._schedule_height_refresh()

    def preferred_height(self) -> int:
        """Return exact panel height needed to display all source rows."""
        if self._header is not None:
            header_h = self._header.sizeHint().height()
        else:
            header_h = 26
        if self._body is not None:
            body_h = self._body.sizeHint().height()
        else:
            body_h = 0
        if self._cbs and len(self._cbs) > self._MAX_VISIBLE_DOC_ROWS:
            full_docs_h = self._docs_rows_height()
            limited_docs_h = self._docs_rows_height(self._MAX_VISIBLE_DOC_ROWS)
            body_h = max(0, body_h - max(0, full_docs_h - limited_docs_h))
        frame_h = 0
        if self._scroll is not None:
            frame_h = self._scroll.frameWidth() * 2
        return max(52, header_h + body_h + frame_h + self._HEIGHT_PADDING)

    def _docs_rows_height(self, limit: int | None = None) -> int:
        if not self._cbs:
            return 0
        rows = list(self._cbs.values())
        if limit is not None:
            rows = rows[: max(0, int(limit))]
        if not rows:
            return 0
        spacing = 0
        if self._body_layout is not None:
            spacing = max(0, int(self._body_layout.spacing()))
        total = 0
        for cb in rows:
            total += max(14, int(cb.sizeHint().height()))
        total += spacing * max(0, len(rows) - 1)
        return total

    def _schedule_height_refresh(self):
        QTimer.singleShot(0, self._refresh_height)

    def _refresh_height(self):
        target = self.preferred_height()
        self.setMinimumHeight(target)
        self.setMaximumHeight(target)
        self.preferred_height_changed.emit(target)

    def add_document(self, name: str, content: str):
        """Register an imported document (unchecked by default)."""
        if name in self._cbs:
            return
        self._docs[name] = content
        cb = QCheckBox(name)
        cb.setChecked(False)
        cb.setStyleSheet(CTX_DOC_CB_STYLE)
        cb.setToolTip(name)
        self._body_layout.addWidget(cb)
        self._cbs[name] = cb
        self._schedule_height_refresh()

    @staticmethod
    def _unique_name(target: str, existing: set[str], current: str) -> str:
        desired = str(target or "").strip() or str(current or "").strip() or "Document"
        if desired == current or desired not in existing:
            return desired

        stem, dot, ext = desired.rpartition(".")
        root = stem if dot else desired
        suffix = f".{ext}" if dot else ""

        idx = 1
        while True:
            candidate = f"{root} ({idx}){suffix}"
            if candidate not in existing or candidate == current:
                return candidate
            idx += 1

    def rename_document(self, old_name: str, new_name: str) -> str:
        """Rename one imported document row while preserving checkbox state."""
        old_key = str(old_name or "").strip()
        if not old_key or old_key not in self._docs:
            return ""

        cb = self._cbs.get(old_key)
        if cb is None:
            return ""

        final = self._unique_name(new_name, set(self._docs.keys()), old_key)
        if final == old_key:
            return old_key

        content = self._docs.pop(old_key)
        self._docs[final] = content

        self._cbs.pop(old_key, None)
        self._cbs[final] = cb
        cb.setText(final)
        cb.setToolTip(final)
        self._schedule_height_refresh()
        return final

    def remove_document(self, name: str):
        cb = self._cbs.pop(name, None)
        if cb:
            self._body_layout.removeWidget(cb)
            cb.deleteLater()
        self._docs.pop(name, None)
        self._schedule_height_refresh()

    def clear_docs(self):
        """Remove all dynamically added document checkboxes."""
        for name in list(self._cbs.keys()):
            self.remove_document(name)
        self._schedule_height_refresh()

    def get_selection(self) -> tuple[bool, bool, list[tuple[str, str]]]:
        """Return ``(use_canvas, use_rag, [(name, content), ...])``."""
        docs = [
            (name, self._docs[name])
            for name, cb in self._cbs.items()
            if cb.isChecked()
        ]
        return self._use_canvas.isChecked(), self._use_rag.isChecked(), docs

    def get_document_content(self, name: str) -> str:
        """Return markdown content for one registered context document."""
        key = str(name or "").strip()
        if not key:
            return ""
        return str(self._docs.get(key, "") or "")

    def get_all_documents(self) -> dict[str, str]:
        """Return a copy of all registered context documents."""
        return {str(name): str(content or "") for name, content in self._docs.items()}
