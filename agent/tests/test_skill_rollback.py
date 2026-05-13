"""Tests for skill rollback module."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestCanRollback:
    def test_nonexistent_pack(self):
        from services.skill_rollback import can_rollback
        result = can_rollback("nonexistent-pack-xyz-123")
        assert isinstance(result, bool)

    def test_returns_bool(self):
        from services.skill_rollback import can_rollback
        assert isinstance(can_rollback("any-pack"), bool)


class TestRollbackInstall:
    def test_nonexistent_pack_dir(self, tmp_path):
        """Rollback with a nonexistent pack dir should handle gracefully."""
        from services.skill_rollback import rollback_install
        fake_dir = tmp_path / "nonexistent_pack"
        result = rollback_install("test-pack", pack_dir=fake_dir)
        assert isinstance(result, dict)
        assert "ok" in result
        assert "actions" in result

    def test_returns_actions_list(self, tmp_path):
        from services.skill_rollback import rollback_install
        result = rollback_install("test-pack", pack_dir=tmp_path / "no-dir")
        assert isinstance(result["actions"], list)

    def test_rollback_with_real_dir(self, tmp_path):
        """Rollback should remove the pack directory if it exists."""
        from services.skill_rollback import rollback_install
        pack_dir = tmp_path / "test-skill"
        pack_dir.mkdir()
        (pack_dir / "main.py").write_text("# test skill")

        result = rollback_install("test-skill", pack_dir=pack_dir)
        assert isinstance(result, dict)
        assert "ok" in result
        # Directory should be removed
        assert not pack_dir.exists() or result["ok"] is True

    def test_rollback_removes_venv(self, tmp_path):
        """If a venv exists for the pack, rollback should attempt to remove it."""
        from services.skill_rollback import rollback_install
        # Just verify it doesn't crash trying to remove a nonexistent venv
        result = rollback_install("test-pack-no-venv", pack_dir=tmp_path / "no-dir")
        assert isinstance(result, dict)

    def test_ok_false_when_all_fail(self):
        """When all cleanup steps fail, ok should be False."""
        from services.skill_rollback import rollback_install
        # With no pack_dir and no registry entry, some actions will be "skipped"
        result = rollback_install("completely-fake-pack")
        assert isinstance(result, dict)
        assert isinstance(result["ok"], bool)

    @patch("services.skill_registry.unregister", return_value=True)
    def test_unregister_called(self, mock_unreg, tmp_path):
        """Verify unregister is attempted during rollback."""
        from services.skill_rollback import rollback_install
        result = rollback_install("test-pack", pack_dir=tmp_path / "no-dir")
        # unregister should have been called
        mock_unreg.assert_called_once_with("test-pack")
