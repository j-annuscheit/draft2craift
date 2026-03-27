from __future__ import annotations

from unittest.mock import Mock, patch

from shared.services.highlights.store_models import HighlightMatch
from studio.canvas.exporting.annotation_export import (
    AnnotationExportOptions,
    build_annotation_export_markdown,
    collect_annotation_export_data,
)


def _fake_store() -> Mock:
    store = Mock()
    store.resolve_matches.return_value = [
        HighlightMatch(
            highlight_id="hl_1",
            start=0,
            end=5,
            color="#F9E2AF",
            hover_text="",
            jump_to="",
            kind="user",
        ),
        HighlightMatch(
            highlight_id="gls_1",
            start=6,
            end=10,
            color="#94E2D5",
            hover_text="",
            jump_to="",
            kind="glossary",
        ),
        HighlightMatch(
            highlight_id="hl_2",
            start=11,
            end=16,
            color="#A6E3A1",
            hover_text="",
            jump_to="",
            kind="user",
        ),
    ]
    store.snapshot.return_value = {
        "highlights": [
            {
                "id": "hl_1",
                "hover_text": "Kommentar A",
                "created_at": "2026-03-01T10:00:00+00:00",
            },
            {
                "id": "gls_1",
                "hover_text": "Definition B",
                "kind": "glossary",
                "created_at": "2026-03-01T10:00:05+00:00",
            },
            {
                "id": "hl_2",
                "hover_text": "Kommentar C",
                "created_at": "2026-03-01T10:01:00+00:00",
            },
        ]
    }
    return store


def test_collect_annotation_export_data_builds_color_and_glossary_metadata():
    source_text = "Alpha Beta Gamma"
    with patch("studio.canvas.exporting.annotation_export.get_highlight_store", return_value=_fake_store()):
        data = collect_annotation_export_data(
            panel_scope="draft",
            tab_name="Draft 1",
            source_text=source_text,
        )

    assert data.has_entries is True
    assert len(data.entries) == 3
    assert data.color_counts == (("#F9E2AF", 1), ("#A6E3A1", 1))
    assert data.glossary_count == 1
    assert data.entries[0].text == "Alpha"
    assert data.entries[1].text == "Beta"
    assert data.entries[2].text == "Gamma"


def test_build_annotation_export_markdown_supports_grouping_and_markers():
    source_text = "Alpha Beta Gamma"
    with patch("studio.canvas.exporting.annotation_export.get_highlight_store", return_value=_fake_store()):
        data = collect_annotation_export_data(
            panel_scope="draft",
            tab_name="Draft 1",
            source_text=source_text,
        )

    markdown = build_annotation_export_markdown(
        panel_scope="draft",
        tab_name="Draft 1",
        data=data,
        options=AnnotationExportOptions(
            include_colors=("#F9E2AF", "#A6E3A1"),
            include_glossary=True,
            include_comments=True,
            sort_mode="grouped_by_color",
            keep_markers=True,
        ),
    )

    assert "## Farbe: Gelb" in markdown
    assert "## Farbe: Grün" in markdown
    assert "## Glossar" in markdown
    assert "#F9E2AF" not in markdown
    assert "#A6E3A1" not in markdown
    assert "#94E2D5" not in markdown
    assert "> **Gelb**:" not in markdown
    assert "> <mark style=\"background-color: lemonchiffon;\">Alpha</mark>" in markdown
    assert "<mark style=\"background-color: lemonchiffon;\">Alpha</mark>" in markdown
    assert "Kommentar: Kommentar A" in markdown
    assert "Glossar-Kommentar: Definition B" in markdown


def test_build_annotation_export_markdown_filters_colors_and_glossary():
    source_text = "Alpha Beta Gamma"
    with patch("studio.canvas.exporting.annotation_export.get_highlight_store", return_value=_fake_store()):
        data = collect_annotation_export_data(
            panel_scope="draft",
            tab_name="Draft 1",
            source_text=source_text,
        )

    markdown = build_annotation_export_markdown(
        panel_scope="draft",
        tab_name="Draft 1",
        data=data,
        options=AnnotationExportOptions(
            include_colors=("#F9E2AF",),
            include_glossary=False,
            include_comments=False,
            sort_mode="chronological",
            keep_markers=False,
        ),
    )

    assert "## Chronologisch" in markdown
    assert "> **Gelb**:" in markdown
    assert "Alpha" in markdown
    assert "Beta" not in markdown
    assert "Gamma" not in markdown
    assert "<mark style=" not in markdown
    assert "#F9E2AF" not in markdown
    assert "Kommentar:" not in markdown
