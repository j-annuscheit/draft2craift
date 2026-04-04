# Plugin System (Obsidian-Style)

The new backend supports local plugins loaded from `plugins/<plugin-id>/`.

Each plugin must provide:

1. `manifest.json`
2. `main.py` or `main.js`

## Manifest

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "0.1.0",
  "entry": "main.js",
  "engine": "obsidian-js",
  "requires_network": false,
  "d2c": {
    "hookCommands": {
      "llm.before_generate": "d2c:rewrite-prompt"
    },
    "hookEvents": {
      "rag.after_search": "d2c:rag:postprocess"
    }
  }
}
```

A complete sample is available at `plugins/examples/obsidian-js/`.

Fields follow the familiar Obsidian pattern (`id`, `name`, `version`).
`requires_network` is optional and defaults to `false`.
`entry` can also be `main` (Obsidian-style field name).
`engine` supports:

- `python` (default)
- `obsidian-js` (also accepts `obsidian`, `javascript`, `js`)

Local-first defaults:

- Plugins are loaded only from repository-local `plugins/<id>/`.
- Path traversal for `entry` is blocked.
- Plugins with `requires_network: true` are skipped unless `D2C_ALLOW_PLUGIN_NETWORK=1` is set.
- JS plugins run only when local `node` is available.

## Obsidian compatibility notes

- Obsidian manifest fields (`main`, `minAppVersion`) are accepted.
- Obsidian-style JS plugins are executed through a local bridge with an `obsidian`
  module shim (`Plugin`, `PluginSettingTab`, `Setting`, `Notice`).
- Command and event mapping into backend hooks is configured via:
  - `hookCommands` / `hookEvents` (top-level)
  - or `d2c.hookCommands` / `d2c.hookEvents` (preferred namespace)
- Mappings from `d2c.*` override top-level mappings for the same hook.

## Entry Module

`main.py` should export:

```python
def register(manager):
    manager.register_hook("llm.before_generate", my_hook, plugin_id="my-plugin")
```

`main.js` can use Obsidian-style commands/events (bridge maps them to backend hooks):

```js
const { Plugin } = require("obsidian");

module.exports = class DemoPlugin extends Plugin {
  async onload() {
    this.addCommand({
      id: "d2c:rewrite-prompt",
      name: "Rewrite Prompt",
      callback: (payload) => {
        const next = { ...(payload || {}) };
        next.prompt = String(next.prompt || "") + "\n\n[JS plugin active]";
        return next;
      },
    });
  }
};
```

## Supported Hooks (v2)

- `llm.before_generate`: mutate prompt payload `{prompt, mode}`
- `llm.after_generate`: mutate generated text payload `{text, mode}`
- `rag.after_search`: mutate retrieval payload `{query, results}`
- `graph.chat.after_draft`: mutate chat draft payload `{answer, hits, question}`
