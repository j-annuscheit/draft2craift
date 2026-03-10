"""Theme controller — UI theme and preview settings."""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMainWindow, QStatusBar

from shared.config.setting_keys import ThemeSettingsKeys
from studio.canvas.preview.pane import CanvasPreviewPane
from studio.theme import apply_theme, normalize_theme_id, theme_tokens

_LOG = logging.getLogger(__name__)


class ThemeController:
    """Applies and tracks theme changes, and preview margin/theme settings."""

    _THEME_SETTING_KEY = ThemeSettingsKeys.UI_THEME
    _PREVIEW_MARGIN_ENABLED_KEY = ThemeSettingsKeys.PREVIEW_PAGE_MARGIN_ENABLED
    _PREVIEW_MARGIN_EM_KEY = ThemeSettingsKeys.PREVIEW_PAGE_MARGIN_EM
    _PREVIEW_THEME_KEY = ThemeSettingsKeys.PREVIEW_MARKDOWN_THEME

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

    def apply_theme_id(self, theme_id: object, persist: bool = True):
        normalized = normalize_theme_id(theme_id)
        app = QApplication.instance()
        if app is not None:
            normalized = apply_theme(app, normalized)
        self._theme_id = normalized
        # Apply chrome to window
        self.apply_window_chrome()
        self.sync_theme_actions(getattr(self._parent_window, "_theme_actions", {}))
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

    def _persist_theme_id(self, theme_id: str):
        normalized = normalize_theme_id(theme_id)
        self._app_settings.setValue(self._THEME_SETTING_KEY, normalized)
        self._app_settings.sync()

    def sync_theme_actions(self, theme_actions: dict):
        current = self.get_theme_id()
        for tid, action in (theme_actions or {}).items():
            if not isinstance(action, QAction):
                continue
            old = action.blockSignals(True)
            action.setChecked(tid == current)
            action.blockSignals(old)

    # ── Preview theme ──────────────────────────────────────────────────

    def get_preview_theme_id(self) -> str:
        return CanvasPreviewPane.global_preview_theme_id()

    def apply_preview_theme_id(self, theme_id: object, *, persist: bool = True):
        CanvasPreviewPane.apply_global_preview_theme(theme_id)
        self.sync_preview_theme_actions(
            getattr(self._parent_window, "_preview_theme_actions", {})
        )
        if persist:
            self._persist_preview_theme_id(theme_id)
            try:
                self._autosave_schedule_fn(220)
            except Exception:
                _LOG.warning(
                    "Theme autosave scheduling failed after apply_preview_theme_id",
                    exc_info=True,
                )

    def _load_preview_theme_id(self) -> str:
        value = self._app_settings.value(
            self._PREVIEW_THEME_KEY,
            CanvasPreviewPane._PREVIEW_THEME_DEFAULT,
        )
        return CanvasPreviewPane._normalize_preview_theme_id(value)

    def _persist_preview_theme_id(self, theme_id: object):
        normalized = CanvasPreviewPane._normalize_preview_theme_id(theme_id)
        self._app_settings.setValue(self._PREVIEW_THEME_KEY, normalized)
        self._app_settings.sync()

    def sync_preview_theme_actions(self, preview_theme_actions: dict):
        current = CanvasPreviewPane.global_preview_theme_id()
        for tid, action in list((preview_theme_actions or {}).items()):
            if not isinstance(action, QAction):
                continue
            old = action.blockSignals(True)
            action.setChecked(str(tid) == str(current))
            action.blockSignals(old)

    # ── Preview page margin ────────────────────────────────────────────

    def get_preview_page_margin_settings(self) -> dict:
        enabled, em = CanvasPreviewPane.global_page_margin_settings()
        return {
            "enabled": bool(enabled),
            "em": float(em),
        }

    def apply_preview_page_margin_settings(self, raw: object):
        if not isinstance(raw, dict):
            return
        enabled = self._as_bool(raw.get("enabled", True), True)
        try:
            em = float(raw.get("em", CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM))
        except Exception:
            _LOG.warning(
                "Invalid preview page-margin value %r; falling back to default",
                raw.get("em", CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM),
                exc_info=True,
            )
            em = float(CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM)
        CanvasPreviewPane.apply_global_page_margin_settings(
            enabled=enabled,
            em=em,
        )
        self._persist_preview_page_margin_settings()
        self.sync_preview_page_margin_actions(
            getattr(self._parent_window, "_action_page_margin_enabled", None),
            getattr(self._parent_window, "_page_margin_actions", []),
        )

    def _load_preview_page_margin_settings(self) -> tuple[bool, float]:
        enabled_raw = self._app_settings.value(
            self._PREVIEW_MARGIN_ENABLED_KEY,
            True,
        )
        em_raw = self._app_settings.value(
            self._PREVIEW_MARGIN_EM_KEY,
            CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM,
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
            em = float(CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM)
        return enabled, em

    def _persist_preview_page_margin_settings(self):
        settings = self.get_preview_page_margin_settings()
        self._app_settings.setValue(
            self._PREVIEW_MARGIN_ENABLED_KEY,
            bool(settings.get("enabled", True)),
        )
        self._app_settings.setValue(
            self._PREVIEW_MARGIN_EM_KEY,
            float(settings.get("em", CanvasPreviewPane._PAGE_MARGIN_DEFAULT_EM)),
        )
        self._app_settings.sync()

    def sync_preview_page_margin_actions(
        self,
        action_page_margin_enabled,
        page_margin_actions: list,
    ):
        enabled, em = CanvasPreviewPane.global_page_margin_settings()
        if isinstance(action_page_margin_enabled, QAction):
            old = action_page_margin_enabled.blockSignals(True)
            action_page_margin_enabled.setChecked(bool(enabled))
            action_page_margin_enabled.blockSignals(old)

        for preset_em, action in list(page_margin_actions or []):
            if not isinstance(action, QAction):
                continue
            old = action.blockSignals(True)
            action.setEnabled(bool(enabled))
            action.setChecked(abs(float(preset_em) - float(em)) < 0.001)
            action.blockSignals(old)

    def toggle_preview_page_margin_enabled(self, checked: bool):
        _enabled, em = CanvasPreviewPane.global_page_margin_settings()
        self.apply_preview_page_margin_settings(
            {
                "enabled": bool(checked),
                "em": float(em),
            }
        )

    def set_preview_page_margin_preset(self, em: float):
        enabled, _em = CanvasPreviewPane.global_page_margin_settings()
        self.apply_preview_page_margin_settings(
            {
                "enabled": bool(enabled),
                "em": float(em),
            }
        )

    # ── Window chrome ──────────────────────────────────────────────────

    def apply_window_chrome(self):
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

    def apply_status_label_styles(self):
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

    def refresh_all_preview_overlays(self):
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
