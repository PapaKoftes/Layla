"""Research lab paths and helpers. Used by research router and main."""
import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger("layla")

AGENT_DIR = Path(__file__).resolve().parent
RESEARCH_LAB_ROOT = AGENT_DIR / ".research_lab"
RESEARCH_LAB_WORKSPACE = RESEARCH_LAB_ROOT / "workspace"
RESEARCH_LAB_SOURCE_COPY = RESEARCH_LAB_WORKSPACE / "source_copy"
RESEARCH_MISSIONS_DIR = AGENT_DIR / "research_missions"
RESEARCH_BRAIN = AGENT_DIR / ".research_brain"
RESEARCH_OUTPUT = AGENT_DIR / ".research_output"

_DEFAULT_OUTPUT_STRUCTURE = (
    "Produce: System Understanding, Weakness Map, Upgrade Opportunities, "
    "Lens Case Study (Carpenter, Assembly, DevOps, Geometry, Product, Strategist), Suggested Roadmap."
)

_ALLOWED_BRAIN_FILES = {
    "summaries/24h_summary.md",
    "actions/action_queue.md",
    "patterns/patterns.md",
    "risk/risk_model.md",
}


def get_default_output_structure() -> str:
    return _DEFAULT_OUTPUT_STRUCTURE


def get_allowed_brain_files() -> set[str]:
    return set(_ALLOWED_BRAIN_FILES)


def ensure_research_lab_dirs() -> None:
    RESEARCH_LAB_ROOT.mkdir(parents=True, exist_ok=True)
    RESEARCH_LAB_WORKSPACE.mkdir(parents=True, exist_ok=True)
    RESEARCH_LAB_SOURCE_COPY.mkdir(parents=True, exist_ok=True)
    (RESEARCH_LAB_WORKSPACE / "experiments").mkdir(parents=True, exist_ok=True)
    (RESEARCH_LAB_WORKSPACE / "notes").mkdir(parents=True, exist_ok=True)


def copy_source_to_lab(workspace_root: str) -> str | None:
    """Copy workspace to .research_lab/workspace/source_copy. Returns lab path or None on failure."""
    src = Path(workspace_root).resolve() if workspace_root else None
    if not src or not src.exists() or not src.is_dir():
        return None
    ensure_research_lab_dirs()
    dst = RESEARCH_LAB_SOURCE_COPY
    try:
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning("research_lab prepare failed: %s", e)
        return None

    EXCLUDE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".research_lab", ".research_brain", ".research_output"}
    MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB

    def _copy_robust(s: Path, d: Path) -> None:
        for entry in s.iterdir():
            if entry.name in EXCLUDE_DIRS:
                continue
            d_entry = d / entry.name
            try:
                if entry.is_dir():
                    d_entry.mkdir(parents=True, exist_ok=True)
                    _copy_robust(entry, d_entry)
                else:
                    if entry.stat().st_size > MAX_FILE_BYTES:
                        continue
                    shutil.copy2(entry, d_entry, follow_symlinks=False)
            except (OSError, Exception) as e:
                logger.debug("research_lab _copy_robust entry failed %s: %s", entry, e)

    try:
        _copy_robust(src, dst)
        return str(RESEARCH_LAB_WORKSPACE)
    except Exception as e:
        logger.warning("research_lab copy failed: %s", e)
        return None


def load_mission_preset(mission_type: str) -> dict:
    preset_path = RESEARCH_MISSIONS_DIR / f"{mission_type}.json"
    if not preset_path.exists():
        return {"objective": "Research the repository. Read-only.", "output_structure": []}
    try:
        return json.loads(preset_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("research_lab load_mission_preset failed: %s", e)
        return {"objective": "Research the repository. Read-only.", "output_structure": []}


def default_mission_state() -> dict:
    """Canonical default so UI always gets the same shape."""
    return {"stage": None, "progress": {}, "completed": [], "status": None, "last_run": None}
