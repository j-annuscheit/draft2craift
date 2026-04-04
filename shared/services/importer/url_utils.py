"""URL utilities for the importer: detection, arXiv normalization, download."""
from __future__ import annotations

import os
import re
import tempfile
from urllib.parse import urlparse

_ARXIV_MODERN_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$", re.IGNORECASE)
_ARXIV_LEGACY_ID_RE = re.compile(
    r"^[a-z\-]+(?:\.[a-z\-]+)?/\d{7}(?:v\d+)?$",
    re.IGNORECASE,
)


def is_url(path: str) -> bool:
    return str(path or "").startswith(("http://", "https://"))


def is_pdf_url(url: str) -> bool:
    """True if the URL most likely points to a PDF document."""
    u = normalize_arxiv_url(str(url or "")).lower()
    # arXiv /pdf/ path (e.g. arxiv.org/pdf/2408.09869)
    if "arxiv.org/pdf/" in u:
        return True
    # Generic .pdf extension (with or without query string)
    path_part = urlparse(u).path
    return path_part.endswith(".pdf")


def _strip_arxiv_pdf_suffix(arxiv_id: str) -> str:
    value = str(arxiv_id or "").strip().strip("/")
    if value.lower().endswith(".pdf"):
        value = value[:-4].rstrip("/")
    return value


def _is_arxiv_id(value: str) -> bool:
    text = _strip_arxiv_pdf_suffix(value)
    if not text:
        return False
    return bool(_ARXIV_MODERN_ID_RE.fullmatch(text) or _ARXIV_LEGACY_ID_RE.fullmatch(text))


def _extract_arxiv_id(input_value: str) -> str:
    """
    Extract an arXiv identifier from free-form user input.

    Supports:
    - 1706.03762
    - arXiv:1706.03762
    - https://arxiv.org/abs/1706.03762
    - https://arxiv.org/pdf/1706.03762(.pdf)
    """
    raw = str(input_value or "").strip()
    if not raw:
        return ""

    compact = raw.replace(" ", "")
    if compact.lower().startswith("arxiv:"):
        compact = compact.split(":", 1)[1]
    compact = _strip_arxiv_pdf_suffix(compact)
    if _is_arxiv_id(compact):
        return compact

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = str(parsed.netloc or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    if host != "arxiv.org":
        return ""

    path = str(parsed.path or "").strip()
    if not path:
        return ""
    for prefix in ("/abs/", "/pdf/"):
        if path.lower().startswith(prefix):
            candidate = _strip_arxiv_pdf_suffix(path[len(prefix) :])
            return candidate if _is_arxiv_id(candidate) else ""
    return ""


def normalize_arxiv_url(url: str) -> str:
    """
    Normalize arXiv inputs to canonical PDF URL form.

    Examples
    --------
    1706.03762                    → https://arxiv.org/pdf/1706.03762
    arXiv:1706.03762v2            → https://arxiv.org/pdf/1706.03762v2
    arxiv.org/abs/2408.09869      → https://arxiv.org/pdf/2408.09869
    arxiv.org/pdf/2408.09869      → unchanged
    arxiv.org/pdf/2408.09869v2    → unchanged
    """
    arxiv_id = _extract_arxiv_id(url)
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}"

    url = str(url or "").strip()
    # /abs/ → /pdf/
    url = re.sub(r"(arxiv\.org)/abs/", r"\1/pdf/", url, flags=re.IGNORECASE)
    # ensure https://
    if re.match(r"^arxiv\.org", url, re.IGNORECASE):
        url = "https://" + url
    return url


def url_display_name(url: str) -> str:
    """
    Derive a human-readable filename from a URL.

    arxiv.org/pdf/2408.09869   → arxiv_2408.09869.pdf
    arxiv.org/pdf/2408.09869v2 → arxiv_2408.09869v2.pdf
    example.com/paper.pdf      → paper.pdf
    """
    normalized = normalize_arxiv_url(url)
    m = re.search(r"arxiv\.org/pdf/([^\s/?#]+)", normalized, re.IGNORECASE)
    if m:
        arxiv_id = _strip_arxiv_pdf_suffix(m.group(1))
        return f"arxiv_{arxiv_id}.pdf"

    parsed = urlparse(normalized)
    name = os.path.basename(parsed.path.rstrip("/"))
    if not name:
        name = "document"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def download_pdf_to_tempfile(url: str) -> str:
    """
    Download *url* to a temporary file and return its path.

    The caller is responsible for deleting the file afterwards.
    Raises an exception if the download fails.
    """
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; canvas2-importer/1.0; "
                "+https://github.com/canvas2)"
            )
        },
    )
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            tmp.write(resp.read())
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise
    tmp.close()
    return tmp.name
