"""
Pytest configuration for the agent test suite.
Ensures the agent directory is on sys.path so all modules are importable
without per-file sys.path.insert() calls.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add the agent directory to sys.path so tests can import agent modules
_AGENT_DIR = Path(__file__).resolve().parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))


@pytest.fixture(autouse=True)
def _relax_python_compat_for_tests(request: pytest.FixtureRequest) -> None:
    """
    main.py runs setup.python_compat before FastAPI loads. Chroma/pydantic wheels can be
    environment-specific; tests use a stub so they target app behavior, not the full stack.
    """
    if request.node.get_closest_marker("real_python_compat"):
        yield
        return
    fake = {
        "status": "supported",
        "version": sys.version.split()[0],
        "issues": [],
        "critical_blockers": [],
        "safe_mode": False,
    }
    with patch("setup.python_compat.check_python_compatibility", return_value=fake):
        yield
