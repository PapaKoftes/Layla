"""Gate the knowledge/packs structure: every pack manifest + doc must validate.

Runs the same validator that builds registry.json/presets.json, in --check mode.
Fails CI if any pack doc is missing front matter, has a mismatched domain, an
over-long summary, a manifest that disagrees with what's on disk, or a preset that
references an unknown pack.
"""
import subprocess
import sys
from pathlib import Path


def test_knowledge_packs_validate():
    script = Path(__file__).resolve().parent.parent / "scripts" / "build_knowledge_registry.py"
    if not script.is_file():
        # packs feature not present on this branch — nothing to gate
        return
    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "knowledge pack validation failed:\n" + result.stdout + result.stderr
    )
