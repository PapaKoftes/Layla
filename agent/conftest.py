"""
Pytest configuration for the agent test suite.
Ensures the agent directory is on sys.path so all modules are importable
without per-file sys.path.insert() calls.
"""
import os
import sys
from pathlib import Path

# `main.py` exits on Python 3.13+ unless this is set; tests may run on newer interpreters.
if sys.version_info >= (3, 13):
    os.environ.setdefault("LAYLA_ALLOW_UNSUPPORTED_PYTHON", "1")

# Add the agent directory to sys.path so tests can import agent modules
_AGENT_DIR = Path(__file__).resolve().parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))
