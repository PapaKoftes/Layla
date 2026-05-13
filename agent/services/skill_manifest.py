"""
Skill pack manifest schema validation.

Every installable skill pack MUST include a `layla-skill.json` manifest.
This module defines the schema and validates manifests on install.

Manifest schema:
{
  "name": str,               # Required: unique pack name
  "version": str,            # Required: semver (e.g. "1.0.0")
  "author": str,             # Optional: author name/email
  "description": str,        # Required: what this pack does
  "entry_point": str,        # Required: Python module or script to run (e.g. "main.py")
  "dependencies": [str],     # Optional: pip requirements (e.g. ["requests>=2.28", "numpy"])
  "layla_version_min": str,  # Optional: minimum Layla version
  "permissions": [str],      # Optional: required permissions (e.g. ["read_memory", "write_file"])
  "tags": [str],             # Optional: categorization tags
  "homepage": str,           # Optional: URL
}
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

# Valid permission strings
VALID_PERMISSIONS = frozenset({
    "read_memory",       # Read from Layla's memory/learnings
    "write_memory",      # Save learnings or entities
    "read_file",         # Read files from workspace
    "write_file",        # Write/create files
    "shell",             # Execute shell commands
    "network",           # Make HTTP requests
    "browser",           # Control browser automation
    "voice",             # Access TTS/STT
})

# Manifest file names (in order of preference)
MANIFEST_NAMES = ("layla-skill.json", "manifest.json")

# Version pattern (loose semver)
_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?(-[\w.]+)?$")


def find_manifest(pack_dir: Path) -> Path | None:
    """Find the manifest file in a pack directory."""
    for name in MANIFEST_NAMES:
        p = pack_dir / name
        if p.exists():
            return p
    return None


def load_manifest(pack_dir: Path) -> dict[str, Any] | None:
    """Load and parse manifest from a pack directory. Returns None if not found."""
    path = find_manifest(pack_dir)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("skill_manifest: failed to load %s: %s", path, e)
        return None


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """
    Validate a manifest dict. Returns list of error strings (empty = valid).
    """
    errors: list[str] = []

    # Required fields
    if not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
        errors.append("'name' is required and must be a non-empty string")
    else:
        name = manifest["name"].strip()
        if not re.match(r"^[a-zA-Z0-9_-]+$", name):
            errors.append(f"'name' must contain only alphanumeric, hyphens, underscores; got '{name}'")

    if not isinstance(manifest.get("version"), str) or not manifest["version"].strip():
        errors.append("'version' is required and must be a non-empty string")
    elif not _VERSION_RE.match(manifest["version"].strip()):
        errors.append(f"'version' must be semver-like (e.g. '1.0.0'); got '{manifest['version']}'")

    if not isinstance(manifest.get("description"), str) or not manifest["description"].strip():
        errors.append("'description' is required and must be a non-empty string")

    if not isinstance(manifest.get("entry_point"), str) or not manifest["entry_point"].strip():
        errors.append("'entry_point' is required and must be a non-empty string")
    else:
        ep = manifest["entry_point"].strip()
        if ".." in ep or ep.startswith("/") or ep.startswith("\\"):
            errors.append(f"'entry_point' must be a relative path without '..'; got '{ep}'")

    # Optional fields with type validation
    deps = manifest.get("dependencies", [])
    if not isinstance(deps, list):
        errors.append("'dependencies' must be a list of strings")
    elif not all(isinstance(d, str) for d in deps):
        errors.append("'dependencies' must be a list of strings")

    perms = manifest.get("permissions", [])
    if not isinstance(perms, list):
        errors.append("'permissions' must be a list of strings")
    elif perms:
        for p in perms:
            if not isinstance(p, str):
                errors.append(f"'permissions' entry must be a string; got {type(p).__name__}")
            elif p not in VALID_PERMISSIONS:
                errors.append(f"Unknown permission '{p}'; valid: {sorted(VALID_PERMISSIONS)}")

    tags = manifest.get("tags", [])
    if not isinstance(tags, list):
        errors.append("'tags' must be a list of strings")

    author = manifest.get("author")
    if author is not None and not isinstance(author, str):
        errors.append("'author' must be a string")

    homepage = manifest.get("homepage")
    if homepage is not None and not isinstance(homepage, str):
        errors.append("'homepage' must be a string")

    return errors


def generate_template(name: str = "my-skill-pack") -> dict[str, Any]:
    """Generate a template manifest for `layla skill init`."""
    return {
        "name": name,
        "version": "0.1.0",
        "author": "",
        "description": "A Layla skill pack",
        "entry_point": "main.py",
        "dependencies": [],
        "permissions": ["read_memory"],
        "tags": [],
        "homepage": "",
    }
