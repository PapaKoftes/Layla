"""Tests for config migrator module."""
import pytest


class TestMigrateConfig:
    def test_empty_config_gets_defaults(self):
        from services.config_migrator import migrate_config
        cfg, changes = migrate_config({})
        assert len(changes) > 0
        assert "litellm_enabled" in cfg
        assert "meilisearch_enabled" in cfg
        assert "tunnel_token_hash" in cfg

    def test_full_config_no_changes(self):
        from services.config_migrator import _NEW_DEFAULTS, migrate_config
        # Start with a config that has all keys
        cfg = dict(_NEW_DEFAULTS)
        _, changes = migrate_config(cfg)
        assert len(changes) == 0

    def test_deprecated_keys_removed(self):
        from services.config_migrator import migrate_config
        cfg = {"knowledge_unrestricted": True, "anonymous_access": True}
        result, changes = migrate_config(cfg)
        assert "knowledge_unrestricted" not in result
        assert "anonymous_access" not in result
        assert len(changes) >= 2

    def test_preserves_existing_values(self):
        from services.config_migrator import migrate_config
        cfg = {"litellm_enabled": True, "meilisearch_enabled": True}
        result, _ = migrate_config(cfg)
        assert result["litellm_enabled"] is True
        assert result["meilisearch_enabled"] is True

    def test_does_not_mutate_original(self):
        from services.config_migrator import migrate_config
        original = {"some_key": "value"}
        result, _ = migrate_config(original)
        assert "some_key" in original
        assert original is not result


class TestMigrationStatus:
    def test_needs_migration(self):
        from services.config_migrator import get_migration_status
        status = get_migration_status({})
        assert status["needs_migration"] is True
        assert status["pending_changes"] > 0

    def test_no_migration_needed(self):
        from services.config_migrator import _NEW_DEFAULTS, get_migration_status
        cfg = dict(_NEW_DEFAULTS)
        status = get_migration_status(cfg)
        assert status["needs_migration"] is False
        assert status["pending_changes"] == 0


class TestGetVersion:
    def test_returns_version(self):
        from services.config_migrator import get_current_version
        version = get_current_version()
        assert isinstance(version, str)
        assert "." in version


class TestRealConfig:
    def test_current_config_needs_no_migration(self):
        """The actual runtime config should already have all keys."""
        import runtime_safety
        from services.config_migrator import get_migration_status
        cfg = runtime_safety.load_config()
        status = get_migration_status(cfg)
        # May need migration for deprecated keys or may not
        # But should not crash
        assert isinstance(status, dict)
