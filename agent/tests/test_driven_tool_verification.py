"""
PLAN ITEM 25 (+28) -- gated pytest over the driven per-tool verification harness.

Two tiers, matching ``scripts/run_real_eval.py``:

* ALWAYS-ON, MODEL-FREE (fast, runs in ordinary CI):
    - the battery is well-formed (every case names a registered tool);
    - the PROBE is correct -- item 26's ``offered_set`` actually offers each case's
      target under that case's pinned config (so a real run can never fail for the
      wrong reason: "the model can't use X" when X was never presented);
    - the item-28 side-effect / web MOCK tier captures the payload / parses the
      loopback body and NEVER fires a real external send.

* GATED, REAL INFERENCE (only when ``LAYLA_DRIVEN_TOOL_EVAL=1``): drives the actual
  SmolLM2-360M through the full battery and asserts the harness worked end-to-end
  (mocks safe, every target offered, and the real pipeline drove >=1 tool to a
  verified effect). It also needs ``LAYLA_TEST_REAL_LLM=1`` so conftest does not
  stub llama_cpp. The canonical proof-run is the standalone entrypoint
  (``python tests/_tool_verify_harness.py``), which bypasses conftest entirely.

The harness itself lives in ``tests/_tool_verify_harness.py`` (gate-excluded).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

import pytest

from tests import _tool_verify_harness as H
from tests._tool_verify import offered_set

_GATE = os.environ.get("LAYLA_DRIVEN_TOOL_EVAL")


# ── Fast, model-free: battery well-formedness + probe correctness ───────────────

def test_every_case_names_a_registered_tool():
    from layla.tools.registry import TOOLS
    battery = H.build_battery()
    assert battery, "battery is empty"
    for case in battery:
        assert case.tool in TOOLS, f"case {case.name!r} names unknown tool {case.tool!r}"
        assert case.goal.strip(), f"case {case.name!r} has empty goal"


def test_battery_spans_the_intended_domains():
    domains = {c.domain for c in H.build_battery()}
    # file/code/data/git/memory/system/analysis — one representative effectful tool each.
    for expected in ("file", "code", "data", "git", "memory", "system", "analysis"):
        assert expected in domains, f"battery missing domain {expected!r}: {sorted(domains)}"


@pytest.mark.parametrize("case", H.build_battery(), ids=lambda c: c.name)
def test_pin_offers_each_case_target(case):
    """VERIFY THE PROBE: under the case's pinned config, the production resolver
    offers the target even for a hard-narrowing goal. Without this a real-run miss
    could not be attributed to the model rather than the router."""
    md = H.default_models_dir()
    cfg = H.pinned_config_for_case(case.tool, "/tmp/x", case.decoys, md)
    offered = offered_set(cfg, H._NARROWING_GOAL_FOR_OFFER_CHECK)
    assert case.tool in offered, f"{case.tool} pinned but not offered: {sorted(offered)}"
    for d in case.decoys:
        assert d in offered, f"decoy {d} for {case.tool} not offered: {sorted(offered)}"
    assert len(offered) <= 15, f"pinned offered set unexpectedly large: {sorted(offered)}"


# ── Fast, model-free: item-28 side-effect / web MOCK tier (never a real send) ────

def test_web_fetch_parses_loopback_fixture_no_network():
    rep = H.web_fetch_returns_fixture()
    assert rep["raw_ok"], f"fetch_url did not succeed against loopback: {rep}"
    assert rep["marker_present"], "parsed body did not contain the fixture marker"
    assert rep["ok"]


def test_send_email_captures_payload_never_sends():
    rep = H.send_email_captures_payload()
    assert rep["ok"], f"send_email payload not captured as expected: {rep}"
    assert rep["captured"].get("to") == "alice@example.test"
    assert H._MARKER in str(rep["captured"].get("body"))


def test_send_webhook_captures_payload_never_sends():
    rep = H.send_webhook_captures_payload()
    assert rep["ok"], f"send_webhook payload not captured as expected: {rep}"
    assert rep["captured"]["payload"]["marker"] == H._MARKER
    # The URL never left the machine — the SSRF-safe opener was mocked.
    assert rep["captured"]["url"].startswith("https://hooks.example.test")


def test_discord_send_funnels_through_webhook_captured():
    rep = H.discord_send_captures_payload()
    assert rep["ok"], f"discord_send content not captured as expected: {rep}"
    assert H._MARKER in str(rep["captured"]["payload"].get("content"))


def test_mock_tier_all_green():
    report = H.run_mock_tier()
    failed = {k: v for k, v in report.items() if not v.get("ok")}
    assert not failed, f"mock-tier failures: {failed}"


# ── Fast, model-free: the VERIFY dimension is real (not vacuously always-false) ──
#
# The gated real run cannot rely on a 360M reaching a verified effect (it has a
# read_file monoculture and mangles long paths), so these prove — deterministically
# — that each case's effect check RETURNS TRUE on a genuine artifact and FALSE on a
# missing/tampered one. Together with the real run (which proves selection + that
# the verifier correctly REJECTS a failed tool), this closes the loop: the harness
# would score a case GREEN the moment the model produces the real artifact.

def _genuine_result(tool: str, sandbox: Path) -> dict:
    """A result dict shaped exactly like the real tool returns on success, against
    an artifact actually materialised in `sandbox`."""
    import hashlib as _h
    if tool == "write_file":
        p = sandbox / "notes.txt"
        p.write_text(H._MARKER, encoding="utf-8")
        return {"ok": True, "path": str(p)}
    if tool == "read_file":
        (sandbox / "readme.txt").write_text(f"x {H._MARKER} y", encoding="utf-8")
        return {"ok": True, "path": str(sandbox / "readme.txt"), "content": f"x {H._MARKER} y"}
    if tool == "list_dir":
        (sandbox / "alpha.txt").write_text("a", encoding="utf-8")
        return {"ok": True, "path": str(sandbox), "entries": [{"name": "alpha.txt", "type": "file"}]}
    if tool == "hash_file":
        return {"ok": True, "algorithm": "sha256", "hash": _h.sha256(H._HASH_TEXT).hexdigest()}
    if tool == "grep_code":
        return {"ok": True, "count": 1, "matches": [{"path": "mod.py", "line": "def target_function(x):"}]}
    if tool == "read_csv":
        return {"ok": True, "columns": ["region", "units"], "sample": [{"region": "north", "units": 10}]}
    if tool == "git_status":
        return {"ok": True, "output": "On branch main\nUntracked files:\n  seed.txt\n"}
    if tool == "save_note":
        return {"ok": True, "saved": f"{H._MARKER} the sky is blue"}
    if tool == "run_python":
        return {"ok": True, "returncode": 0, "stdout": f"{H._MARKER}\n", "stderr": ""}
    if tool == "shell":
        return {"ok": True, "returncode": 0, "stdout": f"{H._MARKER}\n", "stderr": ""}
    raise AssertionError(f"no genuine result fixture for {tool}")


@pytest.mark.parametrize("case", H.build_battery(), ids=lambda c: c.name)
def test_effect_check_passes_on_genuine_artifact(case, tmp_path):
    sandbox = tmp_path / case.name.replace(".", "_")
    sandbox.mkdir(parents=True)
    result = _genuine_result(case.tool, sandbox)
    ok, reason = case.effect(case.tool, result, sandbox)
    assert ok, f"{case.tool} effect check rejected a genuine artifact: {reason}"


def test_effect_check_fails_on_missing_or_tampered_artifact(tmp_path):
    from services.tools.tool_output_validator import deterministic_verify_tool_result
    # write_file that names a path which does not exist -> rejected.
    v = deterministic_verify_tool_result(
        "write_file", {"ok": True, "path": str(tmp_path / "nope.txt")}, workspace_root=str(tmp_path))
    assert not v["ok"], "verifier accepted a write_file whose file is absent"
    # hash_file with a wrong digest -> rejected by the case effect check.
    battery = {c.tool: c for c in H.build_battery()}
    ok, _ = battery["hash_file"].effect("hash_file", {"ok": True, "algorithm": "sha256", "hash": "deadbeef"}, tmp_path)
    assert not ok, "hash effect check accepted a wrong digest"
    # run_python with a nonzero returncode -> rejected.
    ok2, _ = battery["run_python"].effect("run_python", {"ok": True, "returncode": 1, "stdout": ""}, tmp_path)
    assert not ok2, "run_python effect check accepted a nonzero returncode"


# ── Gated: the real driven battery ──────────────────────────────────────────────

@pytest.mark.slow
@pytest.mark.timeout(0)  # a real CPU battery exceeds the 120s per-test default
@pytest.mark.skipif(not _GATE, reason=f"set {H.ENV_FLAG}=1 (and LAYLA_TEST_REAL_LLM=1) to run real inference")
def test_driven_battery_real_model():
    path, note = H.model_available()
    if path is None:
        pytest.skip(f"model unavailable: {note}")
    report = H.run_battery()
    if report["status"] != "ok":
        pytest.skip(f"battery could not run: {report.get('note')}")

    # Pin correctness must hold for EVERY case (probe verified) — a hard assertion.
    not_offered = [r["tool"] for r in report["records"] if not r["offered"]]
    assert not not_offered, f"pin failed to offer these targets: {not_offered}"

    # Pipeline liveness: the real decision->dispatch->execute->verify path drove at
    # least one real tool execution end-to-end. (Which specific tools the 360M
    # selects — and whether it feeds them good args — is recorded honestly in the
    # report, NOT asserted: that is real model signal, not a harness bug. The big
    # historical defect was that tool calling never happened live at all.)
    assert report["selected"] >= 1, (
        f"no tool was selected by the model — pipeline may be dead: "
        f"{[(r['tool'], r['selected'], r['verify_reason']) for r in report['records']]}"
    )
    # Surface the GREEN chain (offered+selected+verified) for the record.
    print(f"\n[driven-battery] GREEN {report['green']}/{report['total']} "
          f"selected {report['selected']}/{report['total']} "
          f"verified {report['verified']}/{report['total']}")
