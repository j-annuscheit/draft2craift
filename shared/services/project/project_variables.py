"""Project variable normalization and placeholder resolution helpers."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re


# Primary syntax (documented): ${variable_key}
# Also supported for convenience: {{ variable_key }}
_DOLLAR_PLACEHOLDER_RE = re.compile(r"\$\{([^{}]+)\}")
_BRACE_PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


@dataclass(slots=True, frozen=True)
class ProjectVariableResolution:
    """Result payload for one placeholder-resolution call."""

    text: str
    used_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]


def canonical_project_variable_key(key: object) -> str:
    """Return normalized key token used for lenient lookup."""
    token = str(key or "").strip().casefold()
    if not token:
        return ""
    return _NON_ALNUM_RE.sub("_", token).strip("_")


def normalize_project_variables(raw: object) -> dict[str, str]:
    """Normalize raw variable payload into ``{key: value}`` string map."""
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name:
            continue
        out[name] = str(value or "")
    return out


def resolve_project_variables_text(
    text: object,
    variables: Mapping[str, object] | None,
) -> ProjectVariableResolution:
    """
    Replace project-variable placeholders in *text*.

    Supported placeholders:
    - ``${variable_key}`` (primary)
    - ``{{ variable_key }}`` (secondary, optional spaces)

    Unknown placeholders remain unchanged.
    """
    source = str(text or "")
    normalized_vars = normalize_project_variables(variables or {})
    if not source or not normalized_vars:
        return ProjectVariableResolution(
            text=source,
            used_keys=(),
            missing_keys=(),
        )

    exact: dict[str, str] = {}
    lower: dict[str, str] = {}
    canonical: dict[str, str] = {}
    for key, value in normalized_vars.items():
        clean = str(key or "").strip()
        if not clean:
            continue
        exact[clean] = value
        lowered = clean.casefold()
        if lowered not in lower:
            lower[lowered] = value
        canon = canonical_project_variable_key(clean)
        if canon and canon not in canonical:
            canonical[canon] = value

    used_keys: list[str] = []
    missing_keys: list[str] = []
    seen_used: set[str] = set()
    seen_missing: set[str] = set()

    def resolve_one(raw_key: str) -> str | None:
        key = str(raw_key or "").strip()
        if not key:
            return None
        if key in exact:
            return exact[key]
        lowered = key.casefold()
        if lowered in lower:
            return lower[lowered]
        canon = canonical_project_variable_key(key)
        if canon and canon in canonical:
            return canonical[canon]
        return None

    def replace_match(match: re.Match[str]) -> str:
        placeholder = str(match.group(0) or "")
        key = str(match.group(1) or "").strip()
        if not key:
            return placeholder
        value = resolve_one(key)
        if value is None:
            if key not in seen_missing:
                seen_missing.add(key)
                missing_keys.append(key)
            return placeholder
        if key not in seen_used:
            seen_used.add(key)
            used_keys.append(key)
        return value

    replaced = _DOLLAR_PLACEHOLDER_RE.sub(replace_match, source)
    replaced = _BRACE_PLACEHOLDER_RE.sub(replace_match, replaced)
    return ProjectVariableResolution(
        text=replaced,
        used_keys=tuple(used_keys),
        missing_keys=tuple(missing_keys),
    )


def resolve_project_variables_from_object(owner: object | None) -> dict[str, str]:
    """
    Walk ``owner`` parent-chain and return project variables from the first
    object exposing ``get_project_variables()``.
    """
    current = owner
    visited: set[int] = set()
    while current is not None:
        marker = id(current)
        if marker in visited:
            break
        visited.add(marker)

        getter = getattr(current, "get_project_variables", None)
        if callable(getter):
            try:
                return normalize_project_variables(getter())
            except Exception:
                return {}

        parent_fn = getattr(current, "parent", None)
        current = parent_fn() if callable(parent_fn) else None
    return {}


__all__ = [
    "ProjectVariableResolution",
    "canonical_project_variable_key",
    "normalize_project_variables",
    "resolve_project_variables_from_object",
    "resolve_project_variables_text",
]
