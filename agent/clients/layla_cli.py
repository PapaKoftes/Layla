#!/usr/bin/env python3
"""Layla CLI client (BL-155) — chat with a local Layla from the terminal.

Dependency-free (stdlib `urllib` only): talks to Layla's OpenAI-compatible
`/v1/chat/completions`, so it works against any Layla instance without importing the
app. One-shot (`layla "question"`) or an interactive REPL; streams tokens by default.

    python -m clients.layla_cli "what changed in this repo?"
    python -m clients.layla_cli            # interactive REPL
    python -m clients.layla_cli --model layla-nyx --no-stream "explain asyncio"
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _post(base_url: str, payload: dict, timeout: int):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=data, headers={"Content-Type": "application/json"}, method="POST",
    )
    return urllib.request.urlopen(req, timeout=timeout)


def _iter_sse(resp):
    """Yield content deltas from an OpenAI-style SSE stream."""
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            break
        try:
            evt = json.loads(body)
        except Exception:
            continue
        for ch in evt.get("choices", []):
            piece = (ch.get("delta") or {}).get("content")
            if piece:
                yield piece


def complete(base_url: str, messages: list, *, model: str = "layla",
             stream: bool = True, timeout: int = 300, out=sys.stdout) -> str:
    """Send messages, print the reply, return the full text."""
    payload = {"model": model, "messages": messages, "stream": stream}
    try:
        resp = _post(base_url, payload, timeout)
    except urllib.error.URLError as e:
        print(f"\n[connection error: {e}. Is Layla running at {base_url}?]", file=sys.stderr)
        return ""
    if stream:
        parts: list[str] = []
        for piece in _iter_sse(resp):
            parts.append(piece)
            out.write(piece)
            out.flush()
        out.write("\n")
        return "".join(parts)
    data = json.loads(resp.read().decode("utf-8", "replace"))
    text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    out.write(text + "\n")
    return text


def repl(base_url: str, model: str, stream: bool, timeout: int) -> int:
    print(f"Layla CLI — {base_url} ({model}). Ctrl-D or /quit to exit.")
    history: list[dict] = []
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/quit", "/exit"):
            return 0
        if line == "/reset":
            history.clear()
            print("[history cleared]")
            continue
        history.append({"role": "user", "content": line})
        sys.stdout.write("layla> ")
        reply = complete(base_url, history, model=model, stream=stream, timeout=timeout)
        if reply:
            history.append({"role": "assistant", "content": reply})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="layla", description="Chat with a local Layla from the terminal.")
    ap.add_argument("prompt", nargs="*", help="one-shot prompt; omit for an interactive REPL")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default="layla", help="layla or layla-<aspect>")
    ap.add_argument("--no-stream", action="store_true")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args(argv)
    stream = not a.no_stream
    if a.prompt:
        text = " ".join(a.prompt)
        reply = complete(a.base_url, [{"role": "user", "content": text}],
                         model=a.model, stream=stream, timeout=a.timeout)
        return 0 if reply else 1
    return repl(a.base_url, a.model, stream, a.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
