"""Dialog for selecting annotation export options."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from shared.domain.user_mode import (
    default_user_mode,
    normalize_user_mode,
    resolve_feature_label,
)
from studio.canvas.exporting.annotation_export import (
    AnnotationExportOptions,
    color_display_name,
)


class AnnotationExportDialog(QDialog):
    """Small options dialog for extracting annotations to a new canvas tab."""

    _SORT_CHRONO = "chronological"
    _SORT_BY_COLOR = "grouped_by_color"

    def __init__(
        self,
        *,
        color_counts: list[tuple[str, int]],
        glossary_count: int,
        user_mode: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._user_mode = normalize_user_mode(
            default_user_mode() if user_mode is None else user_mode
        )
        self._color_checkboxes: dict[str, QCheckBox] = {}
        self._glossary_count = max(0, int(glossary_count))
        self._build_ui(color_counts)
        self.set_user_mode(self._user_mode)

    def _label(self, key: str, default: str) -> str:
        return resolve_feature_label(self._user_mode, key, default)

    def set_user_mode(self, mode: str) -> None:
        self._user_mode = normalize_user_mode(mode)
        self.setWindowTitle(
            self._label(
                "annotation.export.dialog.title",
                "Annotationen extrahieren",
            )
        )
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText(
                self._label(
                    "annotation.export.dialog.button.ok",
                    "In neuen Canvas extrahieren",
                )
            )
        cancel_btn = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText(
                self._label(
                    "annotation.export.dialog.button.cancel",
                    "Abbrechen",
                )
            )
        self._comments_cb.setText(
            self._label(
                "annotation.export.dialog.comments",
                "Kommentare/Definitionen übernehmen",
            )
        )
        self._keep_markers_cb.setText(
            self._label(
                "annotation.export.dialog.keep_markers",
                "Markierungen mit gleicher Farbe beibehalten",
            )
        )
        self._glossary_cb.setText(
            self._format_label(
                "annotation.export.dialog.glossary",
                "Glossar-Einträge ({count})",
                count=str(self._glossary_count),
            )
        )
        self._sort_label.setText(
            self._label(
                "annotation.export.dialog.sort_label",
                "Sortierung:",
            )
        )
        idx_chrono = self._sort_combo.findData(self._SORT_CHRONO)
        if idx_chrono >= 0:
            self._sort_combo.setItemText(
                idx_chrono,
                self._label(
                    "annotation.export.dialog.sort.chronological",
                    "Nur historisch",
                ),
            )
        idx_color = self._sort_combo.findData(self._SORT_BY_COLOR)
        if idx_color >= 0:
            self._sort_combo.setItemText(
                idx_color,
                self._label(
                    "annotation.export.dialog.sort.by_color",
                    "Nach Farben (historisch je Farbe)",
                ),
            )
        self._glossary_hint.setText(
            self._label(
                "annotation.export.dialog.glossary_hint",
                "Hinweis: Glossar-Definitionen erscheinen nur mit aktivierten Kommentaren.",
            )
        )
        self._intro_lbl.setText(
            self._label(
                "annotation.export.dialog.intro",
                "Wähle aus, welche Annotationen in den neuen Canvas extrahiert werden sollen.",
            )
        )
        self._colors_group.setTitle(
            self._label(
                "annotation.export.dialog.group.colors",
                "Highlight-Farben",
            )
        )
        if self._empty_colors_lbl is not None:
            self._empty_colors_lbl.setText(
                self._label(
                    "annotation.export.dialog.group.colors.empty",
                    "Keine benutzerdefinierten Highlight-Farben vorhanden.",
                )
            )

    def options(self) -> AnnotationExportOptions:
        selected_colors = [
            color
            for color, cb in self._color_checkboxes.items()
            if cb.isChecked()
        ]
        sort_mode = str(self._sort_combo.currentData() or self._SORT_CHRONO).strip().lower()
        return AnnotationExportOptions(
            include_colors=tuple(selected_colors),
            include_glossary=bool(self._glossary_cb.isChecked()),
            include_comments=bool(self._comments_cb.isChecked()),
            sort_mode=sort_mode,
            keep_markers=bool(self._keep_markers_cb.isChecked()),
        )

    def _format_label(self, key: str, default: str, **values: str) -> str:
        template = self._label(key, default)
        try:
            return str(template).format(**values)
        except Exception:
            return str(template)

    def _build_ui(self, color_counts: list[tuple[str, int]]) -> None:
        self.setModal(True)
        self.resize(520, 460)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self._intro_lbl = QLabel(
            "Wähle aus, welche Annotationen in den neuen Canvas extrahiert werden sollen."
        )
        self._intro_lbl.setWordWrap(True)
        root.addWidget(self._intro_lbl)

        root.addWidget(self._build_colors_group(color_counts), stretch=1)

        self._glossary_cb = QCheckBox(f"Glossar-Einträge ({self._glossary_count})")
        self._glossary_cb.setChecked(self._glossary_count > 0)
        self._glossary_cb.setEnabled(self._glossary_count > 0)
        root.addWidget(self._glossary_cb)

        self._comments_cb = QCheckBox("Kommentare/Definitionen übernehmen")
        self._comments_cb.setChecked(True)
        root.addWidget(self._comments_cb)

        self._keep_markers_cb = QCheckBox("Markierungen mit gleicher Farbe beibehalten")
        self._keep_markers_cb.setChecked(False)
        root.addWidget(self._keep_markers_cb)

        sort_row = QHBoxLayout()
        sort_row.setContentsMargins(0, 0, 0, 0)
        sort_row.setSpacing(6)
        self._sort_label = QLabel("Sortierung:")
        self._sort_combo = QComboBox()
        self._sort_combo.addItem("Nur historisch", self._SORT_CHRONO)
        self._sort_combo.addItem("Nach Farben (historisch je Farbe)", self._SORT_BY_COLOR)
        self._sort_combo.setCurrentIndex(1)
        sort_row.addWidget(self._sort_label)
        sort_row.addWidget(self._sort_combo, stretch=1)
        root.addLayout(sort_row)

        self._glossary_hint = QLabel(
            "Hinweis: Glossar-Definitionen erscheinen nur mit aktivierten Kommentaren."
        )
        self._glossary_hint.setWordWrap(True)
        self._glossary_hint.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
        root.addWidget(self._glossary_hint)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

    def _build_colors_group(self, color_counts: list[tuple[str, int]]) -> QWidget:
        group = QGroupBox("Highlight-Farben")
        self._colors_group = group
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)

        rows = list(color_counts)
        custom_counter = 0
        self._empty_colors_lbl: QLabel | None = None
        if not rows:
            self._empty_colors_lbl = QLabel("Keine benutzerdefinierten Highlight-Farben vorhanden.")
            self._empty_colors_lbl.setStyleSheet("color: palette(placeholder-text);")
            body_layout.addWidget(self._empty_colors_lbl)
        for color, count in rows:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)

            swatch = QFrame()
            swatch.setFixedSize(18, 18)
            swatch.setFrameShape(QFrame.Shape.Box)
            swatch.setStyleSheet(
                "QFrame {"
                f"background-color: {color};"
                "border: 1px solid palette(mid);"
                "border-radius: 3px;"
                "}"
            )
            label = color_display_name(color)
            if label == "Benutzerfarbe":
                custom_counter += 1
                label = f"Benutzerfarbe {custom_counter}"
            cb = QCheckBox(f"{label} - {int(count)}")
            cb.setChecked(True)
            self._color_checkboxes[str(color)] = cb
            row.addWidget(swatch, alignment=Qt.AlignmentFlag.AlignTop)
            row.addWidget(cb, stretch=1)
            body_layout.addLayout(row)

        body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        return group


__all__ = ["AnnotationExportDialog"]
