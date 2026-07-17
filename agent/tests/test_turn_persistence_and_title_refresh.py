"""BL-243 + BL-244 + BL-245 — the conversation rail: persistence, the async title, the layout.

These are OBSERVATION tests, not source-greps. Each drives a real surface (the /agent HTTP
stream, the /conversations API, or the actual CSS/JS text the browser is served) and then reads
the resulting DB rows or endpoint payloads. A test that greps for a call site cannot fail when
the wiring breaks — only when the source string moves.

Each test proves ONE thing and fails for its OWN reason. Where two tests could collapse into
"the router persists things", they are deliberately split per STATUS, because BL-245 was seven
independent done-frames and a single test would let six of them rot.

Scope honesty: the browser-level proofs (that the rail element actually re-renders, and that the
title stacks below the meta chips) were run against a live Chromium DOM by hand — Playwright is
not installed in this environment, so they are NOT reproduced here. What IS locked here is
everything reachable from Python: the persistence of every done-frame, the learn/no-learn
decision per status, the poll endpoint's contract, and the CSS/JS invariants the rail layout
depends on.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

UI_DIR = AGENT_DIR / "ui"


def _join_bg_threads(timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        alive = [t for t in threading.enumerate() if t.name in ("auto-learn", "conv-entity", "title-synth")]
        if not alive:
            return
        for t in alive:
            t.join(timeout=max(0.05, deadline - time.time()))


def _messages(cid: str) -> list[dict]:
    from layla.memory.db import get_conversation_messages

    return list(get_conversation_messages(cid, limit=50) or [])


def _learning_rows() -> list[dict]:
    from layla.memory.db import get_recent_learnings

    return list(get_recent_learnings(n=50) or [])


def _reset_fingerprints():
    import collections

    import services.infrastructure.outcome_writer as ow

    ow._recent_learning_fingerprints = collections.OrderedDict()


@pytest.fixture
def hermetic_cfg(monkeypatch):
    """Deterministic paths only — no model is loaded in a unit test."""
    import runtime_safety

    base = dict(runtime_safety.load_config() or {})
    base.update(
        {
            "operator_memory_llm_enabled": False,
            "conversation_title_synthesis_enabled": False,
            "identity_capture_enabled": False,
            "emotional_presence_enabled": False,
        }
    )
    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: base)
    return base


def _client(monkeypatch, *, result: dict):
    """A /agent app whose orchestrator returns `result`, with nothing else stubbed.

    commit_turn is deliberately REAL — it is what is under test. `result` is what run_agent's
    holder yields, which is exactly how the router learns a turn timed out / was aborted / etc.

    Every setattr here uses monkeypatch's DEFAULT raising=True on purpose. An earlier draft of this
    fixture patched `run_agent_loop` and `_try_fast_path` with raising=False — neither symbol
    exists. Nothing was stubbed, the requests quietly fell through to the fast path, and the tests
    passed while exercising none of the code they name. raising=True turns that silent lie into a
    loud AttributeError the moment a symbol is renamed.
    """
    from routers import agent as ag

    monkeypatch.setattr(ag, "get_touch_activity", lambda: (lambda: None))
    monkeypatch.setattr(ag, "get_append_history", lambda: (lambda *a, **k: None))
    monkeypatch.setattr(ag, "get_conv_history", lambda cid: [])
    monkeypatch.setattr(ag, "append_conv_history", lambda *a, **k: None)
    monkeypatch.setattr("services.safety.auth.is_direct_local", lambda h, host: True)
    monkeypatch.setattr(ag, "_model_ready_message", lambda: None)
    # Force the FULL generator: the router routes any self-contained question to agen_fast, which
    # never sees these status done-frames. The router imports this symbol from its source module
    # inside the request, so patch it there, not on `ag`.
    monkeypatch.setattr("services.agent.response_builder.is_self_contained_question", lambda *a, **k: False)
    # THE orchestrator seam the router actually calls (run_agent -> _dispatch_autonomous_run).
    monkeypatch.setattr(ag, "_dispatch_autonomous_run", lambda *a, **k: dict(result))

    app = FastAPI()
    app.include_router(ag.router)
    return TestClient(app, raise_server_exceptions=False)


def _post(tc: TestClient, cid: str, msg: str):
    return tc.post("/agent", json={"message": msg, "stream": True, "conversation_id": cid})


# ══════════════════════════════════════════════════════════════════════════════════════════
# BL-245 — every failing done-frame must still persist the operator's message.
# One test PER STATUS: these were seven independent code paths, and a single combined test
# would pass while six of them silently regressed.
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "status,reply,expected_assistant_text",
    [
        # `expected_assistant_text` is what the operator actually SAW in the bubble for that status.
        # Asserting it — not merely "some assistant row exists" — is what gives these tests teeth.
        # The generators carry a last-resort `finally` net that persists ANY uncommitted turn, so a
        # test that only checked "the user row exists" PASSED with the per-status commit deleted:
        # the net silently covered for it. It writes a generic placeholder, so pinning the
        # status-specific text is what distinguishes "this frame persisted correctly" from "the net
        # caught it". This exact vacuity was caught by breaking the code and watching these stay green.
        ("timeout", "I couldn't reply just then.", "Request took too long and was stopped."),
        ("client_abort", "partial answer so far", "partial answer so far"),
        ("system_busy", "I couldn't reply just then.", "System is under load"),
        ("pipeline_needs_input", "Which database are you using?", "Which database are you using?"),
    ],
)
def test_failing_done_frame_persists_the_users_message(
    status, reply, expected_assistant_text, monkeypatch, isolated_db, hermetic_cfg
):
    """The operator typed something; a failed run must not make it vanish on reload."""
    tc = _client(monkeypatch, result={"status": status, "response": reply, "aspect": "morrigan"})
    cid = f"conv-{status}"
    assert _messages(cid) == [], "fixture must start empty"

    r = _post(tc, cid, "How do I index this table?")
    assert r.status_code == 200, r.text
    _join_bg_threads()

    rows = _messages(cid)
    users = [m for m in rows if m.get("role") == "user"]
    assert len(users) == 1, f"{status}: expected exactly ONE user row, got {rows!r}"
    assert "How do I index this table?" in str(users[0].get("content") or ""), rows

    assistants = [str(m.get("content") or "") for m in rows if m.get("role") == "assistant"]
    assert len(assistants) == 1, f"{status}: expected exactly ONE assistant row, got {rows!r}"
    assert expected_assistant_text in assistants[0], (
        f"{status}: the transcript must keep the reply the operator SAW for THIS status, not a "
        f"generic net placeholder. got {assistants[0]!r}"
    )


def test_error_done_frame_persists_the_users_message(monkeypatch, isolated_db, hermetic_cfg):
    """The error_holder frame — distinct path from the status frames above (it fires before
    `result` even exists), so it gets its own test rather than a parametrize case."""
    from routers import agent as ag

    def _boom(*a, **k):
        raise RuntimeError("simulated orchestrator explosion")

    tc = _client(monkeypatch, result={})
    monkeypatch.setattr(ag, "_dispatch_autonomous_run", _boom)

    cid = "conv-error"
    r = _post(tc, cid, "Please summarise this file for me")
    assert r.status_code == 200, r.text
    _join_bg_threads()

    rows = _messages(cid)
    users = [m for m in rows if m.get("role") == "user"]
    assert len(users) == 1, f"an errored turn must persist the operator's message exactly once; got {rows!r}"
    assert "summarise this file" in str(users[0].get("content") or "")
    # Pin the sanitized error the operator SAW, not just "an assistant row exists" — otherwise the
    # generators' last-resort `finally` net satisfies this test with a placeholder and the error
    # frame's own commit could be deleted without a single test going red.
    assistants = [str(m.get("content") or "") for m in rows if m.get("role") == "assistant"]
    assert len(assistants) == 1, rows
    assert "The request failed while processing" in assistants[0], assistants


def test_error_frame_does_not_leak_the_raw_exception_into_the_transcript(monkeypatch, isolated_db, hermetic_cfg):
    """Persisting the error must not persist internal detail. Distinct from the test above:
    that one fails if nothing is stored, this one fails if the WRONG thing is stored."""
    from routers import agent as ag

    def _boom(*a, **k):
        raise RuntimeError("C:/secret/internal/path.py blew up at row 42")

    tc = _client(monkeypatch, result={})
    monkeypatch.setattr(ag, "_dispatch_autonomous_run", _boom)

    cid = "conv-error-leak"
    _post(tc, cid, "Please summarise this file for me")
    _join_bg_threads()

    blob = json.dumps(_messages(cid))
    assert "secret/internal/path.py" not in blob, "the raw exception must never reach the transcript"


# ══════════════════════════════════════════════════════════════════════════════════════════
# BL-245 — the learn/no-learn decision, per status. Persistence is NOT gated; learning is.
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_timed_out_turn_still_learns_what_the_operator_said(isolated_db, hermetic_cfg, monkeypatch):
    """Run mechanics do not invalidate the operator's statement — the extractor reads THEIR turn.
    Fails if someone "helpfully" adds timeout back to _NO_LEARN_STATUSES."""
    import runtime_safety

    cfg = dict(runtime_safety.load_config() or {})
    cfg["operator_memory_llm_enabled"] = False
    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: cfg)

    from services.agent.turn_commit import commit_turn

    _reset_fingerprints()
    assert _learning_rows() == []

    commit_turn(
        "conv-timeout-learn",
        "I prefer tea over coffee, always",
        "Request took too long and was stopped.",
        aspect_id="morrigan",
        status="timeout",
    )
    _join_bg_threads()

    contents = [str(x.get("content") or "") for x in _learning_rows()]
    assert any("tea" in c for c in contents), (
        "a timed-out run must still learn what the OPERATOR said; got " + repr(contents)
    )


def test_system_busy_turn_does_not_spawn_llm_learning(isolated_db, hermetic_cfg):
    """system_busy is the governor REFUSING llm work. Learning makes its own LLM call, so
    answering 'out of resources' with more LLM work is incoherent. Distinct from the blocked/
    refused guards: this one fails if "system_busy" is dropped from _NO_LEARN_STATUSES."""
    from services.agent.turn_commit import commit_turn

    _reset_fingerprints()
    assert _learning_rows() == []

    commit_turn(
        "conv-busy",
        "I prefer tea over coffee, always",
        "System is under load (CPU or RAM). Try again in a moment.",
        aspect_id="morrigan",
        status="system_busy",
    )
    _join_bg_threads()

    assert _learning_rows() == [], "a system_busy turn must not start an LLM extraction"


def test_system_busy_turn_is_still_persisted(isolated_db, hermetic_cfg):
    """The no-learn decision must not be confused for a no-persist decision. This fails if
    someone 'optimises' the busy path by skipping commit_turn entirely."""
    from services.agent.turn_commit import commit_turn

    commit_turn(
        "conv-busy-persist",
        "I prefer tea over coffee, always",
        "System is under load (CPU or RAM). Try again in a moment.",
        aspect_id="morrigan",
        status="system_busy",
    )
    _join_bg_threads()

    roles = [m.get("role") for m in _messages("conv-busy-persist")]
    assert "user" in roles and "assistant" in roles, "withholding LEARNING must not withhold the TRANSCRIPT"


# ══════════════════════════════════════════════════════════════════════════════════════════
# BL-243 — the poll endpoint the rail depends on.
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_title_endpoint_reports_pending_while_synth_runs_then_the_new_title(isolated_db, monkeypatch):
    """The rail's whole bounded poll hangs off `synth_pending`. If it never reports True the UI
    stops after one tick and the operator keeps the extractive title — the original bug."""
    import runtime_safety

    cfg = dict(runtime_safety.load_config() or {})
    cfg.update({"conversation_title_synthesis_enabled": True, "identity_capture_enabled": False,
                "emotional_presence_enabled": False, "operator_memory_llm_enabled": False})
    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: cfg)

    release = threading.Event()

    def _slow_synth(user_msg, assistant_text):
        release.wait(timeout=5)          # hold the synth open so we can observe the pending state
        return "Synthesized Topic Name"

    monkeypatch.setattr(
        "services.agent.title_synthesizer.synthesize_conversation_title", _slow_synth, raising=False
    )

    from routers.conversations import get_conversation_title_api
    from services.agent.turn_commit import commit_turn

    cid = "conv-title-poll"
    commit_turn(cid, "How do hash maps work?", "They use a hash function.", aspect_id="morrigan")

    # While the synth thread is held open, the endpoint must say "keep polling".
    during = json.loads(bytes(get_conversation_title_api(cid).body).decode())
    assert during["ok"] is True
    assert during["synth_pending"] is True, "must report the in-flight synth or the UI stops polling"
    title_at_done = during["title"]

    release.set()
    _join_bg_threads()

    after = json.loads(bytes(get_conversation_title_api(cid).body).decode())
    assert after["synth_pending"] is False, "must stop reporting pending once the synth finished"
    assert after["title"] == "Synthesized Topic Name", after
    assert after["title"] != title_at_done, "the whole point: the title CHANGES after the done-frame"


def test_title_endpoint_reports_not_pending_when_no_synth_runs(isolated_db, monkeypatch):
    """The bound on the poll. Distinct from the test above: that one fails if pending is never
    True, this one fails if pending is ALWAYS True — which would make every turn poll to its
    ceiling on a CPU-bound box."""
    import runtime_safety

    cfg = dict(runtime_safety.load_config() or {})
    cfg["conversation_title_synthesis_enabled"] = False        # synthesis off => nothing in flight
    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: cfg)

    from layla.memory.db import create_conversation
    from routers.conversations import get_conversation_title_api

    cid = "conv-no-synth"
    create_conversation(cid, title="Plain title", aspect_id="morrigan")
    d = json.loads(bytes(get_conversation_title_api(cid).body).decode())
    assert d["ok"] is True and d["synth_pending"] is False, d


def test_title_endpoint_404s_for_unknown_conversation(isolated_db):
    """The UI treats a non-ok body as 'stop polling'. A 500 here would look identical to the
    client but hides a real fault, so pin the 404."""
    from routers.conversations import get_conversation_title_api

    assert get_conversation_title_api("no-such-conversation").status_code == 404


# ══════════════════════════════════════════════════════════════════════════════════════════
# BL-244 — the rail layout invariants.
# These read the CSS/JS the browser is actually served. They are the weakest tests in this file
# and they are honest about it: they can prove the title is its own element and that the rules
# say what they must, but only a browser can prove it LOOKS right (done by hand, see docstring).
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_rail_renders_the_title_as_its_own_element():
    """The title was a BARE TEXT NODE sharing one inline -webkit-box with .conv-meta, which is
    why the chips pushed it onto a wrapped line. It must be its own element."""
    js = (UI_DIR / "components" / "conversations.js").read_text(encoding="utf-8")
    assert '<span class="sess-title">' in js, "the rail title must render into its own .sess-title element"


def test_rail_title_css_stacks_below_meta_and_clamps_to_two_lines():
    css = (UI_DIR / "css" / "layla.css").read_text(encoding="utf-8")
    import re

    prev = re.search(r"\.session-item \.sess-preview \{([^}]*)\}", css)
    title = re.search(r"\.session-item \.sess-title \{([^}]*)\}", css)
    assert prev and title, "the rail layout rules must exist"

    assert "flex-direction:column" in prev.group(1), "meta must stack ABOVE the title, not share its line"
    # fit-content sizing would shrink-wrap a long title into a narrow column and the 2-line clamp
    # would then eat most of it — this was a real defect caught by measuring the live DOM.
    assert "align-items:flex-start" not in prev.group(1), "the title must stretch to the rail width"
    assert "-webkit-line-clamp:2" in title.group(1), "the title clamps to 2 lines"
    assert "overflow-wrap:anywhere" in title.group(1), "break only when a word cannot fit"
    assert "word-break:break-word" not in title.group(1), "word-break chops ordinary words needlessly"
    # The old rule clamped .sess-preview itself, which is what dragged the meta chips into the clamp.
    assert "line-clamp" not in prev.group(1), ".sess-preview must not clamp; only .sess-title does"


def test_rail_css_comment_matches_the_rule_it_documents():
    """The comment said 'up to 2 lines' while the rule clamped 3. A comment that contradicts its
    rule is how the next reader gets misled."""
    css = (UI_DIR / "css" / "layla.css").read_text(encoding="utf-8")
    import re

    m = re.search(r"/\* Title clamps to (\w+) lines.*?\*/\s*\.session-item \.sess-title \{([^}]*)\}", css, re.S)
    assert m, "the .sess-title rule must carry the comment that documents its clamp"
    word_to_n = {"one": 1, "1": 1, "two": 2, "2": 2, "three": 3, "3": 3}
    raw = m.group(1).lower()
    assert raw in word_to_n, f"comment states an unparseable line count: {raw!r}"
    documented = word_to_n[raw]
    actual = int(re.search(r"-webkit-line-clamp:(\d+)", m.group(2)).group(1))
    assert documented == actual, f"comment says {documented} lines, rule clamps {actual}"


def test_service_worker_cache_version_bumped_for_this_ui_change():
    """stale-while-revalidate serves the OLD bundle on the first load after an update. For a bug
    the operator has been told was fixed three times, 'works on the second reload' is a fourth
    false report. The purge is the fix's delivery mechanism, so pin it."""
    sw = (UI_DIR / "sw.js").read_text(encoding="utf-8")
    import re

    v = int(re.search(r'const CACHE = "layla-ui-v(\d+)"', sw).group(1))
    assert v >= 15, f"bump CACHE past v14 so the rail fix reaches existing installs on first load (found v{v})"
