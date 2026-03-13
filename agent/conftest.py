"""
Pytest configuration for the agent test suite.
Ensures the agent directory is on sys.path so all modules are importable
without per-file sys.path.insert() calls.
"""
import sys
from pathlib import Path

# Add the agent directory to sys.path so tests can import agent modules
_AGENT_DIR = Path(__file__).resolve().parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))
