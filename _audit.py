"""Quick audit of Layla's current state."""
import json
import pathlib
import sys
import re

ROOT = pathlib.Path(".")
AGENT = ROOT / "agent"
sys.path.insert(0, str(AGENT))

print("=== PERSONALITIES ===")
for f in sorted(ROOT.glob("personalities/*.json")):
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        spad = d.get("systemPromptAddition", "")
        name = d.get("name", "?")
        print(f"  {f.name:30s}  {len(spad):5d} chars   {name}")
    except Exception as e:
        print(f"  {f.name}: ERROR {e}")

print("\n=== KNOWLEDGE BASE ===")
kfiles = list((ROOT / "knowledge").glob("*.md")) + list((ROOT / "knowledge").glob("*.txt"))
total_kb = sum(f.stat().st_size for f in kfiles) // 1024
print(f"  Files: {len(kfiles)}, Total: {total_kb} KB")
for f in sorted(kfiles):
    print(f"  {f.name:50s}  {f.stat().st_size//1024:4d} KB")

print("\n=== TOOLS ===")
content = (AGENT / "layla/tools/registry.py").read_text(encoding="utf-8")
# Count registered tool names from TOOLS dict entries
in_tools = False
tool_names = []
for line in content.split("\n"):
    if '"fn":' in line:
        continue
    m = re.match(r'\s+"([a-z_][a-z0-9_]*)"\s*:\s*\{', line)
    if m:
        tool_names.append(m.group(1))
print(f"  Registered tools: {len(tool_names)}")

print("\n=== MEMORY ===")
try:
    from layla.memory.db import get_recent_learnings, get_active_study_plans
    ls = get_recent_learnings(n=999)
    plans = get_active_study_plans()
    print(f"  Learnings stored: {len(ls)}")
    print(f"  Study plans: {len(plans)}")
    types = {}
    for l in ls:
        t = l.get("type", "?")
        types[t] = types.get(t, 0) + 1
    print(f"  By type: {dict(sorted(types.items()))}")
except Exception as e:
    print(f"  Memory error: {e}")

print("\n=== TESTS ===")
test_files = list((AGENT / "tests").glob("test_*.py"))
print(f"  Test files: {len(test_files)}")
for tf in sorted(test_files):
    content_t = tf.read_text(encoding="utf-8")
    tests = len(re.findall(r'^\s*def test_', content_t, re.MULTILINE))
    print(f"  {tf.name:40s}  {tests:3d} tests")

print("\n=== GAPS (honest) ===")
gaps = [
    ("CRITICAL", "No model in CI — tests can't verify LLM behavior"),
    ("CRITICAL", "Personality prompts — most aspects are thin (<500 chars)"),
    ("HIGH",     "No real streaming token-by-token (full response buffered)"),
    ("HIGH",     "Agent loop uses sliding window — loses context on long sessions"),
    ("HIGH",     "109 tools but ~60 need optional deps that aren't installed"),
    ("MEDIUM",   "No file tree / project explorer in UI"),
    ("MEDIUM",   "Memory graph queries are heuristic — no semantic graph search"),
    ("MEDIUM",   "Study plans don't accumulate real knowledge between sessions"),
    ("LOW",      "No mobile/tablet responsive layout"),
    ("LOW",      "No export/import of full memory state from UI"),
]
for priority, gap in gaps:
    print(f"  [{priority:8s}] {gap}")
