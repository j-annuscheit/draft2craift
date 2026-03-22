"""Step runner registry."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re
from typing import Any


RunnerFn = Callable[[Any, Any, dict[str, Any]], Any]

_STABILITY_ALLOWED = {"experimental", "beta", "stable", "deprecated", "internal"}


def _infer_owner(runner_id: str) -> str:
    text = str(runner_id or "").strip()
    if not text:
        return "unknown"
    prefix = text.split(".", 1)[0]
    return str(prefix or "unknown")


def _infer_version(runner_id: str) -> str:
    text = str(runner_id or "").strip()
    if not text:
        return "1.0.0"
    match = re.search(r"\.v(\d+)$", text)
    if not match:
        return "1.0.0"
    major = int(match.group(1))
    return f"{major}.0.0"


@dataclass(frozen=True, slots=True)
class RunnerMetadata:
    owner: str = "unknown"
    stability: str = "stable"
    version: str = "1.0.0"
    deprecated: bool = False
    replaced_by: str = ""
    deprecation_note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": str(self.owner or ""),
            "stability": str(self.stability or ""),
            "version": str(self.version or ""),
            "deprecated": bool(self.deprecated),
            "replaced_by": str(self.replaced_by or ""),
            "deprecation_note": str(self.deprecation_note or ""),
        }


def _coerce_metadata(
    runner_id: str,
    meta: RunnerMetadata | Mapping[str, object] | None,
) -> RunnerMetadata:
    if isinstance(meta, RunnerMetadata):
        owner = str(meta.owner or "").strip() or _infer_owner(runner_id)
        stability = str(meta.stability or "").strip().casefold() or "stable"
        if stability not in _STABILITY_ALLOWED:
            stability = "stable"
        version = str(meta.version or "").strip() or _infer_version(runner_id)
        deprecated = bool(meta.deprecated or stability == "deprecated")
        replaced_by = str(meta.replaced_by or "").strip()
        deprecation_note = str(meta.deprecation_note or "").strip()
        return RunnerMetadata(
            owner=owner,
            stability=stability,
            version=version,
            deprecated=deprecated,
            replaced_by=replaced_by,
            deprecation_note=deprecation_note,
        )
    raw = dict(meta or {})
    owner = str(raw.get("owner", "") or "").strip() or _infer_owner(runner_id)
    stability = str(raw.get("stability", "stable") or "stable").strip().casefold()
    if stability not in _STABILITY_ALLOWED:
        stability = "stable"
    version = str(raw.get("version", "") or "").strip() or _infer_version(runner_id)
    deprecated = bool(raw.get("deprecated", False) or stability == "deprecated")
    replaced_by = str(raw.get("replaced_by", "") or "").strip()
    deprecation_note = str(raw.get("deprecation_note", "") or "").strip()
    return RunnerMetadata(
        owner=owner,
        stability=stability,
        version=version,
        deprecated=deprecated,
        replaced_by=replaced_by,
        deprecation_note=deprecation_note,
    )


class StepRegistry:
    def __init__(self) -> None:
        self._runners: dict[str, RunnerFn] = {}
        self._meta: dict[str, RunnerMetadata] = {}

    def register(
        self,
        runner_id: str,
        fn: RunnerFn,
        *,
        meta: RunnerMetadata | Mapping[str, object] | None = None,
    ) -> None:
        key = str(runner_id or "").strip()
        if not key:
            raise ValueError("Runner id must not be empty.")
        self._runners[key] = fn
        self._meta[key] = _coerce_metadata(key, meta)

    def resolve(self, runner_id: str) -> RunnerFn:
        key = str(runner_id or "").strip()
        fn = self._runners.get(key)
        if fn is None:
            raise KeyError(f"Unknown runner: {runner_id}")
        return fn

    def metadata(self, runner_id: str) -> RunnerMetadata:
        key = str(runner_id or "").strip()
        if key not in self._runners:
            raise KeyError(f"Unknown runner: {runner_id}")
        return self._meta.get(key, _coerce_metadata(key, None))

    def metadata_optional(self, runner_id: str) -> RunnerMetadata | None:
        key = str(runner_id or "").strip()
        if key not in self._runners:
            return None
        return self._meta.get(key, _coerce_metadata(key, None))

    def deprecation_notice(self, runner_id: str) -> str:
        meta = self.metadata(runner_id)
        if not bool(meta.deprecated):
            return ""
        note = (
            f"Deprecated runner '{runner_id}' "
            f"(owner={meta.owner}, stability={meta.stability}, version={meta.version})"
        )
        if meta.replaced_by:
            note += f" -> use '{meta.replaced_by}'"
        if meta.deprecation_note:
            note += f" ({meta.deprecation_note})"
        return note

    def has(self, runner_id: str) -> bool:
        return str(runner_id or "").strip() in self._runners

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._runners.keys()))

    def all_metadata(self) -> dict[str, RunnerMetadata]:
        return {runner_id: self.metadata(runner_id) for runner_id in self.ids()}
