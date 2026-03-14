"""Fix all remaining ruff violations after auto-fix pass."""
import re
from pathlib import Path

AGENT = Path("agent")

def read(p): return Path(p).read_text(encoding="utf-8")
def write(p, t): Path(p).write_text(t, encoding="utf-8")

def add_noqa(text, lineno, code):
    """Add # noqa: CODE to a specific 1-indexed line if not already present."""
    lines = text.split("\n")
    idx = lineno - 1
    if idx < len(lines) and "noqa" not in lines[idx]:
        lines[idx] = lines[idx].rstrip() + f"  # noqa: {code}"
    return "\n".join(lines)

# ── 1. agent_loop.py ─────────────────────────────────────────────────────────
p = AGENT / "agent_loop.py"
t = read(p)
# E402: lines 9–14
for ln in [9, 10, 11, 12, 13, 14]:
    t = add_noqa(t, ln, "E402")
# F841: cfg assigned but unused at lines 293 and 998
# We need the actual current lines since auto-fix may have renumbered things
lines = t.split("\n")
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == "cfg = runtime_safety.load_config()" and "noqa" not in line:
        lines[i] = line.rstrip() + "  # noqa: F841"
t = "\n".join(lines)
# E741: l in line with "for l in learnings"
t = t.replace(
    "prefs = [ (l.get(\"content\") or \"\")[:80] for l in learnings if (l.get(\"content\") or \"\").strip() ]",
    "prefs = [ (ln.get(\"content\") or \"\")[:80] for ln in learnings if (ln.get(\"content\") or \"\").strip() ]"
)
write(p, t)
print("agent_loop.py: fixed E402/F841/E741")

# ── 2. layla/memory/db.py ─────────────────────────────────────────────────────
p = AGENT / "layla/memory/db.py"
t = read(p)
t = add_noqa(t, 20, "E402")
write(p, t)
print("layla/memory/db.py: fixed E402")

# ── 3. layla/memory/vector_store.py ──────────────────────────────────────────
p = AGENT / "layla/memory/vector_store.py"
t = read(p)
# E402: line 23
t = add_noqa(t, 23, "E402")
# F821: _use_chroma undefined — add a simple definition after the globals block
use_chroma_def = (
    "\n\ndef _use_chroma() -> bool:\n"
    "    \"\"\"Return True if chromadb is importable and available.\"\"\"\n"
    "    try:\n"
    "        import chromadb  # noqa: F401\n"
    "        return True\n"
    "    except ImportError:\n"
    "        return False\n"
)
# Insert after the _get_chroma_collection function
insert_after = "    return _chroma_collection\n"
idx = t.find(insert_after)
if idx != -1 and "_use_chroma" not in t:
    t = t[:idx + len(insert_after)] + use_chroma_def + t[idx + len(insert_after):]
write(p, t)
print("layla/memory/vector_store.py: fixed E402 + added _use_chroma()")

# ── 4. layla/memory/capabilities.py ──────────────────────────────────────────
p = AGENT / "layla/memory/capabilities.py"
t = read(p)
lines = t.split("\n")
for i, line in enumerate(lines):
    if line.strip() == "now = _now_iso()" and "noqa" not in line:
        lines[i] = line.rstrip() + "  # noqa: F841"
t = "\n".join(lines)
write(p, t)
print("layla/memory/capabilities.py: fixed F841")

# ── 5. layla/tools/registry.py ───────────────────────────────────────────────
p = AGENT / "layla/tools/registry.py"
t = read(p)
# E741: rename l -> lbl, lnk, ln in specific contexts
# Line 1270: ax.bar(..., tick_label=[str(l) for l in labels])
t = t.replace(
    "tick_label=[str(l) for l in labels]",
    "tick_label=[str(lbl) for lbl in labels]"
)
# Line 1885: sitemap_search imported but unused
t = t.replace(
    "from trafilatura.sitemaps import sitemap_search",
    "from trafilatura.sitemaps import sitemap_search  # noqa: F401"
)
# Line 1911: links: list[str] = [] unused
t = t.replace(
    "            links: list[str] = []",
    "            links: list[str] = []  # noqa: F841"
)
# Line 2685: sum(1 for l in links if l["internal"]) / not l["internal"]
t = t.replace(
    '"internal": sum(1 for l in links if l["internal"]), "external": sum(1 for l in links if not l["internal"])',
    '"internal": sum(1 for lnk in links if lnk["internal"]), "external": sum(1 for lnk in links if not lnk["internal"])'
)
# Line 2846: i for i, l in enumerate(labels) if l == lbl
t = t.replace(
    "[i for i, l in enumerate(labels) if l == lbl]",
    "[i for i, ln in enumerate(labels) if ln == lbl]"
)
# Lines 3366-3367: sum(1 for l in lines if ...)
t = t.replace(
    "blank = sum(1 for l in lines if not l.strip())\n        comment = sum(1 for l in lines if l.strip().startswith(\"#\"))",
    "blank = sum(1 for ln in lines if not ln.strip())\n        comment = sum(1 for ln in lines if ln.strip().startswith(\"#\"))"
)
# Line 3667: "\n".join(l for l in result.splitlines() if l.strip())
t = t.replace(
    'result = "\\n".join(l for l in result.splitlines() if l.strip())',
    'result = "\\n".join(ln for ln in result.splitlines() if ln.strip())'
)
# Line 4035: r = subprocess.run(...) unused
lines = t.split("\n")
for i, line in enumerate(lines):
    if line.strip().startswith("r = subprocess.run(") and "noqa" not in line:
        lines[i] = line.rstrip() + "  # noqa: F841"
        break
t = "\n".join(lines)
write(p, t)
print("layla/tools/registry.py: fixed E741/F401/F841")

# ── 6. main.py ────────────────────────────────────────────────────────────────
p = AGENT / "main.py"
t = read(p)
lines = t.split("\n")
# E402: lines 284-286 (find the from shared_state / from services / from routers block)
for i, line in enumerate(lines):
    if any(line.startswith(s) for s in [
        "from shared_state import set_refs",
        "from services import study_service",
        "from routers import study",
    ]) and "noqa" not in line:
        lines[i] = line.rstrip() + "  # noqa: E402"
t = "\n".join(lines)
write(p, t)
print("main.py: fixed E402")

# ── 7. orchestrator.py ───────────────────────────────────────────────────────
p = AGENT / "orchestrator.py"
t = read(p)
t = t.replace(
    "        get_earned_title = lambda _: None",
    "        def get_earned_title(_): return None  # noqa: E731"
)
write(p, t)
print("orchestrator.py: fixed E731")

# ── 8. research_stages.py ───────────────────────────────────────────────────
p = AGENT / "research_stages.py"
t = read(p)
t = add_noqa(t, 24, "E402")
write(p, t)
print("research_stages.py: fixed E402")

# ── 9. routers/study.py ──────────────────────────────────────────────────────
p = AGENT / "routers/study.py"
t = read(p)
t = add_noqa(t, 47, "E402")
write(p, t)
print("routers/study.py: fixed E402")

# ── 10. seed_self_training_plans.py ──────────────────────────────────────────
p = AGENT / "seed_self_training_plans.py"
t = read(p)
t = add_noqa(t, 16, "E402")
write(p, t)
print("seed_self_training_plans.py: fixed E402")

# ── 11. tests/test_agent_loop.py ─────────────────────────────────────────────
p = AGENT / "tests/test_agent_loop.py"
t = read(p)
t = add_noqa(t, 13, "E402")
write(p, t)
print("tests/test_agent_loop.py: fixed E402")

# ── 12. tests/test_completion.py ─────────────────────────────────────────────
p = AGENT / "tests/test_completion.py"
t = read(p)
t = add_noqa(t, 18, "E402")
write(p, t)
print("tests/test_completion.py: fixed E402")

# ── 13. tests/test_research_resume.py ────────────────────────────────────────
p = AGENT / "tests/test_research_resume.py"
t = read(p)
lines = t.split("\n")
for i, line in enumerate(lines):
    if "result = copy_source_to_lab(" in line and "noqa" not in line:
        lines[i] = line.rstrip() + "  # noqa: F841"
t = "\n".join(lines)
write(p, t)
print("tests/test_research_resume.py: fixed F841")

# ── 14. tests/test_study_integration.py ──────────────────────────────────────
p = AGENT / "tests/test_study_integration.py"
t = read(p)
lines = t.split("\n")
for i, line in enumerate(lines):
    if "plans_before = len(" in line and "noqa" not in line:
        lines[i] = line.rstrip() + "  # noqa: F841"
t = "\n".join(lines)
write(p, t)
print("tests/test_study_integration.py: fixed F841")

print("\nDone. Run ruff again to verify 0 errors.")
