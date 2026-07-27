"""
PLAN ITEM 25 (+28) -- Driven per-tool verification harness.

The problem this closes. Every earlier tool-reliability number was measured the
wrong way. Item 26 (`_tool_verify.py`) proved the router can be made to PRESENT a
target tool, and item 27 (`tool_output_validator.deterministic_verify_tool_result`)
proved a tool's RESULT can be checked model-free -- but nothing yet drove a REAL
model turn per tool and asserted the concrete EFFECT. The memory of this repo is
littered with the consequence: "tool calling never happened live" (dispatch
discarded args), "sandbox root empty -> file tools 0/13" (the config sandbox_root
clamp), "verify the probe before the result" (broken probes reported as broken
code). This harness is the driven end of that chain.

What one GREEN case means here, precisely:
  1. OFFERED  -- the production resolver actually presents the target to the model
     for this goal+config (recorded via item 26's ``offered_set`` -- the probe is
     verified, not assumed).
  2. SELECTED -- the REAL local model (SmolLM2-360M, the golden-eval CI model),
     given that offered set, chose the target tool (found in the turn's steps).
  3. VERIFIED -- the artifact the tool claims to have produced actually
     materialised: item 27's deterministic verifier and/or a direct workspace
     check (the file exists / the hash matches / the row is in the DB).

Honesty rule baked in: SELECTED and VERIFIED are recorded separately, so "the 360M
did not pick this tool" (real model signal) is never conflated with "the harness
could not present it" (a probe bug). A case that is offered-but-not-selected is a
true datapoint about a 360M model, not a harness failure.

Design:
  * IN-PROCESS. ``autonomous_run`` is called directly -- no HTTP, no SSE, no
    uvicorn. The only cost is the model itself; everything else is a function call,
    so a per-tool turn is cheap enough to run a whole battery locally.
  * PINNED. Each case runs under ``pin_tools_config(tool)`` (item 26) so the target
    is guaranteed offered; ``offered_set`` records the truth per case.
  * SEEDED SANDBOX. The once-fatal bug (config ``sandbox_root`` clamps the
    caller's workspace, so file tools saw an empty ``~/layla-workspace``) is fixed
    by pointing BOTH the ``workspace_root`` arg AND config ``sandbox_root`` at the
    same freshly-seeded temp dir -- so the disk-tool class is genuinely exercised.
  * SAFE SIDE-EFFECT TIER (item 28). Outbound tools (send_email / send_webhook /
    discord_send) and web tools (fetch_url) are exercised through injected
    stdlib mocks / a loopback ``http.server`` and asserted on the CAPTURED payload
    or PARSED body -- a real external send is never fired.
  * GATED. The real-inference battery runs only when ``LAYLA_DRIVEN_TOOL_EVAL=1``
    (mirroring ``scripts/run_real_eval.py``). The mock tier and the pinning-wiring
    checks are model-free and run always.

This module lives under ``tests/`` on purpose: it is a test-only harness, so the
dead-symbols gate excludes it and no production module gains a test-only caller.
It only READS production mechanisms (autonomous_run, the resolver, the verifiers);
it never edits source.

Standalone (bypasses conftest's llama_cpp block, loads the real cached model):
    ../.venv/Scripts/python.exe agent/tests/_tool_verify_harness.py
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import socket
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable
from unittest import mock

# ── Path bootstrap (must precede first-party imports; standalone + pytest both) ──
_THIS = Path(__file__).resolve()
AGENT_DIR = _THIS.parent.parent          # agent/
REPO_ROOT = AGENT_DIR.parent             # repo root
for _p in (str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests._tool_verify import offered_set, pin_tools_config  # noqa: E402

# The tiny CI model — same catalog/file the golden-eval + run_real_eval use.
MODEL_FILENAME = "SmolLM2-360M-Instruct-Q4_K_M.gguf"
ENV_FLAG = "LAYLA_DRIVEN_TOOL_EVAL"

# A goal whose intent categories would narrow HARD under production routing, so the
# pin (routing off) is doing real work — same rationale as item 26's coding goal.
_NARROWING_GOAL_FOR_OFFER_CHECK = "fix the bug in this code"


def default_models_dir() -> Path:
    """Where the cached GGUF lives (repo/models, matching run_real_eval)."""
    env = (os.environ.get("LAYLA_MODELS_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (REPO_ROOT / "models").resolve()


def model_available(models_dir: Path | None = None) -> tuple[Path | None, str]:
    """Return (path_to_gguf, note). Degrades honestly — never downloads here."""
    md = models_dir or default_models_dir()
    dest = md / MODEL_FILENAME
    try:
        if dest.exists() and dest.stat().st_size > 50 * 1024 * 1024:
            with dest.open("rb") as f:
                if f.read(4) == b"GGUF":
                    return dest, "cached model present"
            return None, f"file at {dest} is not a valid GGUF"
        return None, f"model missing at {dest}"
    except Exception as e:  # noqa: BLE001
        return None, f"model probe failed: {e}"


# ── Config: base eval config + per-case pin ─────────────────────────────────────

def base_eval_config(models_dir: Path, sandbox_root: str) -> dict[str, Any]:
    """A deterministic, snappy config for an in-process real-model turn.

    Mirrors ``scripts/run_real_eval.build_isolated_config`` (tiny model, no Chroma,
    CPU-only, background subsystems off) and additionally pins DETERMINISM knobs so
    the battery is reproducible: auto-tune OFF (so the explicit budgets below are
    authoritative and are not rescaled by the hardware tier), prompt optimizer OFF,
    deliberation OFF, all caches OFF (each case is a fresh inference, never a cache
    hit). Deliberately does NOT set tool_routing_enabled / tools_profile /
    tools_allow — those are owned by the per-case pin so the pin always wins.
    """
    return {
        "model_filename": MODEL_FILENAME,
        "models_dir": str(models_dir),
        "sandbox_root": str(sandbox_root),
        "use_chroma": False,
        "n_ctx": 2048,
        "n_gpu_layers": 0,
        "n_batch": 256,
        "temperature": 0.0,
        "completion_max_tokens": 220,
        # Budgets: enough for a probe + the tool + a finalize, bounded so no single
        # case can run away on a CPU box.
        "max_tool_calls": 3,
        "max_runtime_seconds": 90,
        "tool_call_timeout_seconds": 60,
        # Determinism / isolation.
        "auto_tune_enabled": False,
        "prompt_optimizer_enabled": False,
        "deliberation_enabled": False,
        "engineering_pipeline_enabled": False,
        "response_cache_enabled": False,
        "completion_cache_enabled": False,
        "telemetry_enabled": False,
        "scheduler_study_enabled": False,
        "embedder_prewarm_enabled": False,
        "safe_mode": True,
        # Keep the head lean so the 360M isn't drowned by optional context layers.
        "planning_enabled": False,
        "enable_cognitive_workspace": False,
        "knowledge_max_bytes": 0,
        "learnings_n": 0,
        "semantic_k": 0,
        "convo_turns": 0,
    }


def pinned_config_for_case(
    tool: str, sandbox_root: str, decoys: list[str], models_dir: Path,
) -> dict[str, Any]:
    """Base eval config with the item-26 pin (target guaranteed offered) laid over
    it, and sandbox_root set to the seeded case dir (so it equals the workspace and
    is not clamped by the executor's confinement check)."""
    cfg = base_eval_config(models_dir, sandbox_root)
    cfg.update(pin_tools_config(tool, decoys))  # tool_routing off + minimal + allow
    cfg["sandbox_root"] = str(sandbox_root)
    return cfg


@contextlib.contextmanager
def pinned_runtime(cfg: dict[str, Any]):
    """Make ``runtime_safety.load_config()`` return ``cfg`` for the block.

    Uses the CONFIG_FILE seam (write json -> point runtime_safety.CONFIG_FILE at it
    -> invalidate the TTL cache), NOT a monkeypatch of the function object: every
    consumer calls the real ``load_config()`` regardless of how it imported the
    module, so ALL of them (resolver, llm_decision, executor, tool_permissions) see
    the pinned config. load_config's own overlays (hardware defaults, auto-tune)
    run on top, but PROFILE_KEYS does not include the pin keys, so the pin holds.
    Restores the previous CONFIG_FILE on exit.
    """
    import runtime_safety

    tmp = Path(tempfile.mkdtemp(prefix="layla-toolverify-cfg-")) / "runtime_config.json"
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    prev = runtime_safety.CONFIG_FILE
    runtime_safety.CONFIG_FILE = tmp
    runtime_safety.invalidate_config_cache()
    try:
        yield
    finally:
        runtime_safety.CONFIG_FILE = prev
        runtime_safety.invalidate_config_cache()


# ── Battery: one representative effectful tool per domain ───────────────────────

# Effect-check signature: (tool, result_dict, sandbox_dir) -> (ok: bool, reason: str)
EffectCheck = Callable[[str, dict, Path], "tuple[bool, str]"]

_MARKER = "LAYLA_VERIFY_MARKER_7fae"
_HASH_TEXT = b"layla-hash-fixture-contents\n"


def _deterministic_effect(tool: str, result: dict, sandbox: Path) -> tuple[bool, str]:
    """Default effect check — item 27's model-free artifact verifier."""
    from services.tools.tool_output_validator import deterministic_verify_tool_result

    v = deterministic_verify_tool_result(tool, result, workspace_root=str(sandbox))
    return bool(v.get("ok")), str(v.get("reason") or "")


def _effect_read_file(tool, result, sandbox):
    if not result.get("ok"):
        return False, "tool_reported_failure"
    content = str(result.get("content") or result.get("text") or "")
    return (_MARKER in content), ("marker_present" if _MARKER in content else "marker_absent")


def _effect_list_dir(tool, result, sandbox):
    if not result.get("ok"):
        return False, "tool_reported_failure"
    blob = json.dumps(result, default=str)
    return (_MARKER in blob or "alpha.txt" in blob), "listing_names_present" if (
        _MARKER in blob or "alpha.txt" in blob
    ) else "seeded_names_absent"


def _effect_hash_file(tool, result, sandbox):
    if not result.get("ok"):
        return False, "tool_reported_failure"
    expected = hashlib.sha256(_HASH_TEXT).hexdigest()
    got = str(result.get("hash") or "").strip().lower()
    return (got == expected), ("hash_matches" if got == expected else f"hash_mismatch:{got[:12]}")


def _effect_grep(tool, result, sandbox):
    if not result.get("ok"):
        return False, "tool_reported_failure"
    matches = result.get("matches")
    count = result.get("count")
    has = (isinstance(matches, list) and len(matches) > 0) or (isinstance(count, int) and count > 0)
    blob = json.dumps(result, default=str)
    return (has and "target_function" in blob), "match_found" if (has and "target_function" in blob) else "no_match"


def _effect_git_status(tool, result, sandbox):
    if not result.get("ok"):
        return False, "tool_reported_failure"
    out = str(result.get("output") or result.get("stdout") or "")
    good = ("untracked" in out.lower()) or ("branch" in out.lower()) or ("seed.txt" in out)
    return good, "status_output_present" if good else "empty_or_unexpected_status"


def _effect_run_python(tool, result, sandbox):
    ok, reason = _deterministic_effect(tool, result, sandbox)
    if not ok:
        return ok, reason
    out = str(result.get("stdout") or "")
    return (_MARKER in out), ("stdout_marker_present" if _MARKER in out else "stdout_marker_absent")


def _effect_shell(tool, result, sandbox):
    ok, reason = _deterministic_effect(tool, result, sandbox)
    if not ok:
        return ok, reason
    out = str(result.get("stdout") or result.get("output") or "")
    return (_MARKER in out), ("stdout_marker_present" if _MARKER in out else "stdout_marker_absent")


def _effect_save_note(tool, result, sandbox):
    ok, reason = _deterministic_effect(tool, result, sandbox)  # checks result['saved']
    if not ok:
        return ok, reason
    # Bonus (soft): confirm it reached durable memory. Never fails the case if the
    # probe itself cannot run (rate-limit / migration) — SELECTED+saved already
    # proves the tool fired its effect.
    try:
        from services.memory.memory_router import search_learnings_fts
        hits = search_learnings_fts("sky blue", limit=10) or []
        if any(_MARKER in json.dumps(h, default=str) for h in hits):
            return True, "saved_and_in_memory"
    except Exception:
        pass
    return True, reason


# ── Seed helpers ────────────────────────────────────────────────────────────────

def _seed_none(sandbox: Path) -> None:
    return None


def _seed_read_file(sandbox: Path) -> None:
    (sandbox / "readme.txt").write_text(f"Project notes.\n{_MARKER}\nEnd.\n", encoding="utf-8")


def _seed_list_dir(sandbox: Path) -> None:
    (sandbox / "alpha.txt").write_text("a\n", encoding="utf-8")
    (sandbox / "beta.txt").write_text("b\n", encoding="utf-8")


def _seed_hash_file(sandbox: Path) -> None:
    (sandbox / "data.bin").write_bytes(_HASH_TEXT)


def _seed_grep(sandbox: Path) -> None:
    (sandbox / "mod.py").write_text(
        "def target_function(x):\n    return x + 1\n", encoding="utf-8",
    )


def _seed_read_csv(sandbox: Path) -> None:
    (sandbox / "sales.csv").write_text(
        "region,units\nnorth,10\nsouth,20\neast,30\n", encoding="utf-8",
    )


def _seed_git_repo(sandbox: Path) -> None:
    import subprocess
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    subprocess.run(["git", "init"], cwd=str(sandbox), capture_output=True, env=env)
    (sandbox / "seed.txt").write_text("hello\n", encoding="utf-8")


@dataclass
class Case:
    name: str
    domain: str
    tool: str
    goal: str
    allow_write: bool = True
    allow_run: bool = True
    seed: Callable[[Path], None] = _seed_none
    decoys: list[str] = field(default_factory=list)
    effect: EffectCheck = _deterministic_effect


def _decoys_for(target: str) -> list[str]:
    """Two plausible read-tool alternatives (never the target) so the case is a real
    choice, not a single forced option. Kept tiny to stay under the visibility cap."""
    pool = ["read_file", "list_dir", "grep_code", "save_note"]
    return [t for t in pool if t != target][:2]


def build_battery() -> list[Case]:
    """One representative EFFECTFUL tool per domain (~10 cases). The file/disk class
    is over-represented on purpose — it was once 0/13 on an empty sandbox_root, so it
    is the class most worth proving now works against a real seeded sandbox."""
    # Goals embed the concrete sandbox path (``{d}`` -> the seeded dir, filled per
    # case in run_case). This is realistic — a user names the exact file/dir — and
    # gives the 360M a copyable argument, so a selection can actually reach a
    # verified effect rather than dying on a hallucinated path. It is NOT a cheat:
    # the model still has to CHOOSE the right tool from the offered set and emit a
    # correct call; the harness never pre-selects or pre-fills the tool for it.
    return [
        Case("file.write", "file", "write_file",
             f"Create a new file at {{d}}/notes.txt whose exact contents are: {_MARKER}",
             seed=_seed_none, decoys=_decoys_for("write_file")),
        Case("file.read", "file", "read_file",
             "Read the file {d}/readme.txt and show me its contents.",
             seed=_seed_read_file, decoys=_decoys_for("read_file"),
             effect=_effect_read_file),
        Case("file.list", "file", "list_dir",
             "List the files in the directory {d}.",
             seed=_seed_list_dir, decoys=_decoys_for("list_dir"),
             effect=_effect_list_dir),
        Case("file.hash", "analysis", "hash_file",
             "Compute the sha256 hash of the file {d}/data.bin.",
             seed=_seed_hash_file, decoys=_decoys_for("hash_file"),
             effect=_effect_hash_file),
        Case("code.grep", "code", "grep_code",
             "Search for the text target_function in the file {d}/mod.py.",
             seed=_seed_grep, decoys=_decoys_for("grep_code"),
             effect=_effect_grep),
        Case("data.csv", "data", "read_csv",
             "Read the CSV file {d}/sales.csv and summarise its columns.",
             seed=_seed_read_csv, decoys=_decoys_for("read_csv"),
             effect=_deterministic_effect),
        Case("git.status", "git", "git_status",
             "Show the git status of the repository at {d}.",
             seed=_seed_git_repo, decoys=_decoys_for("git_status"),
             effect=_effect_git_status),
        Case("memory.note", "memory", "save_note",
             f"Save a note to your memory that remembers: {_MARKER} the sky is blue.",
             seed=_seed_none, decoys=_decoys_for("save_note"),
             effect=_effect_save_note),
        # Exec tier — these require the model to supply a valid `cwd`, which the tiny
        # model often omits; the goal states the directory explicitly to give it a
        # fair shot. Selected-but-unverified here is honest exec-arg signal.
        Case("code.run_python", "code", "run_python",
             f"Run this Python code with working directory {{d}}: print('{_MARKER}')",
             seed=_seed_none, decoys=_decoys_for("run_python"),
             effect=_effect_run_python),
        Case("system.shell", "system", "shell",
             f"In the directory {{d}}, run the shell command: echo {_MARKER}",
             seed=_seed_none, decoys=_decoys_for("shell"),
             effect=_effect_shell),
    ]


# ── Running one case ─────────────────────────────────────────────────────────────

def _selected_tool(state: dict, target: str) -> tuple[bool, list[str]]:
    """(selected?, the real tools the model actually invoked this turn).

    ``tools_used`` is populated by register_exact_tool_call for every executed tool
    and already excludes reason/none/finish/wakeup; step ``action`` is a belt-and-
    suspenders second source (also catches synthetic tool steps)."""
    used = list(state.get("tools_used") or [])
    step_actions = [str(s.get("action")) for s in (state.get("steps") or [])]
    selected = (target in used) or (target in step_actions)
    model_selected = sorted(set(used) | {a for a in step_actions if a in used})
    return selected, model_selected


def _result_for_tool(state: dict, target: str) -> dict | None:
    last = None
    for s in state.get("steps") or []:
        if str(s.get("action")) == target and isinstance(s.get("result"), dict):
            last = s["result"]
    return last


def run_case(case: Case, models_dir: Path) -> dict[str, Any]:
    """Drive ONE real-model turn for one tool and record offered/selected/verified."""
    import runtime_safety  # noqa: F401  (ensure importable before pinning)

    sandbox = Path(tempfile.mkdtemp(prefix=f"layla-tv-{case.name.replace('.', '_')}-"))
    # Forward slashes even on Windows: keeps the path clean when the model echoes it
    # into a JSON tool call (no backslash-escaping hazards), and Path() accepts it.
    goal = case.goal.format(d=str(sandbox).replace("\\", "/"))
    record: dict[str, Any] = {
        "name": case.name, "domain": case.domain, "tool": case.tool,
        "offered": False, "offered_size": 0, "selected": False,
        "verified": False, "verify_reason": "", "model_selected": [],
        "tool_error": "", "error": "", "green": False,
    }
    try:
        case.seed(sandbox)
    except Exception as e:  # noqa: BLE001
        record["error"] = f"seed_failed: {e}"
        return record

    cfg = pinned_config_for_case(case.tool, str(sandbox), case.decoys, models_dir)
    with pinned_runtime(cfg):
        # (a) Verify the PROBE: the resolver actually offers the target under the
        # effective (post-overlay) config the run will use. Recorded, not assumed.
        try:
            import runtime_safety as _rs
            effective = _rs.load_config()
            offered = offered_set(effective, goal)
            record["offered"] = case.tool in offered
            record["offered_size"] = len(offered)
        except Exception as e:  # noqa: BLE001
            record["error"] = f"offer_probe_failed: {e}"

        # (b) Drive the real model turn in-process.
        try:
            import agent_loop
            state = agent_loop.autonomous_run(
                goal=goal,
                context="",
                workspace_root=str(sandbox),
                allow_write=case.allow_write,
                allow_run=case.allow_run,
                conversation_history=[],
                aspect_id="",
                show_thinking=False,
            )
        except Exception as e:  # noqa: BLE001
            record["error"] = f"autonomous_run_raised: {e}"
            return record

    selected, model_selected = _selected_tool(state, case.tool)
    record["selected"] = selected
    record["model_selected"] = model_selected
    if selected:
        result = _result_for_tool(state, case.tool)
        if isinstance(result, dict):
            # Diagnostic honesty: when a selected tool fails to verify, record WHY
            # the tool itself reported failure (usually a hallucinated arg from the
            # 360M) so the report distinguishes model-arg weakness from a real bug.
            if not result.get("ok"):
                record["tool_error"] = str(result.get("error") or result.get("reason") or "")[:160]
            try:
                ok, reason = case.effect(case.tool, result, sandbox)
            except Exception as e:  # noqa: BLE001
                ok, reason = False, f"effect_check_raised: {e}"
            record["verified"] = ok
            record["verify_reason"] = reason
        else:
            record["verify_reason"] = "no_result_dict_for_tool_step"
    else:
        record["verify_reason"] = "not_selected"
    record["green"] = bool(record["offered"] and record["selected"] and record["verified"])
    return record


def _warm_model(models_dir: Path) -> str:
    """Load + warm the model once so the first real case doesn't pay cold-load."""
    sandbox = Path(tempfile.mkdtemp(prefix="layla-tv-warm-"))
    cfg = base_eval_config(models_dir, str(sandbox))
    with pinned_runtime(cfg):
        try:
            import agent_loop
            out = agent_loop.run_completion("Reply with the single word OK.", max_tokens=8,
                                            temperature=0.0, stream=False)
            return "warm_ok" if out is not None else "warm_no_output"
        except Exception as e:  # noqa: BLE001
            return f"warm_failed: {e}"


def run_battery(models_dir: Path | None = None, cases: list[Case] | None = None) -> dict[str, Any]:
    """Run the whole driven battery against the real model. Returns a report dict."""
    md = models_dir or default_models_dir()
    path, note = model_available(md)
    if path is None:
        return {"status": "model_unavailable", "note": note, "records": []}

    battery = cases if cases is not None else build_battery()
    t0 = time.time()
    warm = _warm_model(md)
    records: list[dict[str, Any]] = []
    for case in battery:
        rec = run_case(case, md)
        records.append(rec)
        print(_fmt_record(rec), flush=True)
    return {
        "status": "ok",
        "note": note,
        "warm": warm,
        "seconds": round(time.time() - t0, 1),
        "records": records,
        "offered": sum(1 for r in records if r["offered"]),
        "selected": sum(1 for r in records if r["selected"]),
        "verified": sum(1 for r in records if r["verified"]),
        "green": sum(1 for r in records if r["green"]),
        "total": len(records),
    }


def _fmt_record(r: dict[str, Any]) -> str:
    flag = "GREEN" if r["green"] else "    -"
    def y(b):  # noqa: E306
        return "Y" if b else "n"
    tail = ""
    if r["error"]:
        tail = f"  ERR={r['error'][:80]}"
    elif r["selected"] and not r["verified"] and r.get("tool_error"):
        tail = f"  tool_error={r['tool_error']}"
    elif not r["selected"] and r["model_selected"]:
        tail = f"  model_picked={r['model_selected']}"
    return (f"[{flag}] {r['domain']:<8} {r['tool']:<12} "
            f"offered={y(r['offered'])}(n={r['offered_size']}) "
            f"selected={y(r['selected'])} verified={y(r['verified'])} "
            f"({r['verify_reason']}){tail}")


# ── Side-effect / dep-gated MOCK tier (item 28) — model-free, never fires a send ──

class _FixtureHandler(BaseHTTPRequestHandler):
    body = f"<html><head><title>Fixture</title></head><body><p>{_MARKER} loopback body</p></body></html>"

    def do_GET(self):  # noqa: N802
        payload = self.body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence
        return


@contextlib.contextmanager
def loopback_server():
    """A stdlib http.server serving a fixed HTML body on 127.0.0.1:<free port>."""
    srv = HTTPServer(("127.0.0.1", 0), _FixtureHandler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/"
    finally:
        srv.shutdown()
        srv.server_close()


def web_fetch_returns_fixture() -> dict[str, Any]:
    """Assert fetch_url PARSES a known loopback body (not network reachability).

    The SSRF guard blocks loopback by design, so for this PARSE test we neutralise
    the guard (is_safe_url -> True, safe_urlopen -> plain urlopen) and the
    robots/allowlist gates, then fetch our own fixture. This proves the parse path,
    with zero traffic leaving the machine.
    """
    import urllib.request

    import layla.tools.web as web
    import services.safety.url_guard as guard

    def _passthrough(req, timeout=None, **kw):
        return urllib.request.urlopen(req, timeout=timeout)

    with loopback_server() as url, \
            mock.patch.object(guard, "is_safe_url", lambda u: True), \
            mock.patch.object(guard, "safe_urlopen", _passthrough), \
            mock.patch.object(web, "_is_safe_url", lambda u: True), \
            mock.patch.object(web, "_robots_allowed", lambda u: True), \
            mock.patch.object(web, "_get_allowlist", lambda: []):
        from layla.tools.registry import TOOLS
        out = TOOLS["fetch_url"]["fn"](url=url)
    text = str((out or {}).get("text") or (out or {}).get("content") or "")
    return {"ok": bool(out and out.get("ok") and _MARKER in text),
            "marker_present": _MARKER in text, "raw_ok": bool(out and out.get("ok"))}


def send_email_captures_payload() -> dict[str, Any]:
    """Inject a fake smtplib.SMTP; assert the CAPTURED message — no real send."""
    import smtplib

    captured: dict[str, Any] = {}

    class _FakeSMTP:
        def __init__(self, host, port, timeout=None):
            captured["host"], captured["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            captured["starttls"] = True

        def login(self, u, p):
            captured["login"] = u

        def send_message(self, msg):
            captured["to"] = msg["To"]
            captured["subject"] = msg["Subject"]
            captured["body"] = msg.get_payload(decode=True).decode("utf-8", "replace")

    with mock.patch.object(smtplib, "SMTP", _FakeSMTP):
        from layla.tools.registry import TOOLS
        out = TOOLS["send_email"]["fn"](
            to="alice@example.test", subject="Hello", body=f"{_MARKER} body",
        )
    return {"result": out, "captured": captured,
            "ok": bool(out and out.get("ok")
                       and captured.get("to") == "alice@example.test"
                       and _MARKER in str(captured.get("body")))}


def _webhook_capture_ctx(captured: dict[str, Any]):
    """Patch the SSRF-safe opener send_webhook uses so the POST is captured, not sent."""
    import services.safety.url_guard as guard

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    def _fake_urlopen(req, timeout=None, **kw):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        try:
            captured["payload"] = json.loads((req.data or b"").decode("utf-8"))
        except Exception:
            captured["payload"] = (req.data or b"").decode("utf-8", "replace")
        return _Resp()

    return mock.patch.object(guard, "safe_urlopen", _fake_urlopen)


def send_webhook_captures_payload() -> dict[str, Any]:
    """Assert send_webhook's model-supplied payload is CAPTURED, never delivered."""
    captured: dict[str, Any] = {}
    with _webhook_capture_ctx(captured):
        from layla.tools.registry import TOOLS
        out = TOOLS["send_webhook"]["fn"](
            url="https://hooks.example.test/abc",
            payload={"marker": _MARKER, "text": "hi"},
        )
    good = bool(out and out.get("ok")
                and isinstance(captured.get("payload"), dict)
                and captured["payload"].get("marker") == _MARKER)
    return {"result": out, "captured": captured, "ok": good}


def discord_send_captures_payload() -> dict[str, Any]:
    """discord_send funnels through send_webhook — assert the content is captured."""
    captured: dict[str, Any] = {}
    with _webhook_capture_ctx(captured):
        from layla.tools.registry import TOOLS
        out = TOOLS["discord_send"]["fn"](
            content=f"{_MARKER} hello discord",
            webhook_url="https://discord.example.test/webhooks/1/xyz",
        )
    payload = captured.get("payload") if isinstance(captured.get("payload"), dict) else {}
    good = bool(out and out.get("ok") and _MARKER in str(payload.get("content")))
    return {"result": out, "captured": captured, "ok": good}


def run_mock_tier() -> dict[str, Any]:
    """Run every model-free side-effect / web check. Returns {name: report}."""
    return {
        "web.fetch_url_loopback": web_fetch_returns_fixture(),
        "outbound.send_email": send_email_captures_payload(),
        "outbound.send_webhook": send_webhook_captures_payload(),
        "outbound.discord_send": discord_send_captures_payload(),
    }


# ── Standalone entrypoint (bypasses conftest's llama block; loads real model) ─────

def _isolate_data_dir() -> Path:
    """Point LAYLA_DATA_DIR at a throwaway dir and migrate the DB, so save_note et al
    write to an isolated database and never the operator's real one."""
    d = Path(tempfile.mkdtemp(prefix="layla-toolverify-data-"))
    os.environ["LAYLA_DATA_DIR"] = str(d)
    os.environ.pop("LAYLA_DB_PATH", None)
    try:
        import layla.memory.db as db_mod
        import layla.memory.migrations as mig
        db_mod._DB_PATH = d / "layla.db"
        if hasattr(db_mod, "_MIGRATED"):
            db_mod._MIGRATED = False
        if hasattr(mig, "_MIGRATED"):
            mig._MIGRATED = False
        mig.migrate()
    except Exception as e:  # noqa: BLE001
        print(f"[tool-verify] DB migrate note: {e}")
    return d


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    md = default_models_dir()
    print(f"[tool-verify] model_filename={MODEL_FILENAME} models_dir={md}")
    _isolate_data_dir()

    # Mock tier first — model-free, fast, and proves the side-effect safety net.
    print("\n==================== MOCK TIER (model-free) ====================")
    mock_report = run_mock_tier()
    for name, rep in mock_report.items():
        print(f"  [{'PASS' if rep.get('ok') else 'FAIL'}] {name}: ok={rep.get('ok')}")
    mock_all_ok = all(r.get("ok") for r in mock_report.values())

    print("\n==================== DRIVEN BATTERY (real model) ===============")
    report = run_battery(md)
    if report["status"] != "ok":
        print(f"[tool-verify] MODEL UNAVAILABLE — {report['note']}")
        print("[tool-verify] mock tier still ran; no inference performed.")
        return 2

    print("\n==================== SUMMARY ====================")
    print(f"  warm    : {report['warm']}")
    print(f"  offered : {report['offered']}/{report['total']}")
    print(f"  selected: {report['selected']}/{report['total']}")
    print(f"  verified: {report['verified']}/{report['total']}")
    print(f"  GREEN   : {report['green']}/{report['total']}  (offered AND selected AND verified)")
    print(f"  mock    : {'all ok' if mock_all_ok else 'FAILURES'} ({len(mock_report)} checks)")
    print(f"  seconds : {report['seconds']}")
    print("=================================================")

    # Exit 0 iff the HARNESS worked end-to-end: mocks safe, every target offered
    # (probe correct), and the real decision->dispatch->execute->verify pipeline
    # drove at least one real tool execution (pipeline liveness — historically the
    # big defect was that tool calling never happened live at all). GREEN is
    # reported but NOT required: a 360M declining to select a given tool, or
    # feeding it a hallucinated arg, is real model signal, not a harness failure.
    ok = mock_all_ok and report["offered"] == report["total"] and report["selected"] >= 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
