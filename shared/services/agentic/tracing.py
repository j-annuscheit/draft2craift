"""Run trace persistence for agentic workflows."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contracts import WorkflowDefinition, WorkflowRunResult


def _truncate(value: Any, *, max_text: int = 1200, max_items: int = 48) -> Any:
    if isinstance(value, str):
        text = value
        if len(text) <= max_text:
            return text
        return text[:max_text] + " …[truncated]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= max_items:
                out["__truncated_items__"] = len(value) - max_items
                break
            out[str(key)] = _truncate(item, max_text=max_text, max_items=max_items)
        return out
    if isinstance(value, list):
        if len(value) > max_items:
            rows = value[:max_items]
            return [
                _truncate(item, max_text=max_text, max_items=max_items)
                for item in rows
            ] + [f"... [{len(value) - max_items} more]"]
        return [_truncate(item, max_text=max_text, max_items=max_items) for item in value]
    if isinstance(value, tuple):
        return [_truncate(item, max_text=max_text, max_items=max_items) for item in list(value)]
    return value


def _safe_request_digest(request: dict[str, Any]) -> str:
    raw = json.dumps(_truncate(request), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def write_run_trace(
    *,
    repo_root: Path,
    definition: WorkflowDefinition,
    run_result: WorkflowRunResult,
    request: dict[str, Any],
    policy: dict[str, Any],
    wiring: dict[str, str],
    profile_chain: list[str],
) -> str:
    now = datetime.now(timezone.utc)
    run_id = f"{now.strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}"
    request_digest = _safe_request_digest(dict(request or {}))
    folder = Path(repo_root) / "runs" / "agentic" / now.strftime("%Y%m%d")
    folder.mkdir(parents=True, exist_ok=True)
    file_path = folder / f"{run_id}_{definition.workflow_id}_{request_digest}.json"

    payload = {
        "run_id": run_id,
        "created_at_utc": now.isoformat(timespec="seconds"),
        "workflow": {
            "id": definition.workflow_id,
            "version": definition.workflow_version,
            "schema_version": definition.schema_version,
            "job_type": definition.job_type,
        },
        "profile": {
            "active": run_result.profile_id,
            "chain": list(profile_chain or []),
        },
        "ok": bool(run_result.ok),
        "errors": list(run_result.errors or []),
        "request": _truncate(dict(request or {})),
        "policy": _truncate(dict(policy or {})),
        "wiring": _truncate(dict(wiring or {})),
        "result": _truncate(dict(run_result.result or {})),
        "state": _truncate(dict(run_result.state or {})),
        "metrics": _truncate(dict(run_result.metrics or {})),
        "trace": [
            {
                "step_id": str(item.step_id),
                "runner": str(item.runner),
                "status": str(item.status),
                "duration_ms": float(item.duration_ms),
                "reason": str(item.reason or ""),
                "visit_index": int(item.visit_index or 0),
                "input": _truncate(dict(item.input or {})),
                "output": _truncate(dict(item.output or {})),
                "state_after": _truncate(dict(item.state_after or {})),
            }
            for item in list(run_result.trace or [])
        ],
    }
    file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(file_path)
