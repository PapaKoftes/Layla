"""Golden-set eval runner for Layla (BL-101 + capability tiers) — stdlib-only.

Runs a golden case set against a LIVE Layla server and reports a pass-rate. Historically
this was Q&A-only against `/v1/chat/completions`. It now understands a per-case ``kind`` so
the same rig can measure the parts of the product a mocked unit suite CANNOT:

    kind = "qa"        prompt -> /v1 answer, assertions checked against the text (default).
    kind = "tool"      prompt -> /agent turn, assert the model actually SELECTED/EXECUTED
                       the expected tool (the turn's `state.steps`), not merely answered.
    kind = "grounding" seed a fact via the memory router (POST /memory/import) BEFORE the
                       case, ask in a FRESH conversation, assert the answer used the fact.
    kind = "memory"    reuse one conversation_id across two turns, assert carry-over.

Why this exists: the ~4050-test unit suite MOCKS the model (conftest blocks real llama_cpp),
so a green suite is a plumbing signal, not product evidence. These cases run against a real
(tiny) model on a real server, so they are evidence.

Usage:
    python eval/run_golden.py [--base-url http://127.0.0.1:8000] [--model layla]
        [--cases eval/golden_set.json] [--kinds qa,tool,grounding,memory]
        [--fast] [--limit N] [--label NAME]

Assertion types: contains, icontains, not_contains, not_icontains, regex, not_contains_regex.
Exit code 0 always (it's a report, not a gate — the caller decides the floor).
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent

VALID_KINDS = ("qa", "tool", "grounding", "memory")


# ── Assertion checking ────────────────────────────────────────────────────────

def _check(assertion: dict, text: str) -> bool:
    t = assertion.get("type", "contains")
    v = str(assertion.get("value", ""))
    low = text.lower()
    if t == "contains":
        return v in text
    if t == "icontains":
        return v.lower() in low
    if t == "not_contains":
        return v not in text
    if t == "not_icontains":
        return v.lower() not in low
    if t == "regex":
        return re.search(v, text, re.MULTILINE) is not None
    if t == "not_contains_regex":
        return re.search(v, text, re.MULTILINE) is None
    return False


def _all_asserts(case: dict, text: str) -> bool:
    return all(_check(a, text) for a in case.get("assert", []))


# ── HTTP helpers (stdlib only) ────────────────────────────────────────────────

def _post_json(url: str, payload: dict, timeout: int) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _complete(base_url: str, model: str, prompt: str, timeout: int) -> str:
    """qa path — OpenAI-compatible /v1/chat/completions (unchanged, stateless)."""
    d = _post_json(
        base_url.rstrip("/") + "/v1/chat/completions",
        {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False},
        timeout,
    )
    return ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""


def _agent_turn(
    base_url: str,
    message: str,
    *,
    conversation_id: str = "",
    timeout: int = 180,
    allow_run: bool = False,
    allow_write: bool = False,
) -> dict:
    """One non-streaming /agent turn. Returns {response, steps, tools, raw}.

    `steps`/`tools` come from the turn's `state.steps` — the SAME structure the UI and
    decision loop record, where each step's `action` is the tool name that executed.
    """
    d = _post_json(
        base_url.rstrip("/") + "/agent",
        {
            "message": message,
            "conversation_id": conversation_id,
            "stream": False,
            "allow_run": allow_run,
            "allow_write": allow_write,
        },
        timeout,
    )
    response = str(d.get("response") or "")
    tools = _tools_from_agent_result(d)
    return {"response": response, "tools": tools, "raw": d}


def _tools_from_agent_result(d: dict) -> list[str]:
    """Extract executed tool names from an /agent JSON response.

    Primary source is `state.steps[].action`. Also scans the reasoning-tree summary nodes
    and any top-level `steps` for robustness across response shapes.
    """
    tools: list[str] = []

    def _add_from_steps(steps) -> None:
        if not isinstance(steps, list):
            return
        for s in steps:
            if isinstance(s, dict):
                a = str(s.get("action") or s.get("tool") or "").strip()
                if a:
                    tools.append(a)

    state = d.get("state") if isinstance(d.get("state"), dict) else {}
    _add_from_steps(state.get("steps"))
    _add_from_steps(d.get("steps"))
    # reasoning_tree_summary.nodes carry {action|tool} too (fast-path / summary shapes).
    for holder in (d, state):
        rts = holder.get("reasoning_tree_summary") if isinstance(holder, dict) else None
        if isinstance(rts, dict):
            for n in rts.get("nodes") or []:
                if isinstance(n, dict):
                    a = str(n.get("action") or n.get("tool") or "").strip()
                    # 'reason' is a virtual non-tool action; don't count it as a tool call.
                    if a and a not in ("reason", "finish", "wakeup"):
                        tools.append(a)
    return tools


def _seed_learning(base_url: str, content: str, kind: str, timeout: int) -> bool:
    """Seed a durable fact THROUGH THE MEMORY ROUTER via POST /memory/import.

    The import endpoint's writer is `services.memory.memory_router.save_learning` (the
    canonical write chokepoint), so this is a genuine memory-router seed rather than a
    side-channel DB poke. Returns True when the server reports at least one learning added.
    """
    if not content.strip():
        return False
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("learnings.json", json.dumps([{"content": content, "kind": kind or "fact"}]))
        zf.writestr(
            "manifest.json",
            json.dumps({"format_version": "1.0", "description": "golden-eval grounding seed"}),
        )
    data = buf.getvalue()
    boundary = "----laylagoldenseed" + uuid.uuid4().hex
    parts = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="seed.zip"\r\n'
        "Content-Type: application/zip\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/memory/import",
        data=parts,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8", errors="replace"))
        return bool(out.get("ok")) and int(out.get("learnings_added") or 0) >= 1
    except Exception as e:
        # A learning already present (dedup) still counts as "seeded"; report others honestly.
        return f"already" in str(e).lower()


# ── Case schema ───────────────────────────────────────────────────────────────

def normalize_case(case: dict) -> dict:
    """Return a copy of *case* with a validated `kind` (default 'qa') and `tier` (default 'full')."""
    out = dict(case)
    kind = str(out.get("kind") or "qa").strip().lower()
    out["kind"] = kind if kind in VALID_KINDS else "qa"
    tier = str(out.get("tier") or "full").strip().lower()
    out["tier"] = tier if tier in ("fast", "full") else "full"
    return out


def load_cases(path: str | Path) -> list[dict]:
    """Load + normalize a case file. Accepts {"cases": [...]} or a bare list."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = data.get("cases", []) if isinstance(data, dict) else data
    return [normalize_case(c) for c in raw]


# ── Per-kind runners: each returns (ok: bool, detail: str) ─────────────────────

def run_qa(case: dict, base_url: str, model: str, timeout: int) -> tuple[bool, str]:
    text = _complete(base_url, model, case["prompt"], timeout)
    return _all_asserts(case, text), text[:100].replace("\n", " ")


def run_tool(case: dict, base_url: str, model: str, timeout: int) -> tuple[bool, str]:
    conv = case.get("conversation_id") or f"eval-tool-{uuid.uuid4().hex[:8]}"
    res = _agent_turn(
        base_url, case["prompt"], conversation_id=conv, timeout=timeout,
        allow_run=bool(case.get("allow_run")), allow_write=bool(case.get("allow_write")),
    )
    tools = res["tools"]
    expected = case.get("expect_tool_any") or ([case["expect_tool"]] if case.get("expect_tool") else [])
    if expected:
        ok_tool = any(t in tools for t in expected)
    else:
        ok_tool = len(tools) > 0  # any real tool executed
    ok = ok_tool and _all_asserts(case, res["response"])
    return ok, f"tools={tools or '[]'} expect={expected or 'any'}"


def run_grounding(case: dict, base_url: str, model: str, timeout: int) -> tuple[bool, str]:
    seed = case.get("seed") or {}
    seeded = _seed_learning(base_url, seed.get("content", ""), seed.get("kind", "fact"), timeout) if seed else False
    # Fresh conversation id — the answer must come from RECALLED MEMORY, not turn history.
    conv = f"eval-ground-{uuid.uuid4().hex[:8]}"
    res = _agent_turn(base_url, case["prompt"], conversation_id=conv, timeout=timeout)
    ok = _all_asserts(case, res["response"])
    return ok, f"seeded={seeded} :: {res['response'][:90].replace(chr(10), ' ')}"


def run_memory(case: dict, base_url: str, model: str, timeout: int) -> tuple[bool, str]:
    conv = case.get("conversation_id") or f"eval-mem-{uuid.uuid4().hex[:8]}"
    turns = case.get("turns") or []
    if not turns and case.get("prompt"):
        turns = [{"prompt": case["prompt"]}]
    last = ""
    for t in turns:
        res = _agent_turn(base_url, t["prompt"], conversation_id=conv, timeout=timeout)
        last = res["response"]
    ok = _all_asserts(case, last)
    return ok, f"turns={len(turns)} :: {last[:90].replace(chr(10), ' ')}"


_RUNNERS = {
    "qa": run_qa,
    "tool": run_tool,
    "grounding": run_grounding,
    "memory": run_memory,
}


def run_case(case: dict, base_url: str, model: str, timeout: int) -> tuple[bool, str]:
    fn = _RUNNERS.get(case["kind"], run_qa)
    try:
        return fn(case, base_url, model, timeout)
    except Exception as e:  # a broken probe must not abort the whole run
        return False, f"<error: {e}>"


# ── Orchestration ─────────────────────────────────────────────────────────────

def select_cases(
    cases: list[dict], *, kinds: list[str] | None = None, fast_only: bool = False, limit: int = 0
) -> list[dict]:
    out = cases
    if kinds:
        kset = {k.strip().lower() for k in kinds if k.strip()}
        out = [c for c in out if c["kind"] in kset]
    if fast_only:
        out = [c for c in out if c.get("tier") == "fast"]
    if limit and limit > 0:
        out = out[:limit]
    return out


def run(
    base_url: str,
    model: str,
    limit: int,
    timeout: int,
    label: str,
    *,
    cases_path: str | Path | None = None,
    kinds: list[str] | None = None,
    fast_only: bool = False,
) -> dict:
    cases = load_cases(cases_path or (_HERE / "golden_set.json"))
    cases = select_cases(cases, kinds=kinds, fast_only=fast_only, limit=limit)

    passed = 0
    rows: list[tuple] = []
    per_kind: dict[str, dict[str, int]] = {}
    t0 = time.time()
    for c in cases:
        k = c["kind"]
        pk = per_kind.setdefault(k, {"passed": 0, "total": 0})
        pk["total"] += 1
        c0 = time.time()
        ok, detail = run_case(c, base_url, model, timeout)
        dt = time.time() - c0
        if ok:
            passed += 1
            pk["passed"] += 1
        rows.append({"id": c.get("id", "?"), "kind": k, "ok": ok, "seconds": round(dt, 1), "detail": detail[:160]})
        print(f"  [{'PASS' if ok else 'FAIL'}] {k:<9} {str(c.get('id','?')):<26} ({dt:4.1f}s) {detail[:80]!r}")

    total = len(cases)
    rate = (passed / total * 100.0) if total else 0.0
    # Per-kind breakdown (nightly full set shows where the tiny model is weak).
    if per_kind:
        parts = [f"{k}={v['passed']}/{v['total']}" for k, v in sorted(per_kind.items())]
        print("  per-kind: " + "  ".join(parts))
    # KEEP THIS LINE FORMAT: the golden-eval CI job greps 'passed (NN%)'.
    print(f"\n[{label}] {passed}/{total} passed ({rate:.0f}%) in {time.time()-t0:.0f}s")
    return {
        "label": label,
        "passed": passed,
        "total": total,
        "rate": rate,
        "rows": rows,
        "per_kind": per_kind,
        "seconds": round(time.time() - t0, 1),
    }


def main() -> int:
    # Model replies can contain non-Latin-1 glyphs (aspect sigils like ⚔, ∴). On a
    # Windows cp1252 console the diagnostic prints below would raise UnicodeEncodeError
    # and abort the whole eval. Force UTF-8 with replacement so the run never dies on I/O.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default="layla")
    ap.add_argument("--cases", default="", help="Path to a case file (default eval/golden_set.json)")
    ap.add_argument("--kinds", default="", help="Comma filter: qa,tool,grounding,memory")
    ap.add_argument("--fast", action="store_true", help="Only run cases tagged tier=fast (gate subset)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--label", default="golden")
    a = ap.parse_args()
    kinds = [k for k in a.kinds.split(",") if k.strip()] if a.kinds else None
    run(
        a.base_url, a.model, a.limit, a.timeout, a.label,
        cases_path=(a.cases or None), kinds=kinds, fast_only=a.fast,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
