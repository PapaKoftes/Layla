"""Repo layout constants for routers (avoid importing main)."""
from __future__ import annotations

from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent
