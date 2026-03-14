# Layla Plugins

Plugins extend Layla with additional skills and tools. Each plugin lives in its own directory with a `plugin.yaml` manifest.

## Plugin structure

```
plugins/
  my_plugin/
    plugin.yaml
    (optional) tools.py
```

## plugin.yaml

```yaml
name: my_plugin
description: Short description of what this plugin does
skills:
  - name: my_skill
    description: What this skill does
    tools: [tool1, tool2]
tools: []  # Optional: tool names from tools.py
dependencies: []  # Optional: pip package names
```

## Adding a plugin

1. Create `plugins/<name>/plugin.yaml`
2. Optionally add `plugins/<name>/tools.py` that exports a `register(registry)` function
3. Restart Layla — plugins are loaded at startup

See [docs/plugins.md](../docs/plugins.md) for full documentation.
