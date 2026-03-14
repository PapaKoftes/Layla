"""Tests for inference_router (multi-backend LLM routing)."""

from services.inference_router import (
    _BACKENDS,
    _detect_backend,
)


def test_detect_backend_no_url_uses_llama_cpp():
    cfg = {"llama_server_url": "", "inference_backend": "auto"}
    assert _detect_backend(cfg) == "llama_cpp"


def test_detect_backend_ollama_port():
    cfg = {"llama_server_url": "http://localhost:11434", "inference_backend": "auto"}
    assert _detect_backend(cfg) == "ollama"


def test_detect_backend_ollama_hostname():
    cfg = {"llama_server_url": "http://ollama:11434", "inference_backend": "auto"}
    assert _detect_backend(cfg) == "ollama"


def test_detect_backend_openai_compatible():
    cfg = {"llama_server_url": "http://localhost:8000", "inference_backend": "auto"}
    assert _detect_backend(cfg) == "openai_compatible"


def test_detect_backend_explicit_override():
    cfg = {"llama_server_url": "http://localhost:11434", "inference_backend": "openai_compatible"}
    assert _detect_backend(cfg) == "openai_compatible"


def test_detect_backend_explicit_llama_cpp():
    cfg = {"llama_server_url": "http://localhost:8000", "inference_backend": "llama_cpp"}
    assert _detect_backend(cfg) == "llama_cpp"


def test_backends_constant():
    assert "llama_cpp" in _BACKENDS
    assert "openai_compatible" in _BACKENDS
    assert "ollama" in _BACKENDS
