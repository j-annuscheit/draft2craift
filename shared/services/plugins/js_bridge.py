"""Local Obsidian-JS bridge for plugin hooks."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any


_NODE_SCRIPT = r"""
const fs = require("fs");
const Module = require("module");
const path = require("path");
const { pathToFileURL } = require("url");

function parseJson(text, fallback) {
  try {
    return JSON.parse(String(text || ""));
  } catch {
    return fallback;
  }
}

function buildSettingStub() {
  class Setting {
    setName() { return this; }
    setDesc() { return this; }
    addText(cb) { if (typeof cb === "function") { cb({ setPlaceholder() { return this; }, setValue() { return this; }, onChange() { return this; } }); } return this; }
    addToggle(cb) { if (typeof cb === "function") { cb({ setValue() { return this; }, onChange() { return this; } }); } return this; }
    addDropdown(cb) { if (typeof cb === "function") { cb({ addOption() { return this; }, setValue() { return this; }, onChange() { return this; } }); } return this; }
    addButton(cb) { if (typeof cb === "function") { cb({ setButtonText() { return this; }, setCta() { return this; }, onClick() { return this; } }); } return this; }
  }
  return Setting;
}

function createObsidianShim(registry) {
  class Plugin {
    constructor(app, manifest) {
      this.app = app || {};
      this.manifest = manifest || {};
    }
    addCommand(spec) {
      if (spec && typeof spec.id === "string" && typeof spec.callback === "function") {
        registry.commands.push(spec);
      }
      return spec;
    }
    registerHook(name, fn) {
      if (typeof name === "string" && typeof fn === "function") {
        registry.hooks.set(name, fn);
      }
      return fn;
    }
    registerEvent(eventRef) { return eventRef; }
    registerDomEvent() { return null; }
    registerInterval() { return null; }
    addStatusBarItem() { return { setText() {}, remove() {} }; }
    addRibbonIcon() { return null; }
    addSettingTab() { return null; }
  }

  class PluginSettingTab {
    constructor(app, plugin) { this.app = app; this.plugin = plugin; this.containerEl = {}; }
    display() {}
    hide() {}
  }

  class Notice {
    constructor(_text) {}
  }

  return {
    Plugin,
    PluginSettingTab,
    Setting: buildSettingStub(),
    Notice,
  };
}

function patchModuleLoader(obsidianShim, networkAllowed) {
  const originalLoad = Module._load;
  const blocked = new Set(["http", "https", "net", "tls", "dns", "dgram"]);
  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === "obsidian") {
      return obsidianShim;
    }
    if (!networkAllowed && blocked.has(String(request || ""))) {
      throw new Error("Network access blocked by local-first plugin policy.");
    }
    return originalLoad.call(this, request, parent, isMain);
  };
  return () => {
    Module._load = originalLoad;
  };
}

async function loadPluginExport(entryPath, obsidianShim, networkAllowed) {
  const restore = patchModuleLoader(obsidianShim, networkAllowed);
  try {
    try {
      return require(entryPath);
    } catch (err) {
      const text = String(err && err.message || "");
      if (!text.includes("ERR_REQUIRE_ESM")) {
        throw err;
      }
      const moduleUrl = pathToFileURL(entryPath).href;
      return await import(moduleUrl);
    }
  } finally {
    restore();
  }
}

async function initializePlugin(entryPath, manifest, registry, networkAllowed) {
  const obsidianShim = createObsidianShim(registry);
  const loaded = await loadPluginExport(entryPath, obsidianShim, networkAllowed);
  const exported = (loaded && loaded.default) ? loaded.default : loaded;

  const managerShim = {
    registerHook(name, fn) {
      if (typeof name === "string" && typeof fn === "function") {
        registry.hooks.set(name, fn);
      }
    },
    register_hook(name, fn) {
      if (typeof name === "string" && typeof fn === "function") {
        registry.hooks.set(name, fn);
      }
    },
    addCommand(spec) {
      if (spec && typeof spec.id === "string" && typeof spec.callback === "function") {
        registry.commands.push(spec);
      }
    },
  };

  if (exported && typeof exported.register === "function") {
    await exported.register(managerShim);
    return;
  }
  if (exported && typeof exported.onload === "function") {
    await exported.onload();
    return;
  }
  if (typeof exported === "function") {
    let instance = null;
    try {
      instance = new exported({}, manifest || {});
    } catch {
      instance = null;
    }
    if (instance && typeof instance.onload === "function") {
      await instance.onload();
    }
  }
}

function fallbackCommandCandidates(hookName) {
  const clean = String(hookName || "").trim();
  if (!clean) return [];
  return [
    clean,
    clean.replaceAll(".", ":"),
    `d2c:${clean}`,
    `draft2craift:${clean}`,
    `obsidian:${clean}`,
  ];
}

function resolvePayloadOutput(originalPayload, result) {
  if (result && typeof result === "object" && !Array.isArray(result)) {
    return result;
  }
  if (typeof result === "string") {
    const next = Object.assign({}, originalPayload || {});
    if (Object.prototype.hasOwnProperty.call(next, "prompt")) {
      next.prompt = result;
      return next;
    }
    if (Object.prototype.hasOwnProperty.call(next, "text")) {
      next.text = result;
      return next;
    }
  }
  return Object.assign({}, originalPayload || {});
}

async function main() {
  const action = process.argv[2] || "";
  const entryPath = String(process.argv[3] || "");
  const hookName = String(process.argv[4] || "");
  const hookAlias = String(process.argv[5] || "");
  const commandId = String(process.argv[6] || "");
  const payload = parseJson(process.argv[7] || "{}", {});
  const manifest = parseJson(process.argv[8] || "{}", {});
  const networkAllowed = String(process.argv[9] || "") === "1";

  const registry = {
    commands: [],
    hooks: new Map(),
  };

  await initializePlugin(entryPath, manifest, registry, networkAllowed);

  if (action === "discover") {
    const out = {
      ok: true,
      commands: registry.commands.map((row) => String(row && row.id || "")).filter(Boolean),
      hooks: Array.from(registry.hooks.keys()).map((name) => String(name || "")).filter(Boolean),
    };
    process.stdout.write(JSON.stringify(out));
    return;
  }

  if (action !== "invoke") {
    process.stdout.write(JSON.stringify({ ok: false, error: "Unsupported action." }));
    process.exit(2);
    return;
  }

  let fn = null;
  const alias = String(hookAlias || "").trim();
  if (alias && registry.hooks.has(alias)) {
    fn = registry.hooks.get(alias);
  } else if (hookName && registry.hooks.has(hookName)) {
    fn = registry.hooks.get(hookName);
  }

  if (!fn) {
    const byId = new Map();
    for (const command of registry.commands) {
      if (!command || typeof command.id !== "string" || typeof command.callback !== "function") {
        continue;
      }
      byId.set(command.id, command.callback);
    }
    const candidates = [];
    if (commandId) candidates.push(commandId);
    candidates.push(...fallbackCommandCandidates(hookName));
    for (const candidate of candidates) {
      if (byId.has(candidate)) {
        fn = byId.get(candidate);
        break;
      }
    }
  }

  if (!fn) {
    process.stdout.write(JSON.stringify({ ok: true, payload }));
    return;
  }

  const maybeResult = await fn(payload, { hook: hookName, commandId });
  process.stdout.write(JSON.stringify({ ok: true, payload: resolvePayloadOutput(payload, maybeResult) }));
}

main().catch((err) => {
  process.stdout.write(JSON.stringify({ ok: false, error: String(err && err.message || err || "bridge_error") }));
  process.exit(1);
});
"""


@dataclass(slots=True, frozen=True)
class JSDiscovery:
    commands: tuple[str, ...]
    hooks: tuple[str, ...]


class ObsidianJSBridge:
    """Run Obsidian-style JavaScript plugins locally and map them to hook calls."""

    def __init__(
        self,
        *,
        plugin_id: str,
        plugin_dir: Path,
        entry_path: Path,
        manifest_raw: dict[str, Any] | None = None,
        allow_network: bool = False,
        logger: Any = None,
    ) -> None:
        self._plugin_id = str(plugin_id or "").strip()
        self._plugin_dir = Path(plugin_dir)
        self._entry_path = Path(entry_path)
        self._manifest_raw = dict(manifest_raw or {})
        self._allow_network = bool(allow_network)
        self._logger = logger
        self._node_bin = self._resolve_node_executable()

    @property
    def available(self) -> bool:
        return bool(self._node_bin)

    def discover(self) -> JSDiscovery:
        payload = self._run(action="discover", payload={})
        if not isinstance(payload, dict):
            return JSDiscovery(commands=(), hooks=())
        commands = tuple(
            str(item or "").strip()
            for item in list(payload.get("commands", []) or [])
            if str(item or "").strip()
        )
        hooks = tuple(
            str(item or "").strip()
            for item in list(payload.get("hooks", []) or [])
            if str(item or "").strip()
        )
        return JSDiscovery(commands=commands, hooks=hooks)

    def invoke(
        self,
        *,
        hook_name: str,
        payload: dict[str, Any] | None = None,
        hook_alias: str = "",
        command_id: str = "",
    ) -> dict[str, Any]:
        response = self._run(
            action="invoke",
            hook_name=str(hook_name or ""),
            hook_alias=str(hook_alias or ""),
            command_id=str(command_id or ""),
            payload=dict(payload or {}),
        )
        if isinstance(response, dict):
            resolved = response.get("payload")
            if isinstance(resolved, dict):
                return dict(resolved)
        return dict(payload or {})

    def _run(
        self,
        *,
        action: str,
        hook_name: str = "",
        hook_alias: str = "",
        command_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self._node_bin:
            self._log("info", f"Node.js not found, skipping JS plugin: {self._plugin_id}")
            return None
        cmd = [
            self._node_bin,
            "-e",
            _NODE_SCRIPT,
            str(action or ""),
            str(self._entry_path),
            str(hook_name or ""),
            str(hook_alias or ""),
            str(command_id or ""),
            json.dumps(dict(payload or {}), ensure_ascii=False),
            json.dumps(self._manifest_raw, ensure_ascii=False),
            "1" if self._allow_network else "0",
        ]
        env = dict(os.environ)
        env["NODE_NO_WARNINGS"] = "1"
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self._plugin_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=8.0,
                env=env,
            )
        except Exception as exc:
            self._log("warning", f"JS bridge process failed ({self._plugin_id}): {exc}")
            return None
        raw_stdout = str(proc.stdout or "").strip()
        payload_out = self._parse_json(raw_stdout)
        if proc.returncode != 0:
            detail = payload_out.get("error", "") if isinstance(payload_out, dict) else raw_stdout
            self._log("warning", f"JS bridge call failed ({self._plugin_id}): {detail}")
            return None
        if not isinstance(payload_out, dict):
            self._log("warning", f"JS bridge returned invalid payload ({self._plugin_id}).")
            return None
        if not bool(payload_out.get("ok", False)):
            self._log("warning", f"JS bridge reported error ({self._plugin_id}).")
            return None
        return payload_out

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        try:
            data = json.loads(str(text or ""))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _resolve_node_executable() -> str:
        override = str(os.environ.get("D2C_NODE_PATH", "") or "").strip()
        if override:
            return override
        found = shutil.which("node")
        return str(found or "")

    def _log(self, level: str, message: str) -> None:
        logger = self._logger
        if logger is None:
            return
        fn = getattr(logger, str(level or "").lower(), None)
        if callable(fn):
            try:
                fn("PLUGIN", str(message or ""))
            except Exception:
                return
