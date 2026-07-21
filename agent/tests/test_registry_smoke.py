"""
BL-346 — the registry SMOKE test: invoke every SAFE tool and assert it does not raise.

Why this exists
---------------
`test_registered_tools_count.py` only COUNTS registrations. That is why `len(TOOLS) == 198`
stayed green while `math_eval` raised `AttributeError` on every input (a tuple built with the
non-existent `ast.Mul`) and `search_codebase` returned 0 matches for everything. A registration
is not a proof the tool RUNS. This test drives each safe tool with schema-valid minimal args and
fails if it raises — the exact defect class those two bugs belong to. For the pure-compute core it
goes further and asserts the *value* (math_eval == 8, not merely "returned a dict"), because a
try/except that returns {"ok": false} would pass a "didn't raise" check while the tool is dead.

The known trap (do not re-enact)
--------------------------------
A naive "invoke every tool" smoke test HANGS: it reaches tools that call the LLM, the network, a
subprocess, a heavy model, or block. So tools are partitioned three ways and only the safe set is
driven, each under a per-call timeout:

  GUARDED  — computed from the tool's OWN meta (dangerous | require_approval | risk_level=="high").
             Invoking these with junk could mutate real state or hit an approval flow, so they are
             NOT smoke-invoked. Derived, not hand-listed: a new dangerous tool auto-guards, and a
             tool downgraded to safe auto-moves into DRIVEN and gets tested. Nothing to rot.
  SKIP     — an EXPLICIT denylist (below) of low/medium, not-approval tools that STILL cannot be
             driven with placeholder args because they reach the network, spawn a subprocess, call
             an LLM, load a heavy model, need a media fixture, drive hardware, start the scheduler
             thread, or read/write OPERATOR state on a hardcoded path. Every entry carries a reason
             from the SkipReason enum. Meta flags cannot see these — they are correctly marked
             low-risk — which is exactly why the explicit list is required. The classification was
             produced by reading each impl through the code (BL-346 analysis), not from meta alone.
  DRIVEN   — everything else. Pure/local computation and local file/db ops (fed contained temp
             paths, or a temp-isolated LAYLA_DATA_DIR via conftest). Invoked under a timeout; a
             raise or a hang is a RED.

Polarity matters (a scar this repo already took: a hand-maintained ALLOWLIST that missed the very
instance it was built to catch). This uses a DENYLIST with default-drive: forget to skip a
network/subprocess tool and it gets DRIVEN, then errors or times out → RED (loud). A new tool lands
in DRIVEN automatically and must be exercised or explicitly, reasonedly skipped. There is no silent
skip: the partition is asserted to cover the whole registry, and specific hazards are asserted to
BE skipped (test_hazard_tools_are_skipped) so a critical entry cannot be quietly deleted.

Why the SKIP list is broad (and must be)
----------------------------------------
Several tools return {"ok": false} today ONLY because an optional lib is absent in `.venv-test`
(matplotlib, spaCy, KeyBERT, YOLO, whisper, market-data libs). On CI or a fuller box the same call
would load a model or hit the network. Driving them "because they error gracefully today" is the
shipped-dead-TTS scar — a graceful return that exercises nothing. They are skipped with the reason
recorded, not driven. Likewise `log_event` and `memory_stats` APPEND to / CREATE files on hardcoded
repo/operator paths that LAYLA_DATA_DIR does not redirect — a real side effect on operator state —
so they are skipped, not driven.

What counts as failure
----------------------
Only a RAISED exception (or a hang → timeout) is a failure of the generic smoke. A tool that
returns {"ok": False, "error": ...} on junk input has handled its error correctly and PASSES — that
is the contract. The pure-compute teeth (test_pure_tools_produce_correct_results) additionally pin
exact output values.

Schema (spec answer): a pydantic model is derived per tool from inspect.signature at test time and
memoized; it is NOT attached to the tool meta. The meta/TOOLS dict is the LIVE object the running
agent injects into every impl module and the operator process — attaching test-only pydantic
schemas would mutate shared runtime state, push a model-build into the hot import path, and risk
drift against the live signature. The schema is a test artifact, so it lives in the test.
"""
from __future__ import annotations

import enum
import inspect
import os
import sys
import tempfile
import threading
import traceback
import warnings
from pathlib import Path
from typing import Any, get_type_hints

import pytest
from pydantic import ConfigDict, create_model

# conftest.py adds the agent dir to sys.path and isolates LAYLA_DATA_DIR to a temp dir (session
# scope). Re-assert the path insert so the module also imports when run in isolation.
_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from layla.tools import registry  # noqa: E402

TOOLS = registry.TOOLS

# A real block (network/LLM/subprocess/input) hangs for tens of seconds; every safe local tool in
# the driven set finishes in well under a second (empirically the slowest is < 2s). 20s cleanly
# separates the two. Do NOT raise this to paper over a hang — a hang means the SKIP list is
# incomplete; add the tool with a reason instead.
PER_CALL_TIMEOUT_S = float(os.environ.get("LAYLA_SMOKE_TIMEOUT_S", "20"))


class SkipReason(enum.Enum):
    NETWORK = "reaches the network (HTTP / API / scraping / socket / webhook)"
    SUBPROCESS = "spawns a subprocess (git / pip / docker / ruff / shell / ffmpeg)"
    LLM = "calls the local LLM (would block on generation)"
    MODEL = "loads a heavy ML model / embedder (slow, may download weights)"
    MEDIA = "needs a real image/audio/video/ics fixture + codec, or a plotting backend"
    HARDWARE = "drives OS clipboard / display / mouse / keyboard"
    SCHEDULER = "starts the APScheduler background thread (lingers past the test)"
    OPERATOR_STATE = "reads/writes operator state on a hardcoded path LAYLA_DATA_DIR cannot redirect"


# --- EXPLICIT SKIP DENYLIST -------------------------------------------------------------------
# Every low/medium, not-approval tool that cannot be driven with placeholder args, and why. The
# bucketing was verified by reading each impl through the code (BL-346), NOT inferred from optional
# libs happening to be absent here. Bump EXPECTED_SKIP_COUNT deliberately when this changes.
SKIP: dict[str, SkipReason] = {
    # NETWORK — impl uses requests/httpx/urllib/feedparser/arxiv, opens a socket, or posts remote
    "fetch_url": SkipReason.NETWORK, "fetch_article": SkipReason.NETWORK,
    "check_url": SkipReason.NETWORK, "extract_links": SkipReason.NETWORK,
    "crawl_site": SkipReason.NETWORK, "rss_feed": SkipReason.NETWORK,
    "http_request": SkipReason.NETWORK, "browser_navigate": SkipReason.NETWORK,
    "browser_screenshot": SkipReason.NETWORK, "browser_search": SkipReason.NETWORK,
    "arxiv_search": SkipReason.NETWORK, "ddg_search": SkipReason.NETWORK,
    "wiki_search": SkipReason.NETWORK, "geo_query": SkipReason.NETWORK,
    "stock_data": SkipReason.NETWORK, "crypto_prices": SkipReason.NETWORK,
    "economic_indicators": SkipReason.NETWORK, "github_issues": SkipReason.NETWORK,
    "check_ci": SkipReason.NETWORK, "check_port": SkipReason.NETWORK,
    # send_webhook / discord_send used to be listed here as NETWORK. They are now
    # dangerous + require_approval (a model-supplied url and body is an exfil path), so
    # GUARDED covers them and an explicit skip would be redundant — see
    # test_skip_is_not_redundant_with_meta_guard, which is what caught this.
    "translate_text": SkipReason.NETWORK, "pip_list": SkipReason.NETWORK,
    # SUBPROCESS — impl calls subprocess.run (git/pip/docker/ruff/bandit/rg/shell session)
    "git_status": SkipReason.SUBPROCESS, "git_diff": SkipReason.SUBPROCESS,
    "git_log": SkipReason.SUBPROCESS, "git_branch": SkipReason.SUBPROCESS,
    "git_blame": SkipReason.SUBPROCESS, "git_stash": SkipReason.SUBPROCESS,
    "git_add": SkipReason.SUBPROCESS, "git_pull": SkipReason.SUBPROCESS,
    "grep_code": SkipReason.SUBPROCESS, "code_lint": SkipReason.SUBPROCESS,
    "security_scan": SkipReason.SUBPROCESS, "docker_ps": SkipReason.SUBPROCESS,
    "env_info": SkipReason.SUBPROCESS, "shell_session_manage": SkipReason.SUBPROCESS,
    # LLM — impl calls services.llm.llm_gateway.run_completion
    "structured_llm_task": SkipReason.LLM,
    # MODEL — impl loads sentence-transformers / RAG embedder / whisper / BLIP / bart / YOLO / spaCy
    "embedding_generate": SkipReason.MODEL, "classify_text": SkipReason.MODEL,
    "describe_image": SkipReason.MODEL, "analyze_image": SkipReason.MODEL,
    "search_memories": SkipReason.MODEL, "memory_search": SkipReason.MODEL,
    "memory_get": SkipReason.MODEL, "vector_search": SkipReason.MODEL,
    "vector_store": SkipReason.MODEL, "save_note": SkipReason.MODEL,
    "stt_file": SkipReason.MODEL, "tts_speak": SkipReason.MODEL,
    "detect_objects": SkipReason.MODEL, "ocr_image": SkipReason.MODEL,
    "nlp_analyze": SkipReason.MODEL, "extract_entities": SkipReason.MODEL,
    # MEDIA — needs a real image/audio/video/ics fixture + codec, or a matplotlib backend
    "image_resize": SkipReason.MEDIA, "detect_scenes": SkipReason.MEDIA,
    "extract_frames": SkipReason.MEDIA, "calendar_read": SkipReason.MEDIA,
    "plot_chart": SkipReason.MEDIA, "plot_scatter": SkipReason.MEDIA,
    "plot_histogram": SkipReason.MEDIA,
    # HARDWARE — pyautogui / pyperclip / screen grab
    "screenshot_desktop": SkipReason.HARDWARE, "clipboard_read": SkipReason.HARDWARE,
    # SCHEDULER — _get_scheduler() starts a BackgroundScheduler thread (apscheduler present here)
    "schedule_task": SkipReason.SCHEDULER, "cancel_task": SkipReason.SCHEDULER,
    "list_scheduled_tasks": SkipReason.SCHEDULER,
    # OPERATOR_STATE — hardcoded repo/operator path NOT redirected by LAYLA_DATA_DIR
    "log_event": SkipReason.OPERATOR_STATE,        # APPENDS to <agent>/.governance/layla-events.log
    "memory_stats": SkipReason.OPERATOR_STATE,     # sqlite3.connect(<agent>/layla.db) CREATES it + Chroma
    "trace_last_run": SkipReason.OPERATOR_STATE,   # reads <agent>/.governance/audit.log (hardcoded)
    "tool_metrics": SkipReason.OPERATOR_STATE,     # reads <agent>/.governance/audit.log (hardcoded)
    "sync_repo_cognition": SkipReason.OPERATOR_STATE,  # indexes the repo into the cognition store + embeds
}

# Pinned so any addition/removal forces a deliberate review (anti-accretion; the skip list is where
# rot hides). Bump only with a matching SKIP change and a written reason above.
EXPECTED_SKIP_COUNT = 70  # -2: send_webhook/discord_send moved to GUARDED (approval-gated)


def _is_guarded(meta: dict) -> bool:
    return (
        bool(meta.get("dangerous"))
        or bool(meta.get("require_approval"))
        or meta.get("risk_level") == "high"
    )


GUARDED: set[str] = {n for n, m in TOOLS.items() if _is_guarded(m)}
DRIVEN: list[str] = sorted(n for n in TOOLS if n not in GUARDED and n not in SKIP)

# Tools the harness EXISTS to catch: pure/local, historically shipped broken. If an over-broad skip
# list ever excludes one, this canary (asserted below) goes red.
CANARY_DRIVEN = {"math_eval", "search_codebase", "regex_test", "text_stats", "count_tokens"}

# The complement canary: tools that MUST stay skipped. If a critical skip entry is deleted the tool
# would be DRIVEN — which for these means a real subprocess/network/model/operator-write, not just a
# missed test. Asserting they are skipped defends the hand-maintained side of the list (the scar).
CANARY_SKIP = {
    "fetch_url": SkipReason.NETWORK,
    "git_status": SkipReason.SUBPROCESS,
    "structured_llm_task": SkipReason.LLM,
    "embedding_generate": SkipReason.MODEL,
    "schedule_task": SkipReason.SCHEDULER,
    "log_event": SkipReason.OPERATOR_STATE,
    "memory_stats": SkipReason.OPERATOR_STATE,
}


# --- per-tool schema + minimal args (memoized; recomputed at test time, never stored on meta) ---
_MODEL_CACHE: dict[str, tuple[dict, dict]] = {}

# A session temp dir for contained path-args. Required str params become a path INSIDE it: a valid
# string for any tool, "not found" for readers, and — if a writer slips through and its sandbox gate
# is satisfied — contained to temp, never the repo. Network tools (the only ones wanting url-shaped
# strings) are all in SKIP.
_TMP = Path(tempfile.mkdtemp(prefix="layla_smoke_"))
_REAL_FILE = _TMP / "real.txt"
_REAL_FILE.write_text("x,y\n1,2\n", encoding="utf-8")

# Validity / hermeticity overrides. Reason per entry. NEVER used to mask a failure — only to supply
# realistic minimal input, or to route a scan whose scope param DEFAULTS to the real workspace at a
# temp dir instead (workspace_map/project_discovery/search_codebase default root='' → cwd).
ARG_OVERRIDES: dict[str, dict] = {
    "workspace_map": {"root": str(_TMP)},                 # default root='' scans the REAL workspace
    "project_discovery": {"workspace_root": str(_TMP)},   # default '' scans the REAL workspace
    "search_codebase": {"symbol": "smoke", "root": str(_TMP)},  # default root='' scans real workspace
    "glob_files": {"pattern": "*.txt", "root": str(_TMP)},      # hermetic + a real glob
    "create_archive": {"paths": [str(_REAL_FILE)], "output": str(_TMP / "a.zip")},  # contain output
    "merge_pdf": {"paths": [], "output": str(_TMP / "m.pdf")},  # contain output (pypdf absent -> ok:false)
}


def _minimal_value(ann: Any) -> Any:
    """A schema-valid minimal value for a required parameter, derived from its RESOLVED type."""
    if ann is bool:
        return False
    if ann is int:
        return 1
    if ann is float:
        return 1.0
    if ann is str:
        return str(_TMP / "smoke_arg")
    if ann is bytes:
        return b"smoke"
    if ann is list:
        return []
    if ann is dict:
        return {}
    s = str(ann)  # typing constructs / PEP 604 unions (e.g. "list | None", "str | dict")
    if "str" in s:
        return str(_TMP / "smoke_arg")
    if "list" in s:
        return []
    if "dict" in s:
        return {}
    if "float" in s:
        return 1.0
    if "int" in s:
        return 1
    return str(_TMP / "smoke_arg")


def _schema_and_args(name: str) -> tuple[dict, dict]:
    """Derive a pydantic model from the signature, its JSON schema, and validated minimal args."""
    if name in _MODEL_CACHE:
        return _MODEL_CACHE[name]
    fn = TOOLS[name]["fn"]
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)  # resolves string annotations (impls use `from __future__ ...`)
    except Exception:
        hints = {}
    fields: dict[str, tuple] = {}
    required: list[tuple[str, Any]] = []
    for pn, p in sig.parameters.items():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue  # spec: skip *args / **kwargs
        ann = hints.get(pn, p.annotation)
        if ann is inspect.Parameter.empty:
            ann = Any
        if p.default is inspect.Parameter.empty:
            fields[pn] = (ann, ...)
            required.append((pn, ann))
        else:
            fields[pn] = (ann, p.default)
    with warnings.catch_warnings():
        # A tool param named like a BaseModel attribute (e.g. generate_sql's `schema`) warns but is
        # harmless — the model is a throwaway used only for schema + arg validation.
        warnings.simplefilter("ignore", UserWarning)
        Model = create_model(
            f"Args_{name}", __config__=ConfigDict(arbitrary_types_allowed=True), **fields
        )
        schema = Model.model_json_schema()
    args = {pn: _minimal_value(ann) for pn, ann in required}
    args.update(ARG_OVERRIDES.get(name, {}))
    validated = Model(**args)  # proves the synthesized args are schema-valid
    args = {k: getattr(validated, k) for k in args}
    _MODEL_CACHE[name] = (schema, args)
    return schema, args


class _ToolTimeout(Exception):
    pass


def _call_with_timeout(fn, kwargs: dict, timeout: float):
    """Cross-platform per-call timeout (Windows has no SIGALRM): run in a daemon thread, join with a
    deadline. A raise in the worker is re-raised here (with the worker traceback attached) so the
    'does not raise' assertion sees it — this is how math_eval's AttributeError surfaces. A worker
    that overruns cannot be force-killed in Python; it lingers as a daemon (dies at process exit)
    while the main thread returns immediately and fails the test."""
    box: dict[str, Any] = {}

    def _run():
        try:
            box["result"] = fn(**kwargs)
        except BaseException as exc:  # noqa: BLE001 — capture everything to re-raise on main thread
            box["exc"] = exc
            box["tb"] = traceback.format_exc()

    t = threading.Thread(target=_run, name="smoke-tool", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise _ToolTimeout(f"exceeded {timeout}s")
    if "exc" in box:
        exc = box["exc"]
        try:
            exc.add_note(box.get("tb", ""))  # py3.11+: keep the worker frames in the report
        except Exception:
            pass
        raise exc
    return box.get("result")


# ============================== the generic smoke ==============================
@pytest.mark.parametrize("name", DRIVEN, ids=DRIVEN)
def test_safe_tool_does_not_raise_on_minimal_args(name: str):
    """Each SAFE tool, called with schema-valid minimal args under a timeout, must not raise.

    A raise = a broken tool (the math_eval class). {"ok": False, ...} is a handled error and PASSES.
    """
    _schema, args = _schema_and_args(name)
    fn = TOOLS[name]["fn"]
    try:
        result = _call_with_timeout(fn, args, PER_CALL_TIMEOUT_S)
    except _ToolTimeout as e:
        pytest.fail(
            f"{name}: hung {e} on minimal valid args {args!r}. A hang means a real block "
            "(network/LLM/subprocess/input) or a heavy default scope — fix the tool, or add an "
            "explicit, reasoned entry to SKIP. Do NOT raise the timeout to paper over it."
        )
    except Exception as exc:  # noqa: BLE001
        note = "\n".join(getattr(exc, "__notes__", []))
        pytest.fail(
            f"{name}: RAISED on schema-valid minimal args {args!r} — a registered-but-dead tool, "
            f"the exact defect this harness exists to catch (cf. math_eval / ast.Mul).\n"
            f"{type(exc).__name__}: {exc}\n{note}"
        )
    # Contract: tools return a dict (usually with an 'ok' flag). Not required to be truthy.
    assert result is None or isinstance(result, dict), (
        f"{name}: returned {type(result).__name__}, expected dict"
    )


# ============================== the teeth (pin exact values) ==============================
# "Didn't raise" is not enough for pure compute: a try/except returning {"ok": false} would pass it
# while the tool is dead (search_codebase once returned 0 matches for everything). These pin the
# actual OUTPUT of the deterministic pure tools. Verified against the live registry.
def test_pure_tools_produce_correct_results():
    """Value-level teeth for the deterministic pure-compute tools. Reintroducing a real bug in any
    of these (e.g. math_eval's ast.Mul) turns this RED — not just 'raised', but 'wrong answer'."""
    def call(n, **kw):
        return _call_with_timeout(TOOLS[n]["fn"], kw, PER_CALL_TIMEOUT_S)

    r = call("math_eval", expression="2 + 2 * 3")
    assert r.get("ok") is True and r.get("result") == 8, f"math_eval precedence broken: {r}"

    r = call("regex_test", pattern=r"\d+", text="ab12cd")
    assert r.get("ok") is True and r.get("count") == 1, f"regex_test count wrong: {r}"
    assert r["matches"][0]["match"] == "12", f"regex_test match wrong: {r}"

    r = call("count_tokens", text="hello world")
    assert r.get("ok") is True and r.get("tokens", 0) > 0, f"count_tokens dead: {r}"

    r = call("text_stats", text="One. Two three.")
    assert r["counts"]["words"] == 3 and r["counts"]["sentences"] == 2, f"text_stats wrong: {r}"

    r = call("string_transform", text="Hello World", operations=["lower"])
    assert r.get("result") == "hello world", f"string_transform wrong: {r}"

    enc = call("base64_tool", data="hello", mode="encode")
    assert enc.get("result") == "aGVsbG8=", f"base64 encode wrong: {enc}"
    dec = call("base64_tool", data=enc["result"], mode="decode")
    assert dec.get("result") == "hello", f"base64 decode roundtrip wrong: {dec}"

    r = call("uuid_generate", count=2)
    assert len(r.get("uuids", [])) == 2, f"uuid_generate count wrong: {r}"

    r = call("password_generate", length=16)
    assert r.get("length") == 16 and len(r.get("password", "")) == 16, f"password_generate wrong: {r}"

    r = call("random_string", length=12)
    assert len(r.get("value", "")) == 12, f"random_string length wrong: {r}"

    r = call("sympy_solve", expression="x**2 - 4")
    assert set(map(str, r.get("solutions", []))) == {"-2", "2"}, f"sympy_solve wrong: {r}"

    r = call("json_schema", data='{"a":1,"b":"x"}')
    assert r["schema"]["properties"]["a"]["type"] == "integer", f"json_schema wrong: {r}"

    r = call("jwt_decode", token="eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.x")
    assert r["payload"]["sub"] == "1", f"jwt_decode wrong: {r}"

    r = call("timestamp_convert", value=1700000000, output_format="iso")
    assert str(r.get("result", "")).startswith("2023-11-14"), f"timestamp_convert wrong: {r}"

    r = call("cluster_data", data=[[1, 1], [1, 2], [9, 9], [9, 8]], n_clusters=2)
    lab = r.get("labels", [])
    assert r.get("n_clusters_found") == 2 and len(lab) == 4, f"cluster_data shape wrong: {r}"
    assert lab[0] == lab[1] and lab[2] == lab[3] and lab[0] != lab[2], f"cluster_data labels wrong: {r}"

    r = call("list_tools")
    assert r.get("total") == len(TOOLS), f"list_tools total != registry size: {r.get('total')}"


def test_math_eval_multiplication_is_alive():
    """Spec (4): the exact assertion that goes RED if the ast.Mul bug is reintroduced.

    The broken registry built `_SAFE_NODES` with the non-existent `ast.Mul`, raising AttributeError
    while assembling the tuple — BEFORE the try/except and on EVERY input. So both the generic smoke
    (does-not-raise) and this targeted check catch it. Multiplication is the operator the bug
    corrupts: `6*7` needs the ast.Mult handler, so a wrong/absent one yields != 42 and a reintroduced
    ast.Mul raises outright. Either way, RED."""
    fn = TOOLS["math_eval"]["fn"]
    out = fn(expression="6*7")  # must not raise
    assert out.get("ok") is True, f"math_eval('6*7') not ok: {out}"
    assert out.get("result") == 42, f"math_eval('6*7') = {out.get('result')}, expected 42"


# ============================== burn-down (skip list cannot rot) ==============================
def test_partition_covers_every_tool():
    """No tool escapes classification. Driven ∪ Skip ∪ Guarded == the whole registry, disjoint.
    This is the anti-silent-skip guarantee: a new tool is DRIVEN by default (and must pass or be
    explicitly skipped), never quietly untested."""
    driven, skip, guarded = set(DRIVEN), set(SKIP), GUARDED
    assert driven | skip | guarded == set(TOOLS), (
        f"unclassified tools: {sorted(set(TOOLS) - (driven | skip | guarded))}"
    )
    assert driven.isdisjoint(skip) and driven.isdisjoint(guarded) and skip.isdisjoint(guarded), (
        f"overlap: skip&guarded={sorted(skip & guarded)}, driven&skip={sorted(driven & skip)}"
    )


def test_skip_entries_still_exist():
    """A skipped tool that was removed/renamed leaves a stale entry — the 'removed' half of the
    burn-down. Delete it from SKIP (and bump EXPECTED_SKIP_COUNT) when the tool goes."""
    stale = sorted(set(SKIP) - set(TOOLS))
    assert not stale, f"SKIP names no longer in registry (remove them): {stale}"


def test_skip_is_not_redundant_with_meta_guard():
    """If a skipped tool gains dangerous/require_approval/high meta, it is now covered by GUARDED and
    its explicit SKIP entry is redundant. Fires so the stale entry gets pruned."""
    redundant = sorted(set(SKIP) & GUARDED)
    assert not redundant, f"SKIP entries now guarded by meta (drop from SKIP): {redundant}"


def test_skip_reasons_are_known():
    assert all(isinstance(r, SkipReason) for r in SKIP.values())


def test_skip_count_is_pinned():
    """Anti-accretion: any change to the skip list must be deliberate."""
    assert len(SKIP) == EXPECTED_SKIP_COUNT, (
        f"SKIP has {len(SKIP)} entries, pinned at {EXPECTED_SKIP_COUNT}. Update EXPECTED_SKIP_COUNT "
        "and justify the change in the SKIP comments."
    )


def test_canaries_are_driven_not_skipped():
    """Defends the scar: the tools this harness exists to catch (math_eval, search_codebase, ...)
    must be in DRIVEN, never accidentally excluded by an over-broad skip/guard."""
    missing = sorted(CANARY_DRIVEN - set(DRIVEN))
    assert not missing, f"canary tools not in DRIVEN (the harness would miss them): {missing}"


def test_hazard_tools_are_skipped():
    """The complement canary. A denylist's failure mode is a DELETED entry: a hazardous tool then
    gets DRIVEN and does the real subprocess/network/model/operator-write. These specific hazards
    must stay skipped (with the expected reason). This is the guard against the hand-maintained-list
    scar — it asserts the very instances the list exists to catch are still caught."""
    for name, reason in CANARY_SKIP.items():
        assert name in TOOLS, f"hazard canary {name} vanished from registry — update CANARY_SKIP"
        assert SKIP.get(name) == reason, (
            f"{name} must be SKIP={reason.name} but is {SKIP.get(name)}; if it were driven it would "
            "do the real hazardous op, not merely go untested"
        )


def test_driven_set_is_substantial():
    """A guard against the whole thing silently collapsing to near-zero driven tools."""
    assert len(DRIVEN) >= 80, f"only {len(DRIVEN)} driven tools — partition likely broke"
