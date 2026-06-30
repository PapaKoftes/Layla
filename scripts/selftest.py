#!/usr/bin/env python3
"""Layla deep startup self-test - proves a fresh install can actually WORK.

This is the installer's success gate. It does not just check "it imported"; it
resolves the configured model, validates the GGUF, and runs ONE REAL inference
turn - in a subprocess, so a SIGILL from a llama-cpp wheel that uses CPU
features this machine lacks (AVX-512/VNNI on older CPUs) is detected and
reported instead of crashing the whole process. Optionally (--server) it boots
the web server and checks /health, /agent and /ui end-to-end.

Exit code 0 = every critical (P0) check passed. Non-zero = a P0 check failed,
so the installer can react (swap the llama-cpp wheel on SIGILL, re-download a
corrupt GGUF, etc.). Warnings (degraded but usable) never fail the run.

Usage:
    python scripts/selftest.py            # core checks (no server needed)
    python scripts/selftest.py --server   # also boot the server + hit endpoints
    python scripts/selftest.py --json     # machine-readable summary
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = REPO_ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

# Windows NTSTATUS for an illegal instruction (the SIGILL signature for a bad
# AVX-512 wheel). subprocess may surface it as the unsigned or signed form.
_SIGILL_CODES = {-1073741795, 3221225501, -4}  # -4 == POSIX SIGILL

_RESULTS: list[tuple[str, str, str]] = []  # (name, status in {ok,warn,fail}, detail)


def _ok(name: str, detail: str = "") -> None:
    _RESULTS.append((name, "ok", detail))


def _warn(name: str, detail: str = "") -> None:
    _RESULTS.append((name, "warn", detail))


def _fail(name: str, detail: str = "") -> None:
    _RESULTS.append((name, "fail", detail))


# ── Checks ────────────────────────────────────────────────────────────────────

def check_interpreter() -> None:
    v = sys.version_info
    if v[:2] in ((3, 11), (3, 12)):
        _ok("interpreter", f"Python {v.major}.{v.minor}.{v.micro}")
    elif v[:2] >= (3, 13):
        _fail("interpreter", f"Python {v.major}.{v.minor} unsupported - Layla needs 3.11 or 3.12")
    else:
        _fail("interpreter", f"Python {v.major}.{v.minor} too old - need 3.11 or 3.12")


def check_imports() -> None:
    import importlib.util as u

    def has(m: str) -> bool:
        try:
            return u.find_spec(m) is not None
        except Exception:
            return False

    for m in ("fastapi", "numpy", "psutil"):
        (_ok if has(m) else _fail)(f"import {m}")
    (_ok if has("llama_cpp") else _fail)("import llama_cpp", "required to load GGUF models")
    (_ok if has("uvicorn") else _warn)("import uvicorn", "required only to serve the web UI")
    (_ok if has("sentence_transformers") else _warn)(
        "import sentence_transformers", "embedder for semantic recall - RAG degrades without it"
    )


def resolve_model() -> Path | None:
    try:
        import runtime_safety
    except Exception as e:
        _fail("model configured", f"could not import runtime_safety: {e}")
        return None
    try:
        cfg = runtime_safety.load_config()
    except Exception as e:
        _fail("model configured", f"could not load runtime_config: {e}")
        return None
    mf = (cfg.get("model_filename") or "").strip()
    if not mf or mf == "your-model.gguf":
        _fail("model configured", "no model_filename set in agent/runtime_config.json")
        return None
    try:
        p = Path(runtime_safety.resolve_model_path(cfg))
    except Exception as e:
        _fail("model configured", f"resolve_model_path failed: {e}")
        return None
    if p.exists():
        _ok("model configured", f"{mf} ({p.stat().st_size / 1e9:.1f} GB)")
        return p
    _fail("model configured", f"{mf} not found at {p}")
    return None


def check_gguf(path: Path | None) -> None:
    if not path:
        return
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
        if magic == b"GGUF":
            _ok("GGUF integrity", "valid magic bytes")
        else:
            _fail("GGUF integrity", f"bad magic {magic!r} - file is corrupt or a truncated/HTML download")
    except Exception as e:
        _fail("GGUF integrity", str(e))


_INFERENCE_PROBE = r"""
import sys
sys.path.insert(0, r"__AGENT_DIR__")
try:
    from services.llm.llm_gateway import run_completion
    out = run_completion("Reply with exactly one word: ok", max_tokens=8, temperature=0.0, timeout_seconds=180)
    if isinstance(out, dict):
        ch = (out.get("choices") or [{}])[0]
        text = (ch.get("text") or (ch.get("message") or {}).get("content")
                or out.get("text") or out.get("content") or "")
        if not text:
            text = str(out)
    else:
        text = str(out)
    print("PROBE_OK:" + (text or "").strip().replace(chr(10), " ")[:80])
except Exception as e:
    print("PROBE_ERR:" + repr(e)[:300])
    sys.exit(3)
"""


def check_inference(model_path: Path | None) -> None:
    """The load-bearing check: one real turn, isolated so a SIGILL is caught."""
    if not model_path:
        _fail("inference turn", "skipped - no usable model")
        return
    probe = _INFERENCE_PROBE.replace("__AGENT_DIR__", str(AGENT_DIR))
    env = dict(os.environ)
    env.pop("LAYLA_MINIMAL_STARTUP", None)  # we WANT the real model path
    try:
        r = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=300, env=env, cwd=str(AGENT_DIR),
        )
    except subprocess.TimeoutExpired:
        _fail("inference turn", "timed out - model too large/slow for this box, or stuck loading")
        return
    stdout = r.stdout or ""
    if "PROBE_OK:" in stdout:
        txt = stdout.split("PROBE_OK:", 1)[1].strip()
        if txt:
            _ok("inference turn", f'model replied: "{txt[:48]}"')
        else:
            _warn("inference turn", "model loaded but returned empty text")
        return
    if r.returncode in _SIGILL_CODES:
        _fail("inference turn",
              "ILLEGAL INSTRUCTION (SIGILL) - the installed llama-cpp wheel uses CPU "
              "instructions this machine lacks (e.g. AVX-512). Reinstall a basic/AVX2 CPU wheel.")
        return
    if "PROBE_ERR:" in stdout:
        _fail("inference turn", stdout.split("PROBE_ERR:", 1)[1].strip()[:240])
        return
    # Non-zero exit with no probe output → the interpreter crashed (segfault/SIGILL-like)
    if r.returncode != 0:
        _fail("inference turn",
              f"probe process crashed (exit {r.returncode}) - likely an incompatible llama-cpp "
              f"wheel for this CPU. {(r.stderr or '')[-160:]}".strip())
        return
    _fail("inference turn", f"probe produced no result: {(r.stderr or stdout or '')[-200:]}")


def check_rag() -> None:
    import importlib.util as u
    try:
        if u.find_spec("sentence_transformers") is None:
            _warn("RAG / memory", "embedder not installed - semantic recall off until you add sentence-transformers")
            return
    except Exception:
        pass
    try:
        import layla.memory.vector_store as vs
        if not vs._vector_enabled():
            _warn("RAG / memory", "vector memory disabled (LAYLA_CHROMA_DISABLED set)")
            return
        vs.embed("hello world")
        backend = "ChromaDB" if vs._real_chroma() else "SQLite+NumPy fallback"
        _ok("RAG / memory", f"embedder + {backend} active")
    except Exception as e:
        _warn("RAG / memory", f"degraded: {repr(e)[:160]}")


def check_server() -> None:
    """Optional: boot the real server and exercise /health, /agent, /ui."""
    import importlib.util as u
    if u.find_spec("uvicorn") is None:
        _warn("server", "uvicorn not installed - skipped live server checks")
        return
    try:
        import httpx
    except Exception:
        _warn("server", "httpx not available - skipped live server checks")
        return

    from port_guard import resolve_serve_port  # type: ignore
    try:
        port = resolve_serve_port()
    except Exception:
        port = 8000
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", f"--port={port}"],
        cwd=str(AGENT_DIR), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 90
        up = False
        while time.time() < deadline:
            try:
                r = httpx.get(base + "/health", timeout=5)
                if r.status_code in (200, 503):
                    up = True
                    break
            except Exception:
                time.sleep(1.5)
        if not up:
            _fail("server", "did not answer /health within 90s")
            return
        h = {}
        try:
            h = httpx.get(base + "/health?deep=true", timeout=20).json()
        except Exception:
            pass
        _ok("server /health", f"status={h.get('status', '?')} tools={h.get('tools_registered', '?')}")
        try:
            ui = httpx.get(base + "/ui", timeout=10)
            (_ok if (ui.status_code == 200 and "<" in ui.text) else _fail)("server /ui", f"HTTP {ui.status_code}")
        except Exception as e:
            _fail("server /ui", str(e)[:120])
        try:
            a = httpx.post(base + "/agent",
                           json={"message": "Reply with one word: ok", "allow_write": False, "allow_run": False},
                           timeout=180)
            _ok("server /agent", f"HTTP {a.status_code}") if a.status_code == 200 else _warn("server /agent", f"HTTP {a.status_code}")
        except Exception as e:
            _warn("server /agent", str(e)[:120])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


# ── Report ────────────────────────────────────────────────────────────────────

def _print_report() -> int:
    sym = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]"}
    print("\n" + "=" * 64)
    print("  Layla self-test")
    print("=" * 64)
    for name, status, detail in _RESULTS:
        line = f"  {sym[status]}  {name}"
        if detail:
            line += f"  -  {detail}"
        print(line)
    fails = [r for r in _RESULTS if r[1] == "fail"]
    warns = [r for r in _RESULTS if r[1] == "warn"]
    print("-" * 64)
    if fails:
        print(f"  RESULT: FAILED ({len(fails)} critical, {len(warns)} warning)")
    else:
        print(f"  RESULT: PASS ({len(warns)} warning{'s' if len(warns) != 1 else ''})")
    print("=" * 64 + "\n")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Layla deep startup self-test")
    ap.add_argument("--server", action="store_true", help="also boot the server and test /health, /agent, /ui")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON summary")
    args = ap.parse_args()

    check_interpreter()
    check_imports()
    model_path = resolve_model()
    check_gguf(model_path)
    check_inference(model_path)
    check_rag()
    if args.server:
        check_server()

    code = _print_report()
    if args.json:
        print(json.dumps({"results": [{"name": n, "status": s, "detail": d} for n, s, d in _RESULTS],
                          "ok": code == 0}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
