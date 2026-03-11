"""PDF export writer with advanced layout options."""
from __future__ import annotations

import html

from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter

from shared.services.highlights.store_models import HighlightMatch

from .highlight_support import css_color, local_matches_for_range, resolve_matches_for_parsed, segments_for_block
from .markdown_blocks import ParsedMarkdownBlock, parse_markdown_lines
from .models import ExportOptions


def write_pdf(
    md_text: str,
    path: str,
    *,
    options: ExportOptions,
    panel_scope: str,
    tab_name: str,
) -> None:
    """Write a markdown document as PDF using chosen export options."""
    parsed = parse_markdown_lines(md_text)
    matches = resolve_matches_for_parsed(
        parsed,
        options=options,
        panel_scope=panel_scope,
        tab_name=tab_name,
    )
    html_text = build_pdf_html(parsed=parsed, matches=matches, options=options)

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)

    doc = QTextDocument()
    doc.setHtml(html_text)
    doc.print_(printer)


def build_pdf_html(
    *,
    parsed: list[ParsedMarkdownBlock],
    matches: list[HighlightMatch],
    options: ExportOptions,
) -> str:
    """Render parsed markdown blocks into styled HTML for Qt PDF printing."""
    safe_font = str(options.font_name or "Calibri").replace("'", "\\'")
    line_height = max(1.0, float(options.line_spacing))

    css = (
        "<style>"
        "body { margin: 20px; color: #111111; font-family: '"
        f"{safe_font}"
        "'; font-size: "
        f"{int(options.font_size_pt)}pt;"
        " }"
        ".content { line-height: "
        f"{line_height:.2f};"
        " }"
        ".content.multi { column-count: 2; column-gap: 24pt; }"
        "h1,h2,h3,p { margin: 0 0 8pt 0; }"
        "ul,ol { margin: 0 0 8pt 18pt; padding: 0; }"
        ".comment-section { margin-top: 14pt; }"
        ".comment-list { margin: 0 0 0 18pt; padding: 0; }"
        "</style>"
    )

    out: list[str] = [
        "<html><head>",
        css,
        "</head><body>",
        '<div class="content multi">' if options.multi_column else '<div class="content">',
    ]

    comment_numbers: dict[str, int] = {}
    comment_entries: list[tuple[int, str]] = []
    list_mode = ""
    char_pos = 0

    for idx, (text, style) in enumerate(parsed):
        para_start = char_pos
        para_end = para_start + len(text)
        local_matches = local_matches_for_range(matches, start=para_start, end=para_end)

        content_parts: list[str] = []
        for segment, active in segments_for_block(
            text=text,
            para_start=para_start,
            local_matches=local_matches,
        ):
            if not segment:
                continue
            seg_html = html.escape(segment)
            if active is not None and options.include_highlights:
                seg_html = (
                    '<span style="background-color: '
                    f"{css_color(active.color)}"
                    ';">'
                    f"{seg_html}</span>"
                )
            if active is not None and options.include_comments:
                comment_text = str(active.hover_text or "").strip()
                if comment_text and active.highlight_id not in comment_numbers:
                    number = len(comment_entries) + 1
                    comment_numbers[active.highlight_id] = number
                    comment_entries.append((number, comment_text))
                    seg_html += f"<sup>[{number}]</sup>"
            content_parts.append(seg_html)

        content = "".join(content_parts) or "&nbsp;"

        if style in {"bullet", "number"}:
            wanted_mode = "ul" if style == "bullet" else "ol"
            if list_mode != wanted_mode:
                if list_mode:
                    out.append(f"</{list_mode}>")
                out.append(f"<{wanted_mode}>")
                list_mode = wanted_mode
            out.append(f"<li>{content}</li>")
        else:
            if list_mode:
                out.append(f"</{list_mode}>")
                list_mode = ""
            tag = "p"
            if style == "h1":
                tag = "h1"
            elif style == "h2":
                tag = "h2"
            elif style == "h3":
                tag = "h3"
            out.append(f"<{tag}>{content}</{tag}>")

        char_pos = para_end
        if idx + 1 < len(parsed):
            char_pos += 1

    if list_mode:
        out.append(f"</{list_mode}>")

    out.append("</div>")
    if options.include_comments and comment_entries:
        out.append('<div class="comment-section">')
        out.append("<h3>Kommentare</h3>")
        out.append('<ol class="comment-list">')
        for number, text in comment_entries:
            out.append(f"<li>[{number}] {html.escape(str(text or ''))}</li>")
        out.append("</ol>")
        out.append("</div>")
    out.append("</body></html>")
    return "".join(out)
