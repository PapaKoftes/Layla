"""
Plugin loader. Scans plugins/*/plugin.yaml and registers skills (and optionally tools).
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_plugins(cfg: dict | None = None) -> dict:
    """
    Load plugins from plugins_dir (default: repo_root/plugins).
    Returns {"skills_added": int, "tools_added": int, "errors": list[str]}.
    """
    plugins_dir = REPO_ROOT / "plugins"
    raw = (cfg or {}).get("plugins_dir")
    if raw:
        plugins_dir = Path(raw).expanduser().resolve()

    result = {"skills_added": 0, "tools_added": 0, "errors": []}

    if not plugins_dir.exists():
        return result

    for plugin_path in sorted(plugins_dir.iterdir()):
        if not plugin_path.is_dir():
            continue
        manifest_path = plugin_path / "plugin.yaml"
        if not manifest_path.exists():
            continue
        try:
            import yaml
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            result["errors"].append(f"{plugin_path.name}: {e}")
            continue
        if not isinstance(data, dict):
            continue

        name = data.get("name") or plugin_path.name
        skills = data.get("skills") or []
        tools = data.get("tools") or []

        for s in skills:
            if isinstance(s, dict) and s.get("name") and s.get("tools"):
                try:
                    from layla.skills.registry import SKILLS
                    skill_name = s.get("name", "").strip()
                    if skill_name and skill_name not in SKILLS:
                        SKILLS[skill_name] = {
                            "description": s.get("description", ""),
                            "tools": s["tools"] if isinstance(s["tools"], list) else [],
                            "execution_steps": s.get("execution_steps", []),
                        }
                        result["skills_added"] += 1
                except Exception as e:
                    result["errors"].append(f"{name}.{s.get('name', '?')}: {e}")

        if tools:
            try:
                tools_module = plugin_path / "tools.py"
                if tools_module.exists():
                    import importlib.util
                    spec = importlib.util.spec_from_file_location(f"plugin_{name}_tools", tools_module)
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        if hasattr(mod, "register"):
                            from layla.tools import registry as reg
                            before = len(reg.TOOLS)
                            mod.register(reg.TOOLS)
                            result["tools_added"] += len(reg.TOOLS) - before
            except Exception as e:
                result["errors"].append(f"{name}.tools: {e}")

    return result
