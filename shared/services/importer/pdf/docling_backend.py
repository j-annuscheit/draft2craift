from __future__ import annotations

import base64
import importlib
import html as html_mod
import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from ..models import PDFImportSettings


def _parse_docling_page_range(page_range_str: str, path: str) -> Optional[tuple[int, int]]:
    """
    Convert the settings page-range string to Docling's ``(start, end)`` 1-based tuple.

    Returns ``None`` for "all".  Complex multi-segment ranges (e.g. "1-5,7") are not
    supported by Docling's simple API — they also return ``None`` (full document).
    """
    s = str(page_range_str or "").strip().lower()
    if s in ("all", ""):
        return None

    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) != 1:
        return None  # multi-segment — not mappable to a single docling range

    part = parts[0]
    if "-" in part:
        lo_s, hi_s = part.split("-", 1)
        try:
            lo = int(lo_s.strip()) if lo_s.strip() else 1
            if hi_s.strip():
                hi = int(hi_s.strip())
            else:
                # "N-"  →  N to last page
                try:
                    import fitz  # type: ignore

                    doc = fitz.open(path)
                    hi = len(doc)
                    doc.close()
                except Exception:
                    return None
            return (lo, hi)
        except ValueError:
            return None
    else:
        try:
            n = int(part)
            return (n, n)
        except ValueError:
            return None


_DOCLING_PLACEHOLDER_RE = re.compile(
    r"(?im)^[ \t]*<!--\s*(?:image|formula-not-decoded)\s*-->[ \t]*$",
)
_DOCLING_IMAGE_PLACEHOLDER_RE = re.compile(r"(?im)^[ \t]*<!--\s*image\s*-->[ \t]*$")
_HTML_IMG_SRC_RE = re.compile(
    r"<img\b[^>]*\bsrc=(['\"])(.*?)\1",
    re.IGNORECASE | re.DOTALL,
)
_DATA_IMAGE_RE = re.compile(
    r"^data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE | re.DOTALL,
)
_MD_IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\(\s*(<)?([^)\s]+)(>)?\s*\)")


def _clean_docling_markdown_placeholders(text: str) -> str:
    """Drop Docling placeholder comment lines from plain markdown output."""
    cleaned = _DOCLING_PLACEHOLDER_RE.sub("", str(text or ""))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _contains_docling_placeholders(text: str) -> bool:
    low = str(text or "").casefold()
    return ("<!-- image" in low) or ("<!-- formula-not-decoded" in low)


def _extract_img_sources_from_html(html: str) -> list[str]:
    sources: list[str] = []
    for match in _HTML_IMG_SRC_RE.finditer(str(html or "")):
        src = html_mod.unescape(str(match.group(2) or "").strip())
        if src:
            sources.append(src)
    return sources


def _image_ext_from_mime_subtype(subtype: str) -> str:
    token = str(subtype or "").strip().lower()
    token = token.split(";", 1)[0].strip()
    if token == "jpeg":
        token = "jpg"
    if token == "svg+xml":
        token = "svg"
    token = re.sub(r"[^a-z0-9]+", "", token)
    if not token:
        token = "png"
    return f".{token}"


def _decode_data_image_url(source: str) -> tuple[bytes, str] | None:
    match = _DATA_IMAGE_RE.match(str(source or ""))
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
    return blob, _image_ext_from_mime_subtype(subtype)


def _docling_runtime_image_dir(source_hint: str) -> Path:
    root = (Path(tempfile.gettempdir()) / "draft2craift" / "docling_images").resolve(
        strict=False
    )
    digest = hashlib.sha256(str(source_hint or "").encode("utf-8", "ignore")).hexdigest()
    target = root / digest[:24]
    target.mkdir(parents=True, exist_ok=True)
    return target


def _persist_docling_image_source(
    source: str,
    *,
    image_output_dir: Path,
    index: int,
) -> str:
    decoded = _decode_data_image_url(source)
    if decoded is None:
        return str(source or "").strip()
    blob, ext = decoded
    target = image_output_dir / f"docling_image_{int(index):04d}{ext}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    except Exception:
        return str(source or "").strip()
    return str(target.resolve(strict=False))


def _markdown_image_ref(src: str, index: int) -> str:
    safe_src = str(src or "").strip()
    if not safe_src:
        return "<!-- image -->"
    return f"![docling-image-{index}](<{safe_src}>)"


def _inject_docling_markdown_image_refs(
    markdown_text: str,
    html_text: str,
    *,
    image_output_dir: str | os.PathLike[str] | None = None,
) -> str:
    """
    Replace ``<!-- image -->`` placeholders with Markdown image refs from HTML.

    If there are not enough extracted image sources, remaining placeholders
    are kept unchanged so users can still see that an image existed.
    """
    sources = _extract_img_sources_from_html(html_text)
    if not sources:
        return str(markdown_text or "")

    idx = {"value": 0}
    target_dir: Path | None = None
    if image_output_dir is not None:
        try:
            target_dir = Path(image_output_dir).resolve(strict=False)
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            target_dir = None

    def _repl(match: re.Match[str]) -> str:
        pos = int(idx["value"])
        if pos >= len(sources):
            return match.group(0)
        idx["value"] = pos + 1
        source = sources[pos]
        if target_dir is not None:
            source = _persist_docling_image_source(
                source,
                image_output_dir=target_dir,
                index=pos + 1,
            )
        return _markdown_image_ref(source, pos + 1)

    return _DOCLING_IMAGE_PLACEHOLDER_RE.sub(_repl, str(markdown_text or ""))


def _persist_markdown_data_image_refs(
    markdown_text: str,
    *,
    image_output_dir: Path | None,
) -> str:
    if image_output_dir is None:
        return str(markdown_text or "")
    text = str(markdown_text or "")
    if not text:
        return text

    idx = {"value": 0}

    def _repl(match: re.Match[str]) -> str:
        alt = str(match.group(1) or "")
        source = str(match.group(3) or "").strip()
        if not source.lower().startswith("data:image/"):
            return match.group(0)
        idx["value"] = int(idx["value"]) + 1
        resolved = _persist_docling_image_source(
            source,
            image_output_dir=image_output_dir,
            index=int(idx["value"]),
        )
        if not resolved or resolved == source:
            return match.group(0)
        return f"![{alt}](<{resolved}>)"

    return _MD_IMAGE_LINK_RE.sub(_repl, text)


def _resolve_docling_image_mode_values() -> tuple[object, ...]:
    candidates: list[object] = []
    module_names = (
        "docling_core.types.doc",
        "docling.datamodel.base_models",
        "docling.datamodel.document",
    )
    enum_names = ("EMBEDDED", "INLINE", "BASE64", "DATA_URI", "DATAURL")
    for module_name in module_names:
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue
        enum_cls = getattr(mod, "ImageRefMode", None)
        if enum_cls is None:
            continue
        for enum_name in enum_names:
            if hasattr(enum_cls, enum_name):
                candidates.append(getattr(enum_cls, enum_name))
    # String fallbacks for older/newer APIs that accept plain text tokens.
    candidates.extend(("embedded", "inline", "base64", "data_uri", "data-url"))

    unique: list[object] = []
    seen: set[str] = set()
    for item in candidates:
        key = f"{type(item).__name__}:{item!s}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return tuple(unique)


def _export_docling_html(doc, *, want_images: bool) -> str:
    """Try several Docling HTML-export signatures and return best available HTML."""
    attempts: list[dict[str, object]] = []
    if want_images:
        for mode in _resolve_docling_image_mode_values():
            attempts.append({"image_mode": mode})
        attempts.append({"embed_images": True})
        attempts.append({"inline_images": True})
    attempts.append({})

    best_html = ""
    for kwargs in attempts:
        try:
            html = str(doc.export_to_html(**kwargs) or "")
        except TypeError:
            continue
        except Exception:
            continue
        if not html.strip():
            continue
        if not best_html:
            best_html = html
        if not want_images:
            return html
        if not _contains_docling_placeholders(html):
            return html
    return best_html


def _export_docling_markdown(
    doc,
    *,
    show_page_markers: bool,
    want_images: bool,
) -> str:
    """Try multiple markdown-export signatures and prefer non-placeholder output."""
    attempts: list[dict[str, object]] = []
    base = {"page_breaks": bool(show_page_markers)}
    if want_images:
        for mode in _resolve_docling_image_mode_values():
            attempts.append({**base, "image_mode": mode})
        attempts.append({**base, "embed_images": True})
        attempts.append({**base, "inline_images": True})
    attempts.append(base)
    attempts.append({})

    best_md = ""
    for kwargs in attempts:
        try:
            md = str(doc.export_to_markdown(**kwargs) or "")
        except TypeError:
            continue
        except Exception:
            continue
        if not md.strip():
            continue
        if not best_md:
            best_md = md
        if not want_images:
            return md
        if not _contains_docling_placeholders(md):
            return md
    return best_md


def convert_pdf_with_docling(path: str, settings: PDFImportSettings) -> str:
    """
    Convert a PDF to Markdown (and optionally rich HTML) using Docling.

    Accepts both local file paths and URLs (including arXiv links).
    Docling handles header/footer removal, heading detection, table structure,
    and paragraph flow automatically.

    When rich output is requested (images and/or formulas), the function returns
    a packed sentinel string (see ``docling_postprocess.pack_rich_result``) that
    contains both a plain-text Markdown for RAG and a rich HTML for the viewer.
    Otherwise a plain Markdown string is returned.
    """
    from ..url_utils import is_url, normalize_arxiv_url, url_display_name

    if is_url(path):
        path = normalize_arxiv_url(path)
        name = url_display_name(path)
    else:
        name = os.path.basename(path)

    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
    except ImportError:
        return (
            f"# {name}\n\n"
            "*docling ist nicht installiert.*\n\n"
            "```\npip install docling\n```\n"
        )

    want_images = bool(getattr(settings, "docling_images", True))
    want_formulas = bool(getattr(settings, "docling_formulas", False))
    want_code = bool(getattr(settings, "docling_code", False))
    want_ocr = bool(getattr(settings, "docling_ocr", True))
    ocr_force_full = bool(getattr(settings, "docling_ocr_force_full_page", False))
    ocr_lang_raw = str(getattr(settings, "docling_ocr_lang", "") or "").strip()
    table_mode_str = str(getattr(settings, "docling_table_mode", "accurate")).strip().lower()
    images_scale = float(getattr(settings, "docling_images_scale", 2.0) or 2.0)
    timeout = float(getattr(settings, "docling_timeout", 0.0) or 0.0)
    num_threads = int(getattr(settings, "docling_num_threads", 0) or 0)
    force_backend_text = bool(getattr(settings, "docling_force_backend_text", False))
    runtime_image_dir = _docling_runtime_image_dir(path) if want_images else None

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_table_structure = True
    pipeline_options.do_ocr = want_ocr
    pipeline_options.do_formula_enrichment = want_formulas
    pipeline_options.do_code_enrichment = want_code
    pipeline_options.force_backend_text = force_backend_text

    # Table structure mode
    try:
        from docling.datamodel.pipeline_options import TableFormerMode
        pipeline_options.table_structure_options.mode = (
            TableFormerMode.FAST if table_mode_str == "fast" else TableFormerMode.ACCURATE
        )
    except Exception:
        pass

    # OCR options
    if want_ocr:
        try:
            pipeline_options.ocr_options.force_full_page_ocr = ocr_force_full
            if ocr_lang_raw:
                langs = [lg.strip() for lg in ocr_lang_raw.replace(",", " ").split() if lg.strip()]
                if langs:
                    pipeline_options.ocr_options.lang = langs
        except Exception:
            pass

    # Images
    if want_images:
        pipeline_options.generate_picture_images = True
        pipeline_options.images_scale = max(0.5, float(images_scale))

    # Timeout
    if timeout > 0.0:
        try:
            pipeline_options.document_timeout = float(timeout)
        except Exception:
            pass

    # CPU threads
    if num_threads > 0:
        try:
            pipeline_options.accelerator_options.num_threads = int(num_threads)
        except Exception:
            pass

    try:
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
    except Exception as exc:
        return f"# {name}\n\n*Docling-Initialisierung fehlgeschlagen: {exc}*\n"

    page_range_param = _parse_docling_page_range(settings.page_range, path)

    try:
        conv_kwargs: dict = {}
        if page_range_param is not None:
            conv_kwargs["page_range"] = page_range_param
        result = converter.convert(path, **conv_kwargs)
    except Exception as exc:
        return f"# {name}\n\n*Docling-Konvertierung fehlgeschlagen: {exc}*\n"

    doc = result.document

    plain_md = _export_docling_markdown(
        doc,
        show_page_markers=bool(settings.show_page_markers),
        want_images=bool(want_images),
    )
    if not plain_md or not plain_md.strip():
        plain_md = "*Kein Text extrahiert.*"

    # ── Rich HTML (for viewer) ────────────────────────────────────────────────
    if want_images or want_formulas:
        try:
            from .docling_postprocess import postprocess_docling_html, pack_rich_result

            display_html = _export_docling_html(doc, want_images=want_images)
            if not str(display_html or "").strip():
                raise RuntimeError("Docling returned empty HTML export.")
            display_html = postprocess_docling_html(
                display_html, render_formulas=want_formulas
            )
            if want_images and _contains_docling_placeholders(plain_md):
                plain_md = _inject_docling_markdown_image_refs(
                    plain_md,
                    display_html,
                    image_output_dir=runtime_image_dir,
                )
            plain_md = _persist_markdown_data_image_refs(
                plain_md,
                image_output_dir=runtime_image_dir,
            )
            plain_md = f"# {name}\n\n---\n\n{plain_md}\n"
            return pack_rich_result(plain_md, display_html)
        except Exception:
            # Fall back to plain markdown if HTML export fails
            pass

    plain_md = _persist_markdown_data_image_refs(
        plain_md,
        image_output_dir=runtime_image_dir,
    )

    plain_md = f"# {name}\n\n---\n\n{plain_md}\n"
    return plain_md
