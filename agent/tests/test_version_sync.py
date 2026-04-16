from __future__ import annotations

from pathlib import Path


def test_pyproject_version_matches_agent_version():
    repo_root = Path(__file__).resolve().parent.parent.parent
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    # Simple parse (avoid adding deps): look for `version = "x.y.z"` under [project].
    ver = ""
    in_project = False
    for raw in pyproject.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_project = (line == "[project]")
            continue
        if in_project and line.startswith("version"):
            # version = "1.3.0"
            parts = line.split("=", 1)
            if len(parts) == 2:
                ver = parts[1].strip().strip('"').strip("'")
            break
    assert ver, "pyproject.toml [project].version not found"

    from version import __version__

    assert ver == __version__, f"pyproject version {ver} != agent/version.py {__version__}"

