"""BL-351 — an installed skill pack must actually RUN.

The install lifecycle was fully live (clone → validate → register → provision a venv) but
``skill_sandbox.run_entry_point`` had ZERO non-test callers. An operator could author a pack,
install it successfully, and it would never execute. Nothing was broken; the last link was
simply absent. These tests drive the wire that closes it.

What is proved here (each by driving the real thing, not by asserting a grep):

  1. manifest → venv → entry_point → stdout → tool result. A real pack (the copy-pasteable
     temp converter from docs/SKILL_PACKS.md) is authored in a temp INSTALLED_DIR, given a
     real venv in a temp ENVS_DIR, and invoked THROUGH THE REGISTRY. 100 C must come back as
     212 F — a value, not merely "returned a dict". A tool that returns {"ok": false} would
     pass a does-not-raise check while the feature is dead.

  2. The stdin contract. ``run_entry_point`` accepted ``stdin_data`` and never forwarded it to
     ``subprocess.run``, so the documented "your entry point can read JSON from stdin" was a
     lie: packs got EOF. test_stdin_payload_reaches_the_pack is the teeth — delete
     ``input=stdin_data`` and it goes red (verified by doing exactly that).

  3. The default-OFF gate. Merely installing a pack — or a kit that installs one — must not
     grant silent code execution. With skill_packs_execute_enabled false, run_skill_pack must
     refuse BEFORE spawning anything.

  4. The two install bugs that stopped docs-compliant packs from installing at all: a pack
     shipping only the PREFERRED ``layla-skill.json`` name, and declared permissions being
     dropped on the way into the registry.

Honesty note carried through the code: the per-pack venv is DEPENDENCY isolation. There is no
filesystem jail and no network namespace — a pack runs as a subprocess at the operator's full
privilege. The tests assert the consent gate, not a containment claim.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

# The temp converter from docs/SKILL_PACKS.md, verbatim in behaviour: read JSON from stdin,
# print JSON to stdout. If the stdin wire is broken this raises/returns the default and the
# asserted value does not appear.
TEMP_CONVERTER_MAIN = '''\
import json
import sys

data = json.load(sys.stdin)
value = data.get("value", 0)
if data.get("direction", "c_to_f") == "c_to_f":
    print(json.dumps({"input_c": value, "output_f": value * 9 / 5 + 32}))
else:
    print(json.dumps({"input_f": value, "output_c": round((value - 32) * 5 / 9, 2)}))
'''


def _write_pack(base: Path, pack_id: str, *, manifest_name: str = "layla-skill.json",
                main_py: str = TEMP_CONVERTER_MAIN, **manifest_extra) -> Path:
    """Author a real pack on disk: manifest + entry point."""
    pack_dir = base / pack_id
    pack_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": pack_id,
        "version": "0.1.0",
        "description": "Converts Celsius to Fahrenheit and vice versa",
        "entry_point": "main.py",
        "dependencies": [],
        "permissions": [],
    }
    manifest.update(manifest_extra)
    (pack_dir / manifest_name).write_text(json.dumps(manifest), encoding="utf-8")
    (pack_dir / "main.py").write_text(main_py, encoding="utf-8")
    return pack_dir


@pytest.fixture(scope="module")
def real_venv(tmp_path_factory):
    """One real venv for the module — creating one costs ~10-20s, and every execution test
    needs the same one. This is not a mock: it is a genuine venv with a genuine interpreter,
    exactly what a provisioned pack gets."""
    import services.skills.skill_sandbox as ss

    envs = tmp_path_factory.mktemp("skill_envs")
    old = ss.ENVS_DIR
    ss.ENVS_DIR = envs
    ok, msg = ss.create_venv("temp-converter")
    if not ok:
        ss.ENVS_DIR = old
        pytest.skip(f"cannot create venv in this environment: {msg}")
    yield envs
    ss.ENVS_DIR = old


@pytest.fixture
def wired(monkeypatch, tmp_path, real_venv):
    """Point INSTALLED_DIR and ENVS_DIR at temp state and turn the execution gate ON.

    Returns the installed-packs base dir. Nothing here touches operator state.
    """
    import runtime_safety
    import services.skills.skill_packs as sp
    import services.skills.skill_sandbox as ss

    installed = tmp_path / "skill_packs_installed"
    installed.mkdir()
    monkeypatch.setattr(sp, "INSTALLED_DIR", installed)
    monkeypatch.setattr(ss, "ENVS_DIR", real_venv)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"skill_packs_execute_enabled": True})
    return installed


def _run_tool(name: str, **kwargs):
    """Invoke through the LIVE registry — proves the tool is registered and callable, which is
    the half of the wire a direct impl import would silently skip."""
    from layla.tools.registry import TOOLS

    assert name in TOOLS, f"{name} is not registered in TOOLS"
    return TOOLS[name]["fn"](**kwargs)


# ============================== 1. the end-to-end wire ==============================
def test_installed_pack_runs_and_returns_its_computed_value(wired):
    """manifest → venv → entry_point → stdout → turn. The whole dead link, driven."""
    _write_pack(wired, "temp-converter")

    out = _run_tool("run_skill_pack", pack="temp-converter",
                    payload={"value": 100, "direction": "c_to_f"})

    assert out["ok"] is True, f"pack did not run: {out}"
    assert out["timed_out"] is False
    assert out["exit_code"] == 0
    # The teeth: the actual computed value, not just "a dict came back".
    assert json.loads(out["stdout"])["output_f"] == 212.0, f"wrong value: {out['stdout']!r}"


def test_stdin_payload_reaches_the_pack(wired):
    """THE TEETH for the one-line fix. ``run_entry_point`` accepted stdin_data and dropped it
    on the floor; the pack's ``json.load(sys.stdin)`` then got EOF. Revert ``input=stdin_data``
    in skill_sandbox.run_entry_point and this goes red — verified by doing exactly that:
    JSONDecodeError('Expecting value: line 1 column 1 (char 0)') on stderr, ok False."""
    _write_pack(wired, "temp-converter")

    out = _run_tool("run_skill_pack", pack="temp-converter",
                    payload={"value": 32, "direction": "f_to_c"})

    assert out["ok"] is True, (
        "the pack could not read its stdin payload — the documented "
        f"'read JSON from stdin' contract is broken: {out['stderr']!r}"
    )
    assert json.loads(out["stdout"])["output_c"] == 0.0


def test_payload_accepts_a_json_string_too(wired):
    """A model emitting a JSON *string* argument must work as well as a dict."""
    _write_pack(wired, "temp-converter")

    out = _run_tool("run_skill_pack", pack="temp-converter",
                    payload='{"value": 100, "direction": "c_to_f"}')

    assert out["ok"] is True, out
    assert json.loads(out["stdout"])["output_f"] == 212.0


def test_run_updates_registry_last_run_and_health(wired, monkeypatch, tmp_path):
    """last_run / health_status existed as columns but no run path ever wrote them, so they
    were frozen at their defaults. Drive the real registry (temp DB) and assert they move."""
    import services.skills.skill_registry as sr

    old_db, old_conn = sr._DB_PATH, sr._conn
    sr._DB_PATH = tmp_path / "registry.db"
    sr._conn = None
    try:
        _write_pack(wired, "temp-converter")
        sr.register(name="temp-converter", version="0.1.0", pack_dir=str(wired / "temp-converter"))
        assert sr.get_pack("temp-converter")["last_run"] == "", "precondition: last_run starts empty"

        out = _run_tool("run_skill_pack", pack="temp-converter", payload={"value": 0})
        assert out["ok"] is True, out

        row = sr.get_pack("temp-converter")
        assert row["last_run"] != "", "last_run still frozen at its default after a real run"
        assert row["health_status"] == "healthy", row
    finally:
        sr.close_db()
        sr._DB_PATH, sr._conn = old_db, old_conn


def test_failing_pack_is_recorded_as_unhealthy(wired, monkeypatch, tmp_path):
    """A pack that raises must surface as ok:false with stderr, and mark the registry error —
    not vanish into a swallowed exception."""
    import services.skills.skill_registry as sr

    old_db, old_conn = sr._DB_PATH, sr._conn
    sr._DB_PATH = tmp_path / "registry.db"
    sr._conn = None
    try:
        _write_pack(wired, "temp-converter", main_py="raise SystemExit('boom')")
        sr.register(name="temp-converter", version="0.1.0", pack_dir=str(wired / "temp-converter"))

        out = _run_tool("run_skill_pack", pack="temp-converter")
        assert out["ok"] is False
        assert "boom" in out["stderr"]

        assert sr.get_pack("temp-converter")["health_status"] == "error"
    finally:
        sr.close_db()
        sr._DB_PATH, sr._conn = old_db, old_conn


# ============================== 2. the security gate ==============================
def test_execution_is_off_by_default(monkeypatch, tmp_path, real_venv):
    """DEFAULT-OFF. Installing a pack — or a kit that installs one — must not grant silent RCE.

    The config default is False, so a config that never mentions the key must refuse. The pack
    here is fully installed and has a working venv: the ONLY thing stopping it is the gate.
    """
    import runtime_safety
    import services.skills.skill_packs as sp
    import services.skills.skill_sandbox as ss

    installed = tmp_path / "skill_packs_installed"
    installed.mkdir()
    monkeypatch.setattr(sp, "INSTALLED_DIR", installed)
    monkeypatch.setattr(ss, "ENVS_DIR", real_venv)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {})  # key absent entirely
    _write_pack(installed, "temp-converter")

    out = _run_tool("run_skill_pack", pack="temp-converter", payload={"value": 100})

    assert out["ok"] is False
    assert "skill_packs_execute_enabled" in out["error"]
    assert "stdout" not in out, "the gate must refuse BEFORE spawning anything"


def test_schema_default_for_the_gate_is_false():
    """The refusal above is only meaningful if the shipped default is off."""
    from config_schema import EDITABLE_SCHEMA

    entry = next(e for e in EDITABLE_SCHEMA if e["key"] == "skill_packs_execute_enabled")
    assert entry["default"] is False


def test_gate_key_is_protected_from_remote_writes():
    """Same class as plugins_enabled: a remote /settings write must not be able to flip the
    code-execution consent gate on."""
    from routers.settings import _REMOTE_PROTECTED_KEYS

    assert "skill_packs_execute_enabled" in _REMOTE_PROTECTED_KEYS


def test_tool_flows_through_the_dangerous_tool_gates():
    """Registration alone is not protection — it must reach the approval + audit path."""
    import runtime_safety
    from layla.tools.registry import TOOLS
    from services.tools.tool_permissions import _EXEC_TOOLS

    assert "run_skill_pack" in runtime_safety.DANGEROUS_TOOLS
    assert "run_skill_pack" in _EXEC_TOOLS, "must require allow_run in the executor backstop"
    meta = TOOLS["run_skill_pack"]
    assert meta["dangerous"] is True and meta["require_approval"] is True
    assert meta["risk_level"] == "high"


def test_permission_check_refuses_without_allow_run():
    """The executor backstop: a turn without allow_run must not be able to execute a pack."""
    from services.tools.tool_permissions import (
        check_tool_permission,
        clear_tool_permissions,
        set_tool_permissions,
    )

    try:
        set_tool_permissions(allow_write=True, allow_run=False)
        ok, reason = check_tool_permission("run_skill_pack")
        assert ok is False and "allow_run" in reason
        set_tool_permissions(allow_write=False, allow_run=True)
        assert check_tool_permission("run_skill_pack")[0] is True
    finally:
        clear_tool_permissions()


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", "pack;rm"])
def test_bad_pack_ids_are_refused(wired, bad):
    out = _run_tool("run_skill_pack", pack=bad)
    assert out["ok"] is False
    assert "stdout" not in out


def test_args_reach_argv_and_a_bare_string_is_not_shredded(wired):
    """A model that passes args="--verbose" instead of ["--verbose"] must not have the string
    iterated into one argv entry per character."""
    _write_pack(wired, "temp-converter",
                main_py="import sys, json; print(json.dumps(sys.argv[1:]))")

    out = _run_tool("run_skill_pack", pack="temp-converter", args=["--verbose", "2"])
    assert json.loads(out["stdout"]) == ["--verbose", "2"], out

    out = _run_tool("run_skill_pack", pack="temp-converter", args="--verbose")
    assert json.loads(out["stdout"]) == ["--verbose"], f"bare string was shredded: {out}"


def test_unknown_pack_is_a_clean_error(wired):
    out = _run_tool("run_skill_pack", pack="not-installed")
    assert out["ok"] is False and "not installed" in out["error"]


def test_pack_without_entry_point_is_refused(wired):
    """validate_manifest requires an entry_point on install, but a directory dropped in by hand
    (or a manifest edited after install) has not been through it."""
    pack_dir = wired / "broken"
    pack_dir.mkdir()
    (pack_dir / "layla-skill.json").write_text(json.dumps({"name": "broken", "version": "0.1.0"}),
                                               encoding="utf-8")
    out = _run_tool("run_skill_pack", pack="broken")
    assert out["ok"] is False and "entry_point" in out["error"]


# ============================== 3. discovery ==============================
def test_list_skill_packs_is_safe_with_no_packs_installed(monkeypatch, tmp_path):
    """This tool lands in the registry smoke test's DRIVEN set and WILL be invoked with no
    args. It must not raise, must return a dict, and — the part meta flags cannot see — must
    not CREATE the installed dir as a side effect of being asked a read-only question."""
    import services.skills.skill_packs as sp

    missing = tmp_path / "does_not_exist"
    monkeypatch.setattr(sp, "INSTALLED_DIR", missing)

    out = _run_tool("list_skill_packs")

    assert isinstance(out, dict) and out["ok"] is True
    assert out["packs"] == [] and out["count"] == 0
    assert not missing.exists(), "a read-only listing must not materialise operator directories"


def test_list_skill_packs_reports_installed_packs(wired):
    _write_pack(wired, "temp-converter")
    out = _run_tool("list_skill_packs")
    assert out["count"] == 1
    pack = out["packs"][0]
    assert pack["id"] == "temp-converter"
    assert pack["entry_point"] == "main.py" and pack["runnable"] is True
    assert out["execution_enabled"] is True


def test_list_reports_when_execution_is_disabled(monkeypatch, tmp_path):
    """Honesty: listing a pack while it cannot run must say so rather than implying capability."""
    import runtime_safety
    import services.skills.skill_packs as sp

    installed = tmp_path / "installed"
    installed.mkdir()
    _write_pack(installed, "temp-converter")
    monkeypatch.setattr(sp, "INSTALLED_DIR", installed)
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {})

    out = _run_tool("list_skill_packs")
    assert out["execution_enabled"] is False
    assert "skill_packs_execute_enabled" in out["note"]


def test_prompt_summary_names_the_pack_and_the_tool(wired):
    """Without this line in the decision prompt the model never learns a pack exists and will
    never pick run_skill_pack — the wire would be live but unreachable."""
    from services.skills.skill_packs import installed_summary_for_prompt

    _write_pack(wired, "temp-converter")
    text = installed_summary_for_prompt({"skill_packs_execute_enabled": True})

    assert "temp-converter" in text
    assert "run_skill_pack" in text, "the summary must name the tool that runs a pack"


def test_prompt_summary_is_silent_when_execution_is_disabled(wired):
    """Do not advertise a capability that would only refuse at call time."""
    from services.skills.skill_packs import installed_summary_for_prompt

    _write_pack(wired, "temp-converter")
    assert installed_summary_for_prompt({}) == ""
    assert installed_summary_for_prompt({"skill_packs_execute_enabled": False}) == ""


# ============================== 4. the two install bugs ==============================
def _fake_clone(monkeypatch, payload_writer):
    """Replace git clone with a local materialisation, so the install path is driven for real
    without a network. Everything after the clone — manifest discovery, validation, pinning,
    registration — is the genuine code path.

    Rebind the module's ``subprocess`` ATTRIBUTE, never ``subprocess.run`` itself.
    ``monkeypatch.setattr(sp.subprocess, "run", ...)`` looks local but ``sp.subprocess`` *is*
    the global module object, so it hijacks every subprocess call in the process for the
    duration of the test. It did: a hardware probe's ``nvidia-smi --query-gpu=name,vram
    --format=csv,noheader,nounits`` landed here, this helper read its last argv element as a
    clone destination, and wrote skill-pack files into `agent/name/`, `agent/vram/` and
    `agent/--format=csv,noheader,nounits/` in the real working tree. Scoping the patch to the
    module attribute confines it; the destination assert makes any escape loud instead of
    silently littering the repo.
    """
    import services.skills.skill_packs as sp

    installed_root = sp.INSTALLED_DIR.resolve()

    class _FakeSubprocess:
        @staticmethod
        def run(cmd, *a, **kw):
            dest = Path(cmd[-1])
            assert dest.resolve().is_relative_to(installed_root), (
                f"fake clone asked to write outside the temp install dir: {dest} — the patch "
                "has escaped its module scope"
            )
            payload_writer(dest)
            class _R:
                returncode = 0
            return _R()

    monkeypatch.setattr(sp, "subprocess", _FakeSubprocess)


def test_pack_shipping_only_the_preferred_manifest_name_installs(monkeypatch, tmp_path):
    """BUG: the existence pre-check accepted ONLY ``manifest.json`` while the docs call
    ``layla-skill.json`` PREFERRED and ``find_manifest`` accepts both — so a docs-compliant
    pack was rejected with "missing manifest.json" before load_manifest (which would have
    accepted it) ever ran."""
    import services.skills.skill_packs as sp
    import services.skills.skill_registry as sr

    installed = tmp_path / "installed"
    installed.mkdir()
    monkeypatch.setattr(sp, "INSTALLED_DIR", installed)
    _fake_clone(monkeypatch, lambda dest: _write_pack(dest.parent, dest.name,
                                                     manifest_name="layla-skill.json"))

    old_db, old_conn = sr._DB_PATH, sr._conn
    sr._DB_PATH = tmp_path / "registry.db"
    sr._conn = None
    try:
        out = sp.install_from_git("https://example.invalid/temp-converter.git", name="temp-converter")
        assert out["ok"] is True, f"a layla-skill.json-only pack must install: {out}"
    finally:
        sr.close_db()
        sr._DB_PATH, sr._conn = old_db, old_conn


def test_legacy_manifest_name_still_installs(monkeypatch, tmp_path):
    """The fix must widen what is accepted, not swap one hardcoded name for another."""
    import services.skills.skill_packs as sp
    import services.skills.skill_registry as sr

    installed = tmp_path / "installed"
    installed.mkdir()
    monkeypatch.setattr(sp, "INSTALLED_DIR", installed)
    _fake_clone(monkeypatch, lambda dest: _write_pack(dest.parent, dest.name,
                                                     manifest_name="manifest.json"))

    old_db, old_conn = sr._DB_PATH, sr._conn
    sr._DB_PATH = tmp_path / "registry.db"
    sr._conn = None
    try:
        out = sp.install_from_git("https://example.invalid/legacy.git", name="legacy")
        assert out["ok"] is True, out
    finally:
        sr.close_db()
        sr._DB_PATH, sr._conn = old_db, old_conn


def test_a_pack_with_no_manifest_at_all_is_still_rejected(monkeypatch, tmp_path):
    """The widened check must not become an accept-anything check."""
    import services.skills.skill_packs as sp

    installed = tmp_path / "installed"
    installed.mkdir()
    monkeypatch.setattr(sp, "INSTALLED_DIR", installed)

    def _bare(dest: Path):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "README.md").write_text("no manifest here", encoding="utf-8")

    _fake_clone(monkeypatch, _bare)
    out = sp.install_from_git("https://example.invalid/bare.git", name="bare")
    assert out["ok"] is False and "manifest" in out["error"]


def test_declared_permissions_reach_the_registry(monkeypatch, tmp_path):
    """BUG: install called register(...) without permissions=, so a pack's declared permissions
    were silently dropped and the column always stored "[]" — a permissions audit would report
    "none declared" for a pack that asked for network + file writes."""
    import services.skills.skill_packs as sp
    import services.skills.skill_registry as sr

    installed = tmp_path / "installed"
    installed.mkdir()
    monkeypatch.setattr(sp, "INSTALLED_DIR", installed)
    _fake_clone(monkeypatch, lambda dest: _write_pack(
        dest.parent, dest.name, permissions=["network", "write_file"]))

    old_db, old_conn = sr._DB_PATH, sr._conn
    sr._DB_PATH = tmp_path / "registry.db"
    sr._conn = None
    try:
        out = sp.install_from_git("https://example.invalid/perms.git", name="perms")
        assert out["ok"] is True, out
        assert sr.get_pack("perms")["permissions"] == ["network", "write_file"], (
            "declared permissions were dropped between the manifest and the registry"
        )
    finally:
        sr.close_db()
        sr._DB_PATH, sr._conn = old_db, old_conn


# ===================================================================
# B1 — entry-point confinement was a STRING PREFIX test
# ===================================================================
class TestEntryPointConfinement:
    """``run_entry_point`` guarded the entry point with
    ``str(entry).startswith(str(pack_dir.resolve()))``. A sibling directory whose NAME
    EXTENDS the pack dir satisfies that: pack "weather" + entry_point
    "../weather-extra/payload.py" resolves to <base>/weather-extra/payload.py, which
    startswith "<base>/weather". Reproduced before fixing — it EXECUTED (ok=True, exit=0)
    and wrote a marker file outside the pack directory. The guard was real, just
    prefix-matched: the control "../unrelated/p.py" was correctly blocked.

    Real shape of the bug: pack A executes pack B's code — installed, but never meant to
    run, and never consented to. docs/SKILL_PACKS.md asserts the resolved entry point must
    fall inside the pack directory; these make the code true rather than softening the doc.

    Fix is the idiom already used correctly in layla/tools/impl/general.py:
    ``is_relative_to`` compares path COMPONENTS, so "weather-extra" is not "weather/...".
    """

    def test_name_extending_sibling_cannot_be_executed(self, wired, tmp_path):
        """THE TEETH. Restore the startswith() check and this goes red — verified by doing
        exactly that: ok=True, exit_code=0, stdout='SIBLING PAYLOAD EXECUTED', and the
        escape marker written outside the pack dir."""
        import services.skills.skill_sandbox as ss

        pack_dir = _write_pack(wired, "temp-converter")
        sibling = wired / "temp-converter-extra"
        sibling.mkdir()
        marker = tmp_path / "ESCAPED.txt"
        (sibling / "payload.py").write_text(
            "open(r'%s','w').write('pwned')\nprint('SIBLING PAYLOAD EXECUTED')\n" % marker,
            encoding="utf-8")

        out = ss.run_entry_point("temp-converter", pack_dir,
                                 "../temp-converter-extra/payload.py", timeout_seconds=30)

        assert out["ok"] is False, "entry point escaped the pack directory and RAN: %s" % (out,)
        assert "escapes pack directory" in out["stderr"], out
        assert not marker.exists(), (
            "the out-of-pack payload executed — it wrote a file outside the pack directory")

    def test_unrelated_sibling_is_still_blocked(self, wired):
        """Control: the guard was never entirely absent. Keeps the fix honest — if someone
        'fixes' this by deleting the check, this fails too."""
        import services.skills.skill_sandbox as ss

        pack_dir = _write_pack(wired, "temp-converter")
        unrelated = wired / "unrelated"
        unrelated.mkdir()
        (unrelated / "p.py").write_text("print('unrelated ran')\n", encoding="utf-8")

        out = ss.run_entry_point("temp-converter", pack_dir, "../unrelated/p.py",
                                 timeout_seconds=30)
        assert out["ok"] is False and "escapes pack directory" in out["stderr"], out

    def test_a_legitimate_in_pack_entry_point_still_runs(self, wired):
        """The half a confinement fix usually breaks: tightening until nothing runs is not a
        fix. A normal pack must still execute and return its value."""
        _write_pack(wired, "temp-converter")
        out = _run_tool("run_skill_pack", pack="temp-converter",
                        payload={"value": 100, "direction": "c_to_f"})
        assert out["ok"] is True, "legitimate pack stopped running: %s" % (out,)
        assert json.loads(out["stdout"])["output_f"] == 212.0

    def test_a_nested_subdirectory_entry_point_still_runs(self, wired):
        """``is_relative_to`` must not reject legitimate nesting — packs put code in src/."""
        import services.skills.skill_sandbox as ss

        pack_dir = _write_pack(wired, "temp-converter")
        (pack_dir / "src").mkdir(exist_ok=True)
        (pack_dir / "src" / "deep.py").write_text("print('NESTED OK')\n", encoding="utf-8")

        out = ss.run_entry_point("temp-converter", pack_dir, "src/deep.py", timeout_seconds=30)
        assert out["ok"] is True, "a legitimate nested entry point was rejected: %s" % (out,)
        assert "NESTED OK" in out["stdout"]


# ===================================================================
# B2 — installing ran third-party build code with Layla's secrets
# ===================================================================
class TestInstallPathDoesNotLeakSecrets:
    """``install_dependencies`` ran a REAL pip install and passed no ``env=``, so a
    dependency's PEP 517 build backend inherited Layla's whole environment. Proven with
    canaries before the fix: a spec ``evilpkg @ file:///...`` executed at
    prepare_metadata_for_build_wheel and read GITHUB_TOKEN=ghp_CANARY... and
    OPENAI_API_KEY=sk-CANARY... — 87 environment variables in total.

    Meanwhile ``run_entry_point`` had always built a strict allowlist. So with
    skill_venv_enabled=true and skill_packs_execute_enabled=false — the combination the
    docs framed as safe — INSTALLING a pack already ran third-party code with the
    operator's secrets. After the fix the same canary sees 15 variables and neither token.
    """

    def test_pip_install_is_given_the_filtered_env(self, monkeypatch):
        """THE TEETH: delete ``env=_filtered_env(...)`` from install_dependencies and the
        captured env is None → this fails. Asserts the real call's kwargs."""
        import services.skills.skill_sandbox as ss

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_CANARY_must_not_leak")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-CANARY_must_not_leak")

        captured = {}

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        def _fake_run(cmd, **kwargs):
            captured.update(kwargs)
            return _Result()

        monkeypatch.setattr(ss.subprocess, "run", _fake_run)
        monkeypatch.setattr(ss.Path, "exists", lambda self: True)

        ok, _msg = ss.install_dependencies("victim", ["requests==2.31.0"])
        assert ok is True

        env = captured.get("env")
        assert env is not None, (
            "pip install inherited Layla's full environment — a dependency's build backend "
            "runs during install and would see every operator secret")
        assert "GITHUB_TOKEN" not in env, "operator secret leaked to dependency build code"
        assert "OPENAI_API_KEY" not in env, "operator secret leaked to dependency build code"
        assert "PATH" in env, "pip cannot run without PATH — the allowlist is too tight"

    def test_run_path_and_install_path_share_one_allowlist(self, monkeypatch):
        """The two paths drifting apart is what created this bug. A secret must be withheld
        from both, and deny-by-default means a NEW secret needs no code change."""
        import services.skills.skill_sandbox as ss

        monkeypatch.setenv("SOME_BRAND_NEW_SECRET_2026", "leak-me")
        for env in (ss._filtered_env(), ss._filtered_env(ss._PIP_EXTRA_KEYS)):
            assert "SOME_BRAND_NEW_SECRET_2026" not in env

    def test_private_index_url_is_not_handed_to_build_code(self, monkeypatch):
        """PIP_INDEX_URL routinely embeds a token; handing it to an untrusted build backend
        is the exact leak the allowlist exists to stop."""
        import services.skills.skill_sandbox as ss

        monkeypatch.setenv("PIP_INDEX_URL", "https://user:tok3n@private.example/simple")
        assert "PIP_INDEX_URL" not in ss._filtered_env(ss._PIP_EXTRA_KEYS)


class TestDependencyPinning:
    """``_unpinned_dependencies`` treated any ``name @ url`` as pinned, so a MUTABLE git
    reference passed the supply-chain gate while the docstring promised an "immutable
    artifact". A branch re-resolves to whatever was pushed last — the substitution the
    check exists to prevent."""

    @pytest.mark.parametrize("spec", [
        "pkg @ git+https://github.com/a/b.git",
        "pkg @ git+https://github.com/a/b.git@main",
        "pkg @ git+https://github.com/a/b.git@v1.2.3",
    ])
    def test_mutable_vcs_refs_are_unpinned(self, spec):
        from services.skills.skill_packs import _unpinned_dependencies
        assert _unpinned_dependencies([spec]) == [spec], (
            "%r re-resolves on reinstall but was accepted as pinned" % spec)

    @pytest.mark.parametrize("spec", [
        "requests==2.31.0",
        "pkg @ https://host/pkg-1.0.tar.gz",
        "pkg @ git+https://github.com/a/b.git@" + "a" * 40,
    ])
    def test_genuinely_pinned_specs_still_pass(self, spec):
        from services.skills.skill_packs import _unpinned_dependencies
        assert _unpinned_dependencies([spec]) == [], "%r is pinned but was rejected" % spec

    @pytest.mark.parametrize("spec", ["requests", "requests>=2.0", "requests~=2.0"])
    def test_floating_versions_are_still_unpinned(self, spec):
        from services.skills.skill_packs import _unpinned_dependencies
        assert _unpinned_dependencies([spec]) == [spec]


# ===================================================================
# B5 — a failed install left a phantom pack in the listing
# ===================================================================
class TestFailedInstallLeavesNoPhantom:
    def test_manifest_less_directory_is_not_listed_as_a_pack(self, monkeypatch, tmp_path):
        """``list_installed_readonly`` appended EVERY directory regardless of manifest, so
        the leftovers of a failed install surfaced in list_skill_packs as a pack the
        operator never installed. The older ``list_installed`` skipped these."""
        import services.skills.skill_packs as sp

        installed = tmp_path / "installed"
        installed.mkdir()
        (installed / "half-written").mkdir()           # failed install leftover
        (installed / "half-written" / ".git").mkdir()  # clone happened, manifest never landed
        _write_pack(installed, "real-pack")
        monkeypatch.setattr(sp, "INSTALLED_DIR", installed)

        ids = [p["id"] for p in sp.list_installed_readonly()]
        assert "half-written" not in ids, "phantom pack surfaced in the listing: %s" % (ids,)
        assert "real-pack" in ids, "the real pack disappeared: %s" % (ids,)

    def test_rollback_falls_back_when_rollback_install_returns_failure(self, monkeypatch, tmp_path):
        """THE ROOT CAUSE. ``_rollback_cleanup``'s documented "can never leave a half-written
        pack behind" fallback sat in an ``except``, but ``rollback_install`` catches its own
        rmtree failure and signals it by RETURN VALUE — so on the case that actually happens
        (Windows read-only .git objects defeating rmtree) the fallback never ran."""
        import services.skills.skill_packs as sp
        import services.skills.skill_rollback as sr

        dest = tmp_path / "installed" / "doomed"
        dest.mkdir(parents=True)
        (dest / "leftover.txt").write_text("x", encoding="utf-8")

        # Exactly what rollback_install does when rmtree loses: report, don't raise.
        monkeypatch.setattr(sr, "rollback_install", lambda name, d=None: {
            "ok": False, "actions": ["Failed to remove pack directory: [WinError 5]"]})

        sp._rollback_cleanup("doomed", dest)

        assert not dest.exists(), (
            "rollback reported failure by return value and the rmtree fallback never ran — "
            "a half-written pack survived on disk")

    def test_rollback_removes_read_only_files(self, monkeypatch, tmp_path):
        """The concrete Windows case: git objects are read-only, so a plain rmtree raises
        PermissionError. The fallback must clear the write bit."""
        import os
        import stat

        import services.skills.skill_packs as sp
        import services.skills.skill_rollback as sr

        dest = tmp_path / "installed" / "ro"
        (dest / ".git").mkdir(parents=True)
        obj = dest / ".git" / "object"
        obj.write_text("x", encoding="utf-8")
        os.chmod(obj, stat.S_IREAD)

        monkeypatch.setattr(sr, "rollback_install", lambda name, d=None: {"ok": False, "actions": []})
        try:
            sp._rollback_cleanup("ro", dest)
            assert not dest.exists(), "read-only pack files defeated rollback"
        finally:
            if obj.exists():
                os.chmod(obj, stat.S_IWRITE)


class TestEntryPointContractIsEnforcedAndDocumented:
    """The manifest validator must reject exactly what the runtime blocks, and the docs must
    describe the code that exists.

    Adversarial verification of the confinement fix found the documented contract ("Relative
    path to the Python script. No ``..`` or absolute paths allowed.") false in two directions,
    both of which reached ``run_entry_point``:

      - DRIVE-ABSOLUTE ``C:\\Windows\\x.py`` is absolute but begins with neither "/" nor "\\",
        so the leading-slash test ACCEPTED it. The run-time confinement check blocked it, so
        this was never a live bypass — but a validator that accepts what the runtime rejects is
        a defense-in-depth gap, and the doc sentence was simply untrue.
      - A NUL byte survived the validator AND a JSON round-trip, then raised ValueError — not
        OSError — inside ``Path.resolve()``. ``.resolve()`` sat on the line ABOVE the try, so
        the handler never saw it and the tool call CRASHED instead of returning the standard
        error dict every other failure path returns.

    Separately, every ``from services.skill_*`` import in docs/SKILL_PACKS.md named a module
    path that does not exist (the package is ``services.skills.*``), and the module table listed
    ``services/skill_discovery.py`` — a file present nowhere in the repo. Documentation that
    cannot be copy-pasted is documentation nobody ran; the last two tests make that a failure
    rather than a discovery.
    """

    # Every shape the runtime confinement blocks. The validator must agree with it.
    @pytest.mark.parametrize("entry_point", [
        "../x.py",              # parent traversal
        "/etc/passwd.py",       # posix-absolute
        "\\windows\\x.py",      # backslash-absolute
        "C:\\Windows\\x.py",    # DRIVE-absolute — was ACCEPTED before this fix
        "a\x00b.py",            # NUL — was ACCEPTED, then crashed at run time
    ])
    def test_validator_rejects_every_shape_the_runtime_blocks(self, entry_point):
        from services.skills.skill_manifest import validate_manifest

        errors = validate_manifest({
            "name": "p", "version": "1.0.0", "description": "d", "entry_point": entry_point,
        })
        assert errors, (
            "validate_manifest ACCEPTED %r, which the run-time confinement check rejects — the "
            "manifest contract and the runtime disagree" % (entry_point,))
        assert any("entry_point" in e for e in errors), errors

    @pytest.mark.parametrize("entry_point", ["main.py", "src/deep.py", "./main.py"])
    def test_validator_still_accepts_legitimate_relative_paths(self, entry_point):
        """Control. Over-tightening the validator would reject real packs — the failure mode a
        naive 'reject anything suspicious' fix produces."""
        from services.skills.skill_manifest import validate_manifest

        errors = validate_manifest({
            "name": "p", "version": "1.0.0", "description": "d", "entry_point": entry_point,
        })
        assert not errors, "validate_manifest rejected a legitimate entry point %r: %s" % (
            entry_point, errors)

    def test_nul_entry_point_returns_error_dict_instead_of_crashing(self, wired, monkeypatch):
        """THE TEETH for the handler fix. Move ``.resolve()`` back above the try (or drop
        ValueError from the except clause) and this goes red with an uncaught
        ``ValueError: stat: embedded null character in path``.

        The venv check short-circuits before the confinement code, so it is bypassed here to
        reach the path under test — otherwise this passes for the wrong reason.
        """
        import services.skills.skill_sandbox as ss

        pack_dir = _write_pack(wired, "temp-converter")
        monkeypatch.setattr(ss, "_venv_python", lambda name: Path(sys.executable))

        out = ss.run_entry_point("temp-converter", pack_dir, "a\x00b.py", timeout_seconds=30)

        assert out["ok"] is False
        assert out["exit_code"] == -1
        assert "invalid entry point path" in out["stderr"], out

    def test_documented_import_paths_actually_import(self):
        """Doc-rot guard. Every ``from services.skills.X import`` in SKILL_PACKS.md must resolve
        — all five previously raised ModuleNotFoundError verbatim."""
        import importlib
        import re

        doc = (_AGENT_DIR / "docs" / "SKILL_PACKS.md").read_text(encoding="utf-8")
        modules = sorted(set(re.findall(r"from (services\.[a-z_.]+) import", doc)))
        assert modules, "no documented imports found — did the doc structure change?"
        broken = []
        for mod in modules:
            try:
                importlib.import_module(mod)
            except Exception as exc:  # noqa: BLE001 — any import failure is the defect
                broken.append("%s (%s)" % (mod, type(exc).__name__))
        assert not broken, "SKILL_PACKS.md documents import paths that do not exist: %s" % broken

    def test_docs_do_not_name_a_module_that_does_not_exist(self):
        """The module table listed services/skill_discovery.py, which exists nowhere in the
        repo (only a stale .pyc). Every services/skills/*.py the doc names must be a real file."""
        import re

        doc = (_AGENT_DIR / "docs" / "SKILL_PACKS.md").read_text(encoding="utf-8")
        named = sorted(set(re.findall(r"`(services/skills/[a-z_]+\.py)`", doc)))
        assert named, "no module table entries found — did the doc structure change?"
        missing = [p for p in named if not (_AGENT_DIR / p).is_file()]
        assert not missing, "SKILL_PACKS.md documents modules that do not exist: %s" % missing
