# Layla Skill Packs

Skill packs are self-contained extensions that add new tools and capabilities to
Layla. Each pack lives in its own directory, declares a manifest, runs in an
isolated virtual environment, and is tracked in a SQLite registry with version
and health metadata.

---

## Table of Contents

1. [Overview](#overview)
2. [Creating a Skill Pack](#creating-a-skill-pack)
3. [Installing from Git](#installing-from-git)
4. [Listing Installed Packs](#listing-installed-packs)
5. [Removing and Rolling Back Packs](#removing-and-rolling-back-packs)
6. [Security Model](#security-model)
7. [Example: Minimal Skill Pack](#example-minimal-skill-pack)
8. [API Reference](#api-reference)

---

## Overview

A skill pack is a Git repository (or local directory) that contains:

- A **manifest file** (`layla-skill.json` or `manifest.json`) describing the
  pack, its entry point, dependencies, and permissions.
- A **Python entry point** (e.g. `main.py`) that Layla executes in a sandboxed
  virtual environment.
- Optional pip dependencies declared in the manifest.

When you install a pack, Layla:

1. Clones the repository into `.layla/skill_packs_installed/<name>/`.
2. Validates the manifest against the schema (required fields, valid semver, no
   path traversal).
3. Registers the pack in the SQLite skill registry (`~/.layla/skill_registry.db`)
   with version, manifest hash, install timestamp, and health status.
4. Creates an isolated venv under `~/.layla/skill_envs/<name>/` and installs the
   pack's declared pip dependencies into it.

The pack is then available as a tool in Layla's agent loop.

---

## Creating a Skill Pack

### Directory Structure

```
my-weather-pack/
  layla-skill.json      # manifest (preferred name)
  main.py               # entry point
  utils.py              # any additional modules
  README.md             # optional
```

### Manifest Schema

Create a file named `layla-skill.json` (preferred) or `manifest.json` in the
repository root:

```json
{
  "name": "my-weather-pack",
  "version": "1.0.0",
  "author": "Your Name <you@example.com>",
  "description": "Fetches current weather data for any city",
  "entry_point": "main.py",
  "dependencies": [
    "requests>=2.28"
  ],
  "permissions": [
    "network"
  ],
  "layla_version_min": "0.9.0",
  "tags": [
    "weather",
    "api"
  ],
  "homepage": "https://github.com/you/my-weather-pack"
}
```

#### Required Fields

| Field         | Type   | Rules                                                      |
|---------------|--------|------------------------------------------------------------|
| `name`        | string | Alphanumeric, hyphens, underscores only. Must be non-empty.|
| `version`     | string | Semver-like: `1.0.0`, `0.1`, `2.0.0-beta.1`.              |
| `description` | string | Non-empty human-readable summary.                          |
| `entry_point` | string | Relative path to the Python script. No `..` or absolute paths allowed. |

#### Optional Fields

| Field              | Type     | Description                                         |
|--------------------|----------|-----------------------------------------------------|
| `author`           | string   | Author name or email.                               |
| `dependencies`     | string[] | Pip requirement specifiers (e.g. `["numpy>=1.24"]`).|
| `permissions`      | string[] | Capabilities the pack needs (see below).            |
| `layla_version_min`| string   | Minimum Layla version required.                     |
| `tags`             | string[] | Categorization tags.                                |
| `homepage`         | string   | URL to project page or documentation.               |

#### Valid Permissions

Permissions declare what system capabilities your pack requires:

| Permission     | Description                          |
|----------------|--------------------------------------|
| `read_memory`  | Read from Layla's memory/learnings   |
| `write_memory` | Save learnings or entities           |
| `read_file`    | Read files from the workspace        |
| `write_file`   | Write or create files                |
| `shell`        | Execute shell commands               |
| `network`      | Make HTTP requests                   |
| `browser`      | Control browser automation           |
| `voice`        | Access TTS/STT services              |

Unknown permission strings will cause manifest validation to fail.

### Entry Point

The entry point is a Python script that Layla executes via the pack's isolated
venv. The sandbox provides two environment variables:

- `LAYLA_SKILL_PACK` -- the pack name
- `LAYLA_PACK_DIR` -- absolute path to the pack's installed directory

Your entry point receives arguments via `sys.argv` and can read JSON from stdin.
Output is captured from stdout (up to 10 KB) and stderr (up to 5 KB).

```python
#!/usr/bin/env python3
"""main.py -- entry point for my-weather-pack."""
import json
import os
import sys

def run():
    pack_name = os.environ.get("LAYLA_SKILL_PACK", "unknown")
    pack_dir = os.environ.get("LAYLA_PACK_DIR", ".")

    # Read input from stdin if provided
    if not sys.stdin.isatty():
        input_data = json.load(sys.stdin)
    else:
        input_data = {}

    city = input_data.get("city", "Athens")
    # ... do work ...
    result = {"city": city, "temp_c": 22, "conditions": "sunny"}

    # Write JSON to stdout -- Layla captures this
    print(json.dumps(result))

if __name__ == "__main__":
    run()
```

The default execution timeout is **60 seconds**. If the script exceeds this, it
is killed and `timed_out: true` is returned.

---

## Installing from Git

### Via API

```
POST /skill_packs/install
Content-Type: application/json

{
  "url": "https://github.com/you/my-weather-pack.git",
  "name": "my-weather-pack"
}
```

- `url` (required) -- Git clone URL.
- `name` (optional) -- Override the pack slug. Defaults to the repo name with
  `.git` stripped.

The install flow:

1. `git clone --depth 1` into `.layla/skill_packs_installed/<name>/`.
2. Locate and parse `layla-skill.json` (preferred) or `manifest.json`.
3. Validate manifest: required fields, semver format, no path traversal in
   entry_point, valid permissions.
4. Register in the SQLite skill registry with version and manifest hash.
5. Return `{"ok": true, "path": "...", "id": "my-weather-pack"}`.

If the manifest is missing or invalid, the cloned directory is removed and an
error is returned.

If a pack with the same name is already installed, the request fails with
`"already installed: <name>"`.

### Via Python

```python
from services.skill_packs import install_from_git

result = install_from_git(
    url="https://github.com/you/my-weather-pack.git",
    name="my-weather-pack",
)
# result: {"ok": True, "path": "...", "id": "my-weather-pack"}
```

---

## Listing Installed Packs

### Via API

```
GET /skill_packs
```

Returns:

```json
{
  "packs": [
    {
      "name": "my-weather-pack",
      "version": "1.0.0",
      "description": "Fetches current weather data for any city",
      "entry_point": "main.py",
      "dependencies": ["requests>=2.28"],
      "permissions": ["network"],
      "tags": ["weather", "api"]
    }
  ]
}
```

This reads manifest data directly from each directory under
`.layla/skill_packs_installed/`.

### Registry Query

The skill registry provides richer metadata (install time, health, last run):

```python
from services.skill_registry import list_packs, get_pack

all_packs = list_packs()
# [{"name": "my-weather-pack", "version": "1.0.0", "health_status": "installed",
#   "installed_at": "2025-06-01 12:00:00", "last_run": "", ...}]

single = get_pack("my-weather-pack")
```

---

## Removing and Rolling Back Packs

### Remove via API

```
POST /skill_packs/remove
Content-Type: application/json

{
  "id": "my-weather-pack"
}
```

This deletes the pack directory from `.layla/skill_packs_installed/`.

### Full Rollback

For a complete cleanup that also removes the venv and registry entry, use the
rollback module:

```python
from services.skill_rollback import rollback_install
from pathlib import Path

result = rollback_install(
    pack_name="my-weather-pack",
    pack_dir=Path(".layla/skill_packs_installed/my-weather-pack"),
)
# result: {"ok": True, "pack_name": "my-weather-pack", "actions": [
#   "Removed pack directory: ...",
#   "Removed venv: ...",
#   "Removed registry entry"
# ]}
```

`rollback_install` performs three cleanup steps:

1. Removes the pack directory (`.layla/skill_packs_installed/<name>/`).
2. Removes the sandboxed venv (`~/.layla/skill_envs/<name>/`).
3. Deletes the registry row from SQLite.

You can check whether a rollback is possible with:

```python
from services.skill_rollback import can_rollback

if can_rollback("my-weather-pack"):
    rollback_install("my-weather-pack")
```

---

## Security Model

Skill packs run with several layers of isolation and validation.

### Manifest Validation

Before a pack is accepted, `skill_manifest.validate_manifest()` enforces:

- **Required fields** -- `name`, `version`, `description`, `entry_point` must
  all be present and non-empty.
- **Name format** -- only `[a-zA-Z0-9_-]` characters allowed.
- **Semver version** -- must match `^\d+\.\d+(\.\d+)?(-[\w.]+)?$`.
- **Path traversal prevention** -- `entry_point` must be a relative path. Values
  containing `..`, starting with `/`, or starting with `\` are rejected.
- **Permission allow-list** -- only the eight defined permissions are accepted.
  Unknown permissions cause validation failure.

### Sandboxed Execution

Each pack gets its own Python virtual environment under
`~/.layla/skill_envs/<pack_name>/`. The sandbox (`skill_sandbox.py`) provides:

- **Process isolation** -- entry points run as subprocesses, not in Layla's
  process. A non-zero exit code is captured, not propagated.
- **Minimal environment** -- only safe environment variables are passed through
  (`PATH`, `HOME`, `TEMP`, etc.). Layla's API keys, tokens, and config are not
  exposed.
- **Path confinement** -- before execution, the resolved entry point path is
  checked to ensure it falls within the pack directory. Attempts to escape via
  symlinks or `..` are blocked.
- **Timeout enforcement** -- default 60-second execution limit. Configurable per
  invocation. Processes that exceed the limit are killed.
- **Output limits** -- stdout is truncated to 10 KB, stderr to 5 KB.
- **Dependency isolation** -- each pack's pip dependencies are installed into its
  own venv, preventing version conflicts between packs or with Layla itself.

### Registry Integrity

The SQLite skill registry tracks a SHA-256 hash of the manifest contents. This
enables change detection: if a pack's manifest is modified after install, the
hash mismatch can be flagged.

---

## Example: Minimal Skill Pack

This creates a working pack that converts Celsius to Fahrenheit.

### 1. Create the Repository

```
mkdir layla-temp-converter && cd layla-temp-converter
git init
```

### 2. Write the Manifest

Create `layla-skill.json`:

```json
{
  "name": "temp-converter",
  "version": "0.1.0",
  "description": "Converts Celsius to Fahrenheit and vice versa",
  "entry_point": "main.py",
  "dependencies": [],
  "permissions": [],
  "tags": ["utility", "conversion"]
}
```

### 3. Write the Entry Point

Create `main.py`:

```python
#!/usr/bin/env python3
"""Temperature converter skill pack."""
import json
import sys


def main():
    # Read JSON input from stdin
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    value = data.get("value", 0)
    direction = data.get("direction", "c_to_f")

    if direction == "c_to_f":
        result = value * 9 / 5 + 32
        print(json.dumps({"input_c": value, "output_f": result}))
    elif direction == "f_to_c":
        result = (value - 32) * 5 / 9
        print(json.dumps({"input_f": value, "output_c": round(result, 2)}))
    else:
        print(json.dumps({"error": f"Unknown direction: {direction}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### 4. Commit and Push

```bash
git add .
git commit -m "Initial skill pack"
git remote add origin https://github.com/you/layla-temp-converter.git
git push -u origin main
```

### 5. Install into Layla

```
POST /skill_packs/install
{
  "url": "https://github.com/you/layla-temp-converter.git"
}
```

Response:

```json
{
  "ok": true,
  "path": ".layla/skill_packs_installed/layla-temp-converter",
  "id": "layla-temp-converter"
}
```

### 6. Generate a Template

You can also scaffold a manifest programmatically:

```python
from services.skill_manifest import generate_template

template = generate_template("my-new-pack")
# Returns a valid manifest dict with sensible defaults
```

---

## API Reference

| Method | Endpoint                 | Description                       |
|--------|--------------------------|-----------------------------------|
| GET    | `/skill_packs`           | List all installed skill packs    |
| POST   | `/skill_packs/install`   | Install a pack from a Git URL     |
| POST   | `/skill_packs/remove`    | Remove an installed pack by ID    |
| GET    | `/skills`                | List markdown skills (separate system) |

### Key Modules

| Module                          | Responsibility                                   |
|---------------------------------|--------------------------------------------------|
| `services/skill_packs.py`       | Install, list, remove pack directories           |
| `services/skill_manifest.py`    | Load, validate, and template manifest files      |
| `services/skill_sandbox.py`     | Venv creation, dependency install, sandboxed exec|
| `services/skill_registry.py`    | SQLite CRUD for installed pack metadata          |
| `services/skill_rollback.py`    | Full cleanup: directory + venv + registry entry  |
| `services/skill_discovery.py`   | Suggest packs based on task context (heuristic)  |

### Storage Locations

| Path                                       | Contents                              |
|--------------------------------------------|---------------------------------------|
| `.layla/skill_packs_installed/<name>/`     | Cloned pack directory with manifest   |
| `~/.layla/skill_envs/<name>/`             | Isolated Python venv per pack         |
| `~/.layla/skill_registry.db`              | SQLite registry (versions, health)    |
