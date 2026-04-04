"""Core markdown editor widget used across canvas and knowledge panels."""
from __future__ import annotations

import datetime as dt
import html as html_mod
import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse
import weakref

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QAction, QContextMenuEvent, QFont, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QWidget

from shared.config.paths import app_data_dir
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
    _IMAGE_EXTENSIONS = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".webp",
        ".tif",
        ".tiff",
        ".svg",
        ".avif",
    }
    _MD_IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\(\s*(<[^>]+>|[^)\s]+)\s*\)")
    _HTML_IMG_SRC_RE = re.compile(
        r"<img\b[^>]*\bsrc=(['\"])(.*?)\1",
        re.IGNORECASE | re.DOTALL,
    )
    _DATA_IMAGE_RE = re.compile(
        r"^data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)$",
        re.IGNORECASE | re.DOTALL,
    )
    _SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
    _WINDOWS_ABS_RE = re.compile(r"^[a-zA-Z]:[\\/]")
    _IMAGE_COPY_FAILED_MARKER = "<!-- image-copy-failed -->"

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

    def canInsertFromMimeData(self, source: QMimeData) -> bool:
        if source is not None:
            if source.hasImage():
                return True
            if source.hasUrls():
                for path in self._extract_local_image_paths_from_mime_urls(source):
                    if self._is_supported_image_file(path):
                        return True
            for path in self._extract_local_image_paths_from_text(source.text()):
                if self._is_supported_image_file(path):
                    return True
            if self._extract_remote_image_refs_from_mime_data(source):
                return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source is None:
            super().insertFromMimeData(source)
            return
        if self._insert_image_markdown_from_mime_data(source):
            return
        if not source.hasText():
            super().insertFromMimeData(source)
            return
        normalized = self._normalize_paste_text(source.text())
        mime = QMimeData()
        mime.setText(normalized)
        super().insertFromMimeData(mime)

    def paste_image_from_clipboard(self) -> bool:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return False
        mime = clipboard.mimeData()
        if mime is None:
            return False
        return self._insert_image_markdown_from_mime_data(mime)

    def _insert_image_markdown_from_mime_data(self, source: QMimeData) -> bool:
        # Resolve one source class per paste in priority order to avoid
        # duplicates when clipboards expose both image data and image URL text.
        entries: list[str] = self._markdown_images_from_mime_urls(source)
        if not entries:
            entries = self._markdown_images_from_text_paths(source)
        if not entries:
            image_markdown = self._markdown_image_from_mime_data(source)
            if image_markdown:
                entries = [image_markdown]
        if not entries:
            remote_entries, attempted_remote = self._markdown_images_from_remote_refs(source)
            entries = list(
                dict.fromkeys([str(item or "").strip() for item in remote_entries if item])
            )
            if not entries and attempted_remote > 0:
                cursor = self.textCursor()
                cursor.insertText(self._IMAGE_COPY_FAILED_MARKER)
                self.setTextCursor(cursor)
                self.setFocus()
                return True
        if not entries:
            return False
        cursor = self.textCursor()
        payload = "\n".join(entries)
        cursor.insertText(payload)
        self.setTextCursor(cursor)
        self.setFocus()
        return True

    def _markdown_image_from_mime_data(self, source: QMimeData) -> str:
        image = self._extract_image_from_mime_data(source)
        if image is None or image.isNull():
            return ""
        saved = self._save_clipboard_image(image)
        if not saved:
            return ""
        return self._build_markdown_image_link("clipboard-image", saved)

    def _markdown_images_from_mime_urls(self, source: QMimeData) -> list[str]:
        if source is None or not source.hasUrls():
            return []
        out: list[str] = []
        for path in self._extract_local_image_paths_from_mime_urls(source):
            if not self._is_supported_image_file(path):
                continue
            saved = self._save_local_image_file(path)
            if not saved:
                continue
            out.append(self._build_markdown_image_link("clipboard-image", saved))
        return out

    def _markdown_images_from_text_paths(self, source: QMimeData) -> list[str]:
        if source is None:
            return []
        out: list[str] = []
        for path in self._extract_local_image_paths_from_text(source.text()):
            if not self._is_supported_image_file(path):
                continue
            saved = self._save_local_image_file(path)
            if not saved:
                continue
            out.append(self._build_markdown_image_link("clipboard-image", saved))
        return out

    def _markdown_images_from_remote_refs(
        self,
        source: QMimeData,
    ) -> tuple[list[str], int]:
        refs = self._extract_remote_image_refs_from_mime_data(source)
        if not refs:
            return [], 0
        out: list[str] = []
        for alt, image_source in refs:
            saved = self._save_remote_or_data_image_source(image_source)
            if not saved:
                continue
            out.append(self._build_markdown_image_link(alt, saved))
        return out, len(refs)

    def _extract_remote_image_refs_from_mime_data(
        self,
        source: QMimeData,
    ) -> list[tuple[str, str]]:
        if source is None:
            return []
        out: list[tuple[str, str]] = []
        seen: set[str] = set()

        def _append(alt_text: str, raw_source: str) -> None:
            normalized = self._normalize_image_source(raw_source)
            if not normalized:
                return
            if not (self._is_http_source(normalized) or self._is_data_image_source(normalized)):
                return
            key = str(normalized)
            if key in seen:
                return
            seen.add(key)
            out.append((self._normalize_markdown_alt_text(alt_text), normalized))

        for alt_text, image_source in self._extract_markdown_image_refs_from_text(
            source.text()
        ):
            _append(alt_text, image_source)

        if source.hasHtml():
            for image_source in self._extract_image_sources_from_html(source.html()):
                _append("clipboard-image", image_source)

        if source.hasUrls():
            for url in source.urls() or []:
                try:
                    if url.isLocalFile():
                        continue
                    as_text = str(url.toString() or "").strip()
                except Exception:
                    continue
                if self._is_http_source(as_text) and self._looks_like_image_url(as_text):
                    _append("clipboard-image", as_text)

        text = str(source.text() or "").strip()
        if self._is_http_source(text) and self._looks_like_image_url(text):
            _append("clipboard-image", text)

        return out

    @staticmethod
    def _strip_angle_brackets(source: str) -> str:
        text = str(source or "").strip()
        if text.startswith("<") and text.endswith(">"):
            return text[1:-1].strip()
        return text

    def _normalize_image_source(self, source: str) -> str:
        return self._strip_angle_brackets(str(source or "").strip())

    @classmethod
    def _is_data_image_source(cls, source: str) -> bool:
        return cls._DATA_IMAGE_RE.match(str(source or "").strip()) is not None

    @classmethod
    def _is_http_source(cls, source: str) -> bool:
        text = str(source or "").strip().lower()
        return text.startswith("http://") or text.startswith("https://")

    @classmethod
    def _looks_like_image_url(cls, source: str) -> bool:
        text = str(source or "").strip()
        if not text:
            return False
        try:
            parsed = urlparse(text)
        except Exception:
            return False
        suffix = str(Path(parsed.path or "").suffix or "").lower()
        if suffix in cls._IMAGE_EXTENSIONS:
            return True
        query = str(parsed.query or "").lower()
        hints = (
            "format=jpg",
            "format=jpeg",
            "format=png",
            "format=webp",
            "format=gif",
            "fm=jpg",
            "fm=jpeg",
            "fm=png",
            "fm=webp",
            "image",
        )
        return any(hint in query for hint in hints)

    @classmethod
    def _extract_image_sources_from_html(cls, html_text: str) -> list[str]:
        text = str(html_text or "")
        if not text:
            return []
        out: list[str] = []
        for match in cls._HTML_IMG_SRC_RE.finditer(text):
            raw = html_mod.unescape(str(match.group(2) or "").strip())
            if raw:
                out.append(raw)
        return out

    @classmethod
    def _extract_markdown_image_refs_from_text(
        cls,
        text: str,
    ) -> list[tuple[str, str]]:
        raw_text = str(text or "")
        if not raw_text:
            return []
        out: list[tuple[str, str]] = []
        for match in cls._MD_IMAGE_LINK_RE.finditer(raw_text):
            alt = str(match.group(1) or "").strip()
            target = cls._strip_angle_brackets(str(match.group(2) or ""))
            if target:
                out.append((alt, target))
        return out

    @classmethod
    def _extract_local_image_paths_from_text(cls, text: str) -> list[Path]:
        raw_text = str(text or "")
        if not raw_text.strip():
            return []

        candidates: list[str] = []
        for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            token = str(line or "").strip()
            if token:
                candidates.append(token)
        for _alt, target in cls._extract_markdown_image_refs_from_text(raw_text):
            candidates.append(target)

        out: list[Path] = []
        seen: set[str] = set()
        for item in candidates:
            resolved = cls._source_to_local_path(item)
            if resolved is None:
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            out.append(resolved)
        return out

    @classmethod
    def _source_to_local_path(cls, source: str) -> Path | None:
        text = cls._strip_angle_brackets(source)
        if not text:
            return None
        lowered = text.lower()
        if lowered.startswith("file://"):
            try:
                parsed = urlparse(text)
                local = unquote(parsed.path or "")
                if parsed.netloc and parsed.netloc != "localhost":
                    local = f"//{parsed.netloc}{local}"
                if not local:
                    return None
                return Path(local).expanduser().resolve(strict=False)
            except Exception:
                return None
        if cls._SCHEME_RE.match(text):
            return None
        try:
            candidate = Path(text).expanduser()
        except Exception:
            return None
        if cls._WINDOWS_ABS_RE.match(text) or candidate.is_absolute():
            try:
                return candidate.resolve(strict=False)
            except Exception:
                return candidate
        return None

    @classmethod
    def _image_ext_from_data_mime_subtype(cls, subtype: str) -> str:
        token = str(subtype or "").strip().lower().split(";", 1)[0].strip()
        if token == "jpeg":
            token = "jpg"
        if token == "svg+xml":
            token = "svg"
        token = re.sub(r"[^a-z0-9]+", "", token)
        ext = f".{token or 'png'}"
        if ext in cls._IMAGE_EXTENSIONS:
            return ext
        return ".png"

    @classmethod
    def _decode_data_image_source(cls, source: str) -> tuple[bytes, str] | None:
        import base64

        match = cls._DATA_IMAGE_RE.match(str(source or ""))
        if match is None:
            return None
        subtype = str(match.group(1) or "").strip()
        payload = str(match.group(2) or "")
        try:
            blob = base64.b64decode(payload, validate=False)
        except Exception:
            return None
        if not blob:
            return None
        return blob, cls._image_ext_from_data_mime_subtype(subtype)

    @classmethod
    def _image_ext_from_content_type(cls, content_type: str) -> str:
        token = str(content_type or "").strip().lower().split(";", 1)[0].strip()
        if not token.startswith("image/"):
            return ""
        subtype = token.split("/", 1)[1].strip()
        if subtype == "jpeg":
            subtype = "jpg"
        if subtype == "svg+xml":
            subtype = "svg"
        subtype = re.sub(r"[^a-z0-9]+", "", subtype)
        if not subtype:
            return ""
        ext = f".{subtype}"
        if ext in cls._IMAGE_EXTENSIONS:
            return ext
        return ""

    def _fetch_remote_image_bytes(self, source: str) -> tuple[bytes, str] | None:
        import urllib.request

        url = str(source or "").strip()
        if not self._is_http_source(url):
            return None
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; draft2craift-clipboard/1.0)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                payload = bytes(response.read() or b"")
                content_type = ""
                headers = getattr(response, "headers", None)
                if headers is not None:
                    try:
                        content_type = str(headers.get("Content-Type", "") or "")
                    except Exception:
                        content_type = ""
                if not content_type:
                    try:
                        content_type = str(response.getheader("Content-Type") or "")
                    except Exception:
                        content_type = ""
        except Exception:
            return None

        if not payload:
            return None
        ext = self._image_ext_from_content_type(content_type)
        if not ext:
            try:
                suffix = str(Path(urlparse(url).path).suffix or "").lower()
            except Exception:
                suffix = ""
            if suffix in self._IMAGE_EXTENSIONS:
                ext = suffix
        if not ext:
            return None
        # Avoid saving HTML/error pages under an image extension.
        if ext != ".svg":
            probe = QImage.fromData(payload)
            if probe.isNull():
                return None
        return payload, ext

    def _save_remote_or_data_image_source(self, source: str) -> str:
        normalized = self._normalize_image_source(source)
        if not normalized:
            return ""

        decoded = self._decode_data_image_source(normalized)
        if decoded is not None:
            payload, ext = decoded
            return self._save_image_bytes(payload, extension=ext)

        fetched = self._fetch_remote_image_bytes(normalized)
        if fetched is None:
            return ""
        payload, ext = fetched
        return self._save_image_bytes(payload, extension=ext)

    def _save_image_bytes(self, payload: bytes, *, extension: str) -> str:
        resolved = self._resolve_image_storage_target()
        if resolved is None:
            return ""
        target_dir, markdown_prefix = resolved
        target = self._next_image_target_path(target_dir=target_dir, extension=extension)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        except Exception:
            return ""
        return self._markdown_path_for_saved_image(
            saved_path=target,
            markdown_prefix=markdown_prefix,
        )

    @staticmethod
    def _normalize_markdown_alt_text(alt_text: str) -> str:
        cleaned = (
            str(alt_text or "")
            .replace("\r", " ")
            .replace("\n", " ")
            .replace("[", "\\[")
            .replace("]", "\\]")
            .strip()
        )
        return cleaned or "clipboard-image"

    def _build_markdown_image_link(self, alt_text: str, target: str) -> str:
        alt = self._normalize_markdown_alt_text(alt_text)
        return f"![{alt}](<{target}>)"

    @staticmethod
    def _extract_image_from_mime_data(source: QMimeData) -> QImage | None:
        if source is None:
            return None
        if source.hasImage():
            try:
                data = source.imageData()
            except Exception:
                data = None
            if isinstance(data, QImage) and not data.isNull():
                return data
            if isinstance(data, QPixmap) and not data.isNull():
                return data.toImage()
        return None

    @staticmethod
    def _extract_local_image_paths_from_mime_urls(source: QMimeData) -> list[Path]:
        if source is None or not source.hasUrls():
            return []
        out: list[Path] = []
        seen: set[str] = set()
        for url in source.urls() or []:
            try:
                if not url.isLocalFile():
                    continue
                raw = str(url.toLocalFile() or "").strip()
            except Exception:
                continue
            if not raw:
                continue
            try:
                path = Path(raw).expanduser().resolve(strict=False)
            except Exception:
                path = Path(raw)
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
        return out

    def _is_supported_image_file(self, path: Path) -> bool:
        candidate = Path(path)
        if not candidate.exists() or not candidate.is_file():
            return False
        if str(candidate.suffix or "").lower() in self._IMAGE_EXTENSIONS:
            return True
        try:
            probe = QImage(str(candidate))
            return not probe.isNull()
        except Exception:
            return False

    @staticmethod
    def _timestamp_token() -> str:
        return dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    def _next_image_target_path(
        self,
        *,
        target_dir: Path,
        extension: str,
    ) -> Path:
        ext = str(extension or "").strip().lower()
        if not ext.startswith("."):
            ext = f".{ext}" if ext else ".png"
        if not ext:
            ext = ".png"
        token = self._timestamp_token()
        return (target_dir / f"clipboard_{token}{ext}").resolve(strict=False)

    def _save_clipboard_image(self, image: QImage) -> str:
        resolved = self._resolve_image_storage_target()
        if resolved is None:
            return ""
        target_dir, markdown_prefix = resolved
        target = self._next_image_target_path(target_dir=target_dir, extension=".png")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            ok = bool(image.save(str(target), "PNG"))
        except Exception:
            ok = False
        if not ok:
            return ""
        return self._markdown_path_for_saved_image(
            saved_path=target,
            markdown_prefix=markdown_prefix,
        )

    def _save_local_image_file(self, source_path: Path) -> str:
        resolved = self._resolve_image_storage_target()
        if resolved is None:
            return ""
        target_dir, markdown_prefix = resolved
        src = Path(source_path)
        ext = str(src.suffix or "").lower() or ".png"
        target = self._next_image_target_path(target_dir=target_dir, extension=ext)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            return self._markdown_path_for_saved_image(
                saved_path=target,
                markdown_prefix=markdown_prefix,
            )
        except Exception:
            pass
        try:
            image = QImage(str(src))
            if image.isNull():
                return ""
            target_png = self._next_image_target_path(target_dir=target_dir, extension=".png")
            ok = bool(image.save(str(target_png), "PNG"))
            if not ok:
                return ""
            return self._markdown_path_for_saved_image(
                saved_path=target_png,
                markdown_prefix=markdown_prefix,
            )
        except Exception:
            return ""

    @staticmethod
    def _markdown_path_for_saved_image(
        *,
        saved_path: Path,
        markdown_prefix: str,
    ) -> str:
        prefix = str(markdown_prefix or "").strip().strip("/")
        if prefix:
            return f"{prefix}/{Path(saved_path).name}"
        return str(Path(saved_path).resolve(strict=False))

    def _resolve_image_storage_target(self) -> tuple[Path, str] | None:
        window = self.window()
        manager = getattr(window, "_project_manager", None)
        current_project = getattr(manager, "current_project_folder", None)
        if current_project:
            try:
                base = Path(current_project).resolve(strict=False)
                return (
                    (base / "canvas" / "assets" / "clipboard").resolve(strict=False),
                    "assets/clipboard",
                )
            except Exception:
                pass

        autosave_ctrl = getattr(window, "_autosave_ctrl", None)
        autosave_dir = getattr(autosave_ctrl, "autosave_dir", None)
        if autosave_dir:
            try:
                return (
                    (
                        Path(autosave_dir).resolve(strict=False)
                        / "canvas"
                        / "assets"
                        / "clipboard"
                    ).resolve(strict=False),
                    "assets/clipboard",
                )
            except Exception:
                pass

        try:
            fallback = app_data_dir() / "clipboard_images"
            return fallback.resolve(strict=False), ""
        except Exception:
            return None

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
