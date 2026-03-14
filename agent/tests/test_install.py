"""
Tests for the first-run install system.
"""
from __future__ import annotations

# Ensure agent is on path
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_hardware_probe_returns_structure():
    """probe_hardware returns expected keys."""
    from install.hardware_probe import probe_hardware

    h = probe_hardware()
    assert "cpu_model" in h
    assert "cpu_cores" in h
    assert "ram_gb" in h
    assert "gpu_name" in h
    assert "vram_gb" in h
    assert "acceleration_backend" in h
    assert h["acceleration_backend"] in ("cuda", "rocm", "metal", "none")


def test_classify_hardware_returns_tiers():
    """classify_hardware returns cpu_tier, ram_tier, gpu_tier."""
    from install.hardware_probe import classify_hardware, probe_hardware

    h = probe_hardware()
    tiers = classify_hardware(h)
    assert "cpu_tier" in tiers
    assert "ram_tier" in tiers
    assert "gpu_tier" in tiers
    assert tiers["cpu_tier"] in ("low", "medium", "high")
    assert tiers["ram_tier"] in ("low", "medium", "high", "very_high")
    assert tiers["gpu_tier"] in ("none", "low", "medium", "high", "very_high")


def test_model_selector_recommends_for_hardware():
    """recommend_model returns a catalog entry or None."""
    from install.hardware_probe import probe_hardware
    from install.model_selector import load_catalog, recommend_model

    catalog = load_catalog()
    assert len(catalog) > 0

    h = probe_hardware()
    rec = recommend_model(h)
    assert rec is None or isinstance(rec, dict)
    if rec:
        assert "name" in rec or "filename" in rec
        assert "download_url" in rec or "repo_id" in rec


def test_model_selector_picks_small_for_low_ram():
    """4GB RAM gets a small model (SmolLM or TinyDolphin)."""
    from install.model_selector import recommend_model

    h = {"ram_gb": 4.0, "vram_gb": 0.0, "acceleration_backend": "none"}
    rec = recommend_model(h)
    assert rec is not None
    mem_req = rec.get("ram_required", 999)
    assert mem_req <= 6, f"4GB RAM should get model with ram_required <= 6, got {mem_req}"


def test_resolve_model_path_uses_models_dir():
    """resolve_model_path uses models_dir from config when set."""
    import runtime_safety

    cfg = {
        "model_filename": "test.gguf",
        "models_dir": str(Path.home() / ".layla" / "models"),
    }
    p = runtime_safety.resolve_model_path(cfg)
    assert "test.gguf" in str(p)
    assert ".layla" in str(p) or "layla" in str(p).lower()


def test_resolve_model_path_fallback_to_repo_models():
    """resolve_model_path falls back to repo models/ when models_dir not set."""
    import runtime_safety

    cfg = {"model_filename": "foo.gguf"}
    p = runtime_safety.resolve_model_path(cfg)
    assert p.name == "foo.gguf"
    assert "models" in str(p)


def test_model_benchmark_stores_and_retrieves():
    """Benchmarks stored in ~/.layla/benchmarks.json can be retrieved."""
    from services.model_benchmark import BENCHMARKS_PATH, get_all_benchmarks, get_benchmark

    assert BENCHMARKS_PATH == Path.home() / ".layla" / "benchmarks.json"
    all_b = get_all_benchmarks()
    assert isinstance(all_b, dict)
    # If we have benchmarks, get_benchmark should work
    if all_b:
        first = next(iter(all_b.keys()))
        b = get_benchmark(first)
        assert b is not None
        assert "tokens_per_sec" in b or "first_token_ms" in b or "memory_mb" in b


def test_model_router_benchmark_helpers():
    """model_router exposes get_fastest_benchmarked and get_benchmark_for_model."""
    from services.model_router import get_benchmark_for_model, get_fastest_benchmarked

    fastest = get_fastest_benchmarked()
    # May be None if no benchmarks
    assert fastest is None or isinstance(fastest, str)
    b = get_benchmark_for_model("nonexistent.gguf")
    assert b is None


def test_config_schema_and_settings_api():
    """Config schema and settings endpoints work correctly."""
    from config_schema import get_editable_keys, get_schema_for_api, EDITABLE_SCHEMA

    keys = get_editable_keys()
    assert len(keys) >= 10
    assert "model_filename" in keys
    assert "temperature" in keys

    schema = get_schema_for_api()
    assert "fields" in schema
    assert "categories" in schema
    assert len(schema["fields"]) == len(EDITABLE_SCHEMA)

    # Test FastAPI app if available
    try:
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        r = client.get("/settings")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        r2 = client.get("/settings/schema")
        assert r2.status_code == 200
        sch = r2.json()
        assert "fields" in sch
    except ImportError:
        pass
