#!/usr/bin/env python3
"""
Layla CLI — talk to Layla from the terminal.

Usage:
    python layla.py              — help + suggest wakeup
    python layla.py ask "what does this function do?"
    python layla.py ask --voice   — record from mic, transcribe, send
    python layla.py status        — health + token usage
    python layla.py remember "prefer pytest over unittest"
    python layla.py study "asyncio internals"
    python layla.py plans
    python layla.py approve <uuid>
    python layla.py wakeup
    python layla.py doctor
    python layla.py export
    python layla.py pending
    python layla.py aspect <name>
    python layla.py tui
    python layla.py undo
"""
import json
import sys

BASE_URL = "http://localhost:8000"

try:
    import httpx
except ImportError:
    print("httpx not installed. Run: pip install httpx")
    sys.exit(1)


def _post(path: str, payload: dict) -> dict:
    try:
        r = httpx.post(f"{BASE_URL}{path}", json=payload, timeout=120)
        return r.json()
    except httpx.ConnectError:
        print("Cannot connect to Layla. Is the agent running? (cd agent && python -m uvicorn main:app)")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def _get(path: str) -> dict:
    try:
        r = httpx.get(f"{BASE_URL}{path}", timeout=30)
        return r.json()
    except httpx.ConnectError:
        print("Cannot connect to Layla. Is the agent running?")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def _record_voice_cli() -> bytes:
    """Record 5s from mic, return WAV bytes. Requires sounddevice."""
    import struct
    import sounddevice as sd
    import numpy as np
    sample_rate = 16000
    duration_sec = 5
    rec = sd.rec(
        int(duration_sec * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    buf = rec.astype(np.int16).tobytes()
    n = len(buf)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + n, b"WAVE", b"fmt ", 16,
        1, 1, sample_rate, sample_rate * 2, 2, 16, b"data", n,
    )
    return header + buf


def cmd_ask(args: list) -> None:
    use_voice = "--voice" in args
    if use_voice:
        args = [a for a in args if a != "--voice"]
    message = " ".join(args)
    if not message and not use_voice:
        print("Usage: layla ask <message>  or  layla ask --voice")
        return
    # Check if --aspect, --think, or --voice flags are passed
    aspect = ""
    think = False
    use_voice = False
    clean = []
    i = 0
    while i < len(args):
        if args[i] == "--aspect" and i + 1 < len(args):
            aspect = args[i + 1]
            i += 2
        elif args[i] == "--think":
            think = True
            i += 1
        else:
            clean.append(args[i])
            i += 1
    message = " ".join(clean)

    if use_voice:
        try:
            print("Recording 5s from mic…")
            wav_bytes = _record_voice_cli()
            print("Transcribing…")
            r = httpx.post(f"{BASE_URL}/voice/transcribe", content=wav_bytes, timeout=30)
            data = r.json()
            text = (data.get("text") or "").strip()
            if not text:
                print("No speech detected.")
                return
            message = text
            print(f"You said: {message}\n")
        except ImportError:
            print("Voice requires: pip install sounddevice numpy")
            return
        except Exception as e:
            print(f"Voice error: {e}")
            return

    result = _post("/agent", {
        "message": message,
        "aspect_id": aspect,
        "show_thinking": think,
    })
    aspect_name = result.get("aspect_name", "Layla")
    response = result.get("response", "")
    print(f"\n∴ {aspect_name.upper()}: {response}\n")


def cmd_remember(args: list) -> None:
    content = " ".join(args)
    if not content:
        print("Usage: layla remember <fact or preference>")
        return
    kind = "fact"
    if "--type" in args:
        idx = args.index("--type")
        if idx + 1 < len(args):
            kind = args[idx + 1]
    result = _post("/learn/", {"content": content, "type": kind})
    print(f"Saved: {result.get('message', result)}")


def cmd_study(args: list) -> None:
    topic = " ".join(args).strip()
    if not topic:
        print("Usage: layla study <topic>")
        return
    result = _post("/study_plans", {"topic": topic})
    if result.get("ok"):
        print(f"Study plan added: {topic}")
    else:
        print(f"Error: {result}")


def cmd_plans(_args: list) -> None:
    """List active study plans (topics and last studied)."""
    result = _get("/study_plans")
    plans = result.get("plans", [])
    active = [p for p in plans if p.get("status") == "active"]
    if not active:
        print("No active study plans. Add one: layla study \"topic\"")
        return
    print(f"\nActive study plans ({len(active)}):\n")
    for p in active:
        topic = (p.get("topic") or "").strip()
        last = (p.get("last_studied") or "").strip()
        if last:
            print(f"  · {topic}")
            print(f"    last studied: {last}")
        else:
            print(f"  · {topic} (not yet studied)")
    print()


def cmd_approve(args: list) -> None:
    if not args:
        print("Usage: layla approve <uuid>")
        return
    approval_id = args[0]
    result = _post("/approve", {"id": approval_id})
    if result.get("ok"):
        print(f"Approved. Result: {json.dumps(result.get('result', {}), indent=2)}")
    else:
        print(f"Error: {result.get('error', result)}")


def cmd_status(_args: list) -> None:
    """Quick health check and token usage."""
    try:
        health = _get("/health")
        usage_data = _get("/usage")
    except Exception as e:
        print(f"Cannot connect: {e}")
        return
    status = health.get("status", "?")
    model = "loaded" if health.get("model_loaded") else "not loaded"
    tools = health.get("tools_registered", 0)
    print(f"Status: {status}  |  Model: {model}  |  Tools: {tools}")
    if usage_data.get("prompt_tokens") is not None:
        print(f"Tokens: prompt={usage_data.get('prompt_tokens', 0)}  completion={usage_data.get('completion_tokens', 0)}  requests={usage_data.get('request_count', 0)}")
    if health.get("model_error"):
        print(f"Model error: {health['model_error']}")


def cmd_wakeup(_args: list) -> None:
    result = _get("/wakeup")
    greeting = result.get("greeting", "")
    print(f"\n∴ ECHO (SESSION START): {greeting}\n")
    plans = result.get("active_study_plans", [])
    if plans:
        print(f"Active study plans: {', '.join(plans)}")


def cmd_export(_args: list) -> None:
    import time
    result = _get("/system_export")
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = f"layla_export_{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Exported to: {out}")
    print(f"  learnings: {result.get('learnings_count', 0)}")
    print(f"  aspects: {', '.join(result.get('aspects_loaded', []))}")
    print(f"  tools: {', '.join(result.get('tools_registered', []))}")


def cmd_pending(_args: list) -> None:
    result = _get("/pending")
    items = [e for e in result.get("pending", []) if e.get("status") == "pending"]
    if not items:
        print("No pending approvals.")
        return
    print(f"\n{len(items)} pending approval(s):\n")
    for e in items:
        print(f"  [{e['id'][:8]}] {e['tool']} — requested {e['requested_at']}")
        print(f"    args: {json.dumps(e.get('args', {}))[:80]}")
        print(f"    → layla approve {e['id']}")
        print()


def cmd_doctor(_args: list) -> None:
    """Run full system diagnostics. Works without server."""
    import os
    agent_dir = os.path.join(os.path.dirname(__file__), "agent")
    if agent_dir not in sys.path:
        sys.path.insert(0, agent_dir)
    try:
        os.chdir(agent_dir)
        from services.system_doctor import run_diagnostics, format_diagnostics
        report = run_diagnostics(include_llm=False)
        print(format_diagnostics(report))
    except Exception as e:
        print(f"Doctor error: {e}")
        sys.exit(1)


def cmd_tui(_args: list) -> None:
    import subprocess, sys
    from pathlib import Path
    agent_dir = Path(__file__).resolve().parent / "agent"
    subprocess.run([sys.executable, "tui.py"], cwd=str(agent_dir))


def cmd_undo(_args: list) -> None:
    """Revert last Layla auto-commit (git revert HEAD)."""
    result = _post("/undo", {})
    if result.get("ok"):
        print(result.get("message", "Reverted."))
    else:
        print(f"Error: {result.get('error', result)}")


def cmd_aspect(args: list) -> None:
    """Quick aspect-flavored question: layla aspect nyx what is asyncio?"""
    if not args:
        print("Usage: layla aspect <name> <message>")
        return
    aspect = args[0]
    message = " ".join(args[1:])
    if not message:
        print("Usage: layla aspect <name> <message>")
        return
    result = _post("/agent", {"message": message, "aspect_id": aspect})
    aspect_name = result.get("aspect_name", aspect)
    print(f"\n∴ {aspect_name.upper()}: {result.get('response', '')}\n")


COMMANDS = {
    "ask": cmd_ask,
    "status": cmd_status,
    "undo": cmd_undo,
    "doctor": cmd_doctor,
    "remember": cmd_remember,
    "study": cmd_study,
    "plans": cmd_plans,
    "approve": cmd_approve,
    "wakeup": cmd_wakeup,
    "export": cmd_export,
    "pending": cmd_pending,
    "tui": cmd_tui,
    "aspect": cmd_aspect,
}


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        print("\nTry:  python layla.py wakeup   — session greeting + study plans")
        print("      python layla.py ask \"your question\"")
        print("      python layla.py status     — health + token usage")
        return
    cmd = args[0].lower()
    rest = args[1:]
    fn = COMMANDS.get(cmd)
    if fn is None:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(COMMANDS)}")
        sys.exit(1)
    fn(rest)


if __name__ == "__main__":
    main()
