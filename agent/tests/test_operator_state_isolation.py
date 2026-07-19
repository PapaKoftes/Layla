"""The test suite must not write to the operator's real data.

Two things made this urgent rather than theoretical:

  - `system_head_builder` calls `write_profile_snapshot` on EVERY head build, and the R6 path fix made
    `frame_modifier._profile_path()` correctly resolve to `agent/.layla/`. Correct for production; it
    means a suite without data-dir isolation overwrites the operator's real profile.
  - `tunnel_audit` rooted its DB at `Path.home()` and mkdir'd a directory constant SEPARATE from the
    path constant every test patches — so 26 `mkdir` calls landed on the operator's real `~/.layla`
    during a full run, measured with a write tracer over the whole suite.

These tests assert the ISOLATION, not the absence of one particular writer. A new module that resolves
a data path by counting `parent` calls is the recurring defect; this is the net under it.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

REPO = AGENT.parent

# Paths that belong to the operator and must never be written by a test run.
PROTECTED = [
    AGENT / ".layla",
    AGENT / "runtime_config.json",
    REPO / "layla.db",
    Path.home() / ".layla",
]

# (module, resolver) for known writers that own a file under a `.layla/` directory. A resolver must
# be a per-call function so LAYLA_DATA_DIR is honoured whatever the import order was.
#
# THIS LIST IS NOT THE NET. It is a fast, precise check on the writers already found. A hardcoded
# list cannot catch the *next* instance of the defect — it did not catch `repo_indexer` (which was
# mkdir'ing and connecting to a shadow `agent/services/.layla/repo_index.db` ~50x per run) or
# `skill_registry` (which ran a committed UPDATE against the operator's live registry), both of
# which existed while this list claimed to be "the net under" new writers.
# The actual net is `test_no_unsanctioned_writes_under_a_traced_suite_slice` below.
DATA_PATH_RESOLVERS = [
    ("services.memory.working_memory", "_wm_path"),
    ("services.personality.frame_modifier", "_profile_path"),
    ("services.governance.tunnel_audit", "_db_path"),
    ("services.workspace.repo_indexer", "_default_db_path"),
    ("services.skills.skill_registry", "_db_path"),
    ("services.infrastructure.crash_handler", "_crash_dir"),
]

# A slice of the suite chosen to exercise the data-path writers. Run as a subprocess under the
# write tracer.
#
# `test_capability_manifest.py` is the load-bearing entry: building a system head reaches
# `system_head_builder.py:857 -> world_state.summarize -> snapshot -> _repo_index -> get_stats ->
# migrate -> _conn`, which is the path that produced 42 `sqlite3.connect` calls against the shadow
# `agent/services/.layla/repo_index.db`. `test_world_state.py` does NOT reach it — it stubs the
# snapshot — so a slice built from module names that merely sound relevant would have been green
# against the very defect this guard exists for. Verified by breaking the fix and watching this
# list go red (see the module docstring's note on proving guards).
TRACED_SLICE = [
    "tests/test_capability_manifest.py",
    "tests/test_world_state.py",
    "tests/test_skill_pack_execution.py",
    "tests/test_frame_modifier.py",
    "tests/test_tunnel_audit.py",
    "tests/test_repo_indexer.py",
    "tests/test_observability.py",
    "tests/test_memory_commands.py",
]


def _run_traced(targets, out_path: Path, env_extra: dict | None = None, cwd: Path | None = None):
    """Run pytest on `targets` under `_write_tracer_plugin`; return (result, [events])."""
    import json
    import subprocess

    env = dict(os.environ)
    env["LAYLA_WRITE_TRACE_OUT"] = str(out_path)
    # `-p` plugins are imported before conftest, so the collection window is traced too.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(AGENT / "tests"), str(AGENT), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    env.pop("LAYLA_WRITE_TRACE_ROOTS", None)
    if env_extra:
        env.update(env_extra)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-q", "-p", "_write_tracer_plugin",
         "-p", "no:cacheprovider"],
        cwd=str(cwd or AGENT), env=env, capture_output=True, text=True, timeout=900,
    )
    events = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else []
    return result, events


def _resolve(modname: str, attr: str) -> Path:
    mod = importlib.import_module(modname)
    return getattr(mod, attr)()


def test_layla_data_dir_is_set_and_isolated():
    """The whole net depends on this one variable being in force. Assert it directly."""
    raw = os.environ.get("LAYLA_DATA_DIR", "")
    assert raw, (
        "LAYLA_DATA_DIR is not set — conftest's import-time isolation did not take. Every data-dir "
        "writer in the suite is now pointed at the operator's real files."
    )
    data_dir = Path(raw).resolve()
    assert AGENT not in data_dir.parents and data_dir != AGENT, (
        f"LAYLA_DATA_DIR resolves inside the repo ({data_dir})"
    )
    assert data_dir != Path.home().resolve(), (
        f"LAYLA_DATA_DIR is the operator's home ({data_dir})"
    )


@pytest.mark.parametrize("modname,attr", DATA_PATH_RESOLVERS)
def test_every_data_path_resolver_lands_inside_layla_data_dir(modname, attr):
    """RED before the tunnel_audit fix: `_db_path` did not exist and the module's path was rooted at
    `Path.home()` regardless of LAYLA_DATA_DIR."""
    data_dir = Path(os.environ["LAYLA_DATA_DIR"]).resolve()
    p = _resolve(modname, attr).resolve()

    assert data_dir in p.parents, (
        f"{modname}.{attr}() resolved to {p}, which is outside LAYLA_DATA_DIR ({data_dir}). This writer "
        f"is not isolated by the suite's data-dir fixture and will hit operator state."
    )


@pytest.mark.parametrize("modname,attr", DATA_PATH_RESOLVERS)
def test_no_data_path_resolver_touches_a_protected_operator_path(modname, attr):
    p = _resolve(modname, attr).resolve()
    for prot in PROTECTED:
        prot = prot.resolve()
        assert p != prot and prot not in p.parents, (
            f"{modname}.{attr}() resolves to {p}, inside protected operator path {prot}"
        )


def test_tunnel_audit_connection_opens_inside_the_isolated_data_dir(tmp_path, monkeypatch):
    """The specific defect: the mkdir used `_DB_DIR`, a constant SEPARATE from the `_DB_PATH` that every
    tunnel test patches — so patching the path isolated the DB file and left the directory creation
    pointed at the operator's `~/.layla`.

    Asserted through a real connection so it stays true only while the mkdir actually follows the path.
    """
    import services.governance.tunnel_audit as ta

    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ta, "_DB_PATH", None, raising=False)
    monkeypatch.setattr(ta, "_table_ready", False, raising=False)

    home_layla = Path.home() / ".layla"
    home_existed = home_layla.exists()

    conn = ta._get_connection()
    try:
        db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve()
    finally:
        conn.close()

    assert tmp_path.resolve() in db_file.parents, (
        f"tunnel_audit opened {db_file}, outside the configured data dir {tmp_path}"
    )
    if not home_existed:
        assert not home_layla.exists(), (
            "tunnel_audit created ~/.layla even though LAYLA_DATA_DIR pointed elsewhere — the mkdir is "
            "still rooted at Path.home() instead of following the resolved DB path"
        )


def test_patching_db_path_also_moves_the_directory_that_gets_created(tmp_path, monkeypatch):
    """What the existing tunnel tests believe they are doing. Before the fix they patched `_DB_PATH`
    and the mkdir went to `~/.layla` anyway; this pins that patching the path is sufficient."""
    import services.governance.tunnel_audit as ta

    target = tmp_path / "nested" / "audit.db"
    monkeypatch.setattr(ta, "_DB_PATH", target, raising=False)
    monkeypatch.setattr(ta, "_table_ready", False, raising=False)

    conn = ta._get_connection()
    conn.close()

    assert target.parent.is_dir(), (
        "patching _DB_PATH did not move the mkdir — the directory is still resolved independently"
    )


@pytest.mark.timeout(900)
def test_no_unsanctioned_writes_under_a_traced_suite_slice(tmp_path):
    """THE NET. Run a slice of the real suite with every filesystem write instrumented and fail on
    anything landing outside LAYLA_DATA_DIR / the temp area.

    This is what `DATA_PATH_RESOLVERS` above only pretends to be. It needs no knowledge of which
    modules write where, so it catches a writer added tomorrow — see
    `test_the_write_tracer_catches_a_brand_new_wrong_root_writer` for the proof that it does.

    `sqlite3.connect` is instrumented specifically. SQLite opens its file through its own C layer
    and never calls `io.open`/`os.open`, so a tracer without it is blind to every DB write in the
    codebase — which is precisely where this defect class keeps landing.
    """
    out = tmp_path / "trace.json"
    result, events = _run_traced(TRACED_SLICE, out)

    assert result.returncode == 0, (
        "the traced slice itself failed, so the write census is not meaningful:\n"
        f"{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )
    assert out.exists(), (
        "the tracer produced no report — the plugin did not load. "
        f"stdout:\n{result.stdout[-2000:]}"
    )

    if events:
        by_path: dict[str, list[dict]] = {}
        for e in events:
            by_path.setdefault(e["path"], []).append(e)
        detail = "\n".join(
            f"  {p}  x{len(evs)}  [{', '.join(sorted({e['op'] for e in evs}))}]\n"
            f"      first via {next((e['origin'] for e in evs if e['origin']), '?')}"
            for p, evs in sorted(by_path.items(), key=lambda kv: -len(kv[1]))
        )
        pytest.fail(
            f"{len(events)} filesystem write(s) landed outside LAYLA_DATA_DIR and the temp area "
            f"during a traced suite slice:\n{detail}\n\n"
            "A module is resolving its data path without honouring LAYLA_DATA_DIR (usually "
            "`Path(__file__).parent...` with the wrong number of `.parent`s, or `Path.home()` "
            "evaluated at import). Resolve it per call and derive any mkdir from the resolved path."
        )


def test_the_write_tracer_catches_a_brand_new_wrong_root_writer(tmp_path):
    """Proof that the net above is a net and not a mirror.

    A module the guard has never heard of, using the exact recurring idiom (a data path resolved
    at import that ignores LAYLA_DATA_DIR, then mkdir + sqlite3.connect + PRAGMA journal_mode=WAL),
    must be caught with NO edit to the guard.

    The canary writes into a temp directory, not a real protected one: `LAYLA_WRITE_TRACE_ROOTS`
    narrows the sanctioned set so the classification logic is exercised identically without this
    test having to dirty `agent/.layla/` to make its point.
    """
    sanctioned = tmp_path / "sanctioned"
    sanctioned.mkdir()
    pretend_operator_dir = tmp_path / "pretend_operator_home"

    canary_dir = tmp_path / "canary"
    canary_dir.mkdir()
    (canary_dir / "test_canary_wrong_root.py").write_text(
        "import sqlite3\n"
        "from pathlib import Path\n"
        "\n"
        "# The defect, verbatim: resolved at import, ignores LAYLA_DATA_DIR.\n"
        f"_DB = Path(r'{pretend_operator_dir}') / '.layla' / 'canary.db'\n"
        "\n"
        "def test_canary_writes_outside_the_data_dir():\n"
        "    _DB.parent.mkdir(parents=True, exist_ok=True)\n"
        "    con = sqlite3.connect(str(_DB))\n"
        "    con.execute('PRAGMA journal_mode=WAL')\n"
        "    con.close()\n",
        encoding="utf-8",
    )

    out = tmp_path / "canary_trace.json"
    result, events = _run_traced(
        ["test_canary_wrong_root.py"],
        out,
        env_extra={
            "LAYLA_WRITE_TRACE_ROOTS": str(sanctioned),
            "LAYLA_DATA_DIR": str(sanctioned),
        },
        cwd=canary_dir,
    )

    assert result.returncode == 0, f"canary run failed:\n{result.stdout[-3000:]}"

    caught = [e for e in events if "canary" in e["path"]]
    assert caught, (
        "the write tracer did NOT catch a brand-new module using the wrong-root idiom — the net "
        f"has holes. Recorded events: {events}"
    )
    assert any(e["op"] == "sqlite3.connect" for e in caught), (
        "the tracer saw the canary's mkdir but not its sqlite3.connect. sqlite3 is the entry point "
        f"this defect class actually uses; without it the net is decorative. Caught: {caught}"
    )


def test_head_build_writes_its_profile_snapshot_into_the_isolated_dir(monkeypatch, tmp_path):
    """The F1 defect stated as behaviour rather than as a path.

    `write_profile_snapshot` fires on every head build. Driven with LAYLA_DATA_DIR pointed at a temp
    dir, the snapshot must land there — never in `agent/.layla/`.
    """
    from services.personality.frame_modifier import write_profile_snapshot

    operator_profile = AGENT / ".layla" / "layla_profile.json"
    before = operator_profile.read_bytes() if operator_profile.exists() else None

    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path))
    write_profile_snapshot({"name": "isolation-probe", "stat_technical": "9"})

    written = tmp_path / ".layla" / "layla_profile.json"
    assert written.exists(), "the snapshot did not land in LAYLA_DATA_DIR"
    assert "isolation-probe" in written.read_text(encoding="utf-8")

    after = operator_profile.read_bytes() if operator_profile.exists() else None
    assert after == before, (
        "driving a profile snapshot under an isolated LAYLA_DATA_DIR still modified the operator's "
        f"real profile at {operator_profile}"
    )
