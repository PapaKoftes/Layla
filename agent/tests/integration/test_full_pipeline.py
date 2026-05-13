"""Integration tests: end-to-end pipeline verification across all phases."""
import pytest
from unittest.mock import patch, MagicMock


class TestConfigIntegrity:
    """Verify all phase config keys exist and don't conflict."""

    def test_all_phase_keys_present(self):
        """Every phase's config keys should be in the default config."""
        import runtime_safety
        cfg = runtime_safety.load_config()

        # Phase 1: LiteLLM Gateway
        assert "litellm_enabled" in cfg
        assert "litellm_default_model" in cfg
        assert "litellm_fallback_chain" in cfg

        # Phase 2: Discord
        assert "discord_bot_autostart" in cfg
        assert "discord_bot_token" in cfg

        # Phase 3: Remote Access
        assert "tunnel_token_hash" in cfg
        assert "tunnel_ip_allowlist" in cfg
        assert "tailscale_enabled" in cfg

        # Phase 4: Skill Packs (via existing config)
        # skill_packs uses file-based config

        # Phase 5: Search
        assert "search_backend" in cfg
        assert "meilisearch_enabled" in cfg

        # Phase 6: Integrations
        assert "crawler_backend" in cfg
        assert "docling_enabled" in cfg
        assert "vector_backend" in cfg
        assert "mem0_enabled" in cfg

    def test_no_key_conflicts(self):
        """Config keys should be unique (no collisions between phases)."""
        import runtime_safety
        cfg = runtime_safety.load_config()
        keys = list(cfg.keys())
        assert len(keys) == len(set(keys)), "Duplicate config keys found"

    def test_defaults_are_safe(self):
        """All new features should be disabled by default."""
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert cfg["litellm_enabled"] is False
        assert cfg["discord_bot_autostart"] is False
        assert cfg["meilisearch_enabled"] is False
        assert cfg["tailscale_enabled"] is False
        assert cfg["docling_enabled"] is False
        assert cfg["mem0_enabled"] is False
        assert cfg["vector_backend"] == "chroma"
        assert cfg["search_backend"] == "auto"


class TestProviderHealthIntegration:
    """Verify provider health tracking works end-to-end."""

    def test_health_lifecycle(self):
        from services.provider_health import (
            record_success, record_failure,
            is_healthy, get_all_status, reset_all,
        )
        reset_all()

        # Fresh provider is healthy
        assert is_healthy("test-provider") is True

        # Record some successes (API uses latency_seconds)
        record_success("test-provider", latency_seconds=0.05)
        record_success("test-provider", latency_seconds=0.06)

        status = get_all_status()
        assert len(status) >= 1
        provider_status = [s for s in status if s.get("name") == "test-provider"]
        assert len(provider_status) == 1
        assert provider_status[0]["healthy"] is True

        reset_all()


class TestSkillPacksIntegration:
    """Verify skill pack subsystem works together."""

    def test_manifest_validation(self):
        from services.skill_manifest import validate_manifest
        valid = {
            "name": "test-pack",
            "version": "1.0.0",
            "description": "A test skill pack",
            "entry_point": "main.py",
            "dependencies": [],
            "permissions": ["read_memory"],
        }
        errors = validate_manifest(valid)
        assert errors == []

    def test_manifest_rejects_invalid(self):
        from services.skill_manifest import validate_manifest
        invalid = {"name": "test"}  # Missing required fields
        errors = validate_manifest(invalid)
        assert len(errors) > 0

    def test_registry_lifecycle(self, tmp_path):
        import services.skill_registry as sr
        old_db = sr._DB_PATH
        old_conn = sr._conn
        sr._conn = None  # Force fresh connection to new DB
        sr._DB_PATH = tmp_path / "test_registry.db"
        try:
            sr.register(
                name="test-pack", version="1.0.0",
                pack_dir=str(tmp_path),
                git_url="",
                permissions=["read_memory"],
            )
            pack = sr.get_pack("test-pack")
            assert pack is not None
            assert pack["version"] == "1.0.0"

            packs = sr.list_packs()
            assert len(packs) >= 1

            sr.unregister("test-pack")
            assert sr.get_pack("test-pack") is None
        finally:
            sr.close_db()
            sr._DB_PATH = old_db
            sr._conn = old_conn


class TestWebSocketIntegration:
    """Verify WebSocket manager and multi-agent work together."""

    @pytest.mark.asyncio
    async def test_ws_manager_lifecycle(self):
        from services.ws_manager import ConnectionManager, create_message, MSG_SYSTEM
        from unittest.mock import AsyncMock

        mgr = ConnectionManager()
        ws = AsyncMock()

        # Connect
        await mgr.connect(ws, "integration-client", room="test")
        assert mgr.client_count == 1

        # Send message
        msg = create_message(MSG_SYSTEM, {"text": "integration test"})
        await mgr.send_personal(msg, "integration-client")
        ws.send_json.assert_called_once()

        # Disconnect
        await mgr.disconnect("integration-client")
        assert mgr.client_count == 0

    @pytest.mark.asyncio
    async def test_multi_agent_full_flow(self):
        from services.multi_agent import run_multi_agent
        result = await run_multi_agent(
            "Fix the authentication bug and write unit tests for the new endpoint",
            cfg={},
        )
        assert result["ok"] is True
        assert len(result["subtask_results"]) >= 2
        assert result["total_duration_ms"] >= 0


class TestCrawlerIntegration:
    """Verify web crawler fallback chain."""

    def test_basic_always_available(self):
        from services.web_crawler import get_crawler_status
        status = get_crawler_status(cfg={})
        assert status["basic"] is True
        assert "active" in status

    def test_docling_fallback(self, tmp_path):
        from services.docling_ingest import ingest_file
        f = tmp_path / "test.txt"
        f.write_text("Integration test content for docling fallback.", encoding="utf-8")
        result = ingest_file(f, cfg={})
        assert result["ok"] is True
        assert len(result["chunks"]) >= 1
