from __future__ import annotations

from pathlib import Path

from shared.services.project.markdown_assets import (
    absolutize_markdown_image_links,
    materialize_markdown_image_links,
)


def test_materialize_markdown_image_links_decodes_data_uri(tmp_path: Path) -> None:
    assets_dir = tmp_path / "knowledge" / "assets" / "doc_0000"
    markdown = "A\n![img](<data:image/png;base64,QUJD>)\nB"

    out = materialize_markdown_image_links(
        markdown,
        target_assets_dir=assets_dir,
        target_prefix="assets/doc_0000",
    )

    assert "data:image/png;base64" not in out
    assert "![img](<assets/doc_0000/image_0001.png>)" in out
    saved = assets_dir / "image_0001.png"
    assert saved.exists()
    assert saved.read_bytes() == b"ABC"


def test_materialize_markdown_image_links_copies_local_file(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    source_image = source_root / "figure.jpg"
    source_image.write_bytes(b"\x01\x02\x03")

    assets_dir = tmp_path / "knowledge" / "assets" / "doc_0001"
    markdown = "![local](figure.jpg)"

    out = materialize_markdown_image_links(
        markdown,
        target_assets_dir=assets_dir,
        target_prefix="assets/doc_0001",
        source_root=source_root,
    )

    assert "![local](<assets/doc_0001/image_0001.jpg>)" in out
    saved = assets_dir / "image_0001.jpg"
    assert saved.exists()
    assert saved.read_bytes() == b"\x01\x02\x03"


def test_materialize_markdown_image_links_rewrites_external_url_to_local_asset(
    tmp_path: Path,
) -> None:
    assets_dir = tmp_path / "knowledge" / "assets" / "doc_0002"
    markdown = "![img](https://example.com/image.png)"

    out = materialize_markdown_image_links(
        markdown,
        target_assets_dir=assets_dir,
        target_prefix="assets/doc_0002",
    )

    assert "https://example.com" not in out
    assert "![img](<assets/doc_0002/image_0001.png>)" in out
    saved = assets_dir / "image_0001.png"
    assert saved.exists()
    assert saved.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_absolutize_markdown_image_links_resolves_project_relative_paths(
    tmp_path: Path,
) -> None:
    base = tmp_path / "knowledge"
    image = base / "assets" / "doc_0000" / "image_0001.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"png")

    markdown = "![img](<assets/doc_0000/image_0001.png>)"
    out = absolutize_markdown_image_links(markdown, base_dir=base)

    assert out == f"![img](<{image.resolve(strict=False)}>)"


def test_absolutize_markdown_image_links_keeps_external_urls(tmp_path: Path) -> None:
    base = tmp_path / "knowledge"
    base.mkdir(parents=True, exist_ok=True)
    markdown = "![img](https://example.com/image.png)"

    out = absolutize_markdown_image_links(markdown, base_dir=base)

    assert out == markdown
