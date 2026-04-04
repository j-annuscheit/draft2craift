"""
Post-processing for Docling HTML output:

- Strip Docling's hard-coded CSS (Qt viewer applies its own theme).
- Render LaTeX formulas ($$...$$ and $...$) via matplotlib → inline PNG.
- Pack / unpack a "rich result" sentinel so the conversion function can
  return both the plain Markdown (for RAG) and the display HTML through
  the existing single-string conversion interface.
"""
from __future__ import annotations

import base64
import html as html_mod
import io
import re

# ── Sentinel encoding ─────────────────────────────────────────────────────────

_RICH_SENTINEL = "\x00DOCLING_RICH\x00"
_HTML_SENTINEL = "\x00DOCLING_HTML\x00"


def pack_rich_result(plain_markdown: str, display_html: str) -> str:
    """Combine plain markdown + display HTML into a single sentinel string."""
    return f"{_RICH_SENTINEL}{plain_markdown}{_HTML_SENTINEL}{display_html}"


def unpack_rich_result(text: str) -> tuple[str, str] | None:
    """
    Unpack a sentinel string produced by ``pack_rich_result``.

    Returns ``(plain_markdown, display_html)`` or ``None`` if not a rich result.
    """
    if not text.startswith(_RICH_SENTINEL):
        return None
    rest = text[len(_RICH_SENTINEL):]
    if _HTML_SENTINEL not in rest:
        return None
    idx = rest.index(_HTML_SENTINEL)
    return rest[:idx], rest[idx + len(_HTML_SENTINEL):]


# ── CSS stripping ─────────────────────────────────────────────────────────────

_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)


def strip_docling_styles(html: str) -> str:
    """Remove Docling's embedded <style> block so Qt applies its own theme."""
    return _STYLE_RE.sub("", html)


# ── LaTeX formula rendering ───────────────────────────────────────────────────

def _render_formula_to_png_b64(latex: str, display: bool) -> str | None:
    """
    Render *latex* via matplotlib mathtext and return a base64-encoded PNG.

    Returns ``None`` if rendering fails (formula will be kept as-is).
    """
    try:
        import matplotlib  # type: ignore
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore

        fontsize = 13 if display else 11
        # matplotlib mathtext expects $ delimiters
        expr = latex.strip()
        if not (expr.startswith("$") and expr.endswith("$")):
            expr = f"${expr}$"

        fig = plt.figure(figsize=(0.01, 0.01))
        text_obj = fig.text(0, 0, expr, fontsize=fontsize)
        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=130,
            bbox_inches="tight",
            pad_inches=0.06,
            transparent=True,
        )
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except Exception:
        return None


def _formula_to_img_tag(latex: str, display: bool) -> str:
    """Convert a LaTeX string to an HTML <img> tag, or a <code> fallback."""
    b64 = _render_formula_to_png_b64(latex, display)
    if b64 is None:
        escaped = html_mod.escape(latex)
        return f'<code class="formula">{escaped}</code>'
    style = "display:block;margin:0.6em auto;" if display else "vertical-align:middle;margin:0 0.15em;"
    alt = html_mod.escape(latex)
    return f'<img src="data:image/png;base64,{b64}" alt="{alt}" style="{style}"/>'


def _replace_display_math(m: re.Match) -> str:
    return _formula_to_img_tag(m.group(1).strip(), display=True)


def _replace_inline_math(m: re.Match) -> str:
    return _formula_to_img_tag(m.group(1).strip(), display=False)


# Patterns (processed in order; display first to avoid double-matching)
_DISPLAY_PATTERNS = [
    # $$...$$ — most common from Docling formula enrichment
    re.compile(r"\$\$([\s\S]+?)\$\$"),
    # \[...\]
    re.compile(r"\\\[([\s\S]+?)\\\]"),
]
_INLINE_PATTERNS = [
    # $...$ — must not be $$ (already consumed above)
    re.compile(r"(?<!\$)\$(?!\$)((?:[^$]|\\\$)+?)(?<!\$)\$(?!\$)"),
    # \(...\)
    re.compile(r"\\\(([\s\S]+?)\\\)"),
]


def render_latex_in_html(html: str) -> str:
    """Replace LaTeX math blocks in *html* with rendered PNG images."""
    for pat in _DISPLAY_PATTERNS:
        html = pat.sub(_replace_display_math, html)
    for pat in _INLINE_PATTERNS:
        html = pat.sub(_replace_inline_math, html)
    return html


# ── Public entry point ────────────────────────────────────────────────────────

def postprocess_docling_html(html: str, *, render_formulas: bool = False) -> str:
    """
    Prepare Docling HTML for Qt's QTextBrowser:

    1. Strip Docling's hard-coded ``<style>`` block.
    2. Optionally render LaTeX formulas via matplotlib.
    """
    html = strip_docling_styles(html)
    if render_formulas:
        html = render_latex_in_html(html)
    return html
