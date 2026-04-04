from __future__ import annotations

import json
from pathlib import Path

import shared.services.plugins.manager as manager_mod
from shared.services.plugins.manager import PluginManager


class _Discovery:
    def __init__(self, *, commands: tuple[str, ...], hooks: tuple[str, ...]) -> None:
        self.commands = commands
        self.hooks = hooks


class _FakeBridge:
    init_calls: list[dict[str, object]] = []
    invoke_calls: list[dict[str, object]] = []

    def __init__(
        self,
        *,
        plugin_id: str,
        plugin_dir: Path,
        entry_path: Path,
        manifest_raw: dict[str, object] | None = None,
        allow_network: bool = False,
        logger=None,
    ) -> None:
        _ = logger
        self.available = True
        self._plugin_id = str(plugin_id or "")
        self._plugin_dir = Path(plugin_dir)
        self._entry_path = Path(entry_path)
        self._manifest_raw = dict(manifest_raw or {})
        self._allow_network = bool(allow_network)
        _FakeBridge.init_calls.append(
            {
                "plugin_id": self._plugin_id,
                "plugin_dir": self._plugin_dir,
                "entry_path": self._entry_path,
                "allow_network": self._allow_network,
            }
        )

    def discover(self):
        return _Discovery(
            commands=("d2c:rewrite-prompt", "d2c:trim-output"),
            hooks=("graph.chat.after_draft",),
        )

    def invoke(
        self,
        *,
        hook_name: str,
        payload: dict[str, object] | None = None,
        hook_alias: str = "",
        command_id: str = "",
    ) -> dict[str, object]:
        _FakeBridge.invoke_calls.append(
            {
                "hook_name": hook_name,
                "hook_alias": hook_alias,
                "command_id": command_id,
            }
        )
        out = dict(payload or {})
        out["bridge_hook"] = str(hook_name or "")
        out["bridge_alias"] = str(hook_alias or "")
        out["bridge_command"] = str(command_id or "")
        return out


def _write_manifest_plugin(root: Path, *, manifest: dict[str, object]) -> Path:
    plugins_root = root / "plugins"
    plugin_id = str(manifest.get("id", "") or "")
    plugin_dir = plugins_root / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    entry = str(manifest.get("entry", "") or "main.js")
    (plugin_dir / entry).write_text("// test plugin\n", encoding="utf-8")
    return plugins_root


def test_parse_manifest_supports_d2c_hook_overrides(tmp_path: Path) -> None:
    plugin_path = tmp_path / "demo"
    plugin_path.mkdir(parents=True, exist_ok=True)
    manifest = PluginManager._parse_manifest(
        {
            "id": "js-demo",
            "name": "JS Demo",
            "version": "0.1.0",
            "entry": "main.js",
            "engine": "obsidian-js",
            "hookCommands": {
                "llm.before_generate": "top:command",
            },
            "hookEvents": {
                "rag.after_search": "top:event",
            },
            "d2c": {
                "hookCommands": {
                    "llm.before_generate": "d2c:command",
                },
                "hookEvents": {
                    "rag.after_search": "d2c:event",
                },
            },
        },
        plugin_path=plugin_path,
    )
    assert manifest is not None
    assert manifest.engine == "obsidian-js"
    assert dict(manifest.hook_commands)["llm.before_generate"] == "d2c:command"
    assert dict(manifest.hook_events)["rag.after_search"] == "d2c:event"


def test_load_js_plugin_registers_manifest_and_discovered_hooks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _FakeBridge.init_calls.clear()
    _FakeBridge.invoke_calls.clear()
    monkeypatch.setattr(manager_mod, "ObsidianJSBridge", _FakeBridge)
    monkeypatch.setattr(manager_mod, "plugin_network_allowed", lambda: True)

    plugins_root = _write_manifest_plugin(
        tmp_path,
        manifest={
            "id": "js-hooks",
            "name": "JS Hooks",
            "version": "1.0.0",
            "entry": "main.js",
            "engine": "obsidian-js",
            "d2c": {
                "hookCommands": {
                    "llm.before_generate": "d2c:rewrite-prompt",
                },
                "hookEvents": {
                    "rag.after_search": "d2c:rag:postprocess",
                },
            },
        },
    )
    manager = PluginManager(root_dir=plugins_root)
    assert manager.load_all() == ("js-hooks",)

    before = manager.run_hook("llm.before_generate", {"prompt": "Hi"})
    assert before["bridge_hook"] == "llm.before_generate"
    assert before["bridge_command"] == "d2c:rewrite-prompt"

    rag = manager.run_hook("rag.after_search", {"query": "abc"})
    assert rag["bridge_hook"] == "rag.after_search"
    assert rag["bridge_alias"] == "d2c:rag:postprocess"

    graph = manager.run_hook("graph.chat.after_draft", {"answer": "x"})
    assert graph["bridge_hook"] == "graph.chat.after_draft"
    assert graph["bridge_command"] == ""
    assert graph["bridge_alias"] == ""

    assert len(_FakeBridge.init_calls) == 1
    assert _FakeBridge.init_calls[0]["allow_network"] is False


def test_js_plugin_with_network_flag_respects_local_first_policy(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _FakeBridge.init_calls.clear()
    _FakeBridge.invoke_calls.clear()
    monkeypatch.setattr(manager_mod, "ObsidianJSBridge", _FakeBridge)
    monkeypatch.setattr(manager_mod, "plugin_network_allowed", lambda: False)

    plugins_root = _write_manifest_plugin(
        tmp_path,
        manifest={
            "id": "js-network",
            "name": "JS Network",
            "version": "1.0.0",
            "entry": "main.js",
            "engine": "obsidian-js",
            "requires_network": True,
            "d2c": {
                "hookCommands": {
                    "llm.before_generate": "d2c:rewrite-prompt",
                }
            },
        },
    )
    manager = PluginManager(root_dir=plugins_root)
    assert manager.load_all() == ()
    assert _FakeBridge.init_calls == []
