"""Helpers for persisting markdown image references as project assets."""
from __future__ import annotations

import base64
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

_MD_IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\(\s*(<[^>]+>|[^)\s]+)\s*\)")
_DATA_IMAGE_RE = re.compile(
    r"^data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE | re.DOTALL,
)
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_WINDOWS_ABS_RE = re.compile(r"^[a-zA-Z]:[\\/]")
_OFFLINE_IMAGE_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+X2ioAAAAASUVORK5CYII="
)


def _strip_angle_brackets(target: str) -> str:
    raw = str(target or "").strip()
    if raw.startswith("<") and raw.endswith(">"):
        return raw[1:-1].strip()
    return raw


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


def _decode_data_image_url(url: str) -> tuple[bytes, str] | None:
    match = _DATA_IMAGE_RE.match(str(url or ""))
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


def _is_external_url(url: str) -> bool:
    candidate = str(url or "").strip()
    if not candidate:
        return False
    if candidate.lower().startswith("file://"):
        return False
    return bool(_SCHEME_RE.match(candidate))


def _resolve_source_path(source: str, *, source_root: Path | None) -> Path | None:
    raw = str(source or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("file://"):
        parsed = urlparse(raw)
        local = unquote(parsed.path or "")
        if parsed.netloc and parsed.netloc != "localhost":
            local = f"//{parsed.netloc}{local}"
        if not local:
            return None
        return Path(local).expanduser()
    if _WINDOWS_ABS_RE.match(raw):
        return Path(raw)
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    if source_root is not None:
        return (source_root / candidate).resolve(strict=False)
    return candidate.resolve(strict=False)


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def materialize_markdown_image_links(
    markdown_text: str,
    *,
    target_assets_dir: Path,
    target_prefix: str,
    source_root: Path | None = None,
) -> str:
    """
    Copy markdown image sources into ``target_assets_dir`` and rewrite links.

    Supported source inputs:
    - ``data:image/...;base64,...``
    - absolute file paths
    - ``file://`` URLs
    - relative file paths (resolved against ``source_root`` when provided)
    - external URLs (replaced by an offline placeholder image in project assets)
    """
    text = str(markdown_text or "")
    assets_dir = Path(target_assets_dir)
    prefix = str(target_prefix or "").strip().strip("/")
    root = Path(source_root).resolve(strict=False) if source_root is not None else None

    if not text.strip():
        return text
    assets_dir.mkdir(parents=True, exist_ok=True)

    idx = {"value": 0}

    def _rewrite(match: re.Match[str]) -> str:
        alt = str(match.group(1) or "")
        raw_target = str(match.group(2) or "")
        source = _strip_angle_brackets(raw_target)
        if not source:
            return match.group(0)

        payload = _decode_data_image_url(source)
        ext = ""
        blob: bytes | None = None

        if payload is not None:
            blob, ext = payload
        else:
            if _is_external_url(source):
                blob = _OFFLINE_IMAGE_PLACEHOLDER_PNG
                ext = ".png"
            else:
                source_path = _resolve_source_path(source, source_root=root)
                if source_path is None:
                    return match.group(0)
                try:
                    resolved = source_path.resolve(strict=False)
                except Exception:
                    resolved = source_path
                if not resolved.exists() or not resolved.is_file():
                    return match.group(0)
                try:
                    blob = resolved.read_bytes()
                except Exception:
                    return match.group(0)
                ext = str(resolved.suffix or "").lower()
                if not ext:
                    ext = ".png"

        if blob is None:
            return match.group(0)

        idx["value"] = int(idx["value"]) + 1
        file_name = f"image_{int(idx['value']):04d}{ext}"
        target = assets_dir / file_name
        try:
            _write_bytes(target, blob)
        except Exception:
            return match.group(0)

        link_path = f"{prefix}/{file_name}" if prefix else file_name
        return f"![{alt}](<{link_path}>)"

    return _MD_IMAGE_LINK_RE.sub(_rewrite, text)


def absolutize_markdown_image_links(markdown_text: str, *, base_dir: Path) -> str:
    """
    Convert markdown image links with local relative paths to absolute paths.

    External URLs and data-URIs are preserved unchanged.
    """
    text = str(markdown_text or "")
    root = Path(base_dir).resolve(strict=False)
    if not text.strip():
        return text

    def _rewrite(match: re.Match[str]) -> str:
        alt = str(match.group(1) or "")
        raw_target = str(match.group(2) or "")
        source = _strip_angle_brackets(raw_target)
        if not source:
            return match.group(0)
        if _DATA_IMAGE_RE.match(source):
            return match.group(0)
        if _is_external_url(source):
            return match.group(0)
        source_path = _resolve_source_path(source, source_root=root)
        if source_path is None:
            return match.group(0)
        try:
            resolved = source_path.resolve(strict=False)
        except Exception:
            resolved = source_path
        if not resolved.exists() or not resolved.is_file():
            return match.group(0)
        return f"![{alt}](<{resolved}>)"

    return _MD_IMAGE_LINK_RE.sub(_rewrite, text)


__all__ = [
    "absolutize_markdown_image_links",
    "materialize_markdown_image_links",
]
