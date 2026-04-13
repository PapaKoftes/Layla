from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agent"
p = AGENT / "routers" / "agent.py"
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
hdr = '''"""Background agent tasks: queue, threaded/subprocess workers, shared task store."""
import json
import logging
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi.responses import JSONResponse

from agent_loop import autonomous_run
from services.resource_manager import PRIORITY_AGENT, PRIORITY_BACKGROUND, PRIORITY_CHAT
from shared_state import get_conv_history

logger = logging.getLogger("layla")

'''
body = (
    "".join(lines[35:37])
    + "\n"
    + "".join(lines[50:418])
    + "".join(lines[1402:1820])
    + "".join(lines[1994:2024])
)
out = AGENT / "services" / "agent_task_runner.py"
out.write_text(hdr + body, encoding="utf-8")
print("wrote", out, "bytes", len(hdr + body))
