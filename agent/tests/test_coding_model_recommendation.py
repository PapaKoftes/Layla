"""The model picker surfaces a coding-specific recommendation, so a user who wants a coding assistant
isn't steered to the companion default (a general/uncensored model). Audit: /setup/models previously
recommended only a general model even for coders."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
from install.model_selector import models_for_picker  # noqa: E402


def test_coding_recommendation_is_a_coder_model():
    p = models_for_picker(16.0, 0.0)
    assert p.get("recommended_coding"), "expected a coding recommendation"
    assert "oder" in p["recommended_coding"], f"coding rec should be a Coder model, got {p['recommended_coding']}"


def test_coding_and_companion_recs_are_distinct_and_flagged():
    p = models_for_picker(16.0, 0.0)
    # companion default is deliberately NOT a coder model
    assert p["recommended"] != p["recommended_coding"]
    flagged = [e for e in p["models"] if e.get("recommended_coding")]
    assert len(flagged) == 1 and flagged[0]["filename"] == p["recommended_coding"]


def test_low_ram_still_offers_a_fitting_coder():
    p = models_for_picker(8.0, 0.0)
    # a small coder (3B/1.5B) should fit 8 GB
    assert p.get("recommended_coding") is None or "oder" in p["recommended_coding"]
