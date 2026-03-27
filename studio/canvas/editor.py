"""Core markdown editor widget used across canvas and knowledge panels."""
from __future__ import annotations

import re
import weakref

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QAction, QContextMenuEvent, QFont
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from shared.domain.user_mode import (
    default_user_mode,
    is_feature_visible,
    normalize_user_mode,
    resolve_feature_label,
)
from studio.canvas.editor_styles import editor_style
from studio.canvas.highlighter import MarkdownHighlighter


class MarkdownEditor(QPlainTextEdit):
    """
    Core text-editing widget with Markdown highlighting.

    Use ``setReadOnly(True)`` for viewer / RAG mode.
    Use ``setReadOnly(False)`` for editable canvas mode.
    """

    read_only_changed = Signal(bool)
    read_aloud_requested = Signal(str)
    _BASE_FONT_PT = 12.0
    _ZOOM_MIN = 60
    _ZOOM_MAX = 260
    _ZOOM_STEP = 10
    _READ_ALOUD_FEATURE_KEY = "editor.context.read_aloud_selection"
    _DEFAULT_FONT_FAMILY = "Cascadia Code"
    _GLOBAL_FONT_FAMILY = _DEFAULT_FONT_FAMILY
    _INSTANCES: "weakref.WeakSet[MarkdownEditor]" = weakref.WeakSet()

    def __init__(self, parent: QWidget | None = None, read_only: bool = False):
        super().__init__(parent)
        self._font_size_pt = self._BASE_FONT_PT
        self._font_family = self._normalize_font_family(self._GLOBAL_FONT_FAMILY)
        self._user_mode = default_user_mode()
        self._INSTANCES.add(self)
        self._setup_font()
        self.highlighter = MarkdownHighlighter(self.document())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setTabStopDistance(32)
        self.setReadOnly(read_only)

    @classmethod
    def _normalize_font_family(cls, value: object) -> str:
        text = str(value or "").strip()
        if len(text) > 120:
            text = text[:120].strip()
        return text or str(cls._DEFAULT_FONT_FAMILY)

    @classmethod
    def global_font_family(cls) -> str:
        return cls._normalize_font_family(cls._GLOBAL_FONT_FAMILY)

    @classmethod
    def apply_global_font_family(cls, family: object, *, force: bool = False) -> None:
        normalized = cls._normalize_font_family(family)
        if (not force) and normalized == cls._normalize_font_family(cls._GLOBAL_FONT_FAMILY):
            return
        cls._GLOBAL_FONT_FAMILY = normalized
        for editor in list(cls._INSTANCES):
            try:
                editor.set_editor_font_family(normalized, force=force)
            except Exception:
                continue

    def set_editor_font_family(self, family: object, *, force: bool = False) -> bool:
        normalized = self._normalize_font_family(family)
        if (not force) and normalized == str(self._font_family):
            return False
        self._font_family = normalized
        self._setup_font()
        self._apply_style()
        return True

    def _setup_font(self):
        font = QFont(str(self._font_family))
        font.setStyleHint(QFont.StyleHint.AnyStyle)
        font.setPointSizeF(self._font_size_pt)
        self.setFont(font)

    def _apply_style(self):
        self.setStyleSheet(
            editor_style(
                self.isReadOnly(),
                self._font_size_pt,
                str(self._font_family),
            )
        )

    def setReadOnly(self, read_only: bool):
        super().setReadOnly(read_only)
        self._apply_style()
        self.read_only_changed.emit(read_only)

    def toggle_read_only(self) -> bool:
        """Toggle mode. Returns the new read-only state."""
        self.setReadOnly(not self.isReadOnly())
        return self.isReadOnly()

    def set_font_size_pt(self, size_pt: float):
        clamped = max(6.0, min(72.0, float(size_pt)))
        if abs(clamped - self._font_size_pt) < 0.05:
            return
        self._font_size_pt = clamped
        font = self.font()
        font.setPointSizeF(clamped)
        self.setFont(font)
        self._apply_style()

    def font_size_pt(self) -> float:
        return self._font_size_pt

    def zoom_percent(self) -> int:
        return int(round((self._font_size_pt / self._BASE_FONT_PT) * 100))

    def set_zoom_percent(self, percent: int) -> bool:
        clamped = max(self._ZOOM_MIN, min(self._ZOOM_MAX, int(percent)))
        target_pt = self._BASE_FONT_PT * (clamped / 100.0)
        old_size = self._font_size_pt
        self.set_font_size_pt(target_pt)
        return abs(self._font_size_pt - old_size) >= 0.05

    def increase_zoom(self) -> bool:
        return self.set_zoom_percent(self.zoom_percent() + self._ZOOM_STEP)

    def decrease_zoom(self) -> bool:
        return self.set_zoom_percent(self.zoom_percent() - self._ZOOM_STEP)

    def reset_zoom(self) -> bool:
        return self.set_zoom_percent(100)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                delta = event.pixelDelta().y()
            if delta > 0:
                self.increase_zoom()
            elif delta < 0:
                self.decrease_zoom()
            event.accept()
            return
        super().wheelEvent(event)

    @staticmethod
    def _escape_internal_word_asterisks(text: str) -> str:
        # e.g. "Kuenstler*innen" -> "Kuenstler\\*innen"
        return re.sub(
            r"(?<=[^\W\d_])\*(?=[^\W\d_])",
            r"\\*",
            str(text or ""),
            flags=re.UNICODE,
        )

    @staticmethod
    def _normalize_paste_text(text: str) -> str:
        normalized = (
            str(text or "")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\u2028", "\n")
            .replace("\u2029", "\n")
            .replace("\uFFFC", "")
            .replace("\u200b", "")
            .replace("\u200c", "")
            .replace("\u200d", "")
            .replace("\ufeff", "")
        )
        return MarkdownEditor._escape_internal_word_asterisks(normalized)

    def insertFromMimeData(self, source):
        if source is None or not source.hasText():
            super().insertFromMimeData(source)
            return
        normalized = self._normalize_paste_text(source.text())
        mime = QMimeData()
        mime.setText(normalized)
        super().insertFromMimeData(mime)

    def get_selected_text(self) -> str:
        return self.textCursor().selectedText()

    def get_full_text(self) -> str:
        return self.toPlainText()

    @staticmethod
    def _normalize_qt_selected_text(text: str) -> str:
        return str(text or "").replace("\u2029", "\n").replace("\u2028", "\n").strip()

    def _emit_read_aloud_selection(self) -> None:
        selected = self._normalize_qt_selected_text(self.get_selected_text())
        if not selected:
            return
        self.read_aloud_requested.emit(selected)

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = self.createStandardContextMenu()
        selected = self._normalize_qt_selected_text(self.get_selected_text())
        if selected and is_feature_visible(
            self._user_mode,
            self._READ_ALOUD_FEATURE_KEY,
            default=True,
        ):
            menu.addSeparator()
            read_aloud_action = QAction(
                resolve_feature_label(
                    self._user_mode,
                    self._READ_ALOUD_FEATURE_KEY,
                    "🔊 Vorlesen",
                ),
                self,
            )
            read_aloud_action.triggered.connect(self._emit_read_aloud_selection)
            menu.addAction(read_aloud_action)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def load_file(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                self.setPlainText(handle.read())
            return True
        except Exception as exc:
            self.setPlainText(f"⚠ Could not open file:\n{exc}")
            return False

    def save_file(self, path: str) -> bool:
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.toPlainText())
            return True
        except Exception:
            return False
