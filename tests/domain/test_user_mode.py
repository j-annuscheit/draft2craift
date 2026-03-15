from __future__ import annotations

from pathlib import Path

from shared.domain.user_mode import (
    USER_MODE_PLUS,
    USER_MODE_SIMPLE,
    USER_MODE_CONFIG_PATH,
    available_user_modes,
    default_user_mode,
    is_feature_visible,
    mode_rank,
    normalize_user_mode,
    reload_user_mode_config,
    resolve_feature_label,
    resolve_literal_text,
    resolve_literal_tooltip,
)


def test_normalize_user_mode_defaults_to_config_default():
    assert normalize_user_mode("unknown") == default_user_mode()


def test_mode_rank_order_is_stable():
    assert mode_rank(USER_MODE_SIMPLE) < mode_rank(USER_MODE_PLUS)


def test_visibility_from_default_catalog():
    assert is_feature_visible("simple", "menu.ai.edit_prompts", default=True) is False
    assert is_feature_visible("plus", "menu.ai.edit_prompts", default=False) is True


def test_label_resolution_and_inheritance_with_temp_catalog(tmp_path: Path):
    cfg = tmp_path / "user_modes"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "alpha.toml").write_text(
        """
version = 1
id = "alpha"
label = "Alpha"
order = 0
default_profile = true

[visibility]
"feature.a" = true

[labels]
"button.run" = "Run Alpha"
"button.run.tooltip" = "alpha tip"

[literal_labels]
"Model Load" = "Model Setup"

[literal_tooltips]
"Fact Check" = "Validate claims against selected sources."
""".strip(),
        encoding="utf-8",
    )
    (cfg / "beta.toml").write_text(
        """
version = 1
id = "beta"
label = "Beta"
order = 1
default_profile = false

[visibility]
"feature.a" = false
"feature.b" = true

[labels]
"button.run" = "Run Beta"
"button.run.tooltip" = "alpha tip"

[literal_labels]
"Model Load" = "Model Setup Beta"

[literal_tooltips]
"Fact Check" = "Validate claims against selected sources."
""".strip(),
        encoding="utf-8",
    )

    try:
        reload_user_mode_config(cfg)
        assert available_user_modes() == ("alpha", "beta")
        assert default_user_mode() == "alpha"

        assert is_feature_visible("beta", "feature.a", default=True) is False
        assert is_feature_visible("beta", "feature.b", default=False) is True
        assert resolve_feature_label("beta", "button.run", "fallback") == "Run Beta"
        assert resolve_feature_label("beta", "button.run.tooltip", "fallback") == "alpha tip"
        assert resolve_literal_text("beta", "Model Load") == "Model Setup Beta"
        assert (
            resolve_literal_tooltip("beta", "Fact Check")
            == "Validate claims against selected sources."
        )
    finally:
        reload_user_mode_config(USER_MODE_CONFIG_PATH)
