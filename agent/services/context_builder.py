"""
Context builder. Assembles system prompt sections for agent head.
Delegates to agent_loop._build_system_head for now; can be fully extracted later.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("layla")
