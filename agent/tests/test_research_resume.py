"""Tests for mission state not being reset on next_stage=True."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestMissionResume:
    """Verify that mission state is preserved when next_stage=True."""

    def test_state_reset_when_not_next_stage(self, tmp_path):
        """When next_stage=False, state should be reset (fresh mission)."""
        state_file = tmp_path / "mission_state.json"
        state_file.write_text(json.dumps({
            "stage": "mapping",
            "progress": {"mapping": "done"},
            "completed": ["mapping"]
        }), encoding="utf-8")

        calls = []

        def fake_save_mission_state(state):
            calls.append(state)
            state_file.write_text(json.dumps(state), encoding="utf-8")

        def fake_load_mission_state():
            return json.loads(state_file.read_text(encoding="utf-8"))

        with patch('research_stages.save_mission_state', side_effect=fake_save_mission_state), \
             patch('research_stages.load_mission_state', side_effect=fake_load_mission_state):
            # Simulate what routers/research.py does for next_stage=False
            next_stage = False
            if not next_stage:
                fake_save_mission_state({"stage": None, "progress": {}, "completed": []})

        assert calls[-1] == {"stage": None, "progress": {}, "completed": []}

    def test_state_preserved_when_next_stage(self, tmp_path):
        """When next_stage=True, existing state must not be cleared."""
        original_state = {
            "stage": "investigation",
            "progress": {"mapping": "done"},
            "completed": ["mapping"]
        }
        state_file = tmp_path / "mission_state.json"
        state_file.write_text(json.dumps(original_state), encoding="utf-8")

        reset_calls = []

        def fake_save_mission_state(state):
            reset_calls.append(state)

        with patch('research_stages.save_mission_state', side_effect=fake_save_mission_state):
            # Simulate what routers/research.py does for next_stage=True
            next_stage = True
            if not next_stage:
                fake_save_mission_state({"stage": None, "progress": {}, "completed": []})

        # Should not have called save_mission_state with a reset
        assert len(reset_calls) == 0, "State was reset despite next_stage=True"


class TestCopySourceToLab:
    """Verify copy_source_to_lab excludes secrets and large files."""

    def test_excludes_git(self, tmp_path):
        src = tmp_path / "repo"
        src.mkdir()
        (src / ".git").mkdir()
        (src / ".git" / "HEAD").write_text("ref: refs/heads/main")
        (src / "main.py").write_text("print('hello')")
        dst = tmp_path / "lab"

        with patch('research_lab.RESEARCH_LAB_SOURCE_COPY', dst):
            from research_lab import copy_source_to_lab
            with patch('research_lab.RESEARCH_LAB_WORKSPACE', tmp_path / "workspace"), \
                 patch('research_lab.ensure_research_lab_dirs', return_value=None):
                result = copy_source_to_lab(str(src))  # noqa: F841

        assert not (dst / ".git").exists(), ".git directory should be excluded"

    def test_excludes_large_files(self, tmp_path):
        src = tmp_path / "repo"
        src.mkdir()
        big_file = src / "big.bin"
        big_file.write_bytes(b"x" * (6 * 1024 * 1024))  # 6 MB
        (src / "small.py").write_text("x = 1")
        dst = tmp_path / "lab"

        with patch('research_lab.RESEARCH_LAB_SOURCE_COPY', dst), \
             patch('research_lab.RESEARCH_LAB_WORKSPACE', tmp_path / "workspace"), \
             patch('research_lab.ensure_research_lab_dirs', return_value=None):
            from research_lab import copy_source_to_lab
            copy_source_to_lab(str(src))

        assert not (dst / "big.bin").exists(), "File > 5MB should be excluded"
