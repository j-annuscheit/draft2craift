"""Policy merge and enforcement helpers."""
from __future__ import annotations

from typing import Any


def merge_policy_layers(*layers: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for src in layers:
        for key, value in dict(src or {}).items():
            out[str(key)] = value
    return out


def merge_policy(
    base_policy: dict[str, Any] | None,
    profile_policy: dict[str, Any] | None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return merge_policy_layers(base_policy, profile_policy, overrides)


def is_step_allowed(policy: dict[str, Any], step_id: str) -> bool:
    allowed = policy.get("allowed_steps")
    if not isinstance(allowed, list) or not allowed:
        return True
    return str(step_id or "") in {str(x) for x in allowed}


def is_tool_allowed(
    *,
    tool_name: str,
    step_id: str,
    policy: dict[str, Any],
    step_allowlist: dict[str, tuple[str, ...]] | None = None,
) -> bool:
    per_step = policy.get("allowed_tools_per_step")
    if isinstance(per_step, dict):
        row = per_step.get(step_id)
        if isinstance(row, list) and row:
            return str(tool_name or "") in {str(x) for x in row}

    if isinstance(step_allowlist, dict):
        row2 = step_allowlist.get(step_id, ())
        if row2:
            return str(tool_name or "") in set(row2)

    strict_policy = bool(policy.get("strict_policy", False))
    if strict_policy:
        return False

    return True
