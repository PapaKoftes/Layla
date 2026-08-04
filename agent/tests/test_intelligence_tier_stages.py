"""Output-level tests for the research intelligence-tier stages.

The 9 async stage runners in ``services/reasoning/research_intelligence.py`` had ZERO
output-level coverage — only orchestration state was exercised elsewhere. These tests
run each runner with the LLM (``agent_loop.autonomous_run``) mocked so nothing hits real
inference, redirect ``RESEARCH_BRAIN`` to a tmp dir so no operator state is polluted, and
assert the CONTRACT each runner promises:

    - returns (md, data, status) with status == "ok" (text >= 500 chars),
    - persists the per-stage output file named in INTELLIGENCE_OUTPUTS, non-empty,
    - for the confidence stage, that the extracted JSON ``data`` dict is populated.

Hermetic: tmp dirs only, no network, no real model. Async is driven with asyncio.run()
to match the existing suite convention (see test_stream_output_guard.py / test_ws_manager.py).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

# agent/ on sys.path so `research_stages`, `agent_loop`, and `services.*` import as the
# suite expects (mirrors the other tests in this directory).
AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import agent_loop  # noqa: E402
import research_stages  # noqa: E402
from services.reasoning import research_intelligence as ri  # noqa: E402

# The 9 stages, and the runner each maps to. Kept independent of the module's own
# ordering tuple so the test is a real cross-check, not a tautology.
EXPECTED_STAGES = {
    "confidence",
    "consistency",
    "risk",
    "tradeoffs",
    "patterns",
    "actions",
    "agenda",
    "journal",
    "summary",
}


# A JSON object well over 500 chars whose keys the confidence stage promises to emit.
# _extract_json_block must parse this into a populated dict.
_CONFIDENCE_JSON = json.dumps(
    {
        "findings": [
            {
                "id": f"F{i}",
                "claim": f"Finding {i}: the subsystem behaves predictably under sustained load "
                f"and its failure mode is well understood from repeated observation.",
                "confidence": ["high", "medium", "low"][i % 3],
            }
            for i in range(6)
        ],
        "scores": {"high": 2, "medium": 2, "low": 2},
        "criteria": {
            "high": "verified evidence",
            "medium": "repeated signals",
            "low": "speculative inference",
        },
    },
    indent=2,
)

# A markdown blob comfortably over the 500-char status floor, for the non-confidence stages.
_MARKDOWN_OUTPUT = (
    "# Stage output\n\n"
    + "This is a detailed markdown analysis produced by the mocked model. "
    * 20
    + "\n\n- point one\n- point two\n- point three\n"
)


def _fake_autonomous_run(goal, **kwargs):
    """Stand-in for agent_loop.autonomous_run.

    Returns the canned ``{"steps": [{"result": ...}]}`` shape _run_stage reads. The
    confidence stage gets a >500-char JSON string (so its data dict populates); every
    other stage gets >500 chars of markdown. Both clear the 'ok' status threshold.
    """
    result_text = _CONFIDENCE_JSON if "Confidence" in goal else _MARKDOWN_OUTPUT
    return {"steps": [{"result": result_text}]}


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """Redirect RESEARCH_BRAIN (both the intelligence module's own attr and the
    research_stages attr that _ensure_brain_dirs / _mark_stage_completed / mission-state
    save+load resolve against) to a fresh tmp dir, and mock the LLM. Returns the brain root.
    """
    brain_root = tmp_path / ".research_brain"
    monkeypatch.setattr(ri, "RESEARCH_BRAIN", brain_root)
    monkeypatch.setattr(research_stages, "RESEARCH_BRAIN", brain_root)
    monkeypatch.setattr(agent_loop, "autonomous_run", _fake_autonomous_run)
    return brain_root


def test_runners_dict_has_exactly_nine_callable_stages():
    """INTELLIGENCE_RUNNERS registers exactly the 9 stages, each value callable."""
    assert set(ri.INTELLIGENCE_RUNNERS) == EXPECTED_STAGES
    assert len(ri.INTELLIGENCE_RUNNERS) == 9
    for name, runner in ri.INTELLIGENCE_RUNNERS.items():
        assert callable(runner), f"runner for {name!r} is not callable"
    # Every registered stage also has a declared output target.
    assert set(ri.INTELLIGENCE_OUTPUTS) == EXPECTED_STAGES


@pytest.mark.parametrize("stage", sorted(EXPECTED_STAGES))
def test_stage_returns_ok_and_persists_output(stage, brain, tmp_path):
    """Each runner returns (md, data, status=='ok') and writes a non-empty output file."""
    lab_workspace = str(tmp_path / "lab")
    runner = ri.INTELLIGENCE_RUNNERS[stage]

    md, data, status = asyncio.run(runner(lab_workspace))

    # Contract: status ok, markdown text returned.
    assert status == "ok", f"{stage} status was {status!r}, expected 'ok'"
    assert isinstance(md, str) and md.strip(), f"{stage} returned empty md"
    assert isinstance(data, dict)

    # Output file written per INTELLIGENCE_OUTPUTS, and non-empty.
    sub, name = ri.INTELLIGENCE_OUTPUTS[stage]
    out = brain / sub / name
    assert out.exists(), f"{stage} did not write {out}"
    assert out.read_text(encoding="utf-8").strip(), f"{stage} wrote an empty {name}"

    # The stage was marked completed in mission state (uses the redirected brain).
    mission = research_stages.load_mission_state()
    assert stage in (mission.get("completed") or []), f"{stage} not marked completed"


def test_confidence_stage_populates_json_data(brain, tmp_path):
    """The confidence stage's extracted JSON `data` dict is populated and persisted as JSON."""
    lab_workspace = str(tmp_path / "lab")

    md, data, status = asyncio.run(ri.run_confidence_stage(lab_workspace))

    assert status == "ok"
    assert isinstance(data, dict) and data, "confidence data dict is empty"
    # Keys the confidence stage's JSON is expected to carry.
    assert "findings" in data and "scores" in data and "criteria" in data
    assert isinstance(data["findings"], list) and data["findings"]

    # Persisted file is valid JSON round-tripping to the same populated dict.
    sub, name = ri.INTELLIGENCE_OUTPUTS["confidence"]
    persisted = json.loads((brain / sub / name).read_text(encoding="utf-8"))
    assert persisted == data
    assert "raw" not in persisted, "confidence fell back to {'raw': ...} — JSON extraction failed"
