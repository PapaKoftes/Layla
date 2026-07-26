"""One-command real-model capability eval for Layla.

Boots a REAL Layla server against a tiny local GGUF (SmolLM2-360M-Q4_K_M — the same model
the golden-eval CI job uses), runs the extended golden set (qa / tool / grounding / memory)
against the live endpoints, records a history row, prints a pass/fail summary, and tears
everything down. Nothing here touches the operator's data: the server runs under a throwaway
``LAYLA_DATA_DIR`` (its own runtime_config.json, its own layla.db, its own sandbox).

    python scripts/run_real_eval.py                 # full capability set (nightly)
    python scripts/run_real_eval.py --fast --gate   # gate-able fast subset, floor-checked
    python scripts/run_real_eval.py --also-qa       # also run the legacy qa golden_set.json

The model download (~270 MB) is reused from the canonical models dir across runs. If the
model is absent and cannot be fetched (offline), the harness degrades honestly: it says so,
writes a `model_unavailable` history row, and exits without pretending to have measured
anything.

History: agent/eval/history/history.jsonl  (one JSON object per run, append-only).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from tempfile import mkdtemp

_THIS = Path(__file__).resolve()
AGENT_DIR = _THIS.parent.parent
REPO_ROOT = AGENT_DIR.parent
EVAL_DIR = AGENT_DIR / "eval"
HISTORY_DIR = EVAL_DIR / "history"
CAPABILITIES_FILE = EVAL_DIR / "golden_capabilities.json"
QA_FILE = EVAL_DIR / "golden_set.json"

# The tiny CI model — catalog `name` and shipped filename.
MODEL_CATALOG_NAME = "smolLM2-360M-Q4_K_M"
MODEL_FILENAME = "SmolLM2-360M-Instruct-Q4_K_M.gguf"


# ── Isolation: config + data dir (never the operator's) ───────────────────────

def build_isolated_config(model_filename: str, models_dir: str, sandbox_root: str) -> dict:
    """The runtime_config.json for the throwaway eval server.

    Mirrors the golden-eval CI config (tiny model, no Chroma, tight budgets, no background
    scheduler/embedder), plus an explicit ``models_dir`` so the big GGUF can live in a shared
    cache while all mutable state stays inside the temp data dir.
    """
    return {
        "model_filename": model_filename,
        "models_dir": str(models_dir),
        "use_chroma": False,
        "sandbox_root": str(sandbox_root),
        "max_tool_calls": 3,
        "max_runtime_seconds": 60,
        "n_ctx": 2048,
        "n_gpu_layers": 0,
        "scheduler_study_enabled": False,
        "embedder_prewarm_enabled": False,
        # Deterministic-ish + snappy for a report harness on CPU.
        "temperature": 0.2,
        "response_cache_enabled": False,
        "telemetry_enabled": False,
        # Keep tool routing on so tool cases have a real chance on a weak model.
        "deterministic_tool_routes_enabled": True,
        "safe_mode": True,
    }


def prepare_data_dir(base: str | Path | None = None) -> Path:
    """Create a fresh, isolated LAYLA_DATA_DIR. Never the operator's real data dir."""
    if base:
        d = Path(base).expanduser().resolve()
        (d / "sandbox").mkdir(parents=True, exist_ok=True)
        return d
    d = Path(mkdtemp(prefix="layla-real-eval-"))
    (d / "sandbox").mkdir(parents=True, exist_ok=True)
    return d


def write_config(data_dir: Path, cfg: dict) -> Path:
    """Write runtime_config.json into the isolated data dir (where runtime_safety reads it)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / "runtime_config.json"
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return p


# ── Model resolution (reuse install.model_downloader) ─────────────────────────

def _load_catalog_entry(name: str) -> dict | None:
    try:
        cat = json.loads((AGENT_DIR / "models" / "model_catalog.json").read_text(encoding="utf-8"))
        for m in cat.get("models", []):
            if m.get("name") == name:
                return m
    except Exception:
        return None
    return None


def ensure_model(models_dir: Path, *, allow_download: bool = True, progress: bool = True) -> tuple[Path | None, str]:
    """Return (path_to_gguf, note). Reuses an existing file; downloads only if missing.

    Degrades honestly: returns (None, reason) when the model is absent and cannot be fetched,
    rather than raising — the caller reports it and exits cleanly.
    """
    models_dir.mkdir(parents=True, exist_ok=True)
    dest = models_dir / MODEL_FILENAME
    if dest.exists() and dest.stat().st_size > 50 * 1024 * 1024:
        # Cheap sanity: right-sized + GGUF magic.
        try:
            with dest.open("rb") as f:
                if f.read(4) == b"GGUF":
                    return dest, "reused cached model"
        except Exception:
            pass
    if not allow_download:
        return None, f"model missing at {dest} and --no-download set"

    entry = _load_catalog_entry(MODEL_CATALOG_NAME)
    if not entry:
        return None, f"catalog entry {MODEL_CATALOG_NAME!r} not found"
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))
    try:
        from install.model_downloader import download_model
    except Exception as e:
        return None, f"model_downloader import failed: {e}"
    try:
        r = download_model(entry, models_dir=models_dir, progress=progress)
    except Exception as e:
        return None, f"download raised: {e}"
    if r.get("ok") and r.get("path"):
        return Path(r["path"]), "downloaded"
    return None, f"download failed: {r.get('error') or 'unknown error'}"


# ── Server lifecycle ──────────────────────────────────────────────────────────

def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server(python_exe: str, port: int, data_dir: Path, log_path: Path) -> subprocess.Popen:
    """Spawn `uvicorn main:app` from agent/, isolated via LAYLA_DATA_DIR."""
    env = dict(os.environ)
    env["LAYLA_DATA_DIR"] = str(data_dir)
    env["LAYLA_CHROMA_DISABLED"] = "1"  # belt-and-suspenders: no semantic layer on the tiny box
    env.setdefault("PYTHONIOENCODING", "utf-8")
    log = log_path.open("wb")
    proc = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(AGENT_DIR),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    proc._eval_log = log  # type: ignore[attr-defined]  (keep handle for close)
    return proc


def wait_for_health(base_url: str, timeout_s: float, proc: subprocess.Popen | None = None) -> bool:
    """Poll GET /health until 200 or timeout. Fails fast if the server process dies."""
    deadline = time.time() + timeout_s
    url = base_url.rstrip("/") + "/health"
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False  # server exited before becoming healthy
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def stop_server(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except Exception:
        pass
    finally:
        try:
            proc._eval_log.close()  # type: ignore[attr-defined]
        except Exception:
            pass


# ── History ───────────────────────────────────────────────────────────────────

def liveness_snapshot(data_dir: Path) -> dict:
    """Read the liveness counters the server wrote in its ISOLATED DB during this real run, mapped to
    KNOWN_EFFECTS. This is the routine "correct component, nobody drove it" signal — measured against
    real inference, not asserted from a mocked unit. A KNOWN effect at count 0 after a run that should
    have exercised it (e.g. tool_executed after a tool case) is a dead pipeline in a dashboard line."""
    import sqlite3
    try:
        from services.observability.liveness import KNOWN_EFFECTS
    except Exception:  # noqa: BLE001
        KNOWN_EFFECTS = {}
    counts: dict[str, int] = {}
    try:
        for db in Path(data_dir).rglob("*.db"):
            try:
                con = sqlite3.connect(str(db))
                try:
                    for effect, count in con.execute("SELECT effect, count FROM liveness").fetchall():
                        counts[effect] = counts.get(effect, 0) + int(count)
                finally:
                    con.close()
            except Exception:  # noqa: BLE001 — table may not exist in every db file
                continue
    except Exception:  # noqa: BLE001
        pass
    return {
        "fired": counts,
        "dead_effects": [e for e in KNOWN_EFFECTS if counts.get(e, 0) == 0],
        "known": list(KNOWN_EFFECTS),
    }


def append_history(history_dir: Path, row: dict) -> Path:
    """Append one JSON object (a run) to history.jsonl; also refresh latest.json."""
    history_dir.mkdir(parents=True, exist_ok=True)
    jsonl = history_dir / "history.jsonl"
    with jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (history_dir / "latest.json").write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")
    return jsonl


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


# ── run_golden loader (avoid the `eval` package-name shadow) ───────────────────

def load_run_golden():
    spec = importlib.util.spec_from_file_location("layla_run_golden", str(EVAL_DIR / "run_golden.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Real-model capability eval for Layla.")
    ap.add_argument("--port", type=int, default=0, help="Server port (0 = auto-pick a free port)")
    ap.add_argument("--fast", action="store_true", help="Only tier=fast cases (gate subset)")
    ap.add_argument("--also-qa", action="store_true", help="Also run the legacy qa golden_set.json")
    ap.add_argument("--cases", default=str(CAPABILITIES_FILE), help="Capability case file")
    ap.add_argument("--kinds", default="", help="Comma filter: qa,tool,grounding,memory")
    ap.add_argument("--python", default=sys.executable, help="Python used to launch uvicorn")
    ap.add_argument("--models-dir", default="", help="Where the GGUF lives (default: repo/models)")
    ap.add_argument("--data-dir", default="", help="Isolated LAYLA_DATA_DIR (default: fresh temp)")
    ap.add_argument("--case-timeout", type=int, default=120, help="Per-case HTTP timeout seconds")
    ap.add_argument("--boot-timeout", type=int, default=240, help="Server health-wait seconds")
    ap.add_argument("--no-download", action="store_true", help="Fail instead of downloading a missing model")
    ap.add_argument("--keep", action="store_true", help="Keep the temp data dir + logs after the run")
    ap.add_argument("--gate", action="store_true", help="Exit nonzero if pass-rate < --floor")
    ap.add_argument("--floor", type=float, default=1.0, help="Gate floor pass-rate %% (with --gate)")
    a = ap.parse_args()

    label = "real-eval-fast" if a.fast else "real-eval-full"
    kinds = [k for k in a.kinds.split(",") if k.strip()] if a.kinds else None
    models_dir = Path(a.models_dir).expanduser().resolve() if a.models_dir else (REPO_ROOT / "models")
    started = datetime.now(timezone.utc).isoformat()

    def _history_base(status: str, extra: dict | None = None) -> dict:
        row = {
            "timestamp": started,
            "label": label,
            "status": status,
            "model": MODEL_FILENAME,
            "fast": bool(a.fast),
            "git": _git_commit(),
        }
        if extra:
            row.update(extra)
        return row

    print(f"[real-eval] model={MODEL_FILENAME} models_dir={models_dir}")
    model_path, note = ensure_model(models_dir, allow_download=not a.no_download)
    if model_path is None:
        print(f"[real-eval] MODEL UNAVAILABLE — {note}")
        print("[real-eval] degrading honestly: no measurement performed.")
        hp = append_history(HISTORY_DIR, _history_base("model_unavailable", {"note": note}))
        print(f"[real-eval] history: {hp}")
        return 2
    print(f"[real-eval] model ready ({note}): {model_path}")

    data_dir = prepare_data_dir(a.data_dir or None)
    sandbox = data_dir / "sandbox"
    cfg = build_isolated_config(MODEL_FILENAME, str(models_dir), str(sandbox))
    cfg_path = write_config(data_dir, cfg)
    port = a.port or _free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_path = data_dir / "server.log"
    print(f"[real-eval] data_dir={data_dir}")
    print(f"[real-eval] config={cfg_path}")
    print(f"[real-eval] starting server on {base_url} (log: {log_path})")

    proc = start_server(a.python, port, data_dir, log_path)
    result_row = None
    exit_code = 0
    try:
        if not wait_for_health(base_url, a.boot_timeout, proc):
            tail = ""
            try:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            except Exception:
                pass
            print(f"[real-eval] SERVER NEVER BECAME HEALTHY within {a.boot_timeout}s")
            if tail:
                print("---- server.log (tail) ----")
                print(tail)
            hp = append_history(HISTORY_DIR, _history_base("server_unhealthy"))
            print(f"[real-eval] history: {hp}")
            return 3
        print("[real-eval] server healthy — running cases\n")

        rg = load_run_golden()
        # Warm the model once so the first real case doesn't eat cold-load into its budget.
        try:
            rg._complete(base_url, "layla", "Say OK.", timeout=a.case_timeout)
        except Exception:
            pass

        res = rg.run(
            base_url, "layla", 0, a.case_timeout, label,
            cases_path=a.cases, kinds=kinds, fast_only=a.fast,
        )
        # Optionally also run the legacy qa golden_set for extra Q&A coverage.
        if a.also_qa and not a.fast:
            print("\n[real-eval] also running legacy qa golden_set.json\n")
            qa = rg.run(base_url, "layla", 0, a.case_timeout, "golden-qa", cases_path=str(QA_FILE))
            # Merge into the reported totals + per_kind.
            res["passed"] += qa["passed"]
            res["total"] += qa["total"]
            res["rate"] = (res["passed"] / res["total"] * 100.0) if res["total"] else 0.0
            for k, v in qa["per_kind"].items():
                agg = res["per_kind"].setdefault(k, {"passed": 0, "total": 0})
                agg["passed"] += v["passed"]
                agg["total"] += v["total"]
            res["rows"].extend(qa["rows"])

        result_row = _history_base(
            "ok",
            {
                "passed": res["passed"],
                "total": res["total"],
                "rate": round(res["rate"], 1),
                "per_kind": res["per_kind"],
                "seconds": res["seconds"],
                "cases_file": os.path.basename(a.cases),
                "rows": res["rows"],
                "liveness": liveness_snapshot(data_dir),
            },
        )
        print("\n==================== SUMMARY ====================")
        print(f"  label   : {label}")
        print(f"  overall : {res['passed']}/{res['total']} ({res['rate']:.0f}%) in {res['seconds']}s")
        for k, v in sorted(res["per_kind"].items()):
            print(f"    {k:<10} {v['passed']}/{v['total']}")
        _lv = result_row.get("liveness", {})
        if _lv.get("fired"):
            print(f"  liveness: fired {dict(sorted(_lv['fired'].items()))}")
        if _lv.get("dead_effects"):
            print(f"  liveness DEAD (0 fires this run): {_lv['dead_effects']}")
        print("================================================")

        if a.gate and res["rate"] < a.floor:
            print(f"[real-eval] GATE FAIL: pass-rate {res['rate']:.0f}% < floor {a.floor:.0f}%")
            exit_code = 1
    finally:
        stop_server(proc)
        if result_row is not None:
            hp = append_history(HISTORY_DIR, result_row)
            print(f"[real-eval] history appended: {hp}")
        if not a.keep and not a.data_dir:
            try:
                import shutil
                shutil.rmtree(data_dir, ignore_errors=True)
            except Exception:
                pass
        else:
            print(f"[real-eval] kept data dir: {data_dir}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
