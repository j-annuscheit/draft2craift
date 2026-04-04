from __future__ import annotations

from shared.services.importer.url_utils import (
    is_pdf_url,
    normalize_arxiv_url,
    url_display_name,
)


def test_normalize_arxiv_url_accepts_plain_modern_id() -> None:
    assert normalize_arxiv_url("1706.03762") == "https://arxiv.org/pdf/1706.03762"


def test_normalize_arxiv_url_accepts_prefixed_modern_id() -> None:
    assert normalize_arxiv_url("arXiv:1706.03762v2") == "https://arxiv.org/pdf/1706.03762v2"


def test_normalize_arxiv_url_accepts_abs_url() -> None:
    assert (
        normalize_arxiv_url("https://arxiv.org/abs/1706.03762")
        == "https://arxiv.org/pdf/1706.03762"
    )


def test_normalize_arxiv_url_accepts_host_without_scheme() -> None:
    assert (
        normalize_arxiv_url("arxiv.org/abs/1706.03762")
        == "https://arxiv.org/pdf/1706.03762"
    )


def test_is_pdf_url_treats_arxiv_abs_as_pdf_after_normalization() -> None:
    assert is_pdf_url("https://arxiv.org/abs/1706.03762") is True


def test_url_display_name_handles_arxiv_pdf_suffix_without_double_pdf() -> None:
    assert (
        url_display_name("https://arxiv.org/pdf/1706.03762.pdf")
        == "arxiv_1706.03762.pdf"
    )

