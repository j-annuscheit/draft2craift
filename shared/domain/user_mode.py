"""Config-driven user profiles and feature visibility helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

USER_MODE_SIMPLE = "simple"
USER_MODE_PLUS = "plus"
USER_MODE_EXPERT = "expert"


@dataclass(slots=True, frozen=True)
class _ProfileEntry:
    mode_id: str
    label: str
    visibility: dict[str, bool]
    feature_labels: dict[str, str]
    literal_labels: dict[str, str]
    literal_tooltips: dict[str, str]


@dataclass(slots=True, frozen=True)
class _ProfileCatalog:
    order: tuple[str, ...]
    labels: dict[str, str]
    default_mode: str
    visibility: dict[str, dict[str, bool]]
    feature_labels: dict[str, dict[str, str]]
    literal_labels: dict[str, dict[str, str]]
    literal_tooltips: dict[str, dict[str, str]]


_REPO_ROOT = Path(__file__).resolve().parents[2]
USER_MODE_CONFIG_DIR = _REPO_ROOT / "data" / "user_modes"
# Public export used across the codebase/tests.
USER_MODE_CONFIG_PATH = USER_MODE_CONFIG_DIR
_PROFILE_SECTION_KEYS = (
    "visibility",
    "labels",
    "literal_labels",
    "literal_tooltips",
)

_DEFAULT_CATALOG = _ProfileCatalog(
    order=(USER_MODE_SIMPLE, USER_MODE_PLUS, USER_MODE_EXPERT),
    labels={
        USER_MODE_SIMPLE: "Einfach",
        USER_MODE_PLUS: "Plus",
        USER_MODE_EXPERT: "Experte",
    },
    default_mode=USER_MODE_PLUS,
    visibility={},
    feature_labels={},
    literal_labels={},
    literal_tooltips={},
)


def _coerce_visibility_map(raw: object) -> dict[str, bool]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, bool] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name:
            continue
        if isinstance(value, bool):
            out[name] = bool(value)
    return out


def _coerce_label_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name:
            continue
        text = str(value or "").strip()
        if text:
            out[name] = text
    return out


def _parse_single_profile_entry(
    raw: object,
    *,
    fallback_mode_id: str,
) -> tuple[_ProfileEntry | None, int | None, bool]:
    if not isinstance(raw, dict):
        return None, None, False

    # File name is the canonical profile id by convention.
    mode_id = str(fallback_mode_id or "").strip().casefold()
    if not mode_id:
        return None, None, False

    label = str(raw.get("label", mode_id) or "").strip() or mode_id

    order_raw = raw.get("order")
    order: int | None = None
    if isinstance(order_raw, int):
        order = int(order_raw)
    elif isinstance(order_raw, str):
        text = str(order_raw).strip()
        if text:
            try:
                order = int(text)
            except Exception:
                order = None

    default_flag = bool(raw.get("default_profile", False) or raw.get("default", False))
    entry = _ProfileEntry(
        mode_id=mode_id,
        label=label,
        visibility=_coerce_visibility_map(raw.get("visibility", {})),
        feature_labels=_coerce_label_map(raw.get("labels", {})),
        literal_labels=_coerce_label_map(raw.get("literal_labels", {})),
        literal_tooltips=_coerce_label_map(raw.get("literal_tooltips", {})),
    )
    return entry, order, default_flag


def _build_catalog(
    entries_list: list[_ProfileEntry],
    *,
    requested_default: str = "",
) -> _ProfileCatalog:
    if not entries_list:
        return _DEFAULT_CATALOG

    entries_by_id = {entry.mode_id: entry for entry in entries_list}
    order = tuple(entry.mode_id for entry in entries_list)
    labels = {entry.mode_id: entry.label for entry in entries_list}

    requested_default = str(requested_default or "").strip().casefold()
    if requested_default in entries_by_id:
        default_mode = requested_default
    else:
        default_mode = order[0]

    visibility = {entry.mode_id: dict(entry.visibility) for entry in entries_list}
    feature_labels = {entry.mode_id: dict(entry.feature_labels) for entry in entries_list}
    literal_labels = {entry.mode_id: dict(entry.literal_labels) for entry in entries_list}
    literal_tooltips = {entry.mode_id: dict(entry.literal_tooltips) for entry in entries_list}

    return _ProfileCatalog(
        order=order,
        labels=labels,
        default_mode=default_mode,
        visibility=visibility,
        feature_labels=feature_labels,
        literal_labels=literal_labels,
        literal_tooltips=literal_tooltips,
    )


def _load_catalog_from_directory(path: Path) -> _ProfileCatalog:
    files = _sorted_profile_files(path)
    if not files:
        return _DEFAULT_CATALOG

    records: list[tuple[int, int, _ProfileEntry, bool]] = []
    for seq, file_path in enumerate(files):
        raw = _read_toml_file(file_path)
        if raw is None:
            continue

        entry, order, is_default = _parse_single_profile_entry(
            raw,
            fallback_mode_id=file_path.stem,
        )
        if entry is None:
            continue
        order_key = int(order) if order is not None else (100_000 + seq)
        records.append((order_key, seq, entry, is_default))

    if not records:
        return _DEFAULT_CATALOG

    records.sort(key=lambda item: (item[0], item[1]))

    entries_list: list[_ProfileEntry] = []
    default_candidates: list[str] = []
    seen: set[str] = set()
    for _order_key, _seq, entry, is_default in records:
        if entry.mode_id in seen:
            continue
        seen.add(entry.mode_id)
        entries_list.append(entry)
        if is_default:
            default_candidates.append(entry.mode_id)

    requested_default = default_candidates[0] if default_candidates else ""
    return _build_catalog(entries_list, requested_default=requested_default)


def _sorted_profile_files(path: Path) -> list[Path]:
    try:
        return sorted(
            candidate
            for candidate in path.iterdir()
            if candidate.is_file() and candidate.suffix.casefold() == ".toml"
        )
    except Exception:
        return []


def _read_toml_file(path: Path) -> dict | None:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def _load_catalog(path: Path | None = None) -> _ProfileCatalog:
    config_path = USER_MODE_CONFIG_PATH if path is None else Path(path)
    if config_path.is_dir():
        return _load_catalog_from_directory(config_path)
    return _DEFAULT_CATALOG


def validate_user_mode_config(path: str | Path | None = None) -> list[str]:
    """Validate user mode TOML catalog. Returns human-readable issues."""
    config_path = USER_MODE_CONFIG_PATH if path is None else Path(path)
    issues: list[str] = []
    if not config_path.is_dir():
        return [f"Config directory not found: {config_path}"]

    files = _sorted_profile_files(config_path)
    if not files:
        return [f"No profile TOML files found in {config_path}"]

    default_count = 0
    seen_ids: set[str] = set()
    keysets_by_section: dict[str, set[str]] | None = None

    for file_path in files:
        raw = _read_toml_file(file_path)
        if raw is None:
            issues.append(f"{file_path.name}: invalid TOML or unsupported structure.")
            continue

        expected_id = str(file_path.stem).strip().casefold()
        declared_id = str(raw.get("id", "") or "").strip().casefold()
        if declared_id and declared_id != expected_id:
            issues.append(
                f"{file_path.name}: id='{declared_id}' does not match file name '{expected_id}'."
            )
        if expected_id in seen_ids:
            issues.append(f"{file_path.name}: duplicate mode id '{expected_id}'.")
        seen_ids.add(expected_id)

        label = str(raw.get("label", "") or "").strip()
        if not label:
            issues.append(f"{file_path.name}: missing/empty 'label'.")

        if bool(raw.get("default_profile", False)):
            default_count += 1

        current_keysets: dict[str, set[str]] = {}
        for section in _PROFILE_SECTION_KEYS:
            section_map = raw.get(section, {})
            if not isinstance(section_map, dict):
                issues.append(f"{file_path.name}: section '{section}' must be a TOML table.")
                current_keysets[section] = set()
                continue
            keys = {str(k).strip() for k in section_map.keys() if str(k).strip()}
            if not keys:
                issues.append(f"{file_path.name}: section '{section}' must not be empty.")
            current_keysets[section] = keys

        if keysets_by_section is None:
            keysets_by_section = current_keysets
            continue

        for section in _PROFILE_SECTION_KEYS:
            expected = keysets_by_section.get(section, set())
            current = current_keysets.get(section, set())
            if current != expected:
                issues.append(
                    f"{file_path.name}: key set mismatch in section '{section}'."
                )

    if default_count != 1:
        issues.append(
            f"Exactly one profile must set default_profile=true (found {default_count})."
        )
    return issues


def _resolve_profile_map_value(profile_map: dict[str, object], key: str) -> object | None:
    if key in profile_map:
        return profile_map[key]

    parts = [part for part in key.split(".") if part]
    for idx in range(len(parts), 0, -1):
        wildcard = ".".join(parts[:idx]) + ".*"
        if wildcard in profile_map:
            return profile_map[wildcard]

    if "*" in profile_map:
        return profile_map["*"]
    return None


_CATALOG = _load_catalog()

USER_MODE_ORDER = tuple(_CATALOG.order)
USER_MODE_LABELS = dict(_CATALOG.labels)


def reload_user_mode_config(path: str | Path | None = None) -> None:
    """Reload profile config and refresh exported order/labels."""
    global _CATALOG, USER_MODE_ORDER, USER_MODE_LABELS
    _CATALOG = _load_catalog(None if path is None else Path(path))
    USER_MODE_ORDER = tuple(_CATALOG.order)
    USER_MODE_LABELS = dict(_CATALOG.labels)


def default_user_mode() -> str:
    return str(_CATALOG.default_mode or USER_MODE_PLUS)


def available_user_modes() -> tuple[str, ...]:
    return tuple(_CATALOG.order)


def user_mode_label(mode: object) -> str:
    normalized = normalize_user_mode(mode)
    return str(_CATALOG.labels.get(normalized, normalized))


def normalize_user_mode(value: object) -> str:
    text = str(value or "").strip().casefold()
    if text in _CATALOG.labels:
        return text
    for mode_id, label in _CATALOG.labels.items():
        if text == str(label or "").strip().casefold():
            return mode_id
    return default_user_mode()


def mode_rank(value: object) -> int:
    mode = normalize_user_mode(value)
    try:
        return _CATALOG.order.index(mode)
    except ValueError:
        return len(_CATALOG.order)


def is_feature_visible(mode: object, feature_key: str, default: bool = True) -> bool:
    mode_id = normalize_user_mode(mode)
    key = str(feature_key or "").strip()
    if not key:
        return bool(default)

    profile_map = _CATALOG.visibility.get(mode_id, {})
    resolved = _resolve_profile_map_value(profile_map, key)
    if resolved is None:
        return bool(default)
    return bool(resolved)


def resolve_feature_label(mode: object, feature_key: str, default: str) -> str:
    mode_id = normalize_user_mode(mode)
    key = str(feature_key or "").strip()
    if not key:
        return str(default or "")

    profile_map = _CATALOG.feature_labels.get(mode_id, {})
    resolved = _resolve_profile_map_value(profile_map, key)
    if resolved is None:
        return str(default or "")
    return str(resolved or "")


def literal_text_override(mode: object, source_text: str) -> str | None:
    mode_id = normalize_user_mode(mode)
    source = str(source_text or "")
    if not source:
        return None
    profile_map = _CATALOG.literal_labels.get(mode_id, {})
    if source in profile_map:
        return str(profile_map[source] or "")
    return None


def literal_tooltip_override(mode: object, source_tooltip: str) -> str | None:
    mode_id = normalize_user_mode(mode)
    source = str(source_tooltip or "")
    if not source:
        return None
    profile_map = _CATALOG.literal_tooltips.get(mode_id, {})
    if source in profile_map:
        return str(profile_map[source] or "")
    return None


def resolve_literal_text(mode: object, source_text: str) -> str:
    override = literal_text_override(mode, source_text)
    if override is None:
        return str(source_text or "")
    return override


def resolve_literal_tooltip(mode: object, source_tooltip: str) -> str:
    override = literal_tooltip_override(mode, source_tooltip)
    if override is None:
        return str(source_tooltip or "")
    return override
