"""First-run content-policy + persona are FORCED choices, never silent defaults.

Operator decision (v1-scope-decisions 2026-08-01): pd02 = force a content-policy choice at
first-run (no default); pd01 = the installer ASKS companion-vs-coder so a companion-seeker does
not silently land on the coder model + blunt persona (the #1 confuser).
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.infrastructure.setup_engine import (  # noqa: E402
    DEFAULTS,
    apply_content_policy_choice,
    apply_persona_choice,
)


def test_content_policy_not_chosen_by_default():
    # A fresh config must NOT claim the content policy was already chosen — it is a forced step.
    assert DEFAULTS.get("content_policy_chosen") is False


def test_apply_content_policy_uncensored_on():
    cfg = {}
    apply_content_policy_choice(cfg, True)
    assert cfg["uncensored"] is True
    assert cfg["nsfw_allowed"] is True
    assert cfg["knowledge_unrestricted"] is True
    assert cfg["content_policy_chosen"] is True


def test_apply_content_policy_restricted_turns_everything_off():
    cfg = {"uncensored": True, "nsfw_allowed": True, "knowledge_unrestricted": True}
    apply_content_policy_choice(cfg, False)
    assert cfg["uncensored"] is False
    assert cfg["nsfw_allowed"] is False
    assert cfg["knowledge_unrestricted"] is False
    assert cfg["content_policy_chosen"] is True


def test_persona_companion_vs_coder():
    comp = apply_persona_choice({}, "companion")
    assert comp["persona_choice"] == "companion"
    assert comp["model_category_preference"] == "general"

    coder = apply_persona_choice({}, "coder")
    assert coder["persona_choice"] == "coder"
    assert coder["model_category_preference"] == "coding"

    # Unknown / empty falls back to companion (never silently the coder default).
    assert apply_persona_choice({}, "xyz")["persona_choice"] == "companion"
    assert apply_persona_choice({}, "")["persona_choice"] == "companion"


class _RS:
    def __init__(self, cfg):
        self._c = cfg

    def load_config(self):
        return self._c


def test_provision_domain_defaults_to_companion_not_coder():
    """in05 / #1 confuser: with no explicit domain and no persona config, provisioning must default
    to a companion (general) model, NOT the old hardcoded 'coding' default."""
    from install.provision_model import resolve_provision_domain

    # The critical regression: empty config -> 'general', never 'coding'.
    assert resolve_provision_domain(None, _RS({})) == "general"


def test_provision_domain_honors_persona_choice():
    from install.provision_model import resolve_provision_domain

    # explicit --domain always wins
    assert resolve_provision_domain("coding", _RS({})) == "coding"
    # companion persona -> general
    assert resolve_provision_domain(
        None, _RS({"persona_choice": "companion", "model_category_preference": "general"})
    ) == "general"
    # coder persona -> coding
    assert resolve_provision_domain(
        None, _RS({"persona_choice": "coder", "model_category_preference": "coding"})
    ) == "coding"
