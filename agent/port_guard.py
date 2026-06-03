"""Port-conflict guard for the Layla server.

Pure stdlib (socket + urllib) so it runs anywhere and is unit-testable without
the heavy app dependencies. Used by serve.py (and any launcher) to make sure
Layla never silently collides with another process on its port.

Decision logic (resolve_serve_port):
  - port free                         -> action="start"          (use it)
  - port busy AND it is a Layla        -> action="already_running" (don't double-start)
  - port busy AND it is something else -> action="relocated"      (auto-pick next free port)
  - port busy, nothing else free       -> action="blocked"        (clear error)
"""
from __future__ import annotations

import json
import socket
import urllib.request
from typing import Any

DEFAULT_PORT = 8000
_RELOCATE_ATTEMPTS = 20


def is_port_available(host: str, port: int) -> bool:
    """True if we can bind host:port right now (i.e. nothing is listening)."""
    if not (0 < port < 65536):
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # SO_REUSEADDR off: we want to know if a real listener holds the port.
        sock.settimeout(0.5)
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def probe_layla(host: str, port: int, timeout: float = 1.5) -> bool:
    """True if the process on host:port answers /health like a Layla server.

    Checks for a combination of keys that a generic service is very unlikely to
    return, so we don't mistake an unrelated server for Layla.
    """
    url = f"http://{host}:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (localhost only)
            if getattr(resp, "status", 200) >= 400:
                return False
            body = resp.read(65536)
        data = json.loads(body.decode("utf-8", errors="replace"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    signature = ("tools_registered", "study_plans", "vector_store")
    return sum(1 for k in signature if k in data) >= 2


def find_available_port(host: str, start: int, attempts: int = _RELOCATE_ATTEMPTS) -> int | None:
    """Scan upward from `start` for a bindable port; None if none found."""
    for candidate in range(start, min(start + attempts, 65536)):
        if is_port_available(host, candidate):
            return candidate
    return None


def resolve_serve_port(host: str, port: int) -> dict[str, Any]:
    """Decide how to serve given the configured host/port. See module docstring."""
    if is_port_available(host, port):
        return {
            "action": "start",
            "port": port,
            "message": f"Port {port} is free.",
        }

    # Port is busy — is it us already?
    if probe_layla(host, port):
        return {
            "action": "already_running",
            "port": port,
            "message": (
                f"Layla is already running at http://{host}:{port}/ui — "
                f"not starting a second instance."
            ),
        }

    # Busy with a foreign process: relocate to the next free port.
    alt = find_available_port(host, port + 1)
    if alt is not None:
        return {
            "action": "relocated",
            "port": alt,
            "requested_port": port,
            "message": (
                f"Port {port} is in use by another program. "
                f"Starting Layla on http://{host}:{alt}/ui instead."
            ),
        }

    return {
        "action": "blocked",
        "port": port,
        "message": (
            f"Port {port} is in use and no free port was found in "
            f"{port + 1}..{port + _RELOCATE_ATTEMPTS}. Close the other program "
            f"or set a different \"port\" in agent/runtime_config.json."
        ),
    }


if __name__ == "__main__":
    # CLI: `python port_guard.py [port]` -> prints the decision as JSON.
    import sys

    _port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            _port = int(sys.argv[1])
        except ValueError:
            pass
    print(json.dumps(resolve_serve_port("127.0.0.1", _port)))
