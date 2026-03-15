from __future__ import annotations

from pathlib import Path
import tomllib

from shared.domain.user_mode import validate_user_mode_config

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_DIR = _REPO_ROOT / "data" / "user_modes"
_CORE_PROFILE_IDS = (
    "easy_eng",
    "middle_eng",
    "expert_eng",
    "simple",
    "plus",
    "expert",
)
_SECTION_KEYS = (
    "visibility",
    "labels",
    "literal_labels",
    "literal_tooltips",
)


def _read_profile(mode_id: str) -> dict:
    path = _PROFILE_DIR / f"{mode_id}.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_core_profile_files_exist() -> None:
    present = {path.stem for path in _PROFILE_DIR.glob("*.toml")}
    for mode_id in _CORE_PROFILE_IDS:
        assert mode_id in present, f"Missing profile file: {mode_id}.toml"


def test_core_profile_files_are_fully_populated_and_aligned() -> None:
    for order, mode_id in enumerate(_CORE_PROFILE_IDS):
        raw = _read_profile(mode_id)

        assert str(raw.get("id", "")).strip().casefold() == mode_id
        assert str(raw.get("label", "")).strip()
        assert int(raw.get("order", -1)) == order
        for section in _SECTION_KEYS:
            value = raw.get(section, {})
            assert isinstance(value, dict), f"{mode_id}.{section} must be a table."
            assert value, f"{mode_id}.{section} must not be empty."


def test_core_profile_catalog_validation_is_clean() -> None:
    issues = validate_user_mode_config(_PROFILE_DIR)
    assert issues == []
