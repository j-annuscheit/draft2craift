"""CanvasPreviewPane method implementations."""
from __future__ import annotations

from .deps import *  # noqa: F403

def _sync_local_resource_search_paths(self):
    """
    Keep QTextBrowser search paths aligned with current project/autosave canvas dir.

    This allows markdown image links like ``assets/clipboard/foo.png`` to render
    immediately while still staying project-relative in markdown.
    """
    paths: list[str] = []
    window = self.window()

    manager = getattr(window, "_project_manager", None)
    current_project = getattr(manager, "current_project_folder", None)
    if current_project:
        try:
            from pathlib import Path as _Path

            canvas_root = (_Path(current_project).resolve(strict=False) / "canvas").resolve(
                strict=False
            )
            paths.append(str(canvas_root))
        except Exception:
            pass

    autosave_ctrl = getattr(window, "_autosave_ctrl", None)
    autosave_dir = getattr(autosave_ctrl, "autosave_dir", None)
    if autosave_dir:
        try:
            from pathlib import Path as _Path

            autosave_canvas = (_Path(autosave_dir).resolve(strict=False) / "canvas").resolve(
                strict=False
            )
            auto_text = str(autosave_canvas)
            if auto_text not in paths:
                paths.append(auto_text)
        except Exception:
            pass

    previous = list(getattr(self, "_resource_search_paths", []) or [])
    if paths == previous:
        return
    self._resource_search_paths = paths
    try:
        self._view.setSearchPaths(paths)
    except Exception:
        pass


def _render(self):
    if not self.isVisible():
        return
    if self._preview_edit_active:
        return
    self._render_cycle_id += 1
    # Drop stale delayed cursor-sync tasks; render decides the final position.
    self._cursor_timer.stop()
    self._sync_local_resource_search_paths()

    self._apply_view_document_style()
    prior_view_state = self._capture_view_state()
    freeze_updates = True
    if freeze_updates:
        self._view.setUpdatesEnabled(False)

    try:
        self._arm_async_preview_change_suppress()
        self._suppress_preview_change = True
        did_replace_document = False
        try:
            if self._editor is None:
                self._set_structured_graph_state(None)
                self._view.setHtml("<p><em>Keine aktive Draft-Seite.</em></p>")
                self._last_rendered_markdown = None
                did_replace_document = True
                self._rendered_highlights = []
                self._view.setExtraSelections([])
                return

            md = self._editor.get_full_text()
            if not md.strip():
                self._set_structured_graph_state(None)
                self._view.clear()
                self._last_rendered_markdown = None
                did_replace_document = True
                self._rendered_highlights = []
                self._view.setExtraSelections([])
                return

            render_md = self._markdown_for_render(md)
            render_md = self._apply_render_unordered_marker_gap(render_md)
            if render_md != self._last_rendered_markdown:
                self._set_markdown_or_graph_content(render_md)
                self._last_rendered_markdown = render_md
                did_replace_document = True
            else:
                if not self._structured_view_active:
                    # Defensive integrity check for sporadic end-of-document
                    # truncation in HTML-only mode: if the tail is missing in
                    # the currently visible preview, force a full rerender.
                    tail_probe = self._tail_probe_from_markdown(render_md)
                    if tail_probe and not self._contains_tail_probe(
                        self._preview_plain_text(),
                        tail_probe,
                    ):
                        self._set_markdown_or_graph_content(render_md)
                        self._last_rendered_markdown = render_md
                        did_replace_document = True
        finally:
            self._suppress_preview_change = False

        self._apply_block_spacing_overrides()
        self._apply_code_typography_overrides()
        self._apply_highlights()
        if not did_replace_document:
            self._preserve_view_state_once = False
            return
        if self._sync_cursor_with_editor:
            # Keep preview caret stable while the user is interacting in
            # HTML view. Otherwise QTextBrowser resets the caret to start
            # when setMarkdown()/setHtml() replaces the document.
            preserve_cursor = self._focus_is_inside_preview()
            editor_visible = (
                self._editor is not None and self._editor.isVisible()
            )
            if not editor_visible:
                self._restore_view_state(
                    prior_view_state,
                    restore_cursor=preserve_cursor,
                )
                self._preserve_view_state_once = False
                return
            had_prior_scroll_range = int(prior_view_state[3]) > 0
            if (
                self._preserve_view_state_once
                or preserve_cursor
                or had_prior_scroll_range
            ):
                self._restore_view_state(
                    prior_view_state,
                    restore_cursor=preserve_cursor,
                )
                self._preserve_view_state_once = False
            else:
                self._sync_to_cursor()
            return
        # Chat-style rendering (no cursor-sync): keep the viewport pinned
        # to the newest content so there is no visible jump to top.
        self.scroll_to_bottom()
        self._preserve_view_state_once = False
    finally:
        if freeze_updates:
            self._view.setUpdatesEnabled(True)
            self._view.viewport().update()
def _sync_to_cursor(self):
    if (
        not self._sync_cursor_with_editor
        or not self.isVisible()
        or self._editor is None
        or self._preview_edit_active
    ):
        return
    if self._structured_view_active:
        return
    if not self._editor.isVisible():
        return
    if self._focus_is_inside_preview():
        return

    target_ratio = 0.0

    editor_scroll = self._editor.verticalScrollBar()
    if editor_scroll.maximum() > 0:
        target_ratio = max(
            0.0,
            min(
                1.0,
                float(editor_scroll.value()) / float(editor_scroll.maximum()),
            ),
        )
    else:
        return

    scrollbar = self._view.verticalScrollBar()
    if scrollbar.maximum() <= 0:
        return
    scrollbar.setValue(int(round(float(scrollbar.maximum()) * target_ratio)))
def _sync_preview_interaction_mode(self):
    allow_preview_editing = (
        self._allow_editing and not self._structured_view_active
    )
    self._view.setReadOnly(not allow_preview_editing)
    if self._format_bar is not None:
        self._format_bar.setVisible(allow_preview_editing)
    if hasattr(self, "_graph_bar") and self._graph_bar is not None:
        self._graph_bar.setVisible(self._structured_view_active)
    if self._graph_view is not None:
        self._graph_view.setInteractive(self._structured_view_active)
def _set_structured_graph_state(self, spec: GraphSpec | None):
    self._structured_graph_spec = spec
    if spec is None:
        self._structured_graph_signature = ""
        self._graph_collapsed_ids = set()
        self._graph_focus_node_id = ""
        self._graph_manual_positions = {}
        self._graph_layout_nonce = 0
        self._graph_plain_text = ""
        self._structured_view_active = False
        if hasattr(self, "_content_stack"):
            self._content_stack.setCurrentWidget(self._view)
        self._sync_preview_interaction_mode()
        return

    # Structured graph mode is read-only from the graph canvas. Any pending
    # preview->markdown sync would write stale QTextBrowser content back.
    self._preview_to_markdown_timer.stop()
    self._preview_edit_active = False
    self._preview_user_edit_dirty = False
    self._preview_user_edit_intent = False

    signature = graph_spec_signature(spec)
    if signature != self._structured_graph_signature:
        self._structured_graph_signature = signature
        self._graph_collapsed_ids = (
            self._initial_collapsed_graph_nodes(spec)
            | set(spec.default_collapsed_ids)
        )
        self._graph_focus_node_id = ""
        self._graph_manual_positions = {}
        self._graph_layout_nonce = 0

    valid = set(spec.nodes.keys())
    include_edges = spec.kind == "graph"
    expandable = self._expandable_graph_nodes(
        spec,
        include_edges=include_edges,
    )
    self._graph_collapsed_ids = {
        node_id
        for node_id in self._graph_collapsed_ids
        if node_id in valid and node_id in expandable
    }
    if self._graph_focus_node_id not in valid:
        self._graph_focus_node_id = ""

    self._structured_view_active = True
    if hasattr(self, "_content_stack") and self._graph_view is not None:
        self._content_stack.setCurrentWidget(self._graph_view)
    self._sync_preview_interaction_mode()
def _set_markdown_or_graph_content(self, markdown_text: str):
    self._arm_async_preview_change_suppress()
    self._image_rotation_map = {}
    spec = extract_graph_spec(markdown_text)
    if spec is None:
        self._set_structured_graph_state(None)
        # Render LaTeX formulas if present — original $$...$$ stays in the editor,
        # only the HTML preview uses rendered PNG images.
        if _latex_has_formulas(markdown_text):
            try:
                _display_with_latex(
                    self._view,
                    markdown_text,
                    formula_color=_resolve_formula_render_color(self._view),
                )
                return
            except Exception:
                pass  # fall through to plain setMarkdown on any rendering error
        self._view.setMarkdown(markdown_text)
        return

    self._set_structured_graph_state(spec)
    self._render_structured_graph_scene(spec)

def set_html_content(self, html: str):
    """Display pre-rendered HTML directly (e.g. Docling rich output with images/formulas)."""
    self._arm_async_preview_change_suppress()
    self._set_structured_graph_state(None)
    self._image_rotation_map = {}
    self._sync_local_resource_search_paths()
    self._view.setHtml(html)

# ── LaTeX helpers (module-level) ──────────────────────────────────────────────

import re as _re

_LATEX_QUICK_CHECK = _re.compile(r'\$')

# Placeholder format: pure alphanumeric → survives Qt markdown rendering unchanged
_PLACEHOLDER_TMPL = "XFMLA{idx}X"
_PLACEHOLDER_RE = _re.compile(r"XFMLA(\d+)X")


def _latex_has_formulas(text: str) -> bool:
    """Quick check: does *text* contain any $...$ or $$...$$ patterns?"""
    return bool(_LATEX_QUICK_CHECK.search(text))


def _extract_formulas(markdown_text: str):
    """
    Replace all LaTeX blocks in *markdown_text* with unique text placeholders.

    Returns ``(processed_text, formulas)`` where *formulas* is a list of
    ``(is_display, latex_string)`` tuples in placeholder-index order.
    """
    formulas: list[tuple[bool, str]] = []

    def _repl_display(m: _re.Match) -> str:
        idx = len(formulas)
        formulas.append((True, m.group(1).strip()))
        return f"\n\n{_PLACEHOLDER_TMPL.format(idx=idx)}\n\n"

    def _repl_inline(m: _re.Match) -> str:
        idx = len(formulas)
        formulas.append((False, m.group(1).strip()))
        return _PLACEHOLDER_TMPL.format(idx=idx)

    # Display math first ($$...$$) so they're consumed before inline pass
    processed = _re.sub(r'\$\$([\s\S]+?)\$\$', _repl_display, markdown_text)
    # Inline math ($...$) — single-line only, avoids false positives
    processed = _re.sub(r'(?<!\$)\$(?!\$)([^\$\n]+?)\$(?!\$)', _repl_inline, processed)
    return processed, formulas



# In-process cache: sha256(display_flag + latex) → base64 PNG string.
# Keyed by formula content so identical formulas are rendered only once,
# and re-renders are skipped automatically when the LaTeX hasn't changed.
_FORMULA_PNG_CACHE: dict[str, str] = {}


def _normalize_formula_color(value: object) -> str:
    color = QColor(str(value or "").strip())
    if not color.isValid():
        return ""
    return color.name(QColor.NameFormat.HexRgb).upper()


def _resolve_formula_render_color(view) -> str:
    from_property = _normalize_formula_color(view.property("_formula_text_color"))
    if from_property:
        return from_property
    palette_color = view.palette().color(QPalette.ColorRole.Text)
    if isinstance(palette_color, QColor) and palette_color.isValid():
        return palette_color.name(QColor.NameFormat.HexRgb).upper()
    return "#000000"


def _formula_cache_key(
    latex: str,
    display: bool,
    formula_color: str = "",
) -> str:
    import hashlib
    normalized_color = _normalize_formula_color(formula_color)
    if normalized_color:
        payload = f"{'d' if display else 'i'}:{normalized_color}:{latex}"
    else:
        payload = f"{'d' if display else 'i'}:{latex}"
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _render_formula_png_b64(
    latex: str,
    display: bool,
    formula_color: str = "",
) -> str | None:
    """Render *latex* via matplotlib mathtext → base64 PNG.  Returns None on failure."""
    normalized_color = _normalize_formula_color(formula_color)
    cache_key = _formula_cache_key(
        latex,
        display,
        formula_color=normalized_color,
    )
    if cache_key in _FORMULA_PNG_CACHE:
        return _FORMULA_PNG_CACHE[cache_key]
    try:
        import matplotlib  # type: ignore
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
        import base64, io

        expr = latex.strip()
        if not (expr.startswith("$") and expr.endswith("$")):
            expr = f"${expr}$"
        fontsize = 13 if display else 11
        fig = plt.figure(figsize=(0.01, 0.01))
        text_kwargs = {"fontsize": fontsize}
        if normalized_color:
            text_kwargs["color"] = normalized_color
        fig.text(0, 0, expr, **text_kwargs)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=130,
                    bbox_inches="tight", pad_inches=0.06, transparent=True)
        plt.close(fig)
        buf.seek(0)
        result = base64.b64encode(buf.read()).decode()
        _FORMULA_PNG_CACHE[cache_key] = result
        return result
    except Exception:
        return None


def _display_with_latex(
    view,
    markdown_text: str,
    *,
    formula_color: str = "",
) -> None:
    """
    2-pass LaTeX rendering for the markdown preview:

    1. Replace $$...$$ / $...$ with text placeholders and let Qt render the
       markdown.  This preserves all other markdown styling (headings, tables…).
    2. Retrieve Qt's rendered HTML, inject the formula PNG images where the
       placeholders are, then call setHtml() for the final display.

    The original markdown (with $$...$$) is never modified — this only affects
    what is shown in the HTML preview.
    """
    processed_md, formulas = _extract_formulas(markdown_text)
    if not formulas:
        view.setMarkdown(markdown_text)
        return

    # Pre-render formula images — cache key = sha256(display+latex) so identical
    # formulas are only rendered once and a changed formula is detected automatically
    # without any image data ever touching the markdown editor.
    resolved_color = _normalize_formula_color(formula_color) or _resolve_formula_render_color(view)
    b64_map: dict[int, tuple[bool, str, str]] = {}  # idx → (is_display, b64, cache_key)
    for idx, (is_display, latex) in enumerate(formulas):
        b64 = _render_formula_png_b64(
            latex,
            is_display,
            formula_color=resolved_color,
        )
        if b64 is not None:
            b64_map[idx] = (
                is_display,
                b64,
                _formula_cache_key(
                    latex,
                    is_display,
                    formula_color=resolved_color,
                ),
            )

    if not b64_map:
        # No formula rendered successfully → plain markdown
        view.setMarkdown(markdown_text)
        return

    # Pass 1: Qt renders markdown with placeholders → get HTML
    view.setMarkdown(processed_md)
    qt_html = view.document().toHtml()

    # Pass 2: replace placeholder text in HTML with <img> tags.
    # The formula:// link uses the content hash so the click handler can
    # identify the formula by content — not by fragile document position.
    import html as _html_mod

    def _inject(m: _re.Match) -> str:
        idx = int(m.group(1))
        if idx not in b64_map:
            # No image for this formula → keep original LaTeX as code
            _, latex = formulas[idx]
            return f"<code>{_html_mod.escape(latex)}</code>"
        is_display, b64, cache_key = b64_map[idx]
        style = (
            "display:block;margin:0.5em auto;"
            if is_display
            else "vertical-align:middle;margin:0 0.15em;"
        )
        alt = _html_mod.escape(formulas[idx][1])
        img = f'<img src="data:image/png;base64,{b64}" alt="{alt}" style="{style}"/>'
        # href encodes both display-mode and hash so the handler can
        # look up the LaTeX and open the right formula for editing.
        mode = "d" if is_display else "i"
        return f'<a href="formula://{mode}/{cache_key}" style="text-decoration:none;">{img}</a>'

    final_html = _PLACEHOLDER_RE.sub(_inject, qt_html)
    view.setHtml(final_html)
def _arm_async_preview_change_suppress(self):
    """Suppress delayed textChanged signals from programmatic preview updates."""
    self._suppress_preview_change_async += 1

    def release():
        self._suppress_preview_change_async = max(
            0,
            int(self._suppress_preview_change_async) - 1,
        )

    QTimer.singleShot(0, release)
@staticmethod
def _is_preview_content_edit_keypress(event) -> bool:
    if event is None:
        return False
    if event.matches(QKeySequence.StandardKey.Paste):
        return True
    if event.matches(QKeySequence.StandardKey.Cut):
        return True
    if event.matches(QKeySequence.StandardKey.Undo):
        return True
    if event.matches(QKeySequence.StandardKey.Redo):
        return True
    key = int(event.key())
    if key in (
        int(Qt.Key.Key_Backspace),
        int(Qt.Key.Key_Delete),
        int(Qt.Key.Key_Return),
        int(Qt.Key.Key_Enter),
    ):
        return True
    if event.modifiers() & (
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.MetaModifier
    ):
        return False
    return bool(str(event.text() or ""))

__all__ = [
    "_sync_local_resource_search_paths",
    "_render",
    "_sync_to_cursor",
    "_sync_preview_interaction_mode",
    "_set_structured_graph_state",
    "_set_markdown_or_graph_content",
    "set_html_content",
    "_arm_async_preview_change_suppress",
    "_is_preview_content_edit_keypress",
]
