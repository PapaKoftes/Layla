"""Session-scoped uvicorn + base_url for pytest-playwright."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def e2e_server_url():
    port = _free_port()
    env = os.environ.copy()
    sep = os.pathsep
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(AGENT_DIR) + (sep + prev if prev else "")

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(AGENT_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 90
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + "/health", timeout=3)
            break
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last_err = e
            if proc.poll() is not None:
                err_b = proc.stderr.read() if proc.stderr else b""
                err = err_b.decode("utf-8", errors="replace")[:2000]
                pytest.fail(f"uvicorn exited early (code={proc.returncode}): {err}")
            time.sleep(0.4)
    else:
        proc.terminate()
        pytest.fail(f"server did not become ready: {last_err}")

    yield base
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def base_url(e2e_server_url: str) -> str:
    """pytest-playwright uses this for relative navigation."""
    return e2e_server_url
