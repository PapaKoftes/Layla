"""
Architectural validation tests for the Layla agent.

These tests enforce architecture rules and prevent regressions in the
codebase structure.  They are cheap to run (no network, no DB) because
they only inspect the filesystem and AST of source files.

Run from agent/:
    pytest tests/test_architecture_boundaries.py -v
"""

import ast
import importlib
import sys
import warnings
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _iter_py_files(root: Path, *, skip_venv: bool = True, skip_tests: bool = True):
    """Yield .py paths under *root*, optionally skipping venv/test dirs."""
    for py_file in root.rglob("*.py"):
        parts_str = str(py_file)
        if skip_venv and ("venv" in parts_str or "site-packages" in parts_str):
            continue
        if skip_tests and "test" in py_file.name.lower():
            continue
        yield py_file


def _parse_file(path: Path):
    """Return an AST tree or *None* on parse failure. BOM-tolerant.

    The ``.lstrip("\\ufeff")`` is load-bearing: a UTF-8 BOM on routers/agent.py (the main chat
    router) made ``ast.parse`` raise, and every boundary scan below silently skipped it via the
    ``if tree is None: continue`` guard — so the 1629-line router was never checked. test_no_source_
    file_is_unparseable now fails loudly if any file cannot be parsed, so a silent skip is impossible.
    """
    try:
        return ast.parse(path.read_text(encoding="utf-8").lstrip("\ufeff"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def test_no_source_file_is_unparseable():
    """Every boundary scan skips files _parse_file cannot handle. This makes that skip LOUD.

    A UTF-8 BOM on routers/agent.py once made every AST gate skip the 1629-line main chat
    router while reporting green. A gate that silently drops the file it polices reports health
    it never measured. This fails, naming the file, if any source file cannot be parsed after
    the BOM strip - the guard that makes the rest of this module trustworthy.
    """
    unparseable = []
    for py_file in _iter_py_files(AGENT_DIR):
        raw = py_file.read_text(encoding="utf-8", errors="replace")
        try:
            ast.parse(raw.lstrip("\ufeff"))
        except SyntaxError as e:
            unparseable.append(f"{py_file.relative_to(AGENT_DIR)}: {e}")
    joined = ("\n  ").join(unparseable)
    assert not unparseable, (
        "source files the architecture gates cannot parse (silently skipped):"
        + joined
    )


# ---------------------------------------------------------------------------
# Test 1 -- No circular imports in critical paths
# ---------------------------------------------------------------------------

CRITICAL_MODULES = [
    "services.safety.agent_safety",
    "services.context.context_manager",
    "services.llm.llm_gateway",
    "services.infrastructure.resource_manager",
    "services.prompts.system_head_builder",
    "shared_state",
]


@pytest.mark.parametrize("mod_name", CRITICAL_MODULES)
def test_no_circular_import_services(mod_name: str):
    """Critical services should import cleanly without circular dependency."""
    importlib.import_module(mod_name)


# ---------------------------------------------------------------------------
# Test 2 -- Routers don't import DB directly
# ---------------------------------------------------------------------------

def test_routers_dont_import_db_directly():
    """Routers should go through the service layer, not access DB directly."""
    router_dir = AGENT_DIR / "routers"
    if not router_dir.is_dir():
        pytest.skip("routers/ directory not found")

    violations = []
    for py_file in router_dir.glob("*.py"):
        tree = _parse_file(py_file)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "layla.memory.db" in node.module:
                    names = [alias.name for alias in (node.names or [])]
                    if "get_connection" in names:
                        violations.append(f"{py_file.name}: direct DB import ({node.module})")
    assert not violations, "Router DB-bypass violations:\n  " + "\n  ".join(violations)


# ---------------------------------------------------------------------------
# Test 3 -- No unexpected root-level service files
# ---------------------------------------------------------------------------

# Files that legitimately live at the agent/ root.  New logic files must be
# placed in a sub-package (services/, core/, layla/, etc.).
KNOWN_ROOT_FILES: set[str] = {
    "__init__.py",
    "main.py",
    "agent_loop.py",
    "shared_state.py",
    "runtime_safety.py",
    "orchestrator.py",
    "decision_schema.py",
    "conftest.py",
    "constants.py",
    "config_schema.py",
    "version.py",
    "first_run.py",
    "execution_state.py",
    "tui.py",
    "diagnose_startup.py",
    "serve.py",       # server launcher (START.bat runs `python serve.py`)
    "port_guard.py",  # serve.py's port-conflict helper
    # Backward-compat shims — audited (BL-009): all RETAINED, each still live via the old root
    # path (imports and/or docs); not deletable. Implementation lives in services/ sub-packages.
    "research_lab.py",           # imported via old path (3 sites)
    "research_intelligence.py",  # root path referenced by ARCHITECTURE/design docs
    "research_stages.py",        # imported via old path (5 sites)
    "research_utils.py",         # imported via old path
    "lens_refresh.py",           # imported via old path (2 sites)
    "probe_hardware.py",         # imported (2 sites)
    "background_job_worker.py",  # subprocess ENTRYPOINT (WORKER_SCRIPT) — must keep + run main()
    # Intentional standalone manual/maintenance tools (BL-011) — run as `python agent/X.py`,
    # documented (FINE-TUNING.md etc.); 0 imports BY DESIGN, kept at root deliberately.
    "download_docs.py",
    "seed_self_training_plans.py",
    "export_finetune_data.py",
}


def test_no_unexpected_root_files():
    """Root agent/ dir should only contain entrypoints and config, not service logic.

    Known exceptions are listed; new files must be placed in packages.
    """
    py_files = {f.name for f in AGENT_DIR.glob("*.py")}
    unexpected = py_files - KNOWN_ROOT_FILES
    # Soft gate: warn today, turn into hard assert after migration phase.
    if unexpected:
        warnings.warn(
            f"Root-level .py files not in allowlist: {sorted(unexpected)}. "
            "New service logic should go in a sub-package.",
            stacklevel=1,
        )


# ---------------------------------------------------------------------------
# Test 4 -- shared_state import count tracking
# ---------------------------------------------------------------------------

def test_shared_state_import_count():
    """Track files that import shared_state.

    Count should decrease over time as callers migrate to dependency
    injection.  Current known importers: ~11 files.
    """
    importers = []
    for py_file in _iter_py_files(AGENT_DIR):
        tree = _parse_file(py_file)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "shared_state" in node.module:
                importers.append(str(py_file.relative_to(AGENT_DIR)))
                break
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "shared_state" in alias.name:
                        importers.append(str(py_file.relative_to(AGENT_DIR)))
                        break

    # Threshold: 16, the HONEST current count. It was 15 only because routers/agent.py carried a
    # UTF-8 BOM that made _parse_file skip it (CP-1) — and that router is itself a shared_state
    # importer, so the gate under-counted the exact file it should have flagged. Ratchet DOWN as
    # callers migrate to SessionContext; never raise it to admit a new importer.
    assert len(importers) <= 16, (
        f"shared_state has {len(importers)} importers (max 16). "
        f"Refactor callers to use services.session_context.\nFiles:\n  "
        + "\n  ".join(sorted(importers))
    )


# ---------------------------------------------------------------------------
# Test 5 -- memory_router bypass detection
# ---------------------------------------------------------------------------

# Directories/prefixes that are part of the memory infrastructure itself
# and are allowed to import from layla.memory.db* directly.
_MEMORY_INFRA_PREFIXES = (
    "layla/memory/",
    "layla/codex/",
    "layla/ingestion/",
    "layla/scheduler/",
    "layla/tools/",
    "services/memory/memory_router.py",
    "shared_state.py",
    "scripts/",
)


def _is_memory_infra(rel_path: str) -> bool:
    return any(rel_path.startswith(prefix) for prefix in _MEMORY_INFRA_PREFIXES)


def test_memory_router_bypass_count():
    """Track direct DB imports from *non-infrastructure* code that bypass
    memory_router.

    The memory layer itself (layla/memory/*, layla/codex/*, etc.) legitimately
    uses layla.memory.db.  The concern is routers, services, and top-level
    modules reaching past memory_router.py.  Count should decrease over time.
    """
    bypasses = []
    for py_file in _iter_py_files(AGENT_DIR):
        rel = str(py_file.relative_to(AGENT_DIR)).replace("\\", "/")
        if _is_memory_infra(rel):
            continue
        tree = _parse_file(py_file)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("layla.memory.db") and "migration" not in node.module:
                    bypasses.append(rel)
                    break

    unique = sorted(set(bypasses))
    # Current known bypasses: ~75 files across routers/ and services/.
    # Ratchet this down as callers migrate to services/memory_router.py.
    assert len(unique) <= 85, (
        f"memory_router bypasses: {len(unique)} (max 85). "
        f"Route through services/memory_router.py.\nFiles:\n  "
        + "\n  ".join(unique)
    )


# ---------------------------------------------------------------------------
# Test 6 -- Services directory flat-file count
# ---------------------------------------------------------------------------

def test_services_flat_file_count():
    """services/ should contain no flat modules except __init__.py.

    The back-compat shims (R8) were removed; every service now lives in a
    sub-package (services/<domain>/<mod>.py). New service logic must be placed
    in a sub-package, never as a flat services/<mod>.py file.
    """
    services = AGENT_DIR / "services"
    if not services.is_dir():
        pytest.skip("services/ directory not found")

    flat_files = [f for f in services.glob("*.py") if f.name != "__init__.py"]
    assert flat_files == [], (
        f"services/ has {len(flat_files)} flat module(s): "
        f"{sorted(f.name for f in flat_files)}. "
        "Service modules must live in a sub-package (services/<domain>/)."
    )


# ---------------------------------------------------------------------------
# Test 7 -- Dead code markers
# ---------------------------------------------------------------------------

# Files known to be dead code.  If they reappear, something went wrong.
DEAD_CODE_FILES = [
    "services/protocols.py",
    "services/tool_generator.py",
    "ui/js/layla-app.js.bak",
]


def test_no_known_dead_code():
    """Files known to be dead code should stay removed."""
    remaining = [f for f in DEAD_CODE_FILES if (AGENT_DIR / f).exists()]
    assert not remaining, f"Dead code still present: {remaining}. Delete these files."


# ---------------------------------------------------------------------------
# Test 8 -- agent_loop.py size tracking
# ---------------------------------------------------------------------------

def test_agent_loop_size():
    """Track agent_loop.py LOC.  Should decrease as we decompose it.

    Target: 500-800 lines.  Threshold is progressive.
    """
    agent_loop = AGENT_DIR / "agent_loop.py"
    if not agent_loop.exists():
        pytest.skip("agent_loop.py not found")

    lines = len(agent_loop.read_text(encoding="utf-8").splitlines())
    # Reduced from 1574 to ~910 lines via decomposition + alias consolidation.
    assert lines <= 1000, (
        f"agent_loop.py is {lines} lines (max 1000). "
        "Extract logic into services/agent/ sub-modules."
    )


# ---------------------------------------------------------------------------
# Test 9 -- Required sub-packages exist
# ---------------------------------------------------------------------------

REQUIRED_SUBPKGS = [
    "services/agent",
    "services/observability",
    "services/retrieval",
    "services/planning",
    "services/skills",
    "services/tools",
    "services/context",
    "services/personality",
]


@pytest.mark.parametrize("pkg", REQUIRED_SUBPKGS)
def test_required_subpackage_exists(pkg: str):
    """Required services sub-packages must have an __init__.py."""
    init_file = AGENT_DIR / pkg / "__init__.py"
    assert init_file.exists(), f"Missing sub-package: {pkg}/ (no __init__.py)"


# ---------------------------------------------------------------------------
# Test 10 -- No flat shims remain (R8 removed all back-compat shims)
# ---------------------------------------------------------------------------

def test_no_flat_service_shims_remain():
    """The flat back-compat shims were removed in R8.

    Every flat services/*.py (other than __init__.py) used to be a
    ``sys.modules[__name__] = import_module(...)`` shim re-exporting the
    canonical services.<domain>.<mod> module.  They are gone now; assert none
    have reappeared.
    """
    services = AGENT_DIR / "services"
    flat = [f.name for f in sorted(services.glob("*.py")) if f.name != "__init__.py"]
    assert flat == [], (
        "Flat services/*.py shims should no longer exist after R8: "
        f"{flat}. Import from the canonical services.<domain>.<mod> path instead."
    )


# ---------------------------------------------------------------------------
# Test 11 -- Canonical service modules import cleanly
# ---------------------------------------------------------------------------

_CANONICAL_MODULES = [
    "services.llm.llm_gateway",
    "services.personality.maturity_engine",
    "services.infrastructure.resource_manager",
    "services.cluster.cluster_network",
    "services.tools.tool_dispatch",
    "services.memory.memory_router",
    "services.planning.planner",
    "services.observability.telemetry",
    "services.safety.content_guard",
    "services.observability.prom_metrics",
    "services.personality.evolution",
]


@pytest.mark.parametrize("mod_path", _CANONICAL_MODULES)
def test_canonical_service_modules_import(mod_path):
    """Canonical service modules (former shim targets) must import cleanly."""
    importlib.import_module(mod_path)


# ---------------------------------------------------------------------------
# Test 12 -- Subdirectory modules are non-empty
# ---------------------------------------------------------------------------

ALL_SUBDIRS = [
    "agent", "cluster", "context", "governance", "infrastructure",
    "llm", "memory", "observability", "personality", "planning",
    "prompts", "reasoning", "retrieval", "safety", "sandbox",
    "skills", "tools", "user", "workspace",
]


@pytest.mark.parametrize("subdir", ALL_SUBDIRS)
def test_subdir_has_real_modules(subdir):
    """Each service subdirectory should have at least 1 real .py file."""
    d = AGENT_DIR / "services" / subdir
    if not d.is_dir():
        pytest.skip(f"services/{subdir}/ not found")
    real_files = [f for f in d.glob("*.py") if f.name != "__init__.py"]
    assert len(real_files) >= 1, f"services/{subdir}/ has no real modules"


# ---------------------------------------------------------------------------
# Test 13 -- Backward-compat names on agent_loop
# ---------------------------------------------------------------------------

_REQUIRED_AGENT_LOOP_ATTRS = [
    "autonomous_run",
    "stream_reason",
    "_llm_decision",
    "_is_junk_reply",
    "_quick_reply_for_trivial_turn",
    "system_overloaded",
    "classify_intent",
    "_build_system_head",
    "_format_steps",
    "TOOLS",
    "AgentRunRequest",
    "autonomous_run_from_request",
]


def test_agent_loop_backward_compat_attrs():
    """Key names must remain accessible on agent_loop for backward compat."""
    import agent_loop as al
    missing = [a for a in _REQUIRED_AGENT_LOOP_ATTRS if not hasattr(al, a)]
    assert not missing, f"Missing attributes on agent_loop: {missing}"
