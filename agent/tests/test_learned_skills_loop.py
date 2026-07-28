# -*- coding: utf-8 -*-
"""The learned-skills loop closes: acquired skills are reachable by the agent, not just the API.

Previously skills were acquired + stored + shown in the UI, but invoke_skill wasn't a tool and the
skills never reached the prompt — so the agent could never replay one. This pins the wiring:
invoke_skill/list_learned_skills are registered (invoke_skill approval-gated), and the system head
lists learned skills so the model knows to call invoke_skill.
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_invoke_and_list_are_registered_and_gated():
    from layla.tools.registry import TOOLS
    assert "list_learned_skills" in TOOLS and not TOOLS["list_learned_skills"].get("dangerous")
    assert "invoke_skill" in TOOLS
    # Replaying a recorded macro executes its steps → must be approval-gated.
    assert TOOLS["invoke_skill"].get("dangerous") is True
    assert TOOLS["invoke_skill"].get("require_approval") is True


def test_invoke_skill_requires_a_name():
    from layla.tools.registry import TOOLS
    r = TOOLS["invoke_skill"]["fn"](name="")
    assert r.get("ok") is False and "name" in r.get("error", "").lower()


def test_learned_skills_reach_the_prompt(monkeypatch):
    import services.prompts.system_head_builder as shb
    monkeypatch.setattr(
        "services.skills.skill_acquisition.list_learned_skills",
        lambda: [{"name": "deploy-preview", "description": "build + open the preview server", "use_count": 3}],
    )
    block = shb._learned_skills_block("please deploy the preview")
    assert "invoke_skill" in block
    assert "deploy-preview" in block


def test_block_is_empty_when_no_skills(monkeypatch):
    import services.prompts.system_head_builder as shb
    monkeypatch.setattr("services.skills.skill_acquisition.list_learned_skills", lambda: [])
    assert shb._learned_skills_block("anything") == ""
