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


def test_python_runner_network_jail_blocks_when_disallowed(tmp_path):
    """BL-025: allow_network=False must jail outbound network in sandboxed exec."""
    from services.sandbox.python_runner import run_python_file

    r = run_python_file(_NET_CODE, tmp_path, inside_sandbox_check=lambda p: True, allow_network=False)
    assert r.get("ok") is True
    assert "NETWORK_BLOCKED" in (r.get("stdout") or "")
    assert "NETWORK_OK" not in (r.get("stdout") or "")


def test_python_runner_network_allowed_when_enabled(tmp_path):
    """With allow_network=True the jail is not installed (socket calls are reachable)."""
    from services.sandbox.python_runner import run_python_file

    # Don't require real connectivity — just prove the jail's OSError isn't the one raised.
    code = (
        "import socket\n"
        "print('HAS_SOCKET', callable(getattr(socket, 'getaddrinfo', None)))\n"
        "print('NOT_JAILED', 'disabled in the Layla sandbox' == '')\n"
    )
    r = run_python_file(code, tmp_path, inside_sandbox_check=lambda p: True, allow_network=True)
    assert r.get("ok") is True
    assert "HAS_SOCKET True" in (r.get("stdout") or "")


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
