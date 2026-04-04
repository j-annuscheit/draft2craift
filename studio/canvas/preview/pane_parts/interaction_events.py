"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)
_IMG_SRC_RE = re.compile(r"\bsrc=(['\"])(.*?)\1", re.IGNORECASE | re.DOTALL)
_IMG_STYLE_RE = re.compile(r"\bstyle=(['\"])(.*?)\1", re.IGNORECASE | re.DOTALL)
_D2C_ROT_STYLE_RE = re.compile(
    r"(?:^|;)\s*(?:--d2c-rot\s*:[^;]*|transform\s*:\s*rotate\(var\(--d2c-rot\)\)|transform-origin\s*:\s*center\s+center)\s*;?",
    re.IGNORECASE,
)
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def eventFilter(self, watched, event):
    is_preview_target = watched in (self._view, self._view.viewport())
    if is_preview_target and event.type() == QEvent.Type.ContextMenu:
        self._open_preview_context_menu(event.globalPos())
        event.accept()
        return True
    if (
        is_preview_target
        and event.type() == QEvent.Type.MouseButtonDblClick
        and event.button() == Qt.MouseButton.LeftButton
    ):
        if self._handle_preview_image_double_click(event.globalPosition().toPoint()):
            event.accept()
            return True
    if (
        is_preview_target
        and event.type() == QEvent.Type.KeyPress
        and event.matches(QKeySequence.StandardKey.Copy)
    ):
        if self._copy_selection_to_clipboard():
            event.accept()
            return True
    if (
        is_preview_target
        and event.type() == QEvent.Type.KeyPress
        and event.matches(QKeySequence.StandardKey.Paste)
    ):
        if self._handle_preview_image_paste():
            event.accept()
            return True
    if (
        self._allow_editing
        and not self._structured_view_active
        and is_preview_target
        and event.type() == QEvent.Type.KeyPress
        and self._is_preview_content_edit_keypress(event)
    ):
        self._preview_user_edit_intent = True
    if (
        self._allow_editing
        and not self._structured_view_active
        and is_preview_target
        and event.type() in (QEvent.Type.InputMethod, QEvent.Type.Drop)
    ):
        self._preview_user_edit_intent = True
    if is_preview_target and event.type() == QEvent.Type.Wheel:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                delta = event.pixelDelta().y()
            if delta > 0:
                self.increase_preview_text_size()
            elif delta < 0:
                self.decrease_preview_text_size()
            event.accept()
            return True
        # Keep wheel scrolling responsive on complex HTML layouts
        # (e.g. large tables) and stop delayed restore timers from
        # snapping the view back while the user scrolls.
        self._mark_view_scroll_interaction()
        delta = self._wheel_scroll_delta_px(event)
        if delta:
            self._queue_wheel_scroll(int(delta))
            event.accept()
            return True
    if is_preview_target and event.type() == QEvent.Type.MouseMove:
        self._update_hover_tooltip(event.globalPosition().toPoint())
    if (
        is_preview_target
        and event.type() == QEvent.Type.MouseButtonRelease
        and event.button() == Qt.MouseButton.LeftButton
    ):
        if self._handle_preview_link_click(event.globalPosition().toPoint()):
            event.accept()
            return True
        if self._handle_highlight_click(event.globalPosition().toPoint()):
            event.accept()
            return True
    if is_preview_target and event.type() == QEvent.Type.Leave:
        QToolTip.hideText()
        self._hovered_highlight_id = ""
    if (
        self._allow_editing
        and not self._structured_view_active
        and is_preview_target
        and event.type() == QEvent.Type.KeyPress
    ):
        if event.key() == Qt.Key.Key_Tab:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._outdent_list_item()
            else:
                self._indent_list_item()
            event.accept()
            return True
    if (
        self._allow_editing
        and is_preview_target
        and event.type() == QEvent.Type.FocusOut
    ):
        QTimer.singleShot(0, self._finish_preview_edit_session)
    return QWidget.eventFilter(self, watched, event)


def _handle_preview_image_paste(self) -> bool:
    if self._structured_view_active or self._view.isReadOnly():
        return False
    editor = getattr(self, "_editor", None)
    if editor is None:
        return False
    insert_image_markdown = getattr(editor, "_insert_image_markdown_from_mime_data", None)
    if not callable(insert_image_markdown):
        return False

    clipboard = QApplication.clipboard()
    if clipboard is None:
        return False
    mime = clipboard.mimeData()
    if mime is None:
        return False

    can_insert = getattr(editor, "canInsertFromMimeData", None)
    if callable(can_insert):
        try:
            if not bool(can_insert(mime)):
                return False
        except Exception:
            pass

    # Commit pending HTML edits first so inserted image links do not overwrite
    # unsynced preview changes.
    try:
        self._commit_preview_edit_to_markdown(
            force=True,
            preserve_reference_linebreaks=True,
        )
    except Exception:
        pass

    # Place markdown cursor close to the current preview caret position.
    try:
        preview_qt_pos = int(self._view.textCursor().position())
        py_pos = int(self._qt_to_py_pos(preview_qt_pos))
        editor_cursor = editor.textCursor()
        editor_cursor.setPosition(max(0, min(py_pos, len(editor.toPlainText()))))
        editor.setTextCursor(editor_cursor)
    except Exception:
        pass

    try:
        inserted = bool(insert_image_markdown(mime))
    except Exception:
        inserted = False
    if not inserted:
        return False

    self._preview_edit_active = False
    self._preview_user_edit_dirty = False
    self._preview_user_edit_intent = False
    self.request_preserve_view_state()
    self.schedule_update()
    self.schedule_cursor_sync()
    self._view.setFocus(Qt.FocusReason.OtherFocusReason)
    return True


def _open_preview_context_menu(self, global_pos: QPoint) -> None:
    if self._open_image_context_menu(global_pos):
        return
    self._open_highlight_context_menu(global_pos)


def _image_source_at_global_pos(self, global_pos: QPoint) -> str:
    vp_pos = self._view.viewport().mapFromGlobal(global_pos)
    cursor = self._view.cursorForPosition(vp_pos)
    char_format = cursor.charFormat()
    if not char_format.isImageFormat():
        return ""
    try:
        image_format = char_format.toImageFormat()
        source = str(image_format.name() or "").strip()
    except Exception:
        return ""
    if not source:
        return ""
    return html.unescape(source).strip()


def _handle_preview_image_double_click(self, global_pos: QPoint) -> bool:
    vp_pos = self._view.viewport().mapFromGlobal(global_pos)
    href = str(self._view.anchorAt(vp_pos) or "").strip()
    if href.startswith("formula://"):
        return False
    source = self._image_source_at_global_pos(global_pos)
    if not source:
        return False
    return self._open_image_zoom_viewer(source)


def _open_image_zoom_viewer(self, image_src: str) -> bool:
    source = str(image_src or "").strip()
    if not source:
        return False
    try:
        from studio.canvas.image_viewer_dialog import ImageViewerDialog

        search_paths = list(self._view.searchPaths() or [])
        dialog = ImageViewerDialog(
            source,
            parent=self,
            search_paths=search_paths,
        )
        open_list = list(getattr(self, "_open_image_viewers", []) or [])
        open_list.append(dialog)
        self._open_image_viewers = open_list
        if hasattr(dialog, "imageChanged"):
            try:
                dialog.imageChanged.connect(
                    lambda _path="": self._on_preview_image_content_changed()
                )
            except Exception:
                pass
        dialog.destroyed.connect(
            lambda _obj=None, dlg=dialog: self._on_image_zoom_viewer_closed(dlg)
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True
    except Exception:
        return False


def _on_image_zoom_viewer_closed(self, dialog: object) -> None:
    current = list(getattr(self, "_open_image_viewers", []) or [])
    self._open_image_viewers = [item for item in current if item is not dialog]


def _on_preview_image_content_changed(self) -> None:
    current_html = str(self._view.document().toHtml() or "")
    if not current_html:
        return
    try:
        _set_preview_html_preserving_state(self, current_html)
    except Exception:
        pass


def _open_image_context_menu(self, global_pos: QPoint) -> bool:
    image_src = self._image_source_at_global_pos(global_pos)
    if not image_src:
        return False

    menu = self._view.createStandardContextMenu()
    if menu.actions():
        menu.addSeparator()
    rotate_action = menu.addAction(
        resolve_feature_label(
            getattr(self, "_user_mode", ""),
            "preview.context.rotate_image_90",
            "Bild um 90° drehen",
        )
    )
    picked = menu.exec(global_pos)
    if picked is None:
        return True
    if self._is_copy_action(picked):
        self._copy_selection_to_clipboard()
        return True
    if picked is rotate_action:
        self._rotate_preview_image(image_src, degrees=90)
        return True
    return True


def _strip_d2c_rotation_style(style_text: str) -> str:
    style = str(style_text or "")
    style = _D2C_ROT_STYLE_RE.sub("", style)
    parts = [segment.strip() for segment in style.split(";") if segment.strip()]
    return "; ".join(parts)


def _normalize_image_source_token(value: str) -> str:
    token = html.unescape(str(value or "").strip())
    if token.startswith("<") and token.endswith(">"):
        token = token[1:-1].strip()
    return token


def _source_to_path_like(value: str):
    from pathlib import Path
    from urllib.parse import unquote

    token = _normalize_image_source_token(value)
    if not token:
        return None
    low = token.lower()
    if low.startswith("data:image/"):
        return None
    if low.startswith("file://"):
        parsed = urlparse(token)
        local = unquote(parsed.path or "")
        if parsed.netloc and parsed.netloc != "localhost":
            local = f"//{parsed.netloc}{local}"
        if not local:
            return None
        try:
            p = Path(local).expanduser()
        except Exception:
            return None
        try:
            return p.resolve(strict=False)
        except Exception:
            return p
    if _SCHEME_RE.match(token):
        return None
    try:
        p = Path(token).expanduser()
    except Exception:
        return None
    if p.is_absolute():
        try:
            return p.resolve(strict=False)
        except Exception:
            return p
    return p


def _parts_end_with(full_parts: tuple[str, ...], suffix_parts: tuple[str, ...]) -> bool:
    if len(suffix_parts) > len(full_parts):
        return False
    return full_parts[-len(suffix_parts) :] == suffix_parts


def _image_sources_match(candidate: str, wanted: str) -> bool:
    left = _normalize_image_source_token(candidate)
    right = _normalize_image_source_token(wanted)
    if not left or not right:
        return False
    if left == right:
        return True

    left_path = _source_to_path_like(left)
    right_path = _source_to_path_like(right)
    if left_path is None or right_path is None:
        return False

    try:
        left_abs = bool(left_path.is_absolute())
        right_abs = bool(right_path.is_absolute())
    except Exception:
        return False

    left_parts = tuple(str(part).casefold() for part in left_path.parts if str(part))
    right_parts = tuple(str(part).casefold() for part in right_path.parts if str(part))
    if left_abs and right_abs:
        return left_parts == right_parts
    if left_abs and (not right_abs):
        return _parts_end_with(left_parts, right_parts)
    if (not left_abs) and right_abs:
        return _parts_end_with(right_parts, left_parts)
    return left_parts == right_parts


def _apply_image_rotation_to_tag(tag: str, *, degrees: int) -> str:
    raw = str(tag or "")
    style_match = _IMG_STYLE_RE.search(raw)
    base_style = _strip_d2c_rotation_style(
        style_match.group(2) if style_match is not None else ""
    )

    next_style = base_style
    if int(degrees) % 360:
        decl = (
            f"--d2c-rot: {int(degrees) % 360}deg; "
            "transform: rotate(var(--d2c-rot)); "
            "transform-origin: center center"
        )
        next_style = f"{base_style}; {decl}" if base_style else decl

    if style_match is not None:
        start, end = style_match.span()
        if next_style:
            return f'{raw[:start]}style="{next_style}"{raw[end:]}'
        return f"{raw[:start]}{raw[end:]}"

    if not next_style:
        return raw
    insert_pos = raw.rfind(">")
    if insert_pos < 0:
        return raw
    return f'{raw[:insert_pos]} style="{next_style}"{raw[insert_pos:]}'


def _apply_preview_image_rotations(
    html_text: str,
    rotations: dict[str, int],
) -> tuple[str, bool]:
    changed = {"value": False}
    rotation_map = {
        str(src): int(angle) % 360
        for src, angle in dict(rotations or {}).items()
        if str(src).strip()
    }

    def _repl(match: re.Match[str]) -> str:
        tag = str(match.group(0) or "")
        src_match = _IMG_SRC_RE.search(tag)
        if src_match is None:
            return tag
        source = html.unescape(str(src_match.group(2) or "").strip())
        if not source:
            return tag
        degrees = 0
        for mapped_source, mapped_angle in rotation_map.items():
            if _image_sources_match(source, mapped_source):
                degrees = int(mapped_angle) % 360
                break
        updated = _apply_image_rotation_to_tag(tag, degrees=degrees)
        if updated != tag:
            changed["value"] = True
        return updated

    rendered = _IMG_TAG_RE.sub(_repl, str(html_text or ""))
    return rendered, bool(changed["value"])


def _replace_image_source_in_tag(tag: str, *, new_source: str) -> str:
    raw = str(tag or "")
    src_match = _IMG_SRC_RE.search(raw)
    if src_match is None:
        return raw
    start, end = src_match.span(2)
    escaped = html.escape(str(new_source or "").strip(), quote=True)
    return f"{raw[:start]}{escaped}{raw[end:]}"


def _rotate_source_to_data_uri(
    source: str,
    *,
    degrees: int,
    search_paths: list[str] | tuple[str, ...] | None = None,
) -> str:
    angle = int(degrees) % 360
    if angle == 0:
        return ""
    try:
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QTransform
        from studio.canvas.image_viewer_dialog import _pixmap_from_source
    except Exception:
        return ""

    pixmap = _pixmap_from_source(source, search_paths=search_paths)
    if pixmap.isNull():
        return ""

    transform = QTransform()
    transform.rotate(float(angle))
    rotated = pixmap.transformed(
        transform,
        Qt.TransformationMode.SmoothTransformation,
    )
    if rotated.isNull():
        return ""

    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        return ""
    try:
        if not rotated.save(buffer, "PNG"):
            return ""
        payload = bytes(buffer.data().toBase64()).decode("ascii")
    except Exception:
        return ""
    finally:
        try:
            buffer.close()
        except Exception:
            pass

    if not payload:
        return ""
    return f"data:image/png;base64,{payload}"


def _apply_preview_image_raster_rotation(
    html_text: str,
    *,
    target_source: str,
    degrees: int,
    search_paths: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, bool]:
    rendered = str(html_text or "")
    normalized_target = _normalize_image_source_token(target_source)
    angle = int(degrees) % 360
    if not normalized_target or angle == 0:
        return rendered, False

    changed = {"value": False}
    data_uri_cache: dict[str, str] = {}

    def _repl(match: re.Match[str]) -> str:
        tag = str(match.group(0) or "")
        src_match = _IMG_SRC_RE.search(tag)
        if src_match is None:
            return tag
        source = html.unescape(str(src_match.group(2) or "").strip())
        if not source or not _image_sources_match(source, normalized_target):
            return tag

        key = _normalize_image_source_token(source)
        data_uri = data_uri_cache.get(key, "")
        if not data_uri:
            data_uri = _rotate_source_to_data_uri(
                source,
                degrees=angle,
                search_paths=search_paths,
            )
            if data_uri:
                data_uri_cache[key] = data_uri
        if not data_uri:
            return tag

        updated = _replace_image_source_in_tag(tag, new_source=data_uri)
        if updated != tag:
            changed["value"] = True
        return updated

    updated_html = _IMG_TAG_RE.sub(_repl, rendered)
    return updated_html, bool(changed["value"])


def _rotate_local_preview_image_source(
    source: str,
    *,
    degrees: int,
    search_paths: list[str] | tuple[str, ...] | None = None,
) -> bool:
    angle = int(degrees) % 360
    token = _normalize_image_source_token(source)
    if not token or angle == 0:
        return False

    try:
        from PySide6.QtGui import QImage, QTransform
        from studio.canvas.image_viewer_dialog import _resolve_local_image_path
    except Exception:
        return False

    path = _resolve_local_image_path(token, search_paths=search_paths)
    if path is None:
        return False

    try:
        image = QImage(str(path))
    except Exception:
        return False
    if image.isNull():
        return False

    transform = QTransform()
    transform.rotate(float(angle))
    rotated = image.transformed(
        transform,
        Qt.TransformationMode.SmoothTransformation,
    )
    if rotated.isNull():
        return False

    temp_path = path.with_name(f".{path.stem}.d2c_rotate_tmp{path.suffix}")
    try:
        if temp_path.exists():
            temp_path.unlink()
    except Exception:
        pass

    try:
        if not rotated.save(str(temp_path)):
            return False
        temp_path.replace(path)
        return True
    except Exception:
        return False
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass


def _set_preview_html_preserving_state(self, html_text: str) -> None:
    view_state = self._capture_view_state()
    self._arm_async_preview_change_suppress()
    self._suppress_preview_change = True
    try:
        self._view.setHtml(str(html_text or ""))
    finally:
        self._suppress_preview_change = False
    self._restore_view_state(view_state, restore_cursor=True)


def _rotate_preview_image(self, image_src: str, *, degrees: int = 90) -> bool:
    source = str(image_src or "").strip()
    if not source:
        return False
    angle = int(degrees) % 360
    if angle == 0:
        return False

    search_paths = list(self._view.searchPaths() or [])
    if _rotate_local_preview_image_source(
        source,
        degrees=angle,
        search_paths=search_paths,
    ):
        current_html = str(self._view.document().toHtml() or "")
        if not current_html:
            return False
        _set_preview_html_preserving_state(self, current_html)
        return True

    current_html = str(self._view.document().toHtml() or "")
    rotated_html, changed = _apply_preview_image_raster_rotation(
        current_html,
        target_source=source,
        degrees=angle,
        search_paths=search_paths,
    )
    if changed:
        _set_preview_html_preserving_state(self, rotated_html)
        return True

    rotations = dict(getattr(self, "_image_rotation_map", {}) or {})
    current = int(rotations.get(source, 0)) % 360
    next_angle = (current + angle) % 360
    if next_angle:
        rotations[source] = next_angle
    else:
        rotations.pop(source, None)

    rotated_html, changed = _apply_preview_image_rotations(current_html, rotations)
    if not changed:
        return False

    self._image_rotation_map = rotations
    _set_preview_html_preserving_state(self, rotated_html)
    return True


def _handle_preview_link_click(self, global_pos: QPoint) -> bool:
    vp_pos = self._view.viewport().mapFromGlobal(global_pos)
    href = str(self._view.anchorAt(vp_pos) or "").strip()
    if not href:
        return False

    if href.startswith("d2c://graph/"):
        return self._handle_graph_action_link(href)

    if href.startswith("formula://"):
        return self._handle_formula_link(href)

    # External / file links are handled manually because openLinks=False.
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href):
        return bool(QDesktopServices.openUrl(QUrl(href)))
    if href.startswith("/"):
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(href)))
    return False
def _handle_graph_action_link(self, href: str) -> bool:
    spec = self._structured_graph_spec
    if spec is None:
        return False

    parsed = urlparse(href)
    if parsed.scheme != "d2c" or parsed.netloc != "graph":
        return False

    action = str(parsed.path or "").strip("/").lower()
    query = parse_qs(parsed.query)
    node_id = str((query.get("id") or [""])[0] or "").strip()
    changed = False

    if action == "toggle":
        node = spec.nodes.get(node_id)
        if node is None or not node.children:
            return False
        if node_id in self._graph_collapsed_ids:
            self._graph_collapsed_ids.discard(node_id)
        else:
            self._graph_collapsed_ids.add(node_id)
        changed = True
    elif action == "focus":
        if node_id in spec.nodes and self._graph_focus_node_id != node_id:
            self._graph_focus_node_id = node_id
            changed = True
    elif action == "clear_focus":
        if self._graph_focus_node_id:
            self._graph_focus_node_id = ""
            changed = True
    elif action == "expand_all":
        if self._graph_collapsed_ids:
            self._graph_collapsed_ids.clear()
            changed = True
    elif action == "collapse_all":
        target = {
            node.node_id
            for node in spec.nodes.values()
            if node.children
        }
        if target != self._graph_collapsed_ids:
            self._graph_collapsed_ids = target
            changed = True
    else:
        return False

    if not changed:
        return True
    self.request_preserve_view_state()
    self._last_rendered_markdown = None
    self.schedule_update()
    return True

def _handle_formula_link(self, href: str) -> bool:
    """Click on a rendered formula image → open FormulaEditorDialog.

    The href format is ``formula://<mode>/<hash>`` where <mode> is 'd'
    (display $$...$$) or 'i' (inline $...$), and <hash> is the sha256
    prefix of the formula content.  The hash lets us find the right
    formula by content rather than by fragile document position.
    """
    # Parse formula://d/abc123 or formula://i/abc123
    tail = href[len("formula://"):]
    parts = tail.split("/", 1)
    if len(parts) != 2 or parts[0] not in ("d", "i"):
        return False
    mode, target_key = parts[0], parts[1]
    is_display_target = (mode == "d")

    if self._editor is None:
        return False

    md = self._editor.get_full_text()

    # Find the formula whose hash matches — same extraction as render_sync._extract_formulas
    import re as _re2
    from studio.canvas.preview.pane_parts.render_sync import (
        _formula_cache_key,
        _resolve_formula_render_color,
    )
    formula_color = _resolve_formula_render_color(self._view)

    formulas: list[tuple[bool, str]] = []  # (is_display, latex_inner)

    def _collect_display(m):
        formulas.append((True, m.group(1).strip()))
        return ""

    def _collect_inline(m):
        formulas.append((False, m.group(1).strip()))
        return ""

    _re2.sub(r'\$\$([\s\S]+?)\$\$', _collect_display, md)
    _re2.sub(r'(?<!\$)\$(?!\$)([^\$\n]+?)\$(?!\$)', _collect_inline, md)

    # Find the matching formula by content hash
    matched_latex = None
    matched_is_display = is_display_target
    for is_display, latex in formulas:
        colored_key = _formula_cache_key(
            latex,
            is_display,
            formula_color=formula_color,
        )
        legacy_key = _formula_cache_key(latex, is_display)
        if target_key in {colored_key, legacy_key}:
            matched_latex = latex
            matched_is_display = is_display
            break

    if matched_latex is None:
        return True  # stale link, consume click

    from studio.canvas.formula_editor import FormulaEditorDialog
    from PySide6.QtWidgets import QDialog

    dlg = FormulaEditorDialog(parent=self, latex=matched_latex, display_mode=matched_is_display)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return True

    new_result = dlg.result_latex().strip()
    if not new_result:
        return True

    # Decode new delimiters
    if new_result.startswith("$$") and new_result.endswith("$$"):
        new_inner = new_result[2:-2].strip()
        new_is_display = True
    elif new_result.startswith("$") and new_result.endswith("$"):
        new_inner = new_result[1:-1].strip()
        new_is_display = False
    else:
        new_inner = new_result
        new_is_display = matched_is_display

    # Replace the FIRST occurrence matching the target hash (by content)
    replaced = [False]

    def _replace_display(m):
        if replaced[0]:
            return m.group(0)
        inner = m.group(1).strip()
        colored_key = _formula_cache_key(
            inner,
            True,
            formula_color=formula_color,
        )
        legacy_key = _formula_cache_key(inner, True)
        if target_key not in {colored_key, legacy_key}:
            return m.group(0)
        replaced[0] = True
        if new_is_display:
            return f"$${new_inner}$$"
        return f"${new_inner}$"

    def _replace_inline(m):
        if replaced[0]:
            return m.group(0)
        inner = m.group(1).strip()
        colored_key = _formula_cache_key(
            inner,
            False,
            formula_color=formula_color,
        )
        legacy_key = _formula_cache_key(inner, False)
        if target_key not in {colored_key, legacy_key}:
            return m.group(0)
        replaced[0] = True
        if new_is_display:
            return f"\n\n$${new_inner}$$\n\n"
        return f"${new_inner}$"

    if matched_is_display:
        new_md = _re2.sub(r'\$\$([\s\S]+?)\$\$', _replace_display, md)
    else:
        new_md = _re2.sub(r'(?<!\$)\$(?!\$)([^\$\n]+?)\$(?!\$)', _replace_inline, md)

    if replaced[0] and new_md != md:
        self._editor.setPlainText(new_md)

    return True


__all__ = [
    "eventFilter",
    "_handle_preview_image_paste",
    "_open_preview_context_menu",
    "_image_source_at_global_pos",
    "_handle_preview_image_double_click",
    "_open_image_zoom_viewer",
    "_on_image_zoom_viewer_closed",
    "_on_preview_image_content_changed",
    "_open_image_context_menu",
    "_strip_d2c_rotation_style",
    "_apply_image_rotation_to_tag",
    "_apply_preview_image_rotations",
    "_apply_preview_image_raster_rotation",
    "_rotate_local_preview_image_source",
    "_rotate_preview_image",
    "_handle_preview_link_click",
    "_handle_graph_action_link",
    "_handle_formula_link",
]
