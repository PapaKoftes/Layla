# Plugins

Plugins extend Layla with additional skills and optional tools. Loaded automatically at server startup. See also [CAPABILITIES.md](CAPABILITIES.md) for capability discovery and dynamic backend selection.

---

## Plugin structure

```
plugins/
  <plugin_name>/
    plugin.yaml      # Required manifest
    tools.py         # Optional: register custom tools
```

---

## plugin.yaml manifest

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Plugin identifier |
| `description` | No | Short description |
| `skills` | No | List of skill definitions |
| `tools` | No | List of tool names from tools.py |
| `dependencies` | No | Pip package names (informational) |

---

## Config

- `plugins_dir`: Override plugins directory (default: `repo_root/plugins`)

---

## Example

See `plugins/example/plugin.yaml` for a minimal plugin.
