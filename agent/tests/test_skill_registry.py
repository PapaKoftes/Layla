"""Tests for skill pack registry (SQLite-backed)."""
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def temp_registry(tmp_path):
    """Use a temporary database for each test."""
    import services.skill_registry as sr
    sr._conn = None
    sr._DB_PATH = tmp_path / "test_skill_registry.db"
    yield
    sr.close_db()


class TestRegister:
    def test_register_basic(self):
        from services.skill_registry import get_pack, register
        register("test-pack", "1.0.0", "/path/to/pack")
        pack = get_pack("test-pack")
        assert pack is not None
        assert pack["name"] == "test-pack"
        assert pack["version"] == "1.0.0"
        assert pack["health_status"] == "installed"

    def test_register_with_manifest(self):
        from services.skill_registry import get_pack, register
        manifest = {"name": "mp", "version": "2.0"}
        register("mp", "2.0.0", "/path", manifest=manifest, git_url="https://github.com/x/y")
        pack = get_pack("mp")
        assert pack["git_url"] == "https://github.com/x/y"
        assert pack["manifest_hash"] != ""

    def test_register_with_permissions(self):
        from services.skill_registry import get_pack, register
        register("perm-pack", "1.0", "/p", permissions=["read_memory", "write_file"])
        pack = get_pack("perm-pack")
        assert pack["permissions"] == ["read_memory", "write_file"]

    def test_re_register_updates(self):
        from services.skill_registry import get_pack, register
        register("updatable", "1.0", "/v1")
        register("updatable", "2.0", "/v2")
        pack = get_pack("updatable")
        assert pack["version"] == "2.0"
        assert pack["pack_dir"] == "/v2"


class TestUnregister:
    def test_unregister_existing(self):
        from services.skill_registry import get_pack, register, unregister
        register("doomed", "1.0", "/path")
        assert unregister("doomed") is True
        assert get_pack("doomed") is None

    def test_unregister_nonexistent(self):
        from services.skill_registry import unregister
        assert unregister("nope") is False


class TestListPacks:
    def test_empty(self):
        from services.skill_registry import list_packs
        assert list_packs() == []

    def test_lists_all(self):
        from services.skill_registry import list_packs, register
        register("a", "1.0", "/a")
        register("b", "2.0", "/b")
        packs = list_packs()
        names = [p["name"] for p in packs]
        assert "a" in names
        assert "b" in names

    def test_sorted_by_name(self):
        from services.skill_registry import list_packs, register
        register("zzz", "1.0", "/z")
        register("aaa", "1.0", "/a")
        packs = list_packs()
        assert packs[0]["name"] == "aaa"
        assert packs[1]["name"] == "zzz"


class TestHealthStatus:
    def test_default_installed(self):
        from services.skill_registry import get_pack, register
        register("healthy", "1.0", "/path")
        pack = get_pack("healthy")
        assert pack["health_status"] == "installed"

    def test_update_health(self):
        from services.skill_registry import get_pack, register, update_health
        register("checkable", "1.0", "/path")
        update_health("checkable", "healthy")
        assert get_pack("checkable")["health_status"] == "healthy"

    def test_update_health_with_error(self):
        from services.skill_registry import get_pack, register, update_health
        register("broken", "1.0", "/path")
        update_health("broken", "error", error="ImportError: no module")
        pack = get_pack("broken")
        assert pack["health_status"] == "error"
        assert "ImportError" in pack["error_message"]


class TestLastRun:
    def test_update_last_run(self):
        from services.skill_registry import get_pack, register, update_last_run
        register("runner", "1.0", "/path")
        update_last_run("runner")
        pack = get_pack("runner")
        assert pack["last_run"] != ""
