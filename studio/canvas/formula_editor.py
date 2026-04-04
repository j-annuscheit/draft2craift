"""Popup dialog for editing LaTeX formulas with live preview."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


def _render_formula_pixmap(latex: str, display: bool = True) -> QPixmap | None:
    """Render a LaTeX string to a QPixmap via matplotlib.  Returns None on failure."""
    try:
        import io
        import base64
        import matplotlib  # type: ignore
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore

        expr = latex.strip()
        if not (expr.startswith("$") and expr.endswith("$")):
            expr = f"${expr}$"
        fontsize = 14 if display else 12
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0, 0, expr, fontsize=fontsize)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=130,
                    bbox_inches="tight", pad_inches=0.08, transparent=True)
        plt.close(fig)
        buf.seek(0)
        pix = QPixmap()
        pix.loadFromData(buf.read())
        return pix
    except Exception:
        return None


class FormulaEditorDialog(QDialog):
    """
    Modal popup for inserting or editing a LaTeX formula.

    Usage::

        dlg = FormulaEditorDialog(parent=self, latex="E = mc^2")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            use(dlg.result_latex())
    """

    def __init__(
        self,
        parent=None,
        latex: str = "",
        display_mode: bool = True,
    ):
        super().__init__(parent)
        self.setWindowTitle("Formel bearbeiten")
        self.setMinimumWidth(480)
        self.setMinimumHeight(300)
        self._display_mode = display_mode
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(400)
        self._preview_timer.timeout.connect(self._update_preview)
        self._build_ui(latex)

    def _build_ui(self, initial_latex: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Input area
        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText("LaTeX eingeben, z. B.  E = mc^2  oder  \\frac{a}{b}")
        self._editor.setPlainText(initial_latex)
        self._editor.textChanged.connect(self._on_text_changed)
        self._editor.setFixedHeight(80)
        layout.addWidget(self._editor)

        # Display/inline toggle
        mode_row = QHBoxLayout()
        self._btn_display = QPushButton("Display  $$...$$")
        self._btn_display.setCheckable(True)
        self._btn_display.setChecked(self._display_mode)
        self._btn_display.clicked.connect(self._on_display_toggled)
        self._btn_inline = QPushButton("Inline  $...$")
        self._btn_inline.setCheckable(True)
        self._btn_inline.setChecked(not self._display_mode)
        self._btn_inline.clicked.connect(self._on_inline_toggled)
        mode_row.addWidget(self._btn_display)
        mode_row.addWidget(self._btn_inline)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # Preview label
        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumHeight(80)
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preview_label.setStyleSheet(
            "background: palette(base); border: 1px solid palette(mid); border-radius: 4px;"
        )
        layout.addWidget(self._preview_label)

        # Error label
        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: palette(bright-text);")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        # Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Initial preview
        self._update_preview()

    def _on_text_changed(self):
        self._preview_timer.start()

    def _on_display_toggled(self):
        self._display_mode = True
        self._btn_display.setChecked(True)
        self._btn_inline.setChecked(False)
        self._update_preview()

    def _on_inline_toggled(self):
        self._display_mode = False
        self._btn_inline.setChecked(True)
        self._btn_display.setChecked(False)
        self._update_preview()

    def _update_preview(self):
        latex = self._editor.toPlainText().strip()
        if not latex:
            self._preview_label.setText("<i style='color:gray'>Vorschau erscheint hier…</i>")
            self._preview_label.setPixmap(QPixmap())
            self._error_label.setVisible(False)
            return
        pix = _render_formula_pixmap(latex, self._display_mode)
        if pix is not None and not pix.isNull():
            self._preview_label.setPixmap(
                pix.scaled(
                    self._preview_label.width() - 16,
                    self._preview_label.height() - 16,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self._error_label.setVisible(False)
        else:
            self._preview_label.setPixmap(QPixmap())
            self._preview_label.setText("")
            self._error_label.setText("Vorschau nicht verfügbar (matplotlib erforderlich)")
            self._error_label.setVisible(True)

    def result_latex(self) -> str:
        """Return the LaTeX string wrapped in the appropriate delimiters."""
        latex = self._editor.toPlainText().strip()
        if not latex:
            return ""
        if self._display_mode:
            return f"\n\n$${latex}$$\n\n"
        return f"${latex}$"
