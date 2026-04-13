"""Rebuild routers/agent.py without sections moved to agent_task_runner, learn, agent_tasks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
p = ROOT / "agent" / "routers" / "agent.py"
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)

bridge = """
from services.agent_task_runner import (
    _build_reasoning_tree_summary,
    _json_safe,
)
from routers.learn import router as _learn_router
from routers.agent_tasks import router as _agent_tasks_router

router.include_router(_learn_router)
router.include_router(_agent_tasks_router)


"""

# lines 1-35 (router =), skip _TASKS; lines 40-50 _watch; lines 501-1401 body through agent() return
part_a = lines[0:35]
part_b = lines[39:50]
part_c = lines[500:1401]

# Drop subprocess from imports in part_a (no longer used in this module)
new_a = []
for ln in part_a:
    if ln.strip() == "import subprocess":
        continue
    new_a.append(ln)

out = "".join(new_a) + "".join(part_b) + bridge + "".join(part_c)
p.write_text(out, encoding="utf-8")
print("agent.py lines:", len(out.splitlines()))
