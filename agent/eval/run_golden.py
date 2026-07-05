"""Golden-set eval runner for Layla (BL-101) — self-contained, stdlib-only.

Runs eval/golden_set.json against a running Layla `/v1/chat/completions` and reports a
pass-rate. It's also the A/B rig for the mechanism measurements: run once with a flag on
and once with it off (e.g. gbnf_decoding_enabled, self_consistency_samples) and diff the
pass-rates — that IS the BL-104 (GBNF) / BL-105 (self-consistency) gain measurement.

Usage:
    python eval/run_golden.py [--base-url http://127.0.0.1:8000] [--model layla] [--limit N] [--label NAME]

Assertion types: contains, icontains, not_contains, not_icontains, regex, not_contains_regex.
Exit code 0 always (it's a report, not a gate).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent


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


def _complete(base_url: str, model: str, prompt: str, timeout: int) -> str:
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", errors="replace"))
    return ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""


def run(base_url: str, model: str, limit: int, timeout: int, label: str) -> dict:
    cases = json.loads((_HERE / "golden_set.json").read_text(encoding="utf-8"))["cases"]
    if limit > 0:
        cases = cases[:limit]
    passed = 0
    rows = []
    t0 = time.time()
    for c in cases:
        try:
            text = _complete(base_url, model, c["prompt"], timeout)
            ok = all(_check(a, text) for a in c.get("assert", []))
        except Exception as e:
            text, ok = f"<error: {e}>", False
        passed += 1 if ok else 0
        rows.append((c["id"], ok, text[:80].replace("\n", " ")))
        print(f"  [{'PASS' if ok else 'FAIL'}] {c['id']:<24} {text[:60]!r}")
    total = len(cases)
    rate = (passed / total * 100.0) if total else 0.0
    print(f"\n[{label}] {passed}/{total} passed ({rate:.0f}%) in {time.time()-t0:.0f}s")
    return {"label": label, "passed": passed, "total": total, "rate": rate, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default="layla")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--label", default="golden")
    a = ap.parse_args()
    run(a.base_url, a.model, a.limit, a.timeout, a.label)
    return 0


if __name__ == "__main__":
    sys.exit(main())
