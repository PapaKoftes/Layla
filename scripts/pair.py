#!/usr/bin/env python3
"""Guided pairing — connect this Layla to your other Layla (e.g. main PC <-> laptop).

Two roles, picked interactively:
  HOST   - the instance the other PC connects TO. Enables remote access, rotates a
           one-time bearer token, and shows you the address + token to enter elsewhere.
  CLIENT - the instance doing the connecting. You paste the host's address + token;
           it verifies the link actually round-trips (an authenticated request), so
           you find out immediately whether pairing works.

Uses Layla's hardened remote-auth path: a rotated token stored as tunnel_token_hash
(never plaintext), checked with constant-time compare (R5-safe). Run this while Layla
is running locally (cd agent ; python serve.py).
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("httpx is required (it ships with Layla). Activate the venv: .\\.venv\\Scripts\\Activate.ps1")
    sys.exit(1)

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "agent") not in sys.path:
    sys.path.insert(0, str(REPO / "agent"))


def local_base() -> tuple[str, int]:
    port = 8000
    try:
        import runtime_safety
        port = int(runtime_safety.load_config().get("port", 8000) or 8000)
    except Exception:
        pass
    return f"http://127.0.0.1:{port}", port


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def ask(prompt: str, default: str | None = None) -> str:
    try:
        v = input(prompt).strip()
    except EOFError:
        v = ""
    return v or (default or "")


def is_running(base: str) -> bool:
    try:
        return httpx.get(base + "/health", timeout=5).status_code in (200, 503)
    except Exception:
        return False


def host_flow(base: str, port: int) -> None:
    print("\n== HOST setup (the other PC will connect to this one) ==")
    try:
        httpx.post(base + "/settings", json={"remote_enabled": True}, timeout=15)
    except Exception as e:
        print(f"[FAIL] couldn't enable remote access locally: {e}")
        return
    try:
        r = httpx.post(base + "/remote/token/rotate", timeout=15).json()
    except Exception as e:
        print(f"[FAIL] token rotation failed: {e}")
        return
    if not r.get("ok") or not r.get("token"):
        print(f"[FAIL] token rotation failed: {r}")
        return
    token = r["token"]

    print("\nHow will the other PC reach this one?")
    print("  [1] Same network (LAN) - simplest")
    print("  [2] Over the internet (Cloudflare tunnel; needs cloudflared installed)")
    choice = ask("Choose 1 or 2 [1]: ", "1")
    if choice == "2":
        try:
            t = httpx.post(base + "/remote/tunnel/start", timeout=60).json()
        except Exception as e:
            t = {"ok": False, "error": str(e)}
        addr = (t or {}).get("url") or ""
        if not addr:
            print(f"  Tunnel didn't start ({t}); falling back to LAN.")
            addr = f"http://{lan_ip()}:{port}"
    else:
        addr = f"http://{lan_ip()}:{port}"
        print(f"  Note: if the other PC can't connect, allow inbound TCP {port} in Windows Firewall.")

    print("\n" + "=" * 62)
    print("  On the OTHER PC, run:  python scripts\\pair.py   (choose CLIENT)")
    print("  and enter:")
    print(f"    Address: {addr}")
    print(f"    Token:   {token}")
    print("=" * 62)
    print("  (The token is shown once. Re-run to rotate a new one.)")


def client_flow() -> None:
    print("\n== CLIENT connect (this machine connects to your other Layla) ==")
    addr = ask("Host address (e.g. http://192.168.1.20:8000 or https://xxx.trycloudflare.com): ").rstrip("/")
    token = ask("Pairing token: ")
    if not addr or not token:
        print("Need both an address and a token.")
        return
    try:
        r = httpx.get(addr + "/health", headers={"Authorization": f"Bearer {token}"}, timeout=20)
    except Exception as e:
        print(f"\n[FAIL] could not reach {addr}: {e}")
        print("  Check the address, that the host's Layla is running, and the firewall/tunnel.")
        return
    if r.status_code == 200:
        print(f"\n[ OK ] connected and authenticated to {addr}")
        peers = REPO / "agent" / ".governance" / "paired_peers.json"
        peers.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if peers.exists():
            try:
                data = json.loads(peers.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[addr] = {"paired": True}
        peers.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"  Saved to {peers}. This machine can now reach the other Layla's API with that token.")
    elif r.status_code in (401, 403):
        print(f"\n[FAIL] reached {addr} but authentication was rejected.")
        print("  Re-run HOST setup on the other PC to rotate a fresh token, and make sure remote access is enabled there.")
    else:
        print(f"\n[FAIL] {addr} returned HTTP {r.status_code}")


def main() -> int:
    base, port = local_base()
    print("Layla - guided pairing")
    print("----------------------")
    print("Which side is THIS machine?")
    print("  [1] HOST   - the other PC connects to me")
    print("  [2] CLIENT - I connect to my other Layla")
    role = ask("Choose 1 or 2: ")
    if role == "1":
        if not is_running(base):
            print(f"\nLayla isn't responding at {base}.")
            print("Start it first:  .\\.venv\\Scripts\\Activate.ps1 ; cd agent ; python serve.py")
            return 1
        host_flow(base, port)
    elif role == "2":
        client_flow()
    else:
        print("Cancelled.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
