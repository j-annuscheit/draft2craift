from __future__ import annotations

from pathlib import Path

from shared.services.importer.pdf.docling_backend import (
    _contains_docling_placeholders,
    _export_docling_html,
    _inject_docling_markdown_image_refs,
)


class _FakeDoc:
    def __init__(self, handlers: list[tuple[dict[str, object], object]]) -> None:
        self.calls: list[dict[str, object]] = []
        self._handlers = list(handlers)

    def export_to_html(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self._handlers:
            expected, result = self._handlers.pop(0)
            if expected != kwargs:
                # strict mode for predictable tests
                raise AssertionError(f"Unexpected kwargs: got={kwargs!r} expected={expected!r}")
            if isinstance(result, Exception):
                raise result
            return result
        return "<p>fallback</p>"


def test_inject_docling_markdown_image_refs_replaces_known_placeholders() -> None:
    md = "A\n<!-- image -->\nB\n<!-- image -->\nC"
    html = (
        "<div>"
        "<img src=\"data:image/png;base64,AAA\"/>"
        "<img src=\"data:image/png;base64,BBB\"/>"
        "</div>"
    )
    out = _inject_docling_markdown_image_refs(md, html)
    assert "![docling-image-1](<data:image/png;base64,AAA>)" in out
    assert "![docling-image-2](<data:image/png;base64,BBB>)" in out
    assert "<!-- image -->" not in out


def test_inject_docling_markdown_image_refs_keeps_unresolved_placeholders() -> None:
    md = "A\n<!-- image -->\nB\n<!-- image -->\nC"
    html = "<div><img src=\"data:image/png;base64,AAA\"/></div>"
    out = _inject_docling_markdown_image_refs(md, html)
    assert "![docling-image-1](<data:image/png;base64,AAA>)" in out
    assert "<!-- image -->" in out


def test_inject_docling_markdown_image_refs_keeps_formula_placeholder() -> None:
    md = "A\n<!-- formula-not-decoded -->\nB"
    html = "<div><img src=\"data:image/png;base64,AAA\"/></div>"
    out = _inject_docling_markdown_image_refs(md, html)
    assert "<!-- formula-not-decoded -->" in out


def test_inject_docling_markdown_image_refs_persists_data_images_to_files(
    tmp_path: Path,
) -> None:
    md = "A\n<!-- image -->\nB"
    html = "<div><img src=\"data:image/png;base64,QUJD\"/></div>"
    out = _inject_docling_markdown_image_refs(
        md,
        html,
        image_output_dir=tmp_path,
    )
    assert "data:image/png;base64" not in out
    assert "docling_image_0001.png" in out
    expected = tmp_path / "docling_image_0001.png"
    assert expected.exists()
    assert expected.read_bytes() == b"ABC"


def test_export_docling_html_prefers_non_placeholder_result(monkeypatch) -> None:
    import shared.services.importer.pdf.docling_backend as backend

    monkeypatch.setattr(
        backend,
        "_resolve_docling_image_mode_values",
        lambda: ("embedded",),
    )

    class _Doc:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def export_to_html(self, **kwargs):
            self.calls.append(dict(kwargs))
            if kwargs == {"image_mode": "embedded"}:
                return "<p><!-- image --></p>"
            if kwargs == {}:
                return "<div><img src=\"data:image/png;base64,AAA\"/></div>"
            raise TypeError("unsupported kwargs")

    doc = _Doc()

    # Monkey-friendly deterministic path: first call with explicit mode, then fallback {}
    out = _export_docling_html(doc, want_images=True)
    assert "data:image/png;base64" in out
    assert _contains_docling_placeholders(out) is False


def test_export_docling_html_falls_back_when_kwargs_not_supported() -> None:
    class _TypeErrorDoc:
        def __init__(self) -> None:
            self.calls = 0

        def export_to_html(self, **kwargs):
            self.calls += 1
            if kwargs:
                raise TypeError("unexpected keyword")
            return "<p>ok</p>"

    doc = _TypeErrorDoc()
    out = _export_docling_html(doc, want_images=True)
    assert out == "<p>ok</p>"
    assert doc.calls >= 1
