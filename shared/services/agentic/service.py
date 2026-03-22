"""High-level workflow service facade."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .contracts import WorkflowRunResult
from .default_registry import register_default_runners
from .engine import WorkflowEngine
from .loader import load_workflow_definition, load_workflow_profile
from .policy import merge_policy_layers
from .registry import StepRegistry
from .tracing import write_run_trace


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().casefold() in {"1", "true", "yes", "on"}


def _feature_enabled(env_key: str, explicit_enabled: bool | None) -> bool:
    if explicit_enabled is None:
        return _env_flag(env_key)
    return bool(explicit_enabled)


def _feature_enabled_any(
    env_keys: tuple[str, ...],
    explicit_enabled: bool | None,
) -> bool:
    if explicit_enabled is not None:
        return bool(explicit_enabled)
    return any(_env_flag(name) for name in tuple(env_keys or ()))


def _workflow_matches(profile_workflow_id: str, workflow_id: str) -> bool:
    want = str(workflow_id or "").strip()
    got = str(profile_workflow_id or "").strip()
    return got in {"", "*", want}


def _resolve_toml_path(directory: Path, item_id: str, *, required: bool) -> Path | None:
    base = str(item_id or "").strip()
    if not base:
        return None
    path = directory / f"{base}.toml"
    if path.is_file():
        return path
    if required:
        raise FileNotFoundError(f"No .toml file found for: {item_id}")
    return None


class AgenticWorkflowService:
    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        registry: StepRegistry | None = None,
    ) -> None:
        self._repo_root = Path(repo_root or Path(__file__).resolve().parents[3])
        self._definitions_dir = self._repo_root / "data" / "workflows" / "definitions"
        self._profiles_dir = self._repo_root / "data" / "workflows" / "profiles"
        self._registry = registry or register_default_runners(StepRegistry())
        self._engine = WorkflowEngine(self._registry)

    def _load_profile(self, profile_id: str, *, required: bool) -> Any:
        path = _resolve_toml_path(self._profiles_dir, profile_id, required=required)
        if path is None:
            if required:
                raise FileNotFoundError(f"No workflow profile found for: {profile_id}")
            return None
        return load_workflow_profile(path)

    def _resolve_profile_chain(
        self,
        *,
        workflow_id: str,
        profile_id: str,
        overlay_profile_ids: list[str] | tuple[str, ...] | None,
        env_name: str = "",
    ) -> tuple[list[Any], list[str]]:
        ids: list[tuple[str, bool]] = []
        ids.append(("_base", False))
        ids.append((f"{workflow_id}__default", False))
        effective_env_name = str(env_name or "").strip()
        if not effective_env_name:
            effective_env_name = str(os.environ.get("D2C_AGENTIC_ENV", "") or "").strip()
        if effective_env_name:
            ids.append((f"_env_{effective_env_name}", False))
        for item in list(overlay_profile_ids or []):
            ids.append((str(item or "").strip(), True))
        if profile_id:
            ids.append((str(profile_id or "").strip(), True))

        profiles: list[Any] = []
        chain: list[str] = []
        seen_ids: set[str] = set()
        for item, required in ids:
            pid = str(item or "").strip()
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            profile = self._load_profile(pid, required=required)
            if profile is None:
                continue
            if not _workflow_matches(str(profile.workflow_id or ""), workflow_id):
                raise ValueError(
                    f"Profile '{profile.profile_id}' does not match workflow "
                    f"'{workflow_id}'."
                )
            profiles.append(profile)
            chain.append(str(profile.profile_id or pid))
        return profiles, chain

    @staticmethod
    def _extract_override_map(overrides: dict[str, Any] | None, key: str) -> dict[str, Any]:
        src = dict(overrides or {})
        value = src.get(str(key))
        if isinstance(value, dict):
            return dict(value)
        return {}

    def run(
        self,
        *,
        workflow_id: str,
        request: dict[str, Any],
        profile_id: str = "",
        policy_overrides: dict[str, Any] | None = None,
        wiring_overrides: dict[str, str] | None = None,
        overlay_profile_ids: list[str] | tuple[str, ...] | None = None,
        tools: dict[str, Any] | None = None,
        env_name: str = "",
    ) -> WorkflowRunResult:
        definition_path = _resolve_toml_path(self._definitions_dir, workflow_id, required=True)
        assert definition_path is not None
        definition = load_workflow_definition(definition_path)
        if str(definition.workflow_id or "") != str(workflow_id or ""):
            raise ValueError(
                f"Workflow id mismatch: expected '{workflow_id}', "
                f"got '{definition.workflow_id}'."
            )
        profiles, profile_chain = self._resolve_profile_chain(
            workflow_id=definition.workflow_id,
            profile_id=profile_id,
            overlay_profile_ids=overlay_profile_ids,
            env_name=env_name,
        )
        policy_layers: list[dict[str, Any]] = [dict(definition.budgets or {})]
        policy_layers.extend(dict(p.policy or {}) for p in profiles)
        model_routing_layers: list[dict[str, Any]] = [
            dict(p.model_routing or {})
            for p in profiles
        ]
        cache_policy_layers: list[dict[str, Any]] = [
            dict(p.cache_policy or {})
            for p in profiles
        ]
        if _env_flag("D2C_AGENTIC_STRICT_POLICY"):
            policy_layers.append({"strict_policy": True})
        if _env_flag("D2C_AGENTIC_TRACE"):
            policy_layers.append({"trace_enabled": True})
        env_deprecation_policy = str(
            os.environ.get("D2C_AGENTIC_DEPRECATION_POLICY", "") or ""
        ).strip()
        if env_deprecation_policy:
            policy_layers.append({"deprecation_policy": env_deprecation_policy})
        if _env_flag("D2C_AGENTIC_CACHE_DISABLED"):
            cache_policy_layers.append({"enabled": False})
        model_routing = merge_policy_layers(
            *model_routing_layers,
            self._extract_override_map(policy_overrides, "model_routing"),
        )
        cache_policy = merge_policy_layers(
            *cache_policy_layers,
            self._extract_override_map(policy_overrides, "cache_policy"),
        )
        policy = merge_policy_layers(
            *policy_layers,
            dict(policy_overrides or {}),
            {"model_routing": model_routing, "cache_policy": cache_policy},
        )

        wiring_layers: list[dict[str, Any]] = [dict(p.wiring or {}) for p in profiles]
        wiring = merge_policy_layers(*wiring_layers, dict(wiring_overrides or {}))
        active_profile = str(profile_id or (profile_chain[-1] if profile_chain else ""))

        run_result = self._engine.run(
            definition=definition,
            request=dict(request or {}),
            policy=policy,
            tools=dict(tools or {}),
            profile_id=active_profile,
            wiring=wiring,
        )
        run_result.metrics["profile_chain"] = list(profile_chain)
        if bool(policy.get("trace_enabled", False)):
            trace_path = write_run_trace(
                repo_root=self._repo_root,
                definition=definition,
                run_result=run_result,
                request=dict(request or {}),
                policy=policy,
                wiring=dict(wiring or {}),
                profile_chain=list(profile_chain),
            )
            run_result.metrics["trace_path"] = trace_path
        return run_result

    def run_factcheck(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any] | None = None,
        profile_id: str = "factcheck_regex_only",
        enabled: bool | None = None,
        policy_overrides: dict[str, Any] | None = None,
        wiring_overrides: dict[str, str] | None = None,
        overlay_profile_ids: list[str] | tuple[str, ...] | None = None,
        env_name: str = "",
    ) -> WorkflowRunResult:
        if not _feature_enabled("D2C_AGENTIC_FACTCHECK", enabled):
            raise RuntimeError("Agentic factcheck disabled (D2C_AGENTIC_FACTCHECK=1 to enable).")
        return self.run(
            workflow_id="factcheck_agentic",
            request=request,
            profile_id=profile_id,
            policy_overrides=policy_overrides,
            wiring_overrides=wiring_overrides,
            overlay_profile_ids=overlay_profile_ids,
            tools=tools,
            env_name=env_name,
        )

    def run_chat(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any] | None = None,
        profile_id: str = "chat_grounded_strict",
        enabled: bool | None = None,
        policy_overrides: dict[str, Any] | None = None,
        wiring_overrides: dict[str, str] | None = None,
        overlay_profile_ids: list[str] | tuple[str, ...] | None = None,
        env_name: str = "",
    ) -> WorkflowRunResult:
        if not _feature_enabled("D2C_AGENTIC_CHAT", enabled):
            raise RuntimeError("Agentic chat disabled (D2C_AGENTIC_CHAT=1 to enable).")
        return self.run(
            workflow_id="chat_agentic",
            request=request,
            profile_id=profile_id,
            policy_overrides=policy_overrides,
            wiring_overrides=wiring_overrides,
            overlay_profile_ids=overlay_profile_ids,
            tools=tools,
            env_name=env_name,
        )

    def run_canvas(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any] | None = None,
        profile_id: str = "canvas_grounded_rewrite",
        enabled: bool | None = None,
        policy_overrides: dict[str, Any] | None = None,
        wiring_overrides: dict[str, str] | None = None,
        overlay_profile_ids: list[str] | tuple[str, ...] | None = None,
        env_name: str = "",
    ) -> WorkflowRunResult:
        if not _feature_enabled("D2C_AGENTIC_CANVAS", enabled):
            raise RuntimeError("Agentic canvas disabled (D2C_AGENTIC_CANVAS=1 to enable).")
        return self.run(
            workflow_id="canvas_agentic",
            request=request,
            profile_id=profile_id,
            policy_overrides=policy_overrides,
            wiring_overrides=wiring_overrides,
            overlay_profile_ids=overlay_profile_ids,
            tools=tools,
            env_name=env_name,
        )

    def run_mindmap(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any] | None = None,
        profile_id: str = "mindmap_grounded_graph",
        enabled: bool | None = None,
        policy_overrides: dict[str, Any] | None = None,
        wiring_overrides: dict[str, str] | None = None,
        overlay_profile_ids: list[str] | tuple[str, ...] | None = None,
        env_name: str = "",
    ) -> WorkflowRunResult:
        if not _feature_enabled("D2C_AGENTIC_MINDMAP", enabled):
            raise RuntimeError("Agentic mindmap disabled (D2C_AGENTIC_MINDMAP=1 to enable).")
        return self.run(
            workflow_id="mindmap_agentic",
            request=request,
            profile_id=profile_id,
            policy_overrides=policy_overrides,
            wiring_overrides=wiring_overrides,
            overlay_profile_ids=overlay_profile_ids,
            tools=tools,
            env_name=env_name,
        )

    def run_graph(
        self,
        *,
        request: dict[str, Any],
        tools: dict[str, Any] | None = None,
        profile_id: str = "graph_connected_component",
        enabled: bool | None = None,
        policy_overrides: dict[str, Any] | None = None,
        wiring_overrides: dict[str, str] | None = None,
        overlay_profile_ids: list[str] | tuple[str, ...] | None = None,
        env_name: str = "",
    ) -> WorkflowRunResult:
        if not _feature_enabled_any(
            ("D2C_AGENTIC_GRAPH", "D2C_AGENTIC_MINDMAP"),
            enabled,
        ):
            raise RuntimeError(
                "Agentic graph disabled (D2C_AGENTIC_GRAPH=1 to enable)."
            )
        req = dict(request or {})
        req["mode"] = "graph"
        return self.run(
            workflow_id="graph_agentic",
            request=req,
            profile_id=profile_id,
            policy_overrides=policy_overrides,
            wiring_overrides=wiring_overrides,
            overlay_profile_ids=overlay_profile_ids,
            tools=tools,
            env_name=env_name,
        )
