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
    Returns {"skills_added", "tools_added", "capabilities_added", "errors"}.
    """
    plugins_dir = REPO_ROOT / "plugins"
    raw = (cfg or {}).get("plugins_dir")
    if raw:
        plugins_dir = Path(raw).expanduser().resolve()

    result = {"skills_added": 0, "tools_added": 0, "capabilities_added": 0, "errors": []}

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

            raw_yaml = manifest_path.read_text(encoding="utf-8")
            if len(raw_yaml) > 256_000:
                result["errors"].append(f"{plugin_path.name}: plugin.yaml too large, skipped")
                continue
            data = yaml.safe_load(raw_yaml)
        except Exception as e:
            result["errors"].append(f"{plugin_path.name}: yaml parse failed: {e}")
            continue
        if not isinstance(data, dict):
            result["errors"].append(f"{plugin_path.name}: plugin.yaml must be a mapping at root")
            continue

        name = data.get("name") or plugin_path.name
        skills = data.get("skills") or []
        tools = data.get("tools") or []
        capabilities = data.get("capabilities") or []
        if skills and not isinstance(skills, list):
            result["errors"].append(f"{name}: skills must be a list")
            skills = []
        if tools and not isinstance(tools, list):
            result["errors"].append(f"{name}: tools must be a list")
            tools = []
        if capabilities and not isinstance(capabilities, list):
            result["errors"].append(f"{name}: capabilities must be a list")
            capabilities = []

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

        for c in capabilities:
            if not isinstance(c, dict):
                result["errors"].append(f"{name}.capabilities: entry is not an object, skipped")
                continue
            cap_name = (c.get("capability") or "").strip()
            impl_id = (c.get("id") or "").strip()
            if not cap_name or not impl_id:
                result["errors"].append(f"{name}.capabilities: missing capability or id, skipped")
                continue
            if len(cap_name) > 120 or len(impl_id) > 120:
                result["errors"].append(f"{name}.capabilities.{impl_id}: id/capability too long, skipped")
                continue
            try:
                from capabilities.registry import CapabilityImpl, register_implementation

                deps = c.get("dependencies")
                if not isinstance(deps, list):
                    deps = []
                impl = CapabilityImpl(
                    id=impl_id,
                    package=str(c.get("package") or "")[:200],
                    module_path=str(c.get("module_path") or "layla.tools.registry")[:300],
                    description=str(c.get("description") or "")[:2000],
                    min_python=str(c.get("min_python") or "3.11")[:20],
                    dependencies=[str(x)[:120] for x in deps[:50]],
                    config_keys=list(c.get("config_keys") or []) if isinstance(c.get("config_keys"), list) else [],
                    is_default=bool(c.get("is_default", False)),
                )
                register_implementation(cap_name, impl)
                result["capabilities_added"] += 1
            except Exception as e:
                result["errors"].append(f"{name}.capabilities.{impl_id}: {e}")

    return result
