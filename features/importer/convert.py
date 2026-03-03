from __future__ import annotations

import csv
import os
import re
from typing import Optional

from .models import PDFImportSettings, _CODE_EXTENSIONS
from .pdf import convert_pdf_with_settings

def convert_file(path: str, pdf_settings: Optional[PDFImportSettings] = None) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return convert_pdf_with_settings(path, pdf_settings or PDFImportSettings())
    elif ext == ".docx":
        return _convert_docx(path)
    elif ext in (".html", ".htm"):
        return _convert_html(path)
    elif ext == ".csv":
        return _convert_csv(path)
    elif ext in (".txt", ".rst"):
        return _convert_text(path)
    elif ext in (".md", ".markdown"):
        return _read_raw(path)
    elif ext == ".odt":
        return _convert_odt(path)
    elif ext in _CODE_EXTENSIONS:
        return _wrap_code(path, ext)
    else:
        try:
            return _convert_text(path)
        except Exception as exc:
            return f"# {os.path.basename(path)}\n\n*Could not convert: {exc}*\n"


def _read_raw(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _convert_text(path: str) -> str:
    return f"# {os.path.basename(path)}\n\n{_read_raw(path)}\n"


def _convert_docx(path: str) -> str:
    name = os.path.basename(path)
    try:
        from docx import Document  # type: ignore
        doc = Document(path)
        lines: list[str] = []
        for para in doc.paragraphs:
            sn   = para.style.name if para.style else ""
            text = para.text.strip()
            if not text:
                lines.append("")
            elif sn.startswith("Heading 1"):
                lines.append(f"# {text}")
            elif sn.startswith("Heading 2"):
                lines.append(f"## {text}")
            elif sn.startswith("Heading 3"):
                lines.append(f"### {text}")
            elif "List" in sn:
                lines.append(f"- {text}")
            else:
                lines.append(text)
        return f"# {name}\n\n---\n\n" + "\n".join(lines) + "\n"
    except ImportError:
        return f"# {name}\n\n*python-docx not installed.*\n\n```\npip install python-docx\n```\n"
    except Exception as exc:
        return f"# {name}\n\n*Error reading DOCX: {exc}*\n"


def _convert_html(path: str) -> str:
    name = os.path.basename(path)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        html = fh.read()
    try:
        import html2text  # type: ignore
        h = html2text.HTML2Text()
        h.ignore_links = False
        return f"# {name}\n\n---\n\n{h.handle(html)}\n"
    except ImportError:
        pass
    try:
        import markdownify  # type: ignore
        return f"# {name}\n\n---\n\n{markdownify.markdownify(html)}\n"
    except ImportError:
        pass
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return f"# {name}\n\n---\n\n{text}\n"


def _convert_csv(path: str) -> str:
    name = os.path.basename(path)
    try:
        rows: list[list[str]] = []
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.reader(fh):
                rows.append(row)
        if not rows:
            return f"# {name}\n\n*Empty CSV.*\n"
        header = rows[0]
        lines = [
            f"# {name}\n",
            "| " + " | ".join(str(c) for c in header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for row in rows[1:501]:
            while len(row) < len(header):
                row.append("")
            cells = [str(c).replace("|", "\\|") for c in row[: len(header)]]
            lines.append("| " + " | ".join(cells) + " |")
        if len(rows) > 502:
            lines.append(f"\n*… {len(rows) - 501} more rows not shown*\n")
        return "\n".join(lines) + "\n"
    except Exception as exc:
        return f"# {name}\n\n*Error reading CSV: {exc}*\n"


def _convert_odt(path: str) -> str:
    name = os.path.basename(path)
    try:
        from odf.opendocument import load as odf_load  # type: ignore
        from odf import teletype  # type: ignore
        doc = odf_load(path)
        lines = [teletype.extractText(e).strip() for e in doc.text.childNodes]
        return f"# {name}\n\n---\n\n" + "\n\n".join(l for l in lines if l) + "\n"
    except ImportError:
        return f"# {name}\n\n*odfpy not installed.*\n\n```\npip install odfpy\n```\n"
    except Exception as exc:
        return f"# {name}\n\n*Error reading ODT: {exc}*\n"


def _wrap_code(path: str, ext: str) -> str:
    name = os.path.basename(path)
    lang = ext.lstrip(".")
    try:
        return f"# {name}\n\n```{lang}\n{_read_raw(path)}\n```\n"
    except Exception as exc:
        return f"# {name}\n\n*Error reading file: {exc}*\n"
