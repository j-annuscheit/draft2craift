"""Editor panel with optional toolbar and status for one MarkdownEditor."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import (
    default_user_mode,
    normalize_user_mode,
    resolve_feature_label,
)
from studio.canvas.editor import MarkdownEditor
from studio.canvas.editor_styles import TOOLBAR_STYLE


class EditorPanel(QWidget):
    """
    Complete editor panel consisting of optional toolbar + ``MarkdownEditor``.

    Instantiate with ``read_only=True`` for viewer/RAG tabs and
    ``read_only=False`` for canvas tabs.
    """

    file_path: str = ""

    def __init__(
        self,
        parent: QWidget | None = None,
        read_only: bool = False,
        show_toolbar: bool = True,
    ):
        super().__init__(parent)
        self.editor = MarkdownEditor(read_only=read_only)
        self.lock_btn: QPushButton | None = None
        self.status_label: QLabel | None = None
        self._user_mode = default_user_mode()
        self._setup_ui(show_toolbar)
        self.set_user_mode(self._user_mode)

    def _setup_ui(self, show_toolbar: bool):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if show_toolbar:
            layout.addWidget(self._build_toolbar())
        layout.addWidget(self.editor)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget(objectName="toolbar")
        bar.setFixedHeight(30)
        bar.setStyleSheet(TOOLBAR_STYLE)

        hbox = QHBoxLayout(bar)
        hbox.setContentsMargins(4, 0, 4, 0)
        hbox.setSpacing(2)

        self.lock_btn = QPushButton()
        self.lock_btn.setCheckable(True)
        self._sync_lock_btn()
        self.lock_btn.clicked.connect(self._toggle_lock)
        hbox.addWidget(self.lock_btn)

        hbox.addStretch()

        self.status_label = QLabel("")
        hbox.addWidget(self.status_label)
        self.editor.textChanged.connect(self._update_status)

        return bar

    def _sync_lock_btn(self):
        if self.lock_btn is None:
            return
        read_only = self.editor.isReadOnly()
        if read_only:
            self.lock_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "editor.lock.read_only",
                    "🔒 Read-Only",
                )
            )
            self.lock_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "editor.lock.read_only.tooltip",
                    "The draft is locked for editing.",
                )
            )
        else:
            self.lock_btn.setText(
                resolve_feature_label(
                    self._user_mode,
                    "editor.lock.editing",
                    "✏ Editing",
                )
            )
            self.lock_btn.setToolTip(
                resolve_feature_label(
                    self._user_mode,
                    "editor.lock.editing.tooltip",
                    "The draft is editable.",
                )
            )
        self.lock_btn.setChecked(read_only)

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        editor_mode_setter = getattr(self.editor, "set_user_mode", None)
        if callable(editor_mode_setter):
            editor_mode_setter(self._user_mode)
        self._sync_lock_btn()

    def _toggle_lock(self):
        self.editor.toggle_read_only()
        self._sync_lock_btn()

    def _update_status(self):
        text = self.editor.toPlainText()
        words = len(text.split()) if text.strip() else 0
        lines = text.count("\n") + 1
        if self.status_label:
            self.status_label.setText(f"{words} w  {lines} L")
