"""
Tool orchestration. Tool dispatch, approval flow, verification.
Used by agent_loop for executing tools and handling approval_required.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("layla")
