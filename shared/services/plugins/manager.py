"""Small plugin runtime with Obsidian-like manifest files."""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Callable
import json
import re
import traceback

from shared.services.local_policy import plugin_network_allowed
from shared.services.plugins.js_bridge import ObsidianJSBridge


HookFn = Callable[[dict[str, Any]], dict[str, Any] | None]
_PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(slots=True, frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    entry: str
    engine: str
    min_app_version: str
    requires_network: bool
    hook_commands: tuple[tuple[str, str], ...]
    hook_events: tuple[tuple[str, str], ...]
    manifest_raw: dict[str, Any]
    path: Path


class PluginManager:
    """Load and execute repository-local plugins.

    Manifest format follows the common Obsidian fields:
    ``id``, ``name``, ``version``, optional ``entry`` (default: ``main.py``).
    """

    def __init__(self, *, root_dir: Path, logger: Any = None) -> None:
        self._root_dir = Path(root_dir)
        self._logger = logger
        self._manifests: dict[str, PluginManifest] = {}
        self._modules: dict[str, ModuleType] = {}
        self._js_bridges: dict[str, ObsidianJSBridge] = {}
        self._hooks: dict[str, list[tuple[str, HookFn]]] = {}

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def discover(self) -> tuple[PluginManifest, ...]:
        self._manifests.clear()
        if not self._root_dir.is_dir():
            return ()
        for child in sorted(self._root_dir.iterdir()):
            if not child.is_dir():
                continue
            manifest_path = child / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                self._log("warning", f"Plugin manifest unreadable: {manifest_path} ({exc})")
                continue
            manifest = self._parse_manifest(raw, plugin_path=child)
            if manifest is None:
                continue
            self._manifests[manifest.plugin_id] = manifest
        return tuple(self._manifests.values())

    def load_all(self) -> tuple[str, ...]:
        loaded: list[str] = []
        for manifest in self.discover():
            if self.load_plugin(manifest.plugin_id):
                loaded.append(manifest.plugin_id)
        return tuple(loaded)

    def load_plugin(self, plugin_id: str) -> bool:
        plugin_key = str(plugin_id or "").strip()
        manifest = self._manifests.get(plugin_key)
        if manifest is None:
            return False
        if manifest.requires_network and not plugin_network_allowed():
            self._log(
                "warning",
                (
                    f"Plugin skipped by local-first policy (network disabled): "
                    f"{manifest.plugin_id}"
                ),
            )
            return False
        entry_path = self._resolve_entry_path(manifest)
        if entry_path is None:
            return False
        if manifest.engine == "python":
            return self._load_python_plugin(manifest, entry_path)
        if manifest.engine == "obsidian-js":
            return self._load_js_plugin(manifest, entry_path)
        self._log(
            "info",
            (
                f"Plugin skipped (unsupported runtime '{manifest.engine}'): "
                f"{manifest.plugin_id}"
            ),
        )
        return False

    def _resolve_entry_path(self, manifest: PluginManifest) -> Path | None:
        base_path = manifest.path.resolve(strict=False)
        entry_path = (manifest.path / manifest.entry).resolve(strict=False)
        if base_path != entry_path and base_path not in entry_path.parents:
            self._log(
                "warning",
                (
                    f"Plugin entry blocked (path traversal): {manifest.plugin_id} -> "
                    f"{manifest.entry}"
                ),
            )
            return None
        if not entry_path.is_file():
            self._log("warning", f"Plugin entry missing: {entry_path}")
            return None
        return entry_path

    def _load_python_plugin(self, manifest: PluginManifest, entry_path: Path) -> bool:
        module_name = f"d2c_plugin_{manifest.plugin_id.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, entry_path)
        if spec is None or spec.loader is None:
            self._log("warning", f"Plugin import spec failed: {entry_path}")
            return False
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            self._log("error", f"Plugin import failed ({manifest.plugin_id}): {exc}")
            self._log("debug", traceback.format_exc())
            return False

        self._modules[manifest.plugin_id] = module
        register_fn = getattr(module, "register", None)
        if callable(register_fn):
            try:
                register_fn(self)
            except Exception as exc:
                self._log("error", f"Plugin register failed ({manifest.plugin_id}): {exc}")
                self._log("debug", traceback.format_exc())
                return False
        self._log("info", f"Plugin loaded: {manifest.plugin_id} ({manifest.version})")
        return True

    def _load_js_plugin(self, manifest: PluginManifest, entry_path: Path) -> bool:
        bridge = ObsidianJSBridge(
            plugin_id=manifest.plugin_id,
            plugin_dir=manifest.path,
            entry_path=entry_path,
            manifest_raw=manifest.manifest_raw,
            allow_network=bool(manifest.requires_network and plugin_network_allowed()),
            logger=self._logger,
        )
        if not bridge.available:
            self._log(
                "info",
                f"Plugin skipped (Node.js unavailable): {manifest.plugin_id}",
            )
            return False

        discovered = bridge.discover()
        hook_commands = dict(manifest.hook_commands)
        hook_events = dict(manifest.hook_events)
        mapped_hooks = set(hook_commands.keys()) | set(hook_events.keys()) | set(discovered.hooks)

        for hook_name in sorted(mapped_hooks):
            command_id = str(hook_commands.get(hook_name, "") or "").strip()
            hook_alias = str(hook_events.get(hook_name, "") or "").strip()
            self.register_hook(
                hook_name,
                self._make_js_hook(
                    bridge=bridge,
                    hook_name=hook_name,
                    hook_alias=hook_alias,
                    command_id=command_id,
                ),
                plugin_id=manifest.plugin_id,
            )

        self._js_bridges[manifest.plugin_id] = bridge
        self._log(
            "info",
            (
                f"Plugin loaded: {manifest.plugin_id} ({manifest.version}) "
                f"[obsidian-js hooks={len(mapped_hooks)} commands={len(discovered.commands)}]"
            ),
        )
        return True

    @staticmethod
    def _make_js_hook(
        *,
        bridge: ObsidianJSBridge,
        hook_name: str,
        hook_alias: str,
        command_id: str,
    ) -> HookFn:
        def _run(payload: dict[str, Any]) -> dict[str, Any]:
            return bridge.invoke(
                hook_name=hook_name,
                payload=dict(payload or {}),
                hook_alias=hook_alias,
                command_id=command_id,
            )

        return _run

    def register_hook(self, hook_name: str, fn: HookFn, *, plugin_id: str = "") -> None:
        name = str(hook_name or "").strip()
        if not name:
            raise ValueError("Hook name must not be empty.")
        owner = str(plugin_id or "").strip() or "anonymous"
        self._hooks.setdefault(name, []).append((owner, fn))

    def run_hook(self, hook_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        state = dict(payload or {})
        for owner, fn in list(self._hooks.get(str(hook_name or "").strip(), []) or []):
            try:
                out = fn(dict(state))
                if isinstance(out, dict):
                    state = out
            except Exception as exc:
                self._log("warning", f"Plugin hook failed ({owner}:{hook_name}): {exc}")
        return state

    def list_plugins(self) -> tuple[PluginManifest, ...]:
        return tuple(self._manifests.values())

    @staticmethod
    def _parse_manifest(raw: Any, *, plugin_path: Path) -> PluginManifest | None:
        if not isinstance(raw, dict):
            return None
        raw_map = dict(raw)
        plugin_id = str(raw_map.get("id", "") or "").strip()
        name = str(raw_map.get("name", "") or plugin_id).strip()
        version = str(raw_map.get("version", "") or "0.0.0").strip()
        entry = str(raw_map.get("entry", "") or raw_map.get("main", "") or "main.py").strip()
        engine = str(raw_map.get("engine", "") or "").strip().casefold()
        min_app_version = str(raw_map.get("minAppVersion", "") or "").strip()
        requires_network_raw = raw_map.get("requires_network", False)
        requires_network = False
        if isinstance(requires_network_raw, bool):
            requires_network = requires_network_raw
        else:
            requires_network = (
                str(requires_network_raw or "").strip().casefold() in _TRUTHY
            )
        if not plugin_id or not _PLUGIN_ID_RE.fullmatch(plugin_id):
            return None
        if not entry or Path(entry).is_absolute():
            return None
        if engine not in {"", "python", "obsidian", "obsidian-js", "javascript", "js"}:
            return None

        hook_commands = PluginManager._parse_hook_map(raw_map.get("hookCommands"))
        hook_events = PluginManager._parse_hook_map(raw_map.get("hookEvents"))
        d2c = raw_map.get("d2c")
        if isinstance(d2c, dict):
            hook_commands.update(PluginManager._parse_hook_map(d2c.get("hookCommands")))
            hook_events.update(PluginManager._parse_hook_map(d2c.get("hookEvents")))

        normalized_engine = "python"
        if engine in {"obsidian", "obsidian-js", "javascript", "js"} or entry.casefold().endswith(".js"):
            normalized_engine = "obsidian-js"
        return PluginManifest(
            plugin_id=plugin_id,
            name=name or plugin_id,
            version=version or "0.0.0",
            entry=entry or "main.py",
            engine=normalized_engine,
            min_app_version=min_app_version,
            requires_network=requires_network,
            hook_commands=tuple(sorted(hook_commands.items())),
            hook_events=tuple(sorted(hook_events.items())),
            manifest_raw=raw_map,
            path=plugin_path,
        )

    @staticmethod
    def _parse_hook_map(raw: Any) -> dict[str, str]:
        if not isinstance(raw, dict):
            return {}
        out: dict[str, str] = {}
        for key, value in raw.items():
            hook = str(key or "").strip()
            target = str(value or "").strip()
            if hook and target:
                out[hook] = target
        return out

    def _log(self, level: str, message: str) -> None:
        logger = self._logger
        if logger is None:
            return
        fn = getattr(logger, str(level or "").lower(), None)
        if callable(fn):
            try:
                fn("PLUGIN", str(message or ""))
                return
            except Exception:
                return
