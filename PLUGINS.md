# Building Layla plugins

A **plugin** extends Layla with declarative *skills* (named tool sequences), *tools*, or
*capabilities* — no core changes required. The loader discovers `plugins/*/plugin.yaml`
at startup; the SDK (`services/skills/plugin_sdk.py`) helps you scaffold, validate, and
version-pin one.

## Quick start

Scaffold a new plugin (built-in renderer; uses `cookiecutter` automatically if installed):

```bash
# via the API
curl -X POST localhost:8000/plugins/scaffold \
  -H 'Content-Type: application/json' \
  -d '{"name":"My Plugin","description":"does a thing","author":"me","dest_dir":"plugins"}'
```

Or with cookiecutter directly against the shipped template:

```bash
pip install cookiecutter
cookiecutter agent/plugins/_template
```

Either way you get `plugins/<slug>/` with a ready-to-edit `plugin.yaml` + `README.md`.

## The manifest (`plugin.yaml`)

```yaml
name: My Plugin            # required
version: 0.1.0             # required — semver MAJOR.MINOR[.PATCH]
description: does a thing
author: me

requires:
  layla_api: ">=1.0"       # version pin — checked against the running API

skills:                    # declarative tool sequences
  - name: my_plugin_hello
    description: Example skill.
    tools: [read_file]
    execution_steps:
      - "Describe the first step."

# tools: []                # (optional) direct tool registrations
# capabilities: []         # (optional) engine capability implementations
```

### Version pinning

- **`version`** — your plugin's own semver. Bump it on every release.
- **`requires.layla_api`** — the Layla plugin API your plugin targets, as a range
  (`>=1.0`, `==1.0`, `<2.0`, …). The current API version is `LAYLA_PLUGIN_API` in
  `plugin_sdk.py`. A plugin whose pin isn't satisfied fails validation with a clear error
  rather than loading against an incompatible host.

Validate before shipping:

```bash
curl -X POST localhost:8000/plugins/validate -H 'Content-Type: application/json' \
  -d '{"manifest": {"name":"x","version":"0.1.0","requires":{"layla_api":">=1.0"}}}'
# → {"ok": true, "errors": [], "warnings": []}
```

## Distribution

- **Local:** drop the folder in `plugins/` and restart.
- **Git:** `install_from_git(url)` (see `services/skills/skill_packs.py`) clones and installs.

Keep plugins small and declarative; prefer standing on existing tools over shipping code.
