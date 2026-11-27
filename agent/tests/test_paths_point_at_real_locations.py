"""Features find their files where the repo actually keeps them.

Each of these resolved its root one level too shallow (agent/services instead of agent/, or agent/ instead
of the repo root), so the feature silently looked at a folder that does not exist or holds nothing:
background subprocess workers pointed at a missing script, the doctor checked a config file that never
exists, plugins/ and skills/ were never scanned, and mDNS announced version 0.0.0.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_background_subprocess_worker_script_exists():
    from services.infrastructure.background_subprocess import WORKER_SCRIPT

    assert WORKER_SCRIPT.is_file(), WORKER_SCRIPT


def test_plugins_are_loaded_from_the_documented_folder_and_examples_are_skipped(tmp_path):
    from services.skills.plugin_loader import REPO_ROOT as plugin_root
    from services.skills.plugin_loader import load_plugins

    assert plugin_root == REPO_ROOT and (plugin_root / "plugins" / "README.md").is_file()
    for n in ("_example", "real"):
        (tmp_path / n).mkdir()
        manifest = [f"name: {n}", "skills:", f"  - name: {n.strip('_')}_skill", "    description: d",
                    "    tools: [read_file]", "tools: []", ""]
        (tmp_path / n / "plugin.yaml").write_text("\n".join(manifest), encoding="utf-8")
    res = load_plugins({"plugins_dir": str(tmp_path)})
    assert res.get("errors") == [], res
    assert res.get("skills_added") == 1, res  # "real" only; "_example" is skipped


def test_markdown_skills_scan_the_repo_skills_folder():
    from services.skills import markdown_skills

    assert markdown_skills.REPO_ROOT == REPO_ROOT and (REPO_ROOT / "skills" / "README.md").is_file()


def test_doctor_reports_the_real_config_and_database():
    import runtime_safety
    from layla.memory.db_connection import _resolve_db_path
    from services.infrastructure import system_doctor

    src = Path(system_doctor.__file__).read_text(encoding="utf-8")
    assert '"runtime_config.json"' not in src, "the doctor must not read runtime_config.json directly"
    assert "runtime_safety.CONFIG_FILE" in src and "_resolve_db_path()" in src
    assert runtime_safety.CONFIG_FILE and _resolve_db_path()


def test_models_dir_has_one_owner(monkeypatch, tmp_path):
    import runtime_safety

    assert runtime_safety.models_dir({"models_dir": str(tmp_path)}) == tmp_path.resolve()
    assert runtime_safety.models_dir({}) == runtime_safety.default_models_dir()


def test_mdns_announces_the_real_version_and_keeps_its_id_in_agent_governance():
    from services.cluster import mdns_discovery as md
    from version import __version__

    assert md._get_version() == __version__ != "0.0.0"
    assert md._AGENT_DIR == AGENT_DIR
