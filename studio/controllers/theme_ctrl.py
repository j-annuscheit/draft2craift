"""Theme controller — UI theme and preview settings."""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QStatusBar

from shared.config.setting_keys import ThemeSettingsKeys
from studio.canvas.editor import MarkdownEditor
from studio.canvas.highlighter import MarkdownHighlighter
from studio.canvas.preview.pane import CanvasPreviewPane
from studio.canvas.preview.style_settings import (
    default_preview_style_settings,
    normalize_preview_style_settings,
    resolve_preview_style_tokens,
)
from studio.dialogs.window_manager import find_dialog_manager
from studio.theme import apply_theme, normalize_theme_id, theme_tokens

_LOG = logging.getLogger(__name__)


class ThemeController:
    """Applies and tracks theme changes, and preview margin/theme settings."""

    _THEME_SETTING_KEY = ThemeSettingsKeys.UI_THEME
    _PREVIEW_MARGIN_ENABLED_KEY = ThemeSettingsKeys.PREVIEW_PAGE_MARGIN_ENABLED
    _PREVIEW_MARGIN_EM_KEY = ThemeSettingsKeys.PREVIEW_PAGE_MARGIN_EM
    _PREVIEW_THEME_KEY = ThemeSettingsKeys.PREVIEW_MARKDOWN_THEME
    _PREVIEW_STYLE_KEY = ThemeSettingsKeys.PREVIEW_STYLE_SETTINGS

    def __init__(
        self,
        *,
        app_settings: QSettings,
        parent_window: QMainWindow,
        autosave_schedule_fn: Callable[[int], None],
    ):
        self._app_settings = app_settings
        self._parent_window = parent_window
        self._autosave_schedule_fn = autosave_schedule_fn
        self._theme_id: str = self._load_theme_id()

    # ── Theme ──────────────────────────────────────────────────────────

    def get_theme_id(self) -> str:
        return normalize_theme_id(getattr(self, "_theme_id", "dark"))

    def apply_theme_id(self, theme_id: object, persist: bool = True) -> None:
        normalized = normalize_theme_id(theme_id)
        app = QApplication.instance()
        if app is not None:
            normalized = apply_theme(app, normalized)
        self._theme_id = normalized
        # Apply chrome to window
        self.apply_window_chrome()
        self._apply_preview_style_runtime(force=True)
        if hasattr(self._parent_window, "canvas"):
            self.refresh_all_preview_overlays()
        if persist:
            self._persist_theme_id(normalized)
            try:
                self._autosave_schedule_fn(220)
            except Exception:
                _LOG.warning(
                    "Theme autosave scheduling failed after apply_theme_id",
                    exc_info=True,
                )

    def _load_theme_id(self) -> str:
        raw = self._app_settings.value(self._THEME_SETTING_KEY, "dark")
        return normalize_theme_id(raw)

    def _persist_theme_id(self, theme_id: str) -> None:
        normalized = normalize_theme_id(theme_id)
        self._app_settings.setValue(self._THEME_SETTING_KEY, normalized)
        self._app_settings.sync()

    # ── Preview theme ──────────────────────────────────────────────────

    def get_preview_theme_id(self) -> str:
        return CanvasPreviewPane.global_preview_theme_id()

    def apply_preview_theme_id(
        self,
        theme_id: object,
        *,
        persist: bool = True,
    ) -> None:
        CanvasPreviewPane.apply_global_preview_theme(theme_id)
        self._apply_preview_style_runtime(force=True)
        if persist:
            self._persist_preview_theme_id(theme_id)
            try:
                self._autosave_schedule_fn(220)
            except Exception:
                _LOG.warning(
                    "Theme autosave scheduling failed after apply_preview_theme_id",
                    exc_info=True,
                )

    def load_preview_theme_id(self) -> str:
        value = self._app_settings.value(
            self._PREVIEW_THEME_KEY,
            CanvasPreviewPane.preview_theme_default_id(),
        )
        return CanvasPreviewPane.normalize_preview_theme_id(value)

    def _persist_preview_theme_id(self, theme_id: object) -> None:
        normalized = CanvasPreviewPane.normalize_preview_theme_id(theme_id)
        self._app_settings.setValue(self._PREVIEW_THEME_KEY, normalized)
        self._app_settings.sync()

    # ── Preview style settings ────────────────────────────────────────

    def get_preview_style_settings(self) -> dict[str, object]:
        return CanvasPreviewPane.global_preview_style_settings()

    def apply_preview_style_settings(
        self,
        raw: object,
        *,
        persist: bool = True,
        force: bool = False,
    ) -> None:
        normalized = normalize_preview_style_settings(raw)
        CanvasPreviewPane.apply_global_preview_style_settings(
            normalized,
            force=force,
        )
        self._sync_markdown_editor_font(normalized, force=force)
        self._sync_markdown_highlighter_style()
        if persist:
            self._persist_preview_style_settings(normalized)
            try:
                self._autosave_schedule_fn(220)
            except Exception:
                _LOG.warning(
                    "Theme autosave scheduling failed after apply_preview_style_settings",
                    exc_info=True,
                )

    def load_preview_style_settings(self) -> dict[str, object]:
        raw = self._app_settings.value(
            self._PREVIEW_STYLE_KEY,
            default_preview_style_settings(),
        )
        if not isinstance(raw, dict):
            raw = default_preview_style_settings()
        return normalize_preview_style_settings(raw)

    def _persist_preview_style_settings(self, style: object | None = None) -> None:
        payload = (
            normalize_preview_style_settings(style)
            if style is not None
            else self.get_preview_style_settings()
        )
        self._app_settings.setValue(self._PREVIEW_STYLE_KEY, payload)
        self._app_settings.sync()

    def _resolved_preview_style_tokens(self) -> dict[str, object]:
        preview_theme = self.get_preview_theme_id()
        style_settings = self.get_preview_style_settings()
        app = QApplication.instance()
        palette = app.palette() if app is not None else self._parent_window.palette()
        return resolve_preview_style_tokens(
            preview_theme_id=preview_theme,
            style_settings=style_settings,
            base_color=self._palette_hex(
                palette,
                QPalette.ColorRole.Base,
                "#11111B",
            ),
            alt_base_color=self._palette_hex(
                palette,
                QPalette.ColorRole.AlternateBase,
                "#1E1E2E",
            ),
            text_color=self._palette_hex(
                palette,
                QPalette.ColorRole.Text,
                "#CDD6F4",
            ),
            placeholder_color=self._palette_hex(
                palette,
                QPalette.ColorRole.PlaceholderText,
                "#BAC2DE",
            ),
            highlight_color=self._palette_hex(
                palette,
                QPalette.ColorRole.Highlight,
                "#89B4FA",
            ),
            mid_color=self._palette_hex(
                palette,
                QPalette.ColorRole.Mid,
                "#7A7A7A",
            ),
        )

    def _sync_markdown_highlighter_style(self) -> None:
        tokens = self._resolved_preview_style_tokens()
        MarkdownHighlighter.apply_global_style(
            {
                "heading_h1_color": tokens.get("heading_h1_color", "#569CD6"),
                "heading_h2_color": tokens.get("heading_h2_color", "#9CDCFE"),
                "heading_h3_color": tokens.get("heading_h3_color", "#4EC9B0"),
                "heading_h4_color": tokens.get("heading_h4_color", "#CE9178"),
                "heading_h5_color": tokens.get("heading_h5_color", "#DCDCAA"),
                "heading_h6_color": tokens.get("heading_h6_color", "#C586C0"),
                "bold_color": tokens.get("bold_color", "#DCDCAA"),
                "italic_color": tokens.get("italic_color", "#CE9178"),
                "bold_italic_color": tokens.get("bold_italic_color", "#F2B26F"),
                "inline_code_color": tokens.get("code_text_color", "#9CDCFE"),
                "inline_code_bg_color": tokens.get("code_bg_color", "#252526"),
                "image_color": tokens.get("link_color", "#4EC9B0"),
                "link_color": tokens.get("link_color", "#4EC9B0"),
                "list_marker_color": tokens.get("heading_h6_color", "#C586C0"),
                "quote_color": tokens.get("quote_text_color", "#6A9955"),
                "hr_color": tokens.get("hr_color", "#555555"),
                "html_tag_color": tokens.get("placeholder_color", "#808080"),
                "fence_color": tokens.get("heading_h3_color", "#608B4E"),
            }
        )

    @staticmethod
    def _sync_markdown_editor_font(
        style_settings: dict | object,
        *,
        force: bool,
    ) -> None:
        style = normalize_preview_style_settings(style_settings)
        MarkdownEditor.apply_global_font_family(
            style.get("markdown_font_family", "Cascadia Code"),
            force=force,
        )

    def _apply_preview_style_runtime(self, *, force: bool = False) -> None:
        style = self.get_preview_style_settings()
        CanvasPreviewPane.apply_global_preview_style_settings(
            style,
            force=force,
        )
        self._sync_markdown_editor_font(style, force=force)
        self._sync_markdown_highlighter_style()

    def bootstrap_preview_runtime_from_settings(self) -> None:
        """
        Load persisted preview-related settings and apply them to runtime globals.

        This is called during early app bootstrap before preview panes are created.
        """
        enabled, em = self.load_preview_page_margin_settings()
        CanvasPreviewPane.apply_global_page_margin_settings(enabled=enabled, em=em)
        CanvasPreviewPane.apply_global_preview_theme(self.load_preview_theme_id())
        self.apply_preview_style_settings(
            self.load_preview_style_settings(),
            persist=False,
            force=True,
        )

    def persist_runtime_settings(self) -> None:
        """Persist current theme + preview runtime settings."""
        self._persist_preview_page_margin_settings()
        self._persist_preview_theme_id(self.get_preview_theme_id())
        self._persist_preview_style_settings()
        self._persist_theme_id(self.get_theme_id())

    # ── Preview page margin ────────────────────────────────────────────

    def get_preview_page_margin_settings(self) -> dict[str, object]:
        enabled, em = CanvasPreviewPane.global_page_margin_settings()
        return {
            "enabled": bool(enabled),
            "em": float(em),
        }

    def apply_preview_page_margin_settings(self, raw: object) -> None:
        if not isinstance(raw, dict):
            return
        enabled = self._as_bool(raw.get("enabled", True), True)
        try:
            em = float(raw.get("em", CanvasPreviewPane.page_margin_default_em()))
        except Exception:
            _LOG.warning(
                "Invalid preview page-margin value %r; falling back to default",
                raw.get("em", CanvasPreviewPane.page_margin_default_em()),
                exc_info=True,
            )
            em = float(CanvasPreviewPane.page_margin_default_em())
        CanvasPreviewPane.apply_global_page_margin_settings(
            enabled=enabled,
            em=em,
        )
        self._persist_preview_page_margin_settings()
        try:
            self._autosave_schedule_fn(220)
        except Exception:
            _LOG.warning(
                "Theme autosave scheduling failed after apply_preview_page_margin_settings",
                exc_info=True,
            )

    def load_preview_page_margin_settings(self) -> tuple[bool, float]:
        enabled_raw = self._app_settings.value(
            self._PREVIEW_MARGIN_ENABLED_KEY,
            True,
        )
        em_raw = self._app_settings.value(
            self._PREVIEW_MARGIN_EM_KEY,
            CanvasPreviewPane.page_margin_default_em(),
        )
        enabled = self._as_bool(enabled_raw, True)
        try:
            em = float(em_raw)
        except Exception:
            _LOG.warning(
                "Invalid persisted preview page-margin value %r; falling back to default",
                em_raw,
                exc_info=True,
            )
            em = float(CanvasPreviewPane.page_margin_default_em())
        return enabled, em

    def _persist_preview_page_margin_settings(self) -> None:
        settings = self.get_preview_page_margin_settings()
        self._app_settings.setValue(
            self._PREVIEW_MARGIN_ENABLED_KEY,
            bool(settings.get("enabled", True)),
        )
        self._app_settings.setValue(
            self._PREVIEW_MARGIN_EM_KEY,
            float(settings.get("em", CanvasPreviewPane.page_margin_default_em())),
        )
        self._app_settings.sync()

    # ── Window chrome ──────────────────────────────────────────────────

    def apply_window_chrome(self) -> None:
        """Apply theme colours to QMainWindow, QMenuBar, and QStatusBar."""
        win = self._parent_window
        theme_id = self.get_theme_id()
        tokens = theme_tokens(theme_id)
        win.setStyleSheet(
            f"QMainWindow {{background:{tokens['base_bg']};}} "
            f"QMainWindow::separator {{background:{tokens['border']};width:3px;height:3px;}} "
            f"QMainWindow::separator:hover {{background:{tokens['accent']};}}"
        )
        bar = win.menuBar()
        if bar is not None:
            bar.setStyleSheet(
                f"QMenuBar {{background:{tokens['menu_bg']};color:{tokens['text']};"
                f"border-bottom:1px solid {tokens['border_strong']};font-size:11px;}}"
                f"QMenuBar::item:selected {{background:{tokens['menu_item_hover']};}}"
                f"QMenu {{background:{tokens['panel_alt_bg']};color:{tokens['text']};"
                f"border:1px solid {tokens['border']};font-size:11px;}}"
                f"QMenu::item:selected {{background:{tokens['menu_item_hover']};}}"
                f"QMenu::separator {{background:{tokens['border']};height:1px;margin:2px 0;}}"
            )
        sb = win.findChild(QStatusBar)
        if isinstance(sb, QStatusBar):
            sb.setStyleSheet(
                f"QStatusBar {{background:{tokens['menu_bg']};color:{tokens['muted_text']};"
                f"border-top:1px solid {tokens['border_strong']};font-size:10px;}}"
            )
        self.apply_status_label_styles()

    def apply_status_label_styles(self) -> None:
        win = self._parent_window
        theme_id = self.get_theme_id()
        tokens = theme_tokens(theme_id)
        success = getattr(win, "_model_status_success", None)
        model_color = tokens["success"] if success is True else tokens["danger"]
        muted = f"color:{tokens['muted_text']};padding:0 8px;"
        if hasattr(win, "_model_lbl"):
            win._model_lbl.setStyleSheet(f"color:{model_color};padding:0 8px;")
        if hasattr(win, "_backend_lbl"):
            win._backend_lbl.setStyleSheet(muted)
        if hasattr(win, "_mode_lbl"):
            win._mode_lbl.setStyleSheet(muted)

    # ── Preview overlays ───────────────────────────────────────────────

    def refresh_all_preview_overlays(self) -> None:
        from studio.canvas.split_view import MarkdownSplitPanel  # local import
        for panel in self._parent_window.findChildren(MarkdownSplitPanel):
            try:
                panel.refresh_preview_overlays()
            except Exception:
                _LOG.warning(
                    "Preview overlay refresh failed for panel %r",
                    panel,
                    exc_info=True,
                )
                continue

    # ── Preview settings dialog ───────────────────────────────────────

    def open_preview_layout_settings_dialog(self) -> None:
        from studio.dialogs.preview_layout_settings_dialog import (
            PreviewLayoutSettingsDialog,
        )

        mode = str(getattr(self._parent_window, "user_mode", "") or "")

        def _create() -> QDialog:
            return PreviewLayoutSettingsDialog(
                theme_id=self.get_theme_id(),
                preview_theme_id=self.get_preview_theme_id(),
                page_margin_settings=self.get_preview_page_margin_settings(),
                style_settings=self.get_preview_style_settings(),
                user_mode=mode,
                on_theme_changed=lambda theme_id: self.apply_theme_id(
                    theme_id,
                    persist=True,
                ),
                on_preview_theme_changed=lambda theme_id: self.apply_preview_theme_id(
                    theme_id,
                    persist=True,
                ),
                on_page_margin_changed=lambda payload: self.apply_preview_page_margin_settings(
                    payload
                ),
                on_style_changed=lambda payload: self.apply_preview_style_settings(
                    payload,
                    persist=True,
                ),
                parent=self._parent_window,
            )

        manager = find_dialog_manager(self._parent_window)
        if manager is not None:
            manager.show_dialog(
                "preview-layout-settings",
                _create,
                on_reopen=lambda dlg, user_mode=mode: self._reopen_preview_layout_settings_dialog(
                    dlg,
                    user_mode,
                ),
            )
            return
        _create().show()

    def _reopen_preview_layout_settings_dialog(
        self,
        dialog: QDialog,
        mode: str,
    ) -> None:
        setter = getattr(dialog, "set_user_mode", None)
        if callable(setter):
            setter(mode)
        refresher = getattr(dialog, "sync_from_runtime", None)
        if callable(refresher):
            refresher(
                theme_id=self.get_theme_id(),
                preview_theme_id=self.get_preview_theme_id(),
                page_margin_settings=self.get_preview_page_margin_settings(),
                style_settings=self.get_preview_style_settings(),
            )

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _as_bool(raw: object, default: bool) -> bool:
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return bool(default)
        text = str(raw).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    @staticmethod
    def _palette_hex(palette, role, fallback: str) -> str:
        color = palette.color(role)
        if isinstance(color, QColor) and color.isValid():
            return color.name(QColor.NameFormat.HexRgb)
        fallback_color = QColor(str(fallback or ""))
        if fallback_color.isValid():
            return fallback_color.name(QColor.NameFormat.HexRgb)
        return "#000000"
