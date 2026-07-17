"""Sandbox subprocess runners (timeout, cwd check)."""
from pathlib import Path


def test_python_runner_rejects_outside_sandbox(tmp_path):
    from services.sandbox.python_runner import run_python_file

    outside = tmp_path / "out"
    outside.mkdir()
    sandbox = tmp_path / "in"
    sandbox.mkdir()

    def _only_inner(p: Path) -> bool:
        try:
            p.resolve().relative_to(sandbox.resolve())
            return True
        except ValueError:
            return False

    r = run_python_file("print(1)", outside, inside_sandbox_check=_only_inner)
    assert r.get("ok") is False
    assert "sandbox" in (r.get("error") or "").lower()


_NET_CODE = (
    "import socket\n"
    "try:\n"
    "    socket.getaddrinfo('example.com', 80)\n"
    "    print('NETWORK_OK')\n"
    "except OSError as e:\n"
    "    print('NETWORK_BLOCKED')\n"
)


def test_python_runner_network_speedbump_blocks_naive_path(tmp_path):
    """BL-025/BL-295: allow_network=False blocks the NAIVE socket path (accidental egress).

    This is a best-effort speed-bump, NOT a jail — it only proves requests/urllib/httpx that go
    through socket.getaddrinfo fail closed. Completeness is asserted-against below.
    """
    from services.sandbox.python_runner import run_python_file

    r = run_python_file(_NET_CODE, tmp_path, inside_sandbox_check=lambda p: True, allow_network=False)
    assert r.get("ok") is True
    assert "NETWORK_BLOCKED" in (r.get("stdout") or "")
    assert "NETWORK_OK" not in (r.get("stdout") or "")


def test_python_runner_network_speedbump_is_NOT_a_boundary(tmp_path):
    """HONESTY GUARD (BL-295): the network speed-bump is trivially bypassable and MUST NOT be
    described as isolation/a jail. This pins the KNOWN, ACCEPTED limitation so no code or doc can
    silently start claiming the sandbox blocks the network.

    If you ever make network-blocking a REAL boundary, this test SHOULD fail — update it AND
    .identity/capabilities.md ("My Python sandbox does NOT block the network") together, on purpose.
    """
    from services.sandbox.python_runner import run_python_file

    # Bypass 1: the _socket C extension is untouched by the wrapper-module patch.
    raw_socket = (
        "import _socket\n"
        "s = _socket.socket()\n"
        "print('BYPASS_SOCKET_CREATED')\n"
        "s.close()\n"
    )
    r1 = run_python_file(raw_socket, tmp_path, inside_sandbox_check=lambda p: True, allow_network=False)
    assert r1.get("ok") is True
    assert "BYPASS_SOCKET_CREATED" in (r1.get("stdout") or ""), \
        "_socket bypass no longer works — the bump may have become a boundary; update capabilities.md"

    # Bypass 2: importlib.reload re-imports the pristine socket module over the patch.
    reload_bypass = (
        "import socket, importlib\n"
        "importlib.reload(socket)\n"
        "s = socket.socket()\n"
        "print('BYPASS_RELOAD_CREATED')\n"
        "s.close()\n"
    )
    r2 = run_python_file(reload_bypass, tmp_path, inside_sandbox_check=lambda p: True, allow_network=False)
    assert r2.get("ok") is True
    assert "BYPASS_RELOAD_CREATED" in (r2.get("stdout") or ""), \
        "reload bypass no longer works — the bump may have become a boundary; update capabilities.md"


def test_python_runner_network_allowed_when_enabled(tmp_path):
    """With allow_network=True the speed-bump is not installed (socket calls are reachable)."""
    from services.sandbox.python_runner import run_python_file

    # Don't require real connectivity — just prove the bump's OSError isn't the one raised.
    code = (
        "import socket\n"
        "print('HAS_SOCKET', callable(getattr(socket, 'getaddrinfo', None)))\n"
        "s = socket.socket(); print('SOCKET_OBJ_OK'); s.close()\n"
    )
    r = run_python_file(code, tmp_path, inside_sandbox_check=lambda p: True, allow_network=True)
    assert r.get("ok") is True
    assert "HAS_SOCKET True" in (r.get("stdout") or "")
    assert "SOCKET_OBJ_OK" in (r.get("stdout") or "")


def test_shell_runner_blocks_rm(tmp_path):
    from services.sandbox.shell_runner import run_shell_argv

    r = run_shell_argv(["rm", "-rf", "/"], tmp_path, inside_sandbox_check=lambda p: True)
    assert r.get("ok") is False
    assert "blocked" in (r.get("error") or "").lower()


def test_shell_runner_echo(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    # Windows may not have echo as argv[0]; use Python -c
    import sys

    from services.sandbox.shell_runner import run_shell_argv

    r = run_shell_argv([sys.executable, "-c", "print('hi')"], tmp_path, inside_sandbox_check=lambda p: True)
    assert r.get("ok") is True
    assert "hi" in (r.get("stdout") or "")
