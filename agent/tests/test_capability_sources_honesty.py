"""The OTHER capability sources — the ones that can make the manifest lie anyway.

.identity/capabilities.md is not the only thing that tells the model what it can do. Two more
sources write into the same prompt, and a third (the tool declarations) is what the model actually
reasons from. When they disagree with the manifest, the manifest loses — it is advisory prose, while
a declared tool is an affordance and the rank-unlock string is an assertion in the system prompt.

These tests pin the three that were found contradicting it, plus the outbound hole next to them.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ============================ C1: the rank-unlock table ============================

def test_every_named_unlock_maps_to_a_config_key():
    """The table is concatenated into system_instructions by name. A name with no key behind it is
    a capability claim with no implementation — which is exactly what "Cross-aspect synthesis" and
    "Teacher mode" were."""
    from services.personality.maturity_engine import _RANK_UNLOCKS

    for row in _RANK_UNLOCKS:
        assert len(row) == 5, f"unlock row is missing its config-key tuple: {row}"
        min_rank, utype, name, desc, keys = row
        assert keys, (
            f"unlock {name!r} (rank {min_rank}) names a capability with no config key behind it. "
            "Wire it or drop it — do not let the prompt assert it."
        )


def test_named_unlock_keys_are_actually_read_somewhere():
    """A key that is only ever WRITTEN is not a capability either. autonomous_research_mode was
    written in two places, listed in the example config, and read nowhere in the repo."""
    import re

    from services.personality.maturity_engine import _RANK_UNLOCKS

    # Files that only plumb config (define defaults / schema) do not count as readers — and neither
    # does maturity_engine.py itself, which holds the table literal: without that exclusion the
    # declaration IS its own evidence and this test can never fail.
    plumbing = {"runtime_safety.py", "config_schema.py", "maturity_engine.py"}
    sources = [
        p for p in AGENT_DIR.rglob("*.py")
        if "tests" not in p.parts and p.name not in plumbing
    ]
    blobs = []
    for p in sources:
        try:
            blobs.append((p.name, p.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue

    for _rank, _t, name, _d, keys in _RANK_UNLOCKS:
        for key in keys:
            readers = [fn for fn, txt in blobs if re.search(rf'["\']{re.escape(key)}["\']', txt)]
            assert readers, (
                f"unlock {name!r} is gated on config key {key!r}, which nothing outside config "
                f"plumbing reads. The prompt would assert a capability with no code path."
            )


def test_earned_but_disabled_capability_is_not_claimed(monkeypatch):
    """The maturity gate DISABLES below rank but never re-enables above it, so past the threshold
    the feature is whatever setup_profiles left it. Rank alone must not make her claim it."""
    import runtime_safety
    from services.personality import maturity_engine

    keys = [k for row in maturity_engine._RANK_UNLOCKS for k in row[4]]
    base = dict(runtime_safety.load_config())

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {**base, **{k: False for k in keys}})
    assert maturity_engine.get_unlocks_text({"rank": 99}) == "", (
        "every gated feature is switched off, yet the prompt still told her she has them"
    )

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {**base, **{k: True for k in keys}})
    text = maturity_engine.get_unlocks_text({"rank": 99})
    assert "Your current capabilities:" in text and "Proactive suggestions" in text, (
        f"with the features on, the earned unlocks must be named; got {text!r}"
    )


def test_growth_narrative_does_not_announce_a_disabled_unlock(monkeypatch):
    """get_growth_narrative says "I recently unlocked X" out loud — same rule as the prompt."""
    import runtime_safety
    from services.personality import maturity_engine

    keys = [k for row in maturity_engine._RANK_UNLOCKS for k in row[4]]
    base = dict(runtime_safety.load_config())
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {**base, **{k: False for k in keys}})

    narrative = maturity_engine.get_growth_narrative()
    assert "recently unlocked" not in narrative, (
        f"announced an unlock while every gated feature is off: {narrative!r}"
    )


def _strip_js_comments(src: str) -> str:
    """Remove `//` and `/* */` comments, leaving string/template literals intact.

    Needed because asserting a symbol "appears in the file" cannot tell live code from a comment
    that happens to name the symbol — which is exactly how the assertion below passed while the
    code it guards was renamed. Replaces comment bodies with spaces so offsets are preserved.
    """
    out = []
    i, n = 0, len(src)
    quote = None
    while i < n:
        ch = src[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def test_all_unlocks_ladder_is_the_single_source_for_the_ui():
    """growth.js used to hardcode its own copy of the ladder, so trimming a fake capability from the
    table left the user still reading "Teacher mode — Rank 12" in the locked preview."""
    from services.personality.maturity_engine import _RANK_UNLOCKS, all_unlocks

    ladder = all_unlocks(rank=5)
    assert [u["name"] for u in ladder] == [r[2] for r in _RANK_UNLOCKS]
    assert [u["earned"] for u in ladder] == [5 >= r[0] for r in _RANK_UNLOCKS]

    js = (AGENT_DIR / "ui" / "components" / "growth.js").read_text(encoding="utf-8")
    code = _strip_js_comments(js)

    # Asserted against COMMENT-STRIPPED source. `assert "unlocks_all" in js` was green even with the
    # live line renamed, because the comment two lines above the real access reads "...read from the
    # server's ladder (maturity.unlocks_all) rather than a hardcoded copy". The guard was satisfied by
    # the prose describing the thing it was supposed to be checking — the same defect F6 was rewritten
    # to remove. A guard that a comment can satisfy is documentation, not a test.
    assert "maturity.unlocks_all" in code, (
        "growth.js must render the ladder from the server (`maturity.unlocks_all`), not a local copy. "
        "Checked against comment-stripped source, so a mention in prose will not satisfy it."
    )
    for dead in ("Teacher mode", "Cross-aspect synthesis", "Research autonomy"):
        assert dead not in code, f"growth.js still advertises the removed unlock {dead!r}"


# ==================== C2: tool declarations vs installed dependencies ====================

def test_web_tools_declare_their_optional_dependency():
    """Every web/search tool whose impl imports an optional library must say so in its manifest,
    or the gate below cannot know to withhold it."""
    from layla.tools.domains.web import TOOLS as WEB_TOOLS

    expected = {
        "fetch_article": "trafilatura", "wiki_search": "wikipedia",
        "ddg_search": "duckduckgo_search", "arxiv_search": "arxiv",
        "browser_navigate": "playwright", "browser_search": "playwright",
        "browser_screenshot": "playwright", "browser_click": "playwright",
        "browser_fill": "playwright", "crawl_site": "trafilatura",
        "extract_links": "trafilatura", "rss_feed": "feedparser",
    }
    for tool, mod in expected.items():
        assert WEB_TOOLS[tool].get("requires") == mod, (
            f"{tool} imports {mod} but does not declare requires={mod!r}"
        )
    # The three that need nothing extra must stay ungated.
    for always_on in ("fetch_url", "http_request", "check_url"):
        assert not WEB_TOOLS[always_on].get("requires"), (
            f"{always_on} works on a bare install; gating it would hide a working tool"
        )


def test_tool_with_missing_dependency_is_withheld_from_the_model():
    from layla.tools.registry import TOOLS
    from services.agent.llm_decision import _drop_missing_dependency_tools, _module_installed

    _module_installed.cache_clear()
    kept = _drop_missing_dependency_tools(set(TOOLS), TOOLS)
    for name, meta in TOOLS.items():
        req = meta.get("requires") if isinstance(meta, dict) else None
        if req and not _module_installed(str(req)):
            assert name not in kept, (
                f"{name} was offered to the model although {req!r} is not installed — calling it can "
                f"only ever return 'not installed'"
            )


def test_the_gate_is_dependency_driven_not_a_blocklist(monkeypatch):
    """Same tool, both ways: present -> offered, absent -> withheld."""
    import importlib.util

    from layla.tools.registry import TOOLS
    from services.agent.llm_decision import _drop_missing_dependency_tools, _module_installed

    real = importlib.util.find_spec

    def fake(name, *a, **k):
        if name == "duckduckgo_search":
            return object()
        return real(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    _module_installed.cache_clear()
    assert "ddg_search" in _drop_missing_dependency_tools(set(TOOLS), TOOLS)

    monkeypatch.setattr(importlib.util, "find_spec", real)
    _module_installed.cache_clear()
    if importlib.util.find_spec("duckduckgo_search") is None:
        assert "ddg_search" not in _drop_missing_dependency_tools(set(TOOLS), TOOLS)
    _module_installed.cache_clear()


def test_dependency_gate_does_not_shrink_the_registry():
    """The tools stay REGISTERED — skill packs and the pinned tool count must not move."""
    from layla.tools.registry import TOOLS

    assert "ddg_search" in TOOLS and "browser_navigate" in TOOLS


def test_dependency_gate_fails_open_on_a_probe_error(monkeypatch):
    """A namespace/partial package can make find_spec raise. Hiding a working tool on a probe error
    is worse than offering one that refuses, so the gate must fail open."""
    import importlib.util

    from services.agent.llm_decision import _module_installed

    def boom(name, *a, **k):
        raise ValueError("partial package")

    monkeypatch.setattr(importlib.util, "find_spec", boom)
    _module_installed.cache_clear()
    assert _module_installed("anything") is True
    _module_installed.cache_clear()


# ==================== C3: send_webhook / discord_send egress ====================

@pytest.fixture()
def loopback_server():
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", hits
    srv.shutdown()


def test_send_webhook_is_ssrf_guarded(loopback_server):
    """A model-supplied url must not reach loopback / link-local. This is the exfil path."""
    from layla.tools.impl.automation import send_webhook

    base, hits = loopback_server
    out = send_webhook(f"{base}/exfil", {"secret": "user-private-data"})
    assert out.get("ok") is False, "unguarded POST to loopback succeeded"
    assert "SSRF" in str(out.get("error", "")), f"blocked, but not by the guard: {out}"
    assert hits == [], f"the request actually reached the server: {hits}"


def test_discord_send_cannot_bypass_the_webhook_guard(loopback_server):
    """discord_send takes a caller-supplied webhook_url and forwards to send_webhook — gating only
    send_webhook would have left an identical unapproved outbound POST one call away."""
    from layla.tools.impl.automation import discord_send

    base, hits = loopback_server
    out = discord_send(content="hi", webhook_url=f"{base}/discord")
    assert out.get("ok") is False and hits == [], f"discord_send bypassed the guard: {out} {hits}"


def test_outbound_webhook_tools_are_approval_gated():
    import runtime_safety
    from layla.tools.domains.automation import TOOLS as AUTOMATION_TOOLS
    from services.tools.tool_permissions import _EXEC_TOOLS

    for tool in ("send_webhook", "discord_send"):
        meta = AUTOMATION_TOOLS[tool]
        assert meta["dangerous"] and meta["require_approval"], (
            f"{tool} sends model-chosen data to a model-chosen host without approval"
        )
        assert tool in runtime_safety.DANGEROUS_TOOLS, f"{tool} missing from DANGEROUS_TOOLS"
        assert tool in _EXEC_TOOLS, f"{tool} missing from the allow_run permission set"


def test_executor_refuses_webhook_without_allow_run(tmp_path, monkeypatch):
    """Driven through the real executor, not asserted from metadata."""
    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path))
    from core.executor import run_tool
    from services.tools.tool_permissions import clear_tool_permissions, set_tool_permissions

    set_tool_permissions(allow_write=True, allow_run=False)
    try:
        for tool, args in (
            ("send_webhook", {"url": "https://example.com/hook", "payload": {"x": 1}}),
            ("discord_send", {"content": "hi", "webhook_url": "https://example.com/hook"}),
        ):
            out = run_tool(tool, dict(args))
            assert out.get("ok") is False and "allow_run" in str(out.get("error", "")), (
                f"{tool} ran in a turn that never granted allow_run: {out}"
            )
    finally:
        clear_tool_permissions()


def test_approvals_file_gates_the_webhook(tmp_path, monkeypatch):
    """is_tool_allowed must consult approvals.json for these, like the other dangerous tools."""
    import runtime_safety

    approval = tmp_path / "approvals.json"
    monkeypatch.setattr(runtime_safety, "APPROVAL_FILE", approval)

    approval.write_text(json.dumps({}), encoding="utf-8")
    assert runtime_safety.is_tool_allowed("send_webhook") is False
    assert runtime_safety.is_tool_allowed("discord_send") is False

    approval.write_text(json.dumps({"send_webhook": True}), encoding="utf-8")
    assert runtime_safety.is_tool_allowed("send_webhook") is True
    assert runtime_safety.is_tool_allowed("discord_send") is False, "approval must be per-tool"


def test_manifest_tool_count_matches_what_the_model_is_actually_offered():
    """R4: "200 working tools" was FALSE AS DELIVERED.

    registry.TOOLS holds 200, but `_drop_missing_dependency_tools` withholds every tool whose optional
    library is missing — 12 of them on a bare install (arxiv/ddg/wiki search, the five browser_* tools,
    crawl_site, extract_links, fetch_article, rss_feed). The model is shown 188 and was being told it had
    200 "working" ones, which is the manifest lying in the direction that matters most: it is the file she
    answers capability questions FROM.

    This test pins BOTH numbers to the code, so the claim cannot drift from reality in either direction.
    """
    import re
    from pathlib import Path

    from layla.tools.registry import TOOLS
    from services.agent.llm_decision import _drop_missing_dependency_tools, _module_installed

    _module_installed.cache_clear()
    registered = len(TOOLS)
    offered = len(_drop_missing_dependency_tools(set(TOOLS), TOOLS))
    withheld = registered - offered

    text = (Path(__file__).resolve().parent.parent.parent / ".identity" / "capabilities.md").read_text(
        encoding="utf-8"
    )

    # ------------------------------------------------------------------------------------------
    # Assert against the PROMPT-CORE block, not the 14 KB file.
    #
    # This test used to check `re.search(rf"\b{offered}\b", text)` — "188 appears SOMEWHERE in the
    # file". Measured: mutating ONLY the prompt-core line the model actually reads, from
    # "200 tools registered, 188 actually offered here" to "200 actually offered", left this suite
    # GREEN at 104 passed. The number survived elsewhere in the human-facing prose, so the guard
    # passed while the sentence the model reasons from had been turned into the exact lie the test
    # is named after.
    #
    # Only the delimited block is injected (see `_capability_manifest_core`), so only the delimited
    # block is worth asserting on — and the numbers have to be checked in their ROLES, not merely
    # present, or swapping them reads as fine.
    # ------------------------------------------------------------------------------------------
    from services.prompts.prompt_builder import REPO_ROOT, _capability_manifest_core

    _capability_manifest_core.cache_clear()
    core = _capability_manifest_core(REPO_ROOT)
    assert core, (
        "the PROMPT-CORE block did not resolve — the model is being shown no capability manifest at all, "
        "and every assertion below would pass vacuously against the empty string"
    )

    m_reg = re.search(r"(\d+)\s+tools?\s+(?:are\s+)?registered", core)
    assert m_reg, (
        f"the prompt-core block never states the registered tool count. It must say so in words the "
        f"model reads, not only in the human-facing prose below the block.\n---\n{core[:400]}"
    )
    assert int(m_reg.group(1)) == registered, (
        f"prompt-core claims {m_reg.group(1)} tools registered; the registry holds {registered}."
    )

    m_off = re.search(r"(\d+)\s+(?:actually\s+)?offered", core)
    assert m_off, (
        f"the prompt-core block never states how many tools are actually OFFERED ({offered}). Quoting "
        f"only the registered count tells her she has {withheld} capabilities she will never be given."
    )
    assert int(m_off.group(1)) == offered, (
        f"prompt-core claims {m_off.group(1)} tools are actually offered; the real number after "
        f"_drop_missing_dependency_tools is {offered}. This is the exact mutation the old "
        f"'is 188 anywhere in the file' assertion could not see."
    )

    if withheld:
        assert int(m_reg.group(1)) != int(m_off.group(1)), (
            f"prompt-core states the same number ({m_reg.group(1)}) for registered and offered, but "
            f"{withheld} tools are withheld on this box."
        )

    assert "working tools" not in text, (
        "'N working tools' is the phrasing that made this claim false — the registered count is not the "
        "count that works on this box. State registered vs offered, or state neither."
    )


def test_prompt_core_keeps_the_anti_recitation_line_at_BOTH_ends():
    """R3 duplicated "Do not recite this list" to the FRONT of the block so truncation cannot reach it.

    The fix was right and the guard was missing: the tests only ever asserted the TAIL copy
    (`_MANIFEST_TAIL` in test_capability_manifest.py), so deleting the leading line left the suite
    GREEN — and the leading line is the one that actually survives, because the block is tail-truncated
    under budget pressure. Measured on a real-aspect capability turn at n_ctx 2048, the trailing copy was
    already gone.

    So: assert the FRONT copy specifically, by position, not by "appears somewhere".
    """
    from services.prompts.prompt_builder import REPO_ROOT, _capability_manifest_core

    _capability_manifest_core.cache_clear()
    core = _capability_manifest_core(REPO_ROOT).strip()
    assert core, "the PROMPT-CORE block did not resolve"

    needle = "Do not recite this list"
    lines = [ln.strip() for ln in core.split("\n") if ln.strip()]

    assert needle in lines[0], (
        f"the anti-recitation instruction is not the FIRST line of the prompt-core block. It is the only "
        f"copy that cannot be truncated away, so it is the one that has to be there.\n"
        f"first line was: {lines[0]!r}"
    )
    assert needle in lines[-1], (
        f"the anti-recitation instruction is not the LAST line of the prompt-core block. Recency matters "
        f"to a small model when the block does fit.\nlast line was: {lines[-1]!r}"
    )
    assert core.count(needle) >= 2, (
        "the two copies have collapsed into one — which one survived depends on where truncation lands"
    )
