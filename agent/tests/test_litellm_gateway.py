"""Tests for litellm multi-provider gateway."""
import pytest
from unittest.mock import patch, MagicMock


# ── Helper: mock litellm module ─────────────────────────────────────────────


def _make_mock_response(content="Hello", prompt_tokens=10, completion_tokens=5):
    """Create a mock litellm response object."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    choice.delta = msg  # for streaming
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = prompt_tokens + completion_tokens
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_mock_stream_chunks(texts):
    """Create mock streaming chunks."""
    chunks = []
    for text in texts:
        delta = MagicMock()
        delta.content = text
        choice = MagicMock()
        choice.delta = delta
        chunk = MagicMock()
        chunk.choices = [choice]
        chunks.append(chunk)
    return chunks


# ── Provider name extraction ────────────────────────────────────────────────


class TestExtractProviderName:
    def test_slash_format(self):
        from services.litellm_gateway import _extract_provider_name
        assert _extract_provider_name("anthropic/claude-3-5-sonnet") == "anthropic"
        assert _extract_provider_name("openai/gpt-4") == "openai"
        assert _extract_provider_name("groq/llama-3") == "groq"

    def test_gpt_prefix(self):
        from services.litellm_gateway import _extract_provider_name
        assert _extract_provider_name("gpt-4o") == "openai"
        assert _extract_provider_name("gpt-3.5-turbo") == "openai"

    def test_claude_prefix(self):
        from services.litellm_gateway import _extract_provider_name
        assert _extract_provider_name("claude-3-opus") == "anthropic"

    def test_gemini_prefix(self):
        from services.litellm_gateway import _extract_provider_name
        assert _extract_provider_name("gemini-pro") == "google"

    def test_unknown(self):
        from services.litellm_gateway import _extract_provider_name
        result = _extract_provider_name("some-random-model")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_o1_prefix(self):
        from services.litellm_gateway import _extract_provider_name
        assert _extract_provider_name("o1-mini") == "openai"


# ── Prompt → Messages conversion ────────────────────────────────────────────


class TestPromptToMessages:
    def test_simple_prompt(self):
        from services.litellm_gateway import prompt_to_messages
        msgs = prompt_to_messages("Hello, world!")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello, world!"

    def test_empty_prompt(self):
        from services.litellm_gateway import prompt_to_messages
        msgs = prompt_to_messages("")
        assert len(msgs) == 1
        assert msgs[0]["content"] == ""


# ── Config loading ───────────────────────────────────────────────────────────


class TestGatewayConfig:
    def test_load_config_defaults(self):
        from services.litellm_gateway import _load_gateway_config
        cfg = _load_gateway_config()
        assert "enabled" in cfg
        assert "default_model" in cfg
        assert "fallback_chain" in cfg
        assert "timeout" in cfg

    def test_disabled_by_default(self):
        from services.litellm_gateway import _load_gateway_config
        cfg = _load_gateway_config()
        assert cfg["enabled"] is False


# ── Availability check ───────────────────────────────────────────────────────


class TestIsAvailable:
    def test_disabled_returns_false(self):
        from services.litellm_gateway import is_available
        # litellm_enabled defaults to False
        assert is_available() is False

    @patch("services.litellm_gateway._load_gateway_config")
    @patch("services.litellm_gateway._import_litellm")
    def test_enabled_with_litellm(self, mock_import, mock_cfg):
        from services.litellm_gateway import is_available
        mock_cfg.return_value = {"enabled": True}
        mock_import.return_value = MagicMock()
        assert is_available() is True

    @patch("services.litellm_gateway._load_gateway_config")
    @patch("services.litellm_gateway._import_litellm")
    def test_enabled_without_litellm(self, mock_import, mock_cfg):
        from services.litellm_gateway import is_available
        mock_cfg.return_value = {"enabled": True}
        mock_import.return_value = None
        assert is_available() is False


# ── Completion (non-streaming) ───────────────────────────────────────────────


class TestComplete:
    @patch("services.litellm_gateway._import_litellm")
    @patch("services.litellm_gateway._load_gateway_config")
    @patch("services.litellm_gateway._configure_api_keys")
    def test_basic_completion(self, mock_keys, mock_cfg, mock_import):
        from services.litellm_gateway import complete
        from services.provider_health import reset_all
        reset_all()

        mock_lit = MagicMock()
        mock_lit.completion.return_value = _make_mock_response("Test reply")
        mock_lit.completion_cost.return_value = 0.001
        mock_import.return_value = mock_lit
        mock_cfg.return_value = {
            "enabled": True,
            "default_model": "anthropic/claude-3",
            "fallback_chain": [],
            "api_keys": {},
            "timeout": 120,
            "max_retries": 2,
            "raw_cfg": {},
        }

        result = complete(
            [{"role": "user", "content": "Hello"}],
            model="anthropic/claude-3",
        )
        assert result["content"] == "Test reply"
        assert result["provider"] == "anthropic"
        assert result["latency_ms"] >= 0  # mock calls complete instantly; 0.0 is valid
        assert "usage" in result

    @patch("services.litellm_gateway._import_litellm")
    @patch("services.litellm_gateway._load_gateway_config")
    @patch("services.litellm_gateway._configure_api_keys")
    def test_failover_to_next_provider(self, mock_keys, mock_cfg, mock_import):
        from services.litellm_gateway import complete
        from services.provider_health import reset_all
        reset_all()

        mock_lit = MagicMock()
        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs.get("model") == "anthropic/claude-3":
                raise Exception("API error")
            return _make_mock_response("Fallback reply")

        mock_lit.completion.side_effect = side_effect
        mock_lit.completion_cost.return_value = 0.0
        mock_import.return_value = mock_lit
        mock_cfg.return_value = {
            "enabled": True,
            "default_model": "anthropic/claude-3",
            "fallback_chain": ["groq/llama-3"],
            "api_keys": {},
            "timeout": 120,
            "max_retries": 0,  # No retries — immediate failover
            "raw_cfg": {},
        }

        result = complete(
            [{"role": "user", "content": "Hello"}],
            model="anthropic/claude-3",
            fallback_chain=["groq/llama-3"],
        )
        assert result["content"] == "Fallback reply"
        assert result["provider"] == "groq"

    @patch("services.litellm_gateway._import_litellm")
    @patch("services.litellm_gateway._load_gateway_config")
    @patch("services.litellm_gateway._configure_api_keys")
    def test_all_fail_raises(self, mock_keys, mock_cfg, mock_import):
        from services.litellm_gateway import complete
        from services.provider_health import reset_all
        reset_all()

        mock_lit = MagicMock()
        mock_lit.completion.side_effect = Exception("total failure")
        mock_import.return_value = mock_lit
        mock_cfg.return_value = {
            "enabled": True,
            "default_model": "bad/model",
            "fallback_chain": [],
            "api_keys": {},
            "timeout": 120,
            "max_retries": 0,
            "raw_cfg": {},
        }

        with pytest.raises(RuntimeError, match="All providers failed"):
            complete([{"role": "user", "content": "Hello"}])

    def test_no_litellm_raises(self):
        from services.litellm_gateway import complete
        import services.litellm_gateway as mod
        old = mod._litellm
        mod._litellm = None
        with patch.object(mod, "_import_litellm", return_value=None):
            with pytest.raises(RuntimeError, match="litellm not installed"):
                complete([{"role": "user", "content": "Hello"}], model="test")
        mod._litellm = old


# ── Completion (streaming) ───────────────────────────────────────────────────


class TestCompleteStream:
    @patch("services.litellm_gateway._import_litellm")
    @patch("services.litellm_gateway._load_gateway_config")
    @patch("services.litellm_gateway._configure_api_keys")
    def test_stream_yields_chunks(self, mock_keys, mock_cfg, mock_import):
        from services.litellm_gateway import complete_stream
        from services.provider_health import reset_all
        reset_all()

        chunks = _make_mock_stream_chunks(["Hello", " ", "world"])
        mock_lit = MagicMock()
        mock_lit.completion.return_value = iter(chunks)
        mock_import.return_value = mock_lit
        mock_cfg.return_value = {
            "enabled": True,
            "default_model": "anthropic/claude-3",
            "fallback_chain": [],
            "api_keys": {},
            "timeout": 120,
            "max_retries": 0,
            "raw_cfg": {},
        }

        result = list(complete_stream(
            [{"role": "user", "content": "Hello"}],
            model="anthropic/claude-3",
        ))
        assert result == ["Hello", " ", "world"]

    @patch("services.litellm_gateway._import_litellm")
    @patch("services.litellm_gateway._load_gateway_config")
    @patch("services.litellm_gateway._configure_api_keys")
    def test_stream_failover(self, mock_keys, mock_cfg, mock_import):
        from services.litellm_gateway import complete_stream
        from services.provider_health import reset_all
        reset_all()

        def side_effect(**kwargs):
            if kwargs.get("model") == "bad/model":
                raise Exception("stream fail")
            return iter(_make_mock_stream_chunks(["OK"]))

        mock_lit = MagicMock()
        mock_lit.completion.side_effect = side_effect
        mock_import.return_value = mock_lit
        mock_cfg.return_value = {
            "enabled": True,
            "default_model": "bad/model",
            "fallback_chain": ["good/model"],
            "api_keys": {},
            "timeout": 120,
            "max_retries": 0,
            "raw_cfg": {},
        }

        result = list(complete_stream(
            [{"role": "user", "content": "Hello"}],
            model="bad/model",
            fallback_chain=["good/model"],
        ))
        assert result == ["OK"]


# ── inference_router integration ─────────────────────────────────────────────


class TestRunCompletionLitellm:
    @patch("services.litellm_gateway._import_litellm")
    @patch("services.litellm_gateway._load_gateway_config")
    @patch("services.litellm_gateway._configure_api_keys")
    def test_returns_openai_compatible_format(self, mock_keys, mock_cfg, mock_import):
        from services.litellm_gateway import run_completion_litellm
        from services.provider_health import reset_all
        reset_all()

        mock_lit = MagicMock()
        mock_lit.completion.return_value = _make_mock_response("Compat test")
        mock_lit.completion_cost.return_value = 0.002
        mock_import.return_value = mock_lit
        mock_cfg.return_value = {
            "enabled": True,
            "default_model": "anthropic/claude-3",
            "fallback_chain": [],
            "api_keys": {},
            "timeout": 120,
            "max_retries": 2,
            "raw_cfg": {},
        }

        cfg = {"litellm_default_model": "anthropic/claude-3", "litellm_fallback_chain": []}
        result = run_completion_litellm(cfg, "Hello", stream=False)
        assert "choices" in result
        assert result["choices"][0]["message"]["content"] == "Compat test"
        assert "_litellm_meta" in result

    @patch("services.litellm_gateway._import_litellm")
    @patch("services.litellm_gateway._load_gateway_config")
    @patch("services.litellm_gateway._configure_api_keys")
    def test_stream_returns_generator(self, mock_keys, mock_cfg, mock_import):
        from services.litellm_gateway import run_completion_litellm
        from services.provider_health import reset_all
        reset_all()

        chunks = _make_mock_stream_chunks(["Hi", "!"])
        mock_lit = MagicMock()
        mock_lit.completion.return_value = iter(chunks)
        mock_import.return_value = mock_lit
        mock_cfg.return_value = {
            "enabled": True,
            "default_model": "test/model",
            "fallback_chain": [],
            "api_keys": {},
            "timeout": 120,
            "max_retries": 0,
            "raw_cfg": {},
        }

        cfg = {"litellm_default_model": "test/model", "litellm_fallback_chain": []}
        result = run_completion_litellm(cfg, "Hello", stream=True)
        # Should be a generator
        tokens = list(result)
        assert tokens == ["Hi", "!"]


# ── Gateway info ─────────────────────────────────────────────────────────────


class TestGetGatewayInfo:
    def test_returns_dict(self):
        from services.litellm_gateway import get_gateway_info
        info = get_gateway_info()
        assert isinstance(info, dict)
        assert "installed" in info
        assert "enabled" in info
        assert "default_model" in info
        assert "provider_health" in info


# ── Config in runtime_safety ─────────────────────────────────────────────────


class TestRuntimeSafetyConfig:
    def test_litellm_config_keys_exist(self):
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert "litellm_enabled" in cfg
        assert cfg["litellm_enabled"] is False
        assert "litellm_default_model" in cfg
        assert "litellm_fallback_chain" in cfg
        assert "litellm_api_keys" in cfg
        assert "litellm_timeout_seconds" in cfg
        assert "litellm_max_retries" in cfg


# ── inference_router backend detection ───────────────────────────────────────


class TestInferenceRouterBackend:
    def test_litellm_backend_recognized(self):
        from services.inference_router import _detect_backend
        cfg = {"inference_backend": "litellm"}
        assert _detect_backend(cfg) == "litellm"

    def test_litellm_in_backends_list(self):
        from services.inference_router import _BACKENDS
        assert "litellm" in _BACKENDS
