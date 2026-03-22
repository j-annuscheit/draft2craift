"""Generic workflow engine for agentic step graphs."""
from __future__ import annotations

from copy import deepcopy
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .conditions import eval_condition
from .contracts import StepOutcome, StepTrace, WorkflowDefinition, WorkflowRunResult
from .paths import get_path, pop_path, set_path
from .policy import is_step_allowed, is_tool_allowed
from .projection import project_context
from .registry import StepRegistry
from .tool_runtime import (
    cache_enabled,
    cache_ttl_for_tool,
    make_cache_key,
    resolve_model_route,
)


def _set_target(ctx: "ExecutionContext", path: str, value: Any) -> None:
    target = str(path or "")
    if not target:
        return
    if target.startswith("state."):
        set_path(ctx.state, target[len("state."):], value)
        return
    if target.startswith("result."):
        set_path(ctx.result, target[len("result."):], value)
        return
    set_path(ctx.state, target, value)


def _read_target(ctx: "ExecutionContext", path: str) -> Any:
    target = str(path or "").strip()
    if not target:
        return None
    if target.startswith("state."):
        return get_path(ctx.state, target[len("state."):], None)
    if target.startswith("result."):
        return get_path(ctx.result, target[len("result."):], None)
    return get_path(ctx.state, target, None)


def _trace_output_payload(step: Any, outcome: StepOutcome) -> dict[str, Any]:
    payload = {
        "value": outcome.value,
        "updates": dict(outcome.updates or {}),
        "jump": str(outcome.jump or ""),
        "stop": bool(outcome.stop),
        "meta": dict(outcome.meta or {}),
        "candidate_writes": deepcopy(dict(outcome.candidate_writes or {})),
        "commit_candidates": list(outcome.commit_candidates or ()),
        "discard_candidates": list(outcome.discard_candidates or ()),
    }
    write_to = str(getattr(step, "write_to", "") or "").strip()
    if write_to:
        payload["write_to"] = write_to
    return payload


def _trace_state_after(ctx: "ExecutionContext", touched_paths: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    seen: set[str] = set()
    for path in touched_paths:
        clean_path = str(path or "").strip()
        if not clean_path or clean_path in seen:
            continue
        seen.add(clean_path)
        out[clean_path] = _read_target(ctx, clean_path)
    return out


def _candidate_state_path(key: str) -> str:
    return f"state._candidates.{str(key or '').strip()}"


def _runtime_state_path(suffix: str) -> str:
    clean = str(suffix or "").strip()
    return f"state._runtime.{clean}" if clean else "state._runtime"


def _normalize_candidate_write(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return {
            "write_to": str(raw.get("write_to", "") or ""),
            "value": raw.get("value"),
            "updates": dict(raw.get("updates", {}) or {}),
            "meta": dict(raw.get("meta", {}) or {}),
        }
    return {
        "write_to": "",
        "value": raw,
        "updates": {},
        "meta": {},
    }


def _candidate_touched_paths(candidate: dict[str, Any]) -> list[str]:
    touched: list[str] = []
    write_to = str(candidate.get("write_to", "") or "").strip()
    if write_to:
        touched.append(write_to)
    for path in dict(candidate.get("updates", {}) or {}).keys():
        clean_path = str(path or "").strip()
        if clean_path:
            touched.append(clean_path)
    return touched


def _store_candidate(
    ctx: "ExecutionContext",
    *,
    step_id: str,
    visit_index: int,
    key: str,
    raw_candidate: Any,
) -> list[str]:
    candidate = _normalize_candidate_write(raw_candidate)
    candidate_path = _candidate_state_path(key)
    base_paths = _candidate_touched_paths(candidate)
    base_state = {
        path: deepcopy(_read_target(ctx, path))
        for path in base_paths
    }
    envelope = {
        "key": str(key or "").strip(),
        "write_to": candidate.get("write_to"),
        "value": deepcopy(candidate.get("value")),
        "updates": deepcopy(dict(candidate.get("updates", {}) or {})),
        "meta": deepcopy(dict(candidate.get("meta", {}) or {})),
        "base_state": base_state,
        "source_step": str(step_id or ""),
        "visit_index": int(visit_index),
    }
    _set_target(ctx, candidate_path, envelope)
    return [candidate_path]


def _apply_candidate(ctx: "ExecutionContext", key: str) -> list[str]:
    clean_key = str(key or "").strip()
    if not clean_key:
        return []
    candidate_path = _candidate_state_path(clean_key)
    envelope = _read_target(ctx, candidate_path)
    if not isinstance(envelope, dict):
        raise KeyError(f"Candidate not found: {clean_key}")
    touched = [candidate_path]
    write_to = str(envelope.get("write_to", "") or "").strip()
    if write_to:
        _set_target(ctx, write_to, deepcopy(envelope.get("value")))
        touched.append(write_to)
    for path, value in dict(envelope.get("updates", {}) or {}).items():
        clean_path = str(path or "").strip()
        if not clean_path:
            continue
        _set_target(ctx, clean_path, deepcopy(value))
        touched.append(clean_path)
    pop_path(ctx.state, candidate_path[len("state."):])
    return touched


def _discard_candidate(ctx: "ExecutionContext", key: str) -> list[str]:
    clean_key = str(key or "").strip()
    if not clean_key:
        return []
    candidate_path = _candidate_state_path(clean_key)
    pop_path(ctx.state, candidate_path[len("state."):])
    return [candidate_path]


def _outcome_touched_paths(step: Any, outcome: StepOutcome) -> list[str]:
    touched: list[str] = []
    write_to = str(getattr(step, "write_to", "") or "").strip()
    if write_to:
        touched.append(write_to)
    for path in dict(outcome.updates or {}).keys():
        clean_path = str(path or "").strip()
        if clean_path:
            touched.append(clean_path)
    for key in dict(outcome.candidate_writes or {}).keys():
        clean_key = str(key or "").strip()
        if clean_key:
            touched.append(_candidate_state_path(clean_key))
    return touched


def _policy_int(policy: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(policy.get(key, default) or default)
    except Exception:
        return int(default)


def _policy_float(policy: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(policy.get(key, default) or default)
    except Exception:
        return float(default)


def _tool_call_total(metrics: dict[str, int], prefix: str) -> int:
    total = 0
    want = str(prefix or "").strip()
    for name, value in dict(metrics or {}).items():
        key = str(name or "").strip()
        if not key or "#" in key:
            continue
        if key == want or key.startswith(f"{want}."):
            total += int(value or 0)
    return total


def _budget_violation(
    *,
    policy: dict[str, Any],
    metrics: dict[str, int],
    elapsed_ms: float,
) -> str:
    max_runtime_seconds = _policy_float(policy, "max_runtime_seconds", 0.0)
    if max_runtime_seconds > 0 and elapsed_ms > (float(max_runtime_seconds) * 1000.0):
        return f"max_runtime_seconds_exceeded:{round(elapsed_ms / 1000.0, 3)}>{max_runtime_seconds}"

    llm_calls = _tool_call_total(metrics, "llm")
    max_llm_calls = _policy_int(policy, "max_llm_calls", 0)
    if max_llm_calls > 0 and llm_calls > max_llm_calls:
        return f"max_llm_calls_exceeded:{llm_calls}>{max_llm_calls}"

    rag_calls = _tool_call_total(metrics, "rag")
    max_rag_calls = _policy_int(policy, "max_rag_calls", 0)
    if max_rag_calls > 0 and rag_calls > max_rag_calls:
        return f"max_rag_calls_exceeded:{rag_calls}>{max_rag_calls}"

    nli_calls = _tool_call_total(metrics, "nli")
    max_nli_calls = _policy_int(policy, "max_nli_calls", 0)
    if max_nli_calls > 0 and nli_calls > max_nli_calls:
        return f"max_nli_calls_exceeded:{nli_calls}>{max_nli_calls}"
    return ""


@dataclass(slots=True)
class ToolGateway:
    tools: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    step_allowlist: dict[str, tuple[str, ...]] = field(default_factory=dict)
    current_step_id: str = ""
    current_step_logical_key: str = ""
    metrics: dict[str, int] = field(default_factory=dict)
    _cache: dict[str, tuple[float, Any]] = field(default_factory=dict)

    @staticmethod
    def _should_cache_value(tool_name: str, value: Any) -> bool:
        name = str(tool_name or "").strip()
        if name == "llm.generate":
            if value is None:
                return False
            if isinstance(value, str) and not str(value).strip():
                return False
        return True

    def call(self, tool_name: str, *args, **kwargs):
        name = str(tool_name or "").strip()
        if not is_tool_allowed(
            tool_name=name,
            step_id=self.current_step_id,
            policy=self.policy,
            step_allowlist=self.step_allowlist,
        ):
            raise PermissionError(f"Tool not allowed in step '{self.current_step_id}': {name}")
        fn = self.tools.get(name)
        if not callable(fn):
            raise KeyError(f"Tool not found: {name}")

        model_route = resolve_model_route(
            model_routing=dict(self.policy.get("model_routing", {}) or {}),
            step_id=self.current_step_id,
            logical_step_key=self.current_step_logical_key,
        )
        call_kwargs = dict(kwargs or {})
        if model_route and "_model_route" not in call_kwargs:
            call_kwargs["_model_route"] = model_route

        cache_on = cache_enabled(self.policy)
        if cache_on:
            ttl = cache_ttl_for_tool(self.policy, name)
            if ttl > 0:
                key = make_cache_key(name, args, call_kwargs)
                row = self._cache.get(key)
                now = time.monotonic()
                if row is not None:
                    expires_at, value = row
                    if now <= float(expires_at):
                        self.metrics[f"{name}#cache_hit"] = int(
                            self.metrics.get(f"{name}#cache_hit", 0)
                        ) + 1
                        return value
                value = fn(*args, **call_kwargs)
                if self._should_cache_value(name, value):
                    self._cache[key] = (now + ttl, value)
                self.metrics[f"{name}#cache_miss"] = int(
                    self.metrics.get(f"{name}#cache_miss", 0)
                ) + 1
                self.metrics[name] = int(self.metrics.get(name, 0)) + 1
                return value

        self.metrics[name] = int(self.metrics.get(name, 0)) + 1
        return fn(*args, **call_kwargs)


@dataclass(slots=True)
class ExecutionContext:
    request: dict[str, Any]
    state: dict[str, Any]
    policy: dict[str, Any]
    result: dict[str, Any]
    tools: ToolGateway
    errors: list[str] = field(default_factory=list)


def _projected_bucket_path(path: str) -> tuple[str, str] | None:
    text = str(path or "").strip()
    if not text or "." not in text:
        return None
    root, sub = text.split(".", 1)
    root_clean = str(root or "").strip()
    sub_clean = str(sub or "").strip()
    if root_clean not in {"request", "state", "policy", "result"}:
        return None
    if not sub_clean:
        return None
    if "[" in sub_clean or "]" in sub_clean:
        # Indexed/wildcard paths are available via `projected`/projection_get.
        return None
    return root_clean, sub_clean


def _build_projected_execution_context(
    *,
    full_ctx: ExecutionContext,
    projected: dict[str, Any],
) -> ExecutionContext:
    raw = projected.get("raw", {}) if isinstance(projected, dict) else {}
    buckets: dict[str, dict[str, Any]] = {
        "request": {},
        "state": {},
        "policy": {},
        "result": {},
    }
    for path, value in dict(raw or {}).items():
        target = _projected_bucket_path(str(path))
        if target is None:
            continue
        root, sub = target
        set_path(buckets[root], sub, deepcopy(value))
    return ExecutionContext(
        request=buckets["request"],
        state=buckets["state"],
        policy=buckets["policy"],
        result=buckets["result"],
        tools=full_ctx.tools,
        errors=full_ctx.errors,
    )


def _normalize_outcome(value: Any) -> StepOutcome:
    if isinstance(value, StepOutcome):
        return value
    if isinstance(value, dict):
        if any(
            k in value
            for k in (
                "value",
                "updates",
                "jump",
                "stop",
                "meta",
                "candidate_writes",
                "commit_candidates",
                "discard_candidates",
            )
        ):
            return StepOutcome(
                value=value.get("value"),
                updates=dict(value.get("updates", {}) or {}),
                jump=str(value.get("jump", "") or ""),
                stop=bool(value.get("stop", False)),
                meta=dict(value.get("meta", {}) or {}),
                candidate_writes=deepcopy(dict(value.get("candidate_writes", {}) or {})),
                commit_candidates=tuple(
                    str(item or "").strip()
                    for item in list(value.get("commit_candidates", []) or [])
                    if str(item or "").strip()
                ),
                discard_candidates=tuple(
                    str(item or "").strip()
                    for item in list(value.get("discard_candidates", []) or [])
                    if str(item or "").strip()
                ),
            )
    return StepOutcome(value=value)


def _extract_decisive_param(condition: str) -> str:
    """Return the first dotted-path identifier from a condition expression.

    "state.map_validation.ok == False"  →  "state.map_validation.ok"
    "state.graph_closure_decision.retry == True"  →  "state.graph_closure_decision.retry"
    """
    if not condition:
        return ""
    m = re.match(r"([A-Za-z_][A-Za-z0-9_.]*)", condition.strip())
    return m.group(1) if m else ""


def _compute_transition(
    *,
    current: str,
    outcome: "StepOutcome",
    status: str,
    ctx: "ExecutionContext",
    edges_by_from: dict[str, list[Any]],
    terminal_steps: set[str],
    policy: dict[str, Any],
    metrics: dict[str, int],
    started: float,
) -> dict[str, Any]:
    """Evaluate all outgoing edges and return a complete transition record.

    This is called *before* the StepTrace is written so the routing decision
    is captured alongside the step result.  Side-effect free: callers apply
    the resulting ``next_step`` themselves.
    """
    # ── explicit jump (from runner or from error-fallback) ────────────────
    if outcome.jump:
        return {
            "kind": "error" if status == "error" else "jump",
            "next_step": str(outcome.jump),
            "condition": "",
            "decisive_param": "",
            "edges": [],
        }

    # ── stop flag ─────────────────────────────────────────────────────────
    if outcome.stop:
        return {
            "kind": "stop",
            "next_step": "",
            "condition": "",
            "decisive_param": "",
            "edges": [],
        }

    # ── terminal step ─────────────────────────────────────────────────────
    if current in terminal_steps:
        return {
            "kind": "terminal",
            "next_step": "",
            "condition": "",
            "decisive_param": "",
            "edges": [],
        }

    # ── post-step budget check ────────────────────────────────────────────
    budget_error = _budget_violation(
        policy=policy,
        metrics=metrics,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
    )
    if budget_error:
        return {
            "kind": "budget_exceeded",
            "next_step": "",
            "condition": budget_error,
            "decisive_param": "",
            "edges": [],
        }

    # ── edge evaluation ───────────────────────────────────────────────────
    edge_results: list[dict[str, Any]] = []
    next_step = ""
    matched_condition = ""
    matched_color = ""

    for edge in edges_by_from.get(current, []):
        cond = str(edge.when or "")
        matched = eval_condition(
            cond,
            request=ctx.request,
            state=ctx.state,
            policy=ctx.policy,
            result=ctx.result,
        )
        edge_results.append({
            "to_step": str(edge.to_step),
            "when": cond,
            "matched": matched,
            "color": str(getattr(edge, "color", "") or ""),
        })
        if matched and not next_step:
            next_step = str(edge.to_step)
            matched_condition = cond
            matched_color = str(getattr(edge, "color", "") or "")

    if not next_step:
        return {
            "kind": "no_edge_matched",
            "next_step": "",
            "condition": "",
            "decisive_param": "",
            "color": "",
            "edges": edge_results,
        }

    return {
        "kind": "edge",
        "next_step": next_step,
        "condition": matched_condition,
        "decisive_param": _extract_decisive_param(matched_condition),
        "color": matched_color,
        "edges": edge_results,
    }


def _on_error_fallback(ctx: ExecutionContext, step_id: str, on_error: str, exc: Exception) -> str:
    ctx.errors.append(f"{step_id}: {exc}")
    mode = str(on_error or "fail_hard")
    if mode == "continue_with_empty_evidence":
        set_path(ctx.state, "evidence_candidates", [])
        return ""
    if mode == "continue_with_neutral":
        set_path(
            ctx.state,
            "verify_result",
            {"status": "nicht_belegt", "confidence": 0.0, "reason": "runner_error"},
        )
        return ""
    if mode == "finalize_current_claim":
        set_path(
            ctx.state,
            "controller_decision",
            {"retry": False, "reason": "runner_error"},
        )
        return ""
    if mode.startswith("continue_"):
        return ""
    return "fail_hard"


def _deprecation_mode(policy: dict[str, Any]) -> str:
    mode = str(policy.get("deprecation_policy", "warn") or "warn").strip().casefold()
    if mode in {"allow", "warn", "block"}:
        return mode
    return "warn"


class WorkflowEngine:
    def __init__(self, registry: StepRegistry):
        self._registry = registry

    def run(
        self,
        *,
        definition: WorkflowDefinition,
        request: dict[str, Any],
        policy: dict[str, Any],
        tools: dict[str, Any],
        profile_id: str,
        wiring: dict[str, str] | None = None,
    ) -> WorkflowRunResult:
        state = dict(definition.state_init or {})
        result: dict[str, Any] = {}
        traces: list[StepTrace] = []
        errors: list[str] = []
        edges_by_from: dict[str, list[Any]] = {}
        for edge in definition.edges:
            edges_by_from.setdefault(edge.from_step, []).append(edge)

        gateway = ToolGateway(
            tools=dict(tools or {}),
            policy=policy,
            step_allowlist=dict(definition.step_tool_allowlist or {}),
        )
        ctx = ExecutionContext(
            request=dict(request or {}),
            state=state,
            policy=policy,
            result=result,
            tools=gateway,
            errors=errors,
        )

        steps = definition.step_by_id()
        current = str(definition.entry_step or "")
        max_steps = max(1, int(policy.get("max_engine_steps", 400)))
        started = time.perf_counter()
        hops = 0
        wiring_map = dict(wiring or {})
        deprecation_warnings: list[str] = []

        while current:
            budget_error = _budget_violation(
                policy=policy,
                metrics=gateway.metrics,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
            )
            if budget_error:
                errors.append(budget_error)
                break
            hops += 1
            if hops > max_steps:
                errors.append(f"Max engine steps exceeded: {max_steps}")
                break
            step = steps.get(current)
            if step is None:
                errors.append(f"Unknown step id: {current}")
                break
            if not is_step_allowed(policy, step.id):
                errors.append(f"Step blocked by policy: {step.id}")
                break
            step_visit_path = _runtime_state_path(f"step_visits.{step.id}")
            visit_index = int(_read_target(ctx, step_visit_path) or 0) + 1
            _set_target(ctx, step_visit_path, visit_index)
            _set_target(ctx, _runtime_state_path("last_step_id"), step.id)
            _set_target(ctx, _runtime_state_path("last_visit_index"), visit_index)
            max_visits = max(0, int(getattr(step, "max_visits", 0) or 0))
            if max_visits > 0 and visit_index > max_visits:
                overflow_target = str(getattr(step, "on_max_visits", "") or "").strip() or "fail_hard"
                reason = f"max_visits_exceeded:{visit_index}>{max_visits}"
                traces.append(
                    StepTrace(
                        step_id=step.id,
                        runner=str(step.runner or ""),
                        status="skipped",
                        duration_ms=0.0,
                        reason=reason,
                        visit_index=visit_index,
                        input={},
                        output={
                            "max_visits": max_visits,
                            "visit_index": visit_index,
                            "jump": overflow_target,
                        },
                        state_after=_trace_state_after(
                            ctx,
                            [
                                step_visit_path,
                                _runtime_state_path("last_step_id"),
                                _runtime_state_path("last_visit_index"),
                            ],
                        ),
                        transition={
                            "kind": "max_visits",
                            "next_step": overflow_target,
                            "condition": reason,
                            "decisive_param": "visit_index",
                            "edges": [],
                        },
                    )
                )
                current = overflow_target
                continue

            runner_id = str(step.runner or "")
            logical_key = f"{definition.job_type}.{step.id}"
            runner_id = wiring_map.get(logical_key, wiring_map.get(runner_id, runner_id))
            meta = self._registry.metadata_optional(runner_id)
            deprecation_note = ""
            if meta is not None and bool(meta.deprecated):
                notice = self._registry.deprecation_notice(runner_id)
                mode = _deprecation_mode(policy)
                if mode == "block":
                    errors.append(notice)
                    traces.append(
                        StepTrace(
                            step_id=step.id,
                            runner=runner_id,
                            status="error",
                            duration_ms=0.0,
                            reason=notice,
                            visit_index=visit_index,
                        )
                    )
                    break
                if mode == "warn":
                    deprecation_note = notice
                    deprecation_warnings.append(notice)

            gateway.current_step_id = step.id
            gateway.current_step_logical_key = logical_key
            t0 = time.perf_counter()
            status = "ok"
            reason = ""
            outcome = StepOutcome()
            projected: dict[str, Any] = {}
            touched_paths = [
                step_visit_path,
                _runtime_state_path("last_step_id"),
                _runtime_state_path("last_visit_index"),
            ]
            try:
                projected = project_context(
                    projection_name=step.input_projection,
                    projection_map=definition.projections,
                    context={
                        "request": ctx.request,
                        "state": ctx.state,
                        "policy": ctx.policy,
                        "result": ctx.result,
                    },
                )
                runner_ctx = (
                    _build_projected_execution_context(full_ctx=ctx, projected=projected)
                    if str(step.input_projection or "").strip()
                    else ctx
                )
                fn = self._registry.resolve(runner_id)
                raw = fn(runner_ctx, step, projected)
                outcome = _normalize_outcome(raw)
                if step.write_to:
                    _set_target(ctx, step.write_to, outcome.value)
                for path, value in outcome.updates.items():
                    _set_target(ctx, str(path), value)
                touched_paths.extend(_outcome_touched_paths(step, outcome))
                for key, value in dict(outcome.candidate_writes or {}).items():
                    touched_paths.extend(
                        _store_candidate(
                            ctx,
                            step_id=step.id,
                            visit_index=visit_index,
                            key=str(key or ""),
                            raw_candidate=value,
                        )
                    )
                for key in tuple(outcome.commit_candidates or ()):
                    touched_paths.extend(_apply_candidate(ctx, key))
                for key in tuple(outcome.discard_candidates or ()):
                    touched_paths.extend(_discard_candidate(ctx, key))
            except Exception as exc:
                status = "error"
                reason = str(exc)
                fallback = _on_error_fallback(ctx, step.id, step.on_error, exc)
                if fallback:
                    outcome.jump = fallback
            if deprecation_note and status == "ok" and not reason:
                reason = deprecation_note

            # Evaluate routing BEFORE writing trace so the decision is recorded.
            transition = _compute_transition(
                current=current,
                outcome=outcome,
                status=status,
                ctx=ctx,
                edges_by_from=edges_by_from,
                terminal_steps=set(definition.terminal_steps),
                policy=policy,
                metrics=gateway.metrics,
                started=started,
            )

            traces.append(
                StepTrace(
                    step_id=step.id,
                    runner=runner_id,
                    status=status,
                    duration_ms=(time.perf_counter() - t0) * 1000.0,
                    reason=reason,
                    visit_index=visit_index,
                    input=dict((projected or {}).get("raw", {}) or {}),
                    output=_trace_output_payload(step, outcome),
                    state_after=_trace_state_after(ctx, touched_paths),
                    transition=transition,
                )
            )

            kind = transition["kind"]
            if kind in ("stop", "terminal"):
                break
            if kind == "budget_exceeded":
                errors.append(transition["condition"])
                break
            if kind == "no_edge_matched":
                errors.append(f"No edge matched from step: {current}")
                break
            current = transition["next_step"]

        elapsed = (time.perf_counter() - started) * 1000.0
        metrics: dict[str, Any] = {
            "elapsed_ms": round(elapsed, 3),
            "steps": hops,
            "tool_calls": dict(gateway.metrics),
        }
        if deprecation_warnings:
            metrics["deprecation_warnings"] = list(deprecation_warnings)
        ok = not errors
        return WorkflowRunResult(
            ok=ok,
            workflow_id=definition.workflow_id,
            profile_id=profile_id,
            result=result,
            state=state,
            trace=traces,
            errors=errors,
            metrics=metrics,
        )
