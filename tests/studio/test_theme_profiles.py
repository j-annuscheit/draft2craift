from __future__ import annotations

import pytest

from studio.theme import (
    apply_theme,
    available_themes,
    current_theme_id,
    normalize_theme_id,
    theme_tokens,
)


pytestmark = pytest.mark.usefixtures("qt_app")


def test_available_themes_contains_requested_variants():
    ids = [theme_id for theme_id, _label in available_themes()]
    assert "light" in ids
    assert "dark" in ids
    assert "darker" in ids
    assert "colorful-light" in ids
    assert "colorful-dark" in ids


def test_normalize_theme_id_accepts_alias():
    assert normalize_theme_id("colorful_light") == "colorful-light"
    assert normalize_theme_id("classic-dark") == "dark"
    assert normalize_theme_id("unknown") == "dark"


def test_apply_theme_sets_current_theme(qt_app):
    previous = current_theme_id()
    try:
        resolved = apply_theme(qt_app, "colorful-dark")
        assert resolved == "colorful-dark"
        assert current_theme_id() == "colorful-dark"
        tokens = theme_tokens("colorful-dark")
        assert tokens["theme_id"] == "colorful-dark"
        assert tokens["accent"].startswith("#")
    finally:
        apply_theme(qt_app, previous)
