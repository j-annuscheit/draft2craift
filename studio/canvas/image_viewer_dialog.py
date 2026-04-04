"""Zoomable image viewer dialog with a small paint/rotate editor."""
from __future__ import annotations

import base64
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QPoint, QPointF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

_DATA_IMAGE_RE = re.compile(
    r"^data:image/[a-zA-Z0-9.+-]+;base64,([A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE | re.DOTALL,
)


def _resolve_local_image_path(
    source: str,
    *,
    search_paths: list[str] | tuple[str, ...] | None = None,
) -> Path | None:
    text = str(source or "").strip()
    if not text:
        return None

    if text.lower().startswith("file://"):
        parsed = urlparse(text)
        local = unquote(parsed.path or "")
        if parsed.netloc and parsed.netloc != "localhost":
            local = f"//{parsed.netloc}{local}"
        text = local

    try:
        candidate = Path(text).expanduser()
    except Exception:
        return None

    if candidate.is_absolute():
        try:
            resolved = candidate.resolve(strict=False)
        except Exception:
            resolved = candidate
        if resolved.exists() and resolved.is_file():
            return resolved
        return None

    roots = list(search_paths or [])
    for root in roots:
        base = str(root or "").strip()
        if not base:
            continue
        try:
            joined = (Path(base).expanduser().resolve(strict=False) / candidate).resolve(
                strict=False
            )
        except Exception:
            continue
        if joined.exists() and joined.is_file():
            return joined

    # Final fallback for relative path against current working directory.
    try:
        fallback = candidate.resolve(strict=False)
    except Exception:
        fallback = candidate
    if fallback.exists() and fallback.is_file():
        return fallback
    return None


def _pixmap_from_source(
    source: str,
    *,
    search_paths: list[str] | tuple[str, ...] | None = None,
) -> QPixmap:
    text = str(source or "").strip()
    if not text:
        return QPixmap()

    match = _DATA_IMAGE_RE.match(text)
    if match is not None:
        payload = str(match.group(1) or "")
        try:
            data = base64.b64decode(payload, validate=False)
        except Exception:
            return QPixmap()
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            return pixmap
        return QPixmap()

    path = _resolve_local_image_path(text, search_paths=search_paths)
    if path is None:
        return QPixmap()
    if not path.exists() or not path.is_file():
        return QPixmap()

    pixmap = QPixmap()
    if pixmap.load(str(path)):
        return pixmap
    return QPixmap()


class _ZoomableImageView(QGraphicsView):
    def __init__(
        self,
        scene: QGraphicsScene,
        parent=None,
        *,
        on_zoom=None,
        on_draw_start=None,
        on_draw_move=None,
        on_draw_end=None,
    ):
        super().__init__(scene, parent)
        self._on_zoom = on_zoom
        self._on_draw_start = on_draw_start
        self._on_draw_move = on_draw_move
        self._on_draw_end = on_draw_end
        self._drawing = False
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        factor = 1.15 if delta > 0 else (1.0 / 1.15)
        if callable(self._on_zoom):
            try:
                self._on_zoom()
            except Exception:
                pass
        self.scale(factor, factor)
        event.accept()

    def _event_scene_pos(self, event) -> QPointF:
        try:
            vp = event.position().toPoint()
        except Exception:
            vp = event.pos()
        return self.mapToScene(vp)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and callable(self._on_draw_start):
            try:
                started = bool(self._on_draw_start(self._event_scene_pos(event)))
            except Exception:
                started = False
            if started:
                self._drawing = True
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drawing and callable(self._on_draw_move):
            try:
                self._on_draw_move(self._event_scene_pos(event))
                event.accept()
                return
            except Exception:
                self._drawing = False
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drawing and event.button() == Qt.MouseButton.LeftButton:
            self._drawing = False
            if callable(self._on_draw_end):
                try:
                    self._on_draw_end()
                except Exception:
                    pass
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ImageViewerDialog(QDialog):
    """Simple image viewer/editor with zoom, rotate and basic painting."""

    imageChanged = Signal(str)

    _COLOR_PRESETS: tuple[tuple[str, str], ...] = (
        ("Schwarz", "#000000"),
        ("Weiß", "#FFFFFF"),
        ("Rot", "#E53935"),
        ("Grün", "#43A047"),
        ("Blau", "#1E88E5"),
        ("Gelb", "#FDD835"),
        ("Violett", "#8E24AA"),
        ("Orange", "#FB8C00"),
    )

    def __init__(
        self,
        source: str,
        parent=None,
        *,
        search_paths: list[str] | tuple[str, ...] | None = None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("Bildansicht")
        self._source = str(source or "").strip()
        self._search_paths = list(search_paths or [])
        self._local_path = _resolve_local_image_path(
            self._source,
            search_paths=self._search_paths,
        )
        self._item: QGraphicsPixmapItem | None = None
        self._base_image: QImage | None = None
        self._overlay_image: QImage | None = None
        self._last_draw_point: QPoint | None = None
        self._stroke_changed = False
        self._user_has_zoomed = False
        self._auto_fit_pending = False
        self._dirty = False
        self._brush_color = QColor("#E53935")
        self._brush_size = 4
        self._eraser_enabled = False
        self._controls: list[QWidget] = []
        self._configure_initial_geometry(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        root.addLayout(self._build_toolbar())

        self._hint = QLabel("")
        root.addWidget(self._hint)

        self._scene = QGraphicsScene(self)
        self._view = _ZoomableImageView(
            self._scene,
            self,
            on_zoom=self._on_user_zoom,
            on_draw_start=self._on_draw_start,
            on_draw_move=self._on_draw_move,
            on_draw_end=self._on_draw_end,
        )
        self._view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._view, 1)

        pixmap = _pixmap_from_source(self._source, search_paths=self._search_paths)
        if pixmap.isNull():
            self._hint.setText("Bild konnte nicht geladen werden.")
            self._set_controls_enabled(False)
            return

        base = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        self._base_image = base
        self._overlay_image = self._new_overlay_like(base)
        self._refresh_pixmap_item()
        self._set_controls_enabled(True)
        self._update_hint_default()
        self._auto_fit_pending = True
        QTimer.singleShot(0, self._fit_item_to_view)

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._btn_rotate_left = QPushButton("↺ 90°")
        self._btn_rotate_right = QPushButton("↻ 90°")
        self._btn_fit = QPushButton("Einpassen")
        self._btn_save = QPushButton("Speichern")
        self._btn_eraser = QPushButton("Radierer")
        self._btn_color_custom = QPushButton("Farbe…")
        self._color_combo = QComboBox()
        self._brush_size_spin = QSpinBox()
        self._brush_size_spin.setRange(1, 64)
        self._brush_size_spin.setValue(self._brush_size)
        self._btn_eraser.setCheckable(True)

        for name, hex_color in self._COLOR_PRESETS:
            self._color_combo.addItem(name, hex_color)
        self._color_combo.setCurrentIndex(2)  # Rot

        row.addWidget(self._btn_rotate_left)
        row.addWidget(self._btn_rotate_right)
        row.addWidget(self._btn_fit)
        row.addWidget(QLabel("Farbe:"))
        row.addWidget(self._color_combo)
        row.addWidget(self._btn_color_custom)
        row.addWidget(QLabel("Stift:"))
        row.addWidget(self._brush_size_spin)
        row.addWidget(self._btn_eraser)
        row.addStretch(1)
        row.addWidget(self._btn_save)

        self._controls = [
            self._btn_rotate_left,
            self._btn_rotate_right,
            self._btn_fit,
            self._btn_save,
            self._btn_eraser,
            self._btn_color_custom,
            self._color_combo,
            self._brush_size_spin,
        ]

        self._btn_rotate_left.clicked.connect(lambda: self._rotate_image(-90))
        self._btn_rotate_right.clicked.connect(lambda: self._rotate_image(90))
        self._btn_fit.clicked.connect(self._on_fit_clicked)
        self._btn_save.clicked.connect(self._save_current_image)
        self._btn_eraser.toggled.connect(self._on_eraser_toggled)
        self._btn_color_custom.clicked.connect(self._pick_custom_color)
        self._color_combo.currentIndexChanged.connect(self._on_color_changed)
        self._brush_size_spin.valueChanged.connect(self._on_brush_size_changed)
        return row

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in list(self._controls):
            try:
                widget.setEnabled(bool(enabled))
            except Exception:
                continue
        if hasattr(self, "_btn_save") and self._btn_save is not None:
            self._btn_save.setEnabled(bool(enabled) and self._local_path is not None)

    def _update_hint_default(self) -> None:
        if self._local_path is not None:
            self._hint.setText(
                "Mausrad: Zoom  |  Linke Maustaste: Malen  |  Radierer löscht nur neue Striche."
            )
            return
        self._hint.setText(
            "Mausrad: Zoom  |  Linke Maustaste: Malen  |  Kein lokaler Bildpfad (nur Vorschau-Bearbeitung)."
        )

    def _new_overlay_like(self, base: QImage) -> QImage:
        overlay = QImage(
            base.width(),
            base.height(),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        overlay.fill(Qt.GlobalColor.transparent)
        return overlay

    def _composited_image(self) -> QImage:
        if self._base_image is None or self._base_image.isNull():
            return QImage()
        combined = QImage(self._base_image)
        if self._overlay_image is None or self._overlay_image.isNull():
            return combined
        painter = QPainter(combined)
        try:
            painter.drawImage(0, 0, self._overlay_image)
        finally:
            painter.end()
        return combined

    def _refresh_pixmap_item(self) -> None:
        combined = self._composited_image()
        if combined.isNull():
            return
        pixmap = QPixmap.fromImage(combined)
        if pixmap.isNull():
            return
        if self._item is None:
            self._item = QGraphicsPixmapItem(pixmap)
            self._scene.addItem(self._item)
        else:
            self._item.setPixmap(pixmap)
        self._scene.setSceneRect(self._item.sceneBoundingRect())

    def _on_fit_clicked(self) -> None:
        self._user_has_zoomed = False
        self._fit_item_to_view()

    def _on_color_changed(self, _index: int) -> None:
        if not hasattr(self, "_color_combo"):
            return
        value = str(self._color_combo.currentData() or "").strip()
        color = QColor(value)
        if color.isValid():
            self._brush_color = color

    def _pick_custom_color(self) -> None:
        color = QColorDialog.getColor(self._brush_color, self, "Farbe wählen")
        if not isinstance(color, QColor) or not color.isValid():
            return
        self._brush_color = color

    def _on_brush_size_changed(self, value: int) -> None:
        self._brush_size = max(1, int(value))

    def _on_eraser_toggled(self, checked: bool) -> None:
        self._eraser_enabled = bool(checked)

    def _effective_pen_width(self) -> int:
        base = max(1, int(self._brush_size))
        if self._eraser_enabled:
            return max(2, base * 2)
        return base

    def _scene_to_image_point(self, scene_pos: QPointF) -> QPoint | None:
        if self._base_image is None or self._base_image.isNull():
            return None
        x = int(round(float(scene_pos.x())))
        y = int(round(float(scene_pos.y())))
        width = int(self._base_image.width())
        height = int(self._base_image.height())
        if width <= 0 or height <= 0:
            return None
        x = max(0, min(width - 1, x))
        y = max(0, min(height - 1, y))
        return QPoint(x, y)

    def _paint_segment(self, start: QPoint, end: QPoint) -> bool:
        if self._overlay_image is None or self._overlay_image.isNull():
            return False
        painter = QPainter(self._overlay_image)
        try:
            if self._eraser_enabled:
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                pen = QPen(QColor(0, 0, 0, 0))
            else:
                pen = QPen(self._brush_color)
            pen.setWidth(self._effective_pen_width())
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            if start == end:
                painter.drawPoint(start)
            else:
                painter.drawLine(start, end)
            return True
        except Exception:
            return False
        finally:
            painter.end()

    def _on_draw_start(self, scene_pos: QPointF) -> bool:
        point = self._scene_to_image_point(scene_pos)
        if point is None:
            return False
        self._last_draw_point = point
        self._stroke_changed = False
        if self._paint_segment(point, point):
            self._stroke_changed = True
            self._refresh_pixmap_item()
        return True

    def _on_draw_move(self, scene_pos: QPointF) -> None:
        if self._last_draw_point is None:
            return
        point = self._scene_to_image_point(scene_pos)
        if point is None:
            return
        if self._paint_segment(self._last_draw_point, point):
            self._stroke_changed = True
            self._last_draw_point = point
            self._refresh_pixmap_item()

    def _on_draw_end(self) -> None:
        self._last_draw_point = None
        if not self._stroke_changed:
            return
        self._commit_image_edit()

    def _rotate_image(self, degrees: int) -> None:
        if self._base_image is None or self._base_image.isNull():
            return
        angle = int(degrees) % 360
        if angle == 0:
            return
        transform = QTransform()
        transform.rotate(float(angle))
        rotated_base = self._base_image.transformed(
            transform,
            Qt.TransformationMode.SmoothTransformation,
        )
        if rotated_base.isNull():
            return
        if self._overlay_image is not None and not self._overlay_image.isNull():
            rotated_overlay = self._overlay_image.transformed(
                transform,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            rotated_overlay = QImage()
        self._base_image = rotated_base.convertToFormat(QImage.Format.Format_ARGB32)
        if rotated_overlay.isNull():
            self._overlay_image = self._new_overlay_like(self._base_image)
        else:
            self._overlay_image = rotated_overlay.convertToFormat(
                QImage.Format.Format_ARGB32_Premultiplied
            )
        self._refresh_pixmap_item()
        if not self._user_has_zoomed:
            self._auto_fit_pending = True
            QTimer.singleShot(0, self._fit_item_to_view)
        self._commit_image_edit()

    def _commit_image_edit(self) -> None:
        self._dirty = True
        if self._local_path is None:
            self._hint.setText(
                "Änderung in der Vorschau aktiv. Kein lokaler Pfad zum Speichern vorhanden."
            )
            return
        if self._save_current_image():
            self._dirty = False
            self._update_hint_default()
        else:
            self._hint.setText("Speichern fehlgeschlagen.")

    def _save_current_image(self) -> bool:
        combined = self._composited_image()
        if combined.isNull():
            return False
        if self._local_path is None:
            return False
        path = self._local_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            return False

        temp_path = path.with_name(f".{path.stem}.d2c_edit_tmp{path.suffix}")
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass

        try:
            if not combined.save(str(temp_path)):
                return False
            temp_path.replace(path)
        except Exception:
            return False
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass

        self._dirty = False
        self.imageChanged.emit(str(path))
        return True

    def _configure_initial_geometry(self, parent) -> None:
        screen = None
        if parent is not None and hasattr(parent, "screen"):
            try:
                screen = parent.screen()
            except Exception:
                screen = None
        if screen is None:
            app = QApplication.instance()
            if app is not None:
                try:
                    screen = app.primaryScreen()
                except Exception:
                    screen = None
        if screen is None:
            self.resize(1100, 800)
            return

        available = screen.availableGeometry()
        # Keep the dialog in a moderate size on open (not near fullscreen).
        width = 1100
        height = 800
        try:
            if parent is not None:
                parent_geom = parent.frameGeometry()
                if parent_geom.isValid():
                    width = min(width, int(parent_geom.width() * 0.78))
                    height = min(height, int(parent_geom.height() * 0.78))
        except Exception:
            pass
        width = max(760, width)
        height = max(560, height)
        width = min(width, int(available.width() * 0.92))
        height = min(height, int(available.height() * 0.92))
        self.resize(width, height)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _on_user_zoom(self) -> None:
        self._user_has_zoomed = True

    def _fit_item_to_view(self) -> None:
        if self._item is None:
            return
        rect = self._item.sceneBoundingRect()
        if rect.isNull():
            return
        self._view.resetTransform()
        self._view.setSceneRect(rect)
        self._view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._view.centerOn(self._item)
        self._auto_fit_pending = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._item is None:
            return
        if self._auto_fit_pending or (not self._user_has_zoomed):
            QTimer.singleShot(0, self._fit_item_to_view)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._item is None:
            return
        if self._user_has_zoomed:
            return
        QTimer.singleShot(0, self._fit_item_to_view)


__all__ = ["ImageViewerDialog", "_pixmap_from_source", "_resolve_local_image_path"]
