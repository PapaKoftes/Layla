"""Tests for Mem0 memory extraction integration."""
import pytest
from unittest.mock import patch, MagicMock


class TestIsAvailable:
    def test_returns_bool(self):
        from services.mem0_integration import is_available
        result = is_available()
        assert isinstance(result, bool)


class TestExtractFallback:
    def test_identity_pattern(self):
        from services.mem0_integration import _extract_fallback
        messages = [{"role": "user", "content": "My name is Alice and I work at Acme Corp."}]
        memories = _extract_fallback(messages)
        assert len(memories) >= 1
        types = [m["type"] for m in memories]
        assert "identity" in types or "fact" in types

    def test_preference_pattern(self):
        from services.mem0_integration import _extract_fallback
        messages = [{"role": "user", "content": "I prefer dark mode and Python over JavaScript."}]
        memories = _extract_fallback(messages)
        assert len(memories) >= 1

    def test_remember_pattern(self):
        from services.mem0_integration import _extract_fallback
        messages = [{"role": "user", "content": "Remember that the meeting is at 3pm tomorrow."}]
        memories = _extract_fallback(messages)
        assert len(memories) >= 1

    def test_no_patterns(self):
        from services.mem0_integration import _extract_fallback
        messages = [{"role": "user", "content": "Hello, how are you?"}]
        memories = _extract_fallback(messages)
        assert isinstance(memories, list)

    def test_multiple_messages(self):
        from services.mem0_integration import _extract_fallback
        messages = [
            {"role": "user", "content": "My name is Bob."},
            {"role": "assistant", "content": "Nice to meet you, Bob!"},
            {"role": "user", "content": "I prefer using Vim."},
        ]
        memories = _extract_fallback(messages)
        assert len(memories) >= 2

    def test_empty_messages(self):
        from services.mem0_integration import _extract_fallback
        memories = _extract_fallback([])
        assert memories == []


class TestExtractMemories:
    def test_fallback_when_disabled(self):
        from services.mem0_integration import extract_memories
        cfg = {"mem0_enabled": False}
        messages = [{"role": "user", "content": "My name is Alice."}]
        result = extract_memories(cfg, messages)
        assert isinstance(result, dict)
        assert "memories" in result or "memories_extracted" in result

    def test_empty_messages(self):
        from services.mem0_integration import extract_memories
        result = extract_memories({}, [])
        assert isinstance(result, dict)


class TestSearchMemories:
    def test_disabled(self):
        from services.mem0_integration import search_memories
        result = search_memories({}, "test query")
        assert isinstance(result, dict)
        assert "hits" in result or "error" in result


class TestGetAllMemories:
    def test_disabled(self):
        from services.mem0_integration import get_all_memories
        result = get_all_memories({})
        assert isinstance(result, dict)


class TestDeleteMemory:
    def test_disabled(self):
        from services.mem0_integration import delete_memory
        result = delete_memory({}, "some-id")
        assert isinstance(result, dict)


class TestGetStatus:
    def test_disabled(self):
        from services.mem0_integration import get_status
        status = get_status(cfg={"mem0_enabled": False})
        assert isinstance(status, dict)
        assert "enabled" in status
        assert status["enabled"] is False

    def test_default_config(self):
        from services.mem0_integration import get_status
        status = get_status(cfg={})
        assert isinstance(status, dict)


class TestConfigKeys:
    def test_mem0_config_exists(self):
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert "mem0_enabled" in cfg
        assert cfg["mem0_enabled"] is False
        assert "mem0_api_key" in cfg
        assert "mem0_provider" in cfg
        assert cfg["mem0_provider"] == "local"
