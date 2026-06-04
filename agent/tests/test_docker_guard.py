"""Tests for docker_run sandbox-escape flag guard (layla/tools/impl/system.py).

docker_run is approval-gated, but on approval it passed arbitrary args straight
to `docker run` — including host bind mounts / privileged / host namespaces that
escape the sandbox. The guard refuses those before exec. Pure logic, no Docker
needed.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.tools.impl.system import _docker_dangerous_flags, docker_run  # noqa: E402

DANGEROUS = [
    "--privileged",
    "-v /:/host",
    "--volume /etc:/etc",
    "--mount type=bind,src=/,dst=/h",
    "--network=host",
    "--net host",
    "--pid=host",
    "--ipc=host",
    "--device /dev/sda",
    "--cap-add SYS_ADMIN",
    "--security-opt seccomp=unconfined",
    "--userns=host",
]

BENIGN = [
    "echo hi",
    "--network=bridge alpine echo hi",
    "-e FOO=bar python:3.12 python -c print(1)",
    "alpine sh -c 'echo ok'",
]


def test_dangerous_flags_detected():
    for a in DANGEROUS:
        assert _docker_dangerous_flags(a), f"should be blocked: {a}"


def test_benign_flags_allowed():
    for a in BENIGN:
        assert not _docker_dangerous_flags(a), f"should be allowed: {a}"


def test_docker_run_refuses_before_exec():
    r = docker_run("alpine", "--privileged")
    assert r["ok"] is False
    assert "Refused" in r["error"]
    r2 = docker_run("alpine", "-v /:/host")
    assert r2["ok"] is False and "Refused" in r2["error"]
