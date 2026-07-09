"""Feature themes: grouped capability toggles map to real, disjoint, whitelisted flags."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import config_schema as cs  # noqa: E402


def test_themes_defined_with_flags():
    assert cs.FEATURE_THEMES
    for t in cs.FEATURE_THEMES:
        assert t["key"] and t["label"] and t["desc"]
        assert t["flags"] and isinstance(t["flags"], dict)


def test_theme_flag_sets_are_disjoint():
    seen = set()
    for t in cs.FEATURE_THEMES:
        for k in t["flags"]:
            assert k not in seen, f"flag {k} used by more than one theme"
            seen.add(k)


def test_theme_state_reflects_config():
    st = cs.get_feature_themes({"scheduler_study_enabled": True, "cluster_enabled": False})
    by = {t["key"]: t["enabled"] for t in st}
    assert by["automation"] is True
    assert by["clustering"] is False


def test_apply_updates_are_whitelisted_and_flip():
    on = cs.feature_theme_updates("external_tools", True)
    off = cs.feature_theme_updates("external_tools", False)
    assert on == {"mcp_client_enabled": True, "plugins_enabled": True}
    assert off == {"mcp_client_enabled": False, "plugins_enabled": False}
    # every key an apply can touch must be in the theme whitelist
    for updates in (on, off):
        assert set(updates).issubset(cs._THEME_FLAG_WHITELIST)


def test_unknown_theme_returns_none():
    assert cs.feature_theme_updates("does_not_exist", True) is None


def test_theme_flags_actually_gate_features():
    # Guard against no-op toggles: every theme flag must be read (gated) somewhere in the
    # backend, not just declared. (voice_input_enabled etc. were rejected for this reason.)
    import re
    src_files = list((AGENT_DIR / "services").rglob("*.py")) + list((AGENT_DIR / "layla").rglob("*.py")) \
        + list((AGENT_DIR / "routers").rglob("*.py")) + [AGENT_DIR / "runtime_safety.py"]
    blob = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in src_files)
    for flag in cs._THEME_FLAG_WHITELIST:
        assert re.search(rf"""get\(["']{re.escape(flag)}["']""", blob), f"{flag} is never gated (no-op toggle)"
