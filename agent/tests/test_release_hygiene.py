"""Operator data must never reach an end user's machine.

The Windows installer shipped ~10.7MB of operator state — including agent/.layla/memory_encryption.key,
the Fernet key protecting encrypted learnings — because build_installer.ps1 did a recursive Copy-Item of
the BUILD MACHINE'S WORKING TREE. Copy-Item does not read .gitignore, so every "it's gitignored" guarantee
was irrelevant on the one path that actually reaches a friend's laptop. The `git clone` and pip-packaging
paths were always clean; the artifact you hand someone was not.

These tests pin the two properties that make the leak structurally impossible:
  1. the installer payload is EXPORTED FROM GIT (allowlist), never copied from disk (denylist), and
  2. a leak gate fails the build if operator state appears in the payload anyway.
Plus .dockerignore/.gitignore coverage, so a new operator file can't quietly become shippable.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _read(rel: str) -> str:
    p = ROOT / rel
    assert p.exists(), f"missing: {rel}"
    return p.read_text(encoding="utf-8", errors="replace")


def test_installer_payload_is_exported_from_git_not_the_working_tree():
    ps1 = _read("installer/build_installer.ps1")
    assert "git archive" in ps1, (
        "installer payload must be exported from git HEAD (allowlist semantics). A working-tree copy "
        "ships whatever happens to be on the build machine — including the Fernet key."
    )
    # the specific line that caused the leak must not come back
    assert not re.search(r'Copy-Item\s+-Path\s+\(Join-Path\s+\$Root\s+"agent"\)\s+-Destination\s+\$Payload\s+-Recurse',
                         ps1), "recursive working-tree copy of agent/ into the payload reintroduces the leak"


def test_installer_has_a_leak_gate_that_fails_the_build():
    ps1 = _read("installer/build_installer.ps1")
    assert "REFUSING TO BUILD" in ps1, "installer must hard-fail when operator state is found in the payload"
    # the gate must cover the worst offenders by name
    for pat in ("memory_encryption.key", "*.db", "*.graphml", "runtime_config.json", ".governance", ".layla"):
        assert pat in ps1, f"leak gate must check for {pat}"
    assert "throw" in ps1, "the gate must throw (fail the build), not merely warn"


def test_dockerignore_exists_and_covers_operator_state():
    # Dockerfile does `COPY agent/ ./agent/`, which ignores .gitignore entirely.
    dockerfile = _read("Dockerfile")
    assert "COPY" in dockerfile
    di = _read(".dockerignore")
    for pat in ("**/.layla/", "**/.governance/", "**/chroma_db/", "*.db", "*.graphml",
                "**/memory_encryption.key"):
        assert pat in di, f".dockerignore must exclude {pat}"


def test_gitignore_covers_every_known_operator_store():
    gi = _read(".gitignore")
    # The .bak hole: the old rule named knowledge_graph.graphml exactly, so the byte-identical .bak
    # sibling was untracked but NOT ignored — one `git add -A` from being committed.
    assert ("agent/layla/memory/knowledge_graph.graphml*" in gi or "*.graphml.bak" in gi), \
        ".gitignore must cover the .graphml.bak sibling, not just the .graphml"
    assert "agent/titles.txt" in gi, ".gitignore must cover agent/titles.txt"
    assert "benchmarks/scorecard_live.json" in gi, ".gitignore must cover the live scorecard"


def test_no_operator_data_is_tracked_in_git():
    """Nothing matching an operator-data shape may be tracked. Guards against a careless `git add -A`."""
    import subprocess
    out = subprocess.run(["git", "ls-files"], cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, f"git ls-files failed: {out.stderr}"
    tracked = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    bad = []
    for f in tracked:
        low = f.lower()
        if low.endswith((".db", ".sqlite", ".sqlite3", ".graphml", ".graphml.bak")):
            bad.append(f)
        if "/.layla/" in low or low.startswith(".layla/"):
            bad.append(f)
        if "/.governance/" in low or low.startswith(".governance/"):
            bad.append(f)
        if low.endswith("memory_encryption.key") or low.endswith("runtime_config.json"):
            bad.append(f)
        if low.endswith("scorecard_live.json") or low.endswith("agent/titles.txt"):
            bad.append(f)
        if low.endswith("conversation_history.json"):
            bad.append(f)
    assert not bad, f"operator-data files are TRACKED IN GIT and would ship to every clone: {sorted(set(bad))}"
