"""Panel capability helpers for selection handling."""
from __future__ import annotations

from studio.canvas.selection_text import normalize_selection_text


def get_preview_selected_text(panel) -> str:
    if hasattr(panel, "get_preview_selected_text"):
        try:
            return str(panel.get_preview_selected_text() or "")
        except Exception:
            return ""
    return ""


def should_use_preview_selection(panel) -> bool:
    if hasattr(panel, "should_use_preview_selection"):
        try:
            return bool(panel.should_use_preview_selection())
        except Exception:
            return False

    has_visibility_api = hasattr(panel, "is_markdown_visible") and hasattr(panel, "is_preview_visible")
    if not has_visibility_api:
        return False
    try:
        return bool(panel.is_preview_visible() and not panel.is_markdown_visible())
    except Exception:
        return False


def should_use_preview_selection_path(panel) -> bool:
    """Prefer preview text when preview is authoritative or editor has no selection."""
    if should_use_preview_selection(panel):
        return True
    preview_text = normalize_selection_text(get_preview_selected_text(panel))
    if not preview_text.strip():
        return False
    editor_text = normalize_selection_text(panel.editor.get_selected_text())
    return not bool(editor_text.strip())
