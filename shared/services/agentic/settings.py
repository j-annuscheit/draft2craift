"""Shared runtime settings for agentic workflow execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Any

from .loader import load_workflow_profile

_TRUTHY = {"1", "true", "yes", "on"}
_WORKFLOW_KEYS = ("factcheck", "chat", "canvas", "mindmap", "graph")
_WORKFLOW_IDS = {
    "factcheck": "factcheck_agentic",
    "chat": "chat_agentic",
    "canvas": "canvas_agentic",
    "mindmap": "mindmap_agentic",
    "graph": "graph_agentic",
}
_WORKFLOW_ID_TO_KEY = {value: key for key, value in _WORKFLOW_IDS.items()}
_DEFAULT_PROFILES = {
    "factcheck": "factcheck_regex_only",
    "chat": "chat_grounded_strict",
    "canvas": "canvas_grounded_rewrite",
    "mindmap": "mindmap_grounded_graph",
    "graph": "graph_connected_component",
}
_MAP_RESULT_DETAIL_LEVELS = {"auto", "compact", "standard", "detailed"}


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().casefold() in _TRUTHY


def _env_text(name: str, default: str = "") -> str:
    value = str(os.environ.get(name, "") or "").strip()
    return value if value else str(default or "")


def _env_flag_with_fallback(name: str, fallback: bool) -> bool:
    raw = os.environ.get(name)
    text = str(raw or "").strip()
    if not text:
        return bool(fallback)
    return _parse_bool(text, default=bool(fallback))


def _parse_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return bool(value)
    text = str(value or "").strip().casefold()
    if text in _TRUTHY:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _parse_text(value: object, *, default: str) -> str:
    text = str(value or "").strip()
    return text if text else str(default or "")


def _normalize_map_result_detail_level(value: object, *, default: str = "auto") -> str:
    text = str(value or "").strip().casefold()
    if text in _MAP_RESULT_DETAIL_LEVELS:
        return text
    return str(default or "auto")


def _split_overlay_ids(raw: object) -> list[str]:
    text = str(raw or "")
    out: list[str] = []
    seen: set[str] = set()
    for token in text.replace("\n", ",").split(","):
        item = str(token or "").strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


@dataclass(slots=True)
class AgenticRuntimeSettings:
    """User-configurable runtime settings used by agentic workflow entrypoints."""

    factcheck_enabled: bool
    chat_enabled: bool
    canvas_enabled: bool
    mindmap_enabled: bool
    graph_enabled: bool

    factcheck_profile_id: str
    chat_profile_id: str
    canvas_profile_id: str
    mindmap_profile_id: str
    graph_profile_id: str

    strict_policy: bool
    trace_enabled: bool
    cache_enabled: bool
    map_result_detail_level: str
    env_name: str
    overlay_profile_ids_raw: str

    @classmethod
    def defaults(cls) -> "AgenticRuntimeSettings":
        mindmap_enabled = _env_flag("D2C_AGENTIC_MINDMAP")
        return cls(
            factcheck_enabled=_env_flag("D2C_AGENTIC_FACTCHECK"),
            chat_enabled=_env_flag("D2C_AGENTIC_CHAT"),
            canvas_enabled=_env_flag("D2C_AGENTIC_CANVAS"),
            mindmap_enabled=mindmap_enabled,
            graph_enabled=_env_flag_with_fallback(
                "D2C_AGENTIC_GRAPH",
                mindmap_enabled,
            ),
            factcheck_profile_id=_env_text(
                "D2C_AGENTIC_FACTCHECK_PROFILE",
                _DEFAULT_PROFILES["factcheck"],
            ),
            chat_profile_id=_env_text(
                "D2C_AGENTIC_CHAT_PROFILE",
                _DEFAULT_PROFILES["chat"],
            ),
            canvas_profile_id=_env_text(
                "D2C_AGENTIC_CANVAS_PROFILE",
                _DEFAULT_PROFILES["canvas"],
            ),
            mindmap_profile_id=_env_text(
                "D2C_AGENTIC_MINDMAP_PROFILE",
                _DEFAULT_PROFILES["mindmap"],
            ),
            graph_profile_id=_env_text(
                "D2C_AGENTIC_GRAPH_PROFILE",
                _DEFAULT_PROFILES["graph"],
            ),
            strict_policy=_env_flag("D2C_AGENTIC_STRICT_POLICY"),
            trace_enabled=_env_flag("D2C_AGENTIC_TRACE"),
            cache_enabled=not _env_flag("D2C_AGENTIC_CACHE_DISABLED"),
            map_result_detail_level=_normalize_map_result_detail_level(
                os.environ.get("D2C_AGENTIC_MAP_RESULT_DETAIL", "auto"),
            ),
            env_name=_env_text("D2C_AGENTIC_ENV", ""),
            overlay_profile_ids_raw="",
        )

    @classmethod
    def from_dict(cls, raw: object) -> "AgenticRuntimeSettings":
        defaults = cls.defaults()
        if not isinstance(raw, dict):
            return defaults
        data = dict(raw)
        return cls(
            factcheck_enabled=_parse_bool(
                data.get("factcheck_enabled"),
                default=defaults.factcheck_enabled,
            ),
            chat_enabled=_parse_bool(
                data.get("chat_enabled"),
                default=defaults.chat_enabled,
            ),
            canvas_enabled=_parse_bool(
                data.get("canvas_enabled"),
                default=defaults.canvas_enabled,
            ),
            mindmap_enabled=_parse_bool(
                data.get("mindmap_enabled"),
                default=defaults.mindmap_enabled,
            ),
            graph_enabled=_parse_bool(
                data.get("graph_enabled"),
                default=defaults.graph_enabled,
            ),
            factcheck_profile_id=_parse_text(
                data.get("factcheck_profile_id"),
                default=defaults.factcheck_profile_id,
            ),
            chat_profile_id=_parse_text(
                data.get("chat_profile_id"),
                default=defaults.chat_profile_id,
            ),
            canvas_profile_id=_parse_text(
                data.get("canvas_profile_id"),
                default=defaults.canvas_profile_id,
            ),
            mindmap_profile_id=_parse_text(
                data.get("mindmap_profile_id"),
                default=defaults.mindmap_profile_id,
            ),
            graph_profile_id=_parse_text(
                data.get("graph_profile_id"),
                default=defaults.graph_profile_id,
            ),
            strict_policy=_parse_bool(
                data.get("strict_policy"),
                default=defaults.strict_policy,
            ),
            trace_enabled=_parse_bool(
                data.get("trace_enabled"),
                default=defaults.trace_enabled,
            ),
            cache_enabled=_parse_bool(
                data.get("cache_enabled"),
                default=defaults.cache_enabled,
            ),
            map_result_detail_level=_normalize_map_result_detail_level(
                data.get("map_result_detail_level"),
                default=defaults.map_result_detail_level,
            ),
            env_name=_parse_text(
                data.get("env_name"),
                default=defaults.env_name,
            ),
            overlay_profile_ids_raw=_parse_text(
                data.get("overlay_profile_ids_raw"),
                default=defaults.overlay_profile_ids_raw,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def clone(self) -> "AgenticRuntimeSettings":
        return self.from_dict(self.to_dict())

    def enabled_for(self, workflow_key: str) -> bool:
        key = str(workflow_key or "").strip().casefold()
        if key == "factcheck":
            return bool(self.factcheck_enabled)
        if key == "chat":
            return bool(self.chat_enabled)
        if key == "canvas":
            return bool(self.canvas_enabled)
        if key == "mindmap":
            return bool(self.mindmap_enabled)
        if key == "graph":
            return bool(self.graph_enabled)
        return False

    def profile_for(self, workflow_key: str) -> str:
        key = str(workflow_key or "").strip().casefold()
        if key == "factcheck":
            return str(self.factcheck_profile_id or _DEFAULT_PROFILES["factcheck"])
        if key == "chat":
            return str(self.chat_profile_id or _DEFAULT_PROFILES["chat"])
        if key == "canvas":
            return str(self.canvas_profile_id or _DEFAULT_PROFILES["canvas"])
        if key == "mindmap":
            return str(self.mindmap_profile_id or _DEFAULT_PROFILES["mindmap"])
        if key == "graph":
            return str(self.graph_profile_id or _DEFAULT_PROFILES["graph"])
        return ""

    def overlay_profile_ids(self) -> list[str]:
        return _split_overlay_ids(self.overlay_profile_ids_raw)

    def policy_overrides(self) -> dict[str, Any]:
        return {
            "strict_policy": bool(self.strict_policy),
            "trace_enabled": bool(self.trace_enabled),
            "cache_policy": {"enabled": bool(self.cache_enabled)},
        }

    def run_options_for(self, workflow_key: str) -> dict[str, Any]:
        return {
            "enabled": self.enabled_for(workflow_key),
            "profile_id": self.profile_for(workflow_key),
            "policy_overrides": self.policy_overrides(),
            "overlay_profile_ids": self.overlay_profile_ids(),
            "env_name": str(self.env_name or ""),
        }


def discover_profile_ids_by_workflow(
    repo_root: Path | None = None,
) -> dict[str, list[str]]:
    """Return discovered profile ids keyed by logical workflow name."""
    root = Path(repo_root or Path(__file__).resolve().parents[3])
    profiles_dir = root / "data" / "workflows" / "profiles"
    out: dict[str, list[str]] = {key: [] for key in _WORKFLOW_KEYS}
    if not profiles_dir.is_dir():
        return out

    for candidate in sorted(profiles_dir.iterdir()):
        if not candidate.is_file():
            continue
        if candidate.suffix.casefold() != ".toml":
            continue
        try:
            profile = load_workflow_profile(candidate)
        except Exception:
            continue
        workflow_key = _WORKFLOW_ID_TO_KEY.get(str(profile.workflow_id or "").strip())
        profile_id = str(profile.profile_id or "").strip()
        if not workflow_key or not profile_id:
            continue
        out[workflow_key].append(profile_id)

    for key, fallback in _DEFAULT_PROFILES.items():
        rows = out.get(key, [])
        dedup = sorted({str(item or "").strip() for item in rows if str(item or "").strip()})
        if fallback not in dedup:
            dedup.insert(0, fallback)
        out[key] = dedup
    return out


def workflow_id_for_key(workflow_key: str) -> str:
    """Resolve logical workflow name to concrete workflow id."""
    key = str(workflow_key or "").strip().casefold()
    return str(_WORKFLOW_IDS.get(key, "") or "")
