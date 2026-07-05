"""Plugin SDK polish (BL-239) — scaffold, validate, version-pin Layla plugins.

The loader already discovers `plugins/*/plugin.yaml`. This adds the author-facing SDK
around it: `scaffold_plugin()` generates a ready-to-edit plugin skeleton (using
`cookiecutter` when the on-disk template + library are available, else a built-in render
of the same layout), and `validate_manifest()` enforces the manifest contract — required
fields plus **version pinning** (a semver-ish plugin `version` and a `requires.layla_api`
range checked against the current API version). Docs live in PLUGINS.md.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

# The plugin API version this build speaks. Bump on breaking manifest changes.
LAYLA_PLUGIN_API = "1.0"

_SEMVER = re.compile(r"^\d+\.\d+(\.\d+)?$")
_SLUG = re.compile(r"[^a-z0-9_]+")


def plugin_slug(name: str) -> str:
    return _SLUG.sub("_", (name or "plugin").strip().lower()).strip("_") or "plugin"


# ── manifest validation + version pinning ────────────────────────────────────
def _parse_req(req: str) -> tuple[str, tuple[int, ...]]:
    """Parse a requirement like '>=1.0' → ('>=', (1,0)). Defaults to '>='."""
    req = (req or "").strip()
    m = re.match(r"^(>=|<=|==|>|<)?\s*(\d+(?:\.\d+)*)$", req)
    if not m:
        return ">=", (0,)
    op = m.group(1) or ">="
    return op, tuple(int(x) for x in m.group(2).split("."))


def _cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    return (a > b) - (a < b)


def _api_satisfied(requirement: str, current: str = LAYLA_PLUGIN_API) -> bool:
    op, want = _parse_req(requirement)
    cur = tuple(int(x) for x in current.split("."))
    n = max(len(want), len(cur))
    want += (0,) * (n - len(want))
    cur += (0,) * (n - len(cur))
    c = _cmp(cur, want)
    return {">=": c >= 0, "<=": c <= 0, "==": c == 0, ">": c > 0, "<": c < 0}.get(op, c >= 0)


def validate_manifest(manifest: dict, *, current_api: str = LAYLA_PLUGIN_API) -> dict[str, Any]:
    """Validate a plugin manifest. Returns {ok, errors, warnings}."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(manifest, dict):
        return {"ok": False, "errors": ["manifest must be a mapping"], "warnings": []}

    if not str(manifest.get("name") or "").strip():
        errors.append("missing required field: name")

    version = str(manifest.get("version") or "").strip()
    if not version:
        errors.append("missing required field: version (use semver, e.g. 0.1.0)")
    elif not _SEMVER.match(version):
        errors.append(f"version {version!r} is not semver (MAJOR.MINOR[.PATCH])")

    requires = manifest.get("requires") or {}
    if requires and not isinstance(requires, dict):
        errors.append("requires must be a mapping (e.g. {layla_api: '>=1.0'})")
    else:
        api_req = str((requires or {}).get("layla_api") or "").strip()
        if not api_req:
            warnings.append("no requires.layla_api pin — add one for forward-compat safety")
        elif not _api_satisfied(api_req, current_api):
            errors.append(f"requires.layla_api {api_req!r} not satisfied by current API {current_api}")

    if not (manifest.get("skills") or manifest.get("tools") or manifest.get("capabilities")):
        warnings.append("plugin declares no skills, tools, or capabilities")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


# ── scaffolding ──────────────────────────────────────────────────────────────
def _template_files(ctx: dict) -> dict[str, str]:
    """The built-in plugin layout (also mirrored as a cookiecutter template on disk)."""
    name = ctx["plugin_name"]
    slug = ctx["plugin_slug"]
    desc = ctx.get("description", "")
    author = ctx.get("author", "")
    version = ctx.get("version", "0.1.0")
    manifest = f"""# Layla plugin manifest — see PLUGINS.md
name: {name}
version: {version}
description: {desc}
author: {author}

# Version pinning: which Layla plugin API this targets.
requires:
  layla_api: ">={LAYLA_PLUGIN_API}"

# Declarative skills: a named tool sequence the agent can run.
skills:
  - name: {slug}_hello
    description: Example skill — replace with your own.
    tools: [read_file]
    execution_steps:
      - "Describe the first step here."

# (optional) tools: []
# (optional) capabilities: []
"""
    readme = f"""# {name}

{desc or "A Layla plugin."}

## Install
Drop this folder into Layla's `plugins/` directory (or install from git), then restart.

## Develop
- Edit `plugin.yaml` to declare skills / tools / capabilities.
- Keep `version` semver and `requires.layla_api` pinned.
- See the top-level PLUGINS.md for the full contract.

Author: {author or "you"}
"""
    return {"plugin.yaml": manifest, "README.md": readme}


def scaffold_plugin(
    name: str,
    dest_dir: str | Path,
    *,
    description: str = "",
    author: str = "",
    version: str = "0.1.0",
    use_cookiecutter: bool = True,
) -> dict[str, Any]:
    """Create a new plugin skeleton under dest_dir/<slug>/. Returns the written paths."""
    slug = plugin_slug(name)
    ctx = {
        "plugin_name": name.strip() or slug,
        "plugin_slug": slug,
        "description": description,
        "author": author,
        "version": version,
    }
    root = Path(dest_dir).expanduser().resolve() / slug
    if root.exists() and any(root.iterdir()):
        return {"ok": False, "error": f"{root} already exists and is not empty"}

    # Prefer the real cookiecutter template if the library + template are present.
    if use_cookiecutter:
        tpl = _cookiecutter_template_dir()
        if tpl is not None:
            try:
                from cookiecutter.main import cookiecutter
                out = cookiecutter(
                    str(tpl), no_input=True, output_dir=str(Path(dest_dir).expanduser().resolve()),
                    extra_context={"plugin_name": ctx["plugin_name"], "plugin_slug": slug,
                                   "description": description, "author": author, "version": version},
                    overwrite_if_exists=False,
                )
                return {"ok": True, "path": out, "via": "cookiecutter"}
            except Exception as e:  # noqa: BLE001 — fall back to built-in render
                logger.debug("cookiecutter scaffold failed, using built-in: %s", e)

    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for rel, content in _template_files(ctx).items():
        p = root / rel
        p.write_text(content, encoding="utf-8")
        written.append(str(p))
    return {"ok": True, "path": str(root), "files": written, "via": "builtin"}


def _cookiecutter_template_dir() -> Path | None:
    """Locate the on-disk cookiecutter template, if shipped."""
    here = Path(__file__).resolve()
    # agent/plugins/_template  (cookiecutter.json lives there)
    candidate = here.parents[2] / "plugins" / "_template"
    return candidate if (candidate / "cookiecutter.json").exists() else None
