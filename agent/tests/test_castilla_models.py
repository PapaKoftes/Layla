"""Tests for Castilla model selection: per-aspect kits + the language helper.

Verifies each personality maps to its domain's model and that the translation/intent
helper is a small multilingual model. numpy-free; runs anywhere.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from install.model_selector import (  # noqa: E402
    _params_b,
    recommend_aspect_kit,
    recommend_language_assist,
)

HER = {"ram_gb": 16.0, "vram_gb": 0.0, "acceleration_backend": "none",
       "gpu_name": "none", "physical_cores": 4}


def test_language_assist_is_small_multilingual():
    la = recommend_language_assist(HER)
    assert la is not None
    assert la.get("multilingual") is True
    assert _params_b(la) <= 2.0           # a lightweight helper, not the main model
    assert "1.5b" in la["name"].lower()


def test_aspect_morrigan_gets_coding_model():
    k = recommend_aspect_kit("morrigan", HER, prefer="lite")
    assert k and k["primary"]["category"] == "coding"


def test_aspect_nyx_gets_reasoning_model():
    k = recommend_aspect_kit("nyx", HER, prefer="lite")
    assert k and k["primary"]["category"] == "reasoning"


def test_aspect_echo_gets_general_model():
    k = recommend_aspect_kit("echo", HER, prefer="lite")
    assert k and k["primary"]["category"] == "general"


def test_unknown_aspect_defaults_to_general():
    k = recommend_aspect_kit("doesnotexist", HER, prefer="lite")
    assert k and k["primary"]["category"] == "general"


def test_aspect_case_insensitive():
    a = recommend_aspect_kit("MORRIGAN", HER, prefer="lite")
    b = recommend_aspect_kit("morrigan", HER, prefer="lite")
    assert a["primary"]["name"] == b["primary"]["name"]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
