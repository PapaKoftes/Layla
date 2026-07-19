"""
Tests for the first-run install system.
"""
from __future__ import annotations

# Ensure agent is on path
import os
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
    """4GB RAM gets a model within ~90% RAM headroom (install selector margin)."""
    from install.model_selector import recommend_model

    h = {"ram_gb": 4.0, "vram_gb": 0.0, "acceleration_backend": "none"}
    rec = recommend_model(h)
    assert rec is not None
    mem_req = rec.get("ram_required", 999)
    assert mem_req <= 4.0 * 0.9 + 0.02, (
        f"4GB RAM should get model with ram_required <= 90% headroom, got {mem_req}"
    )


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


def test_model_search_roots_ordered_and_deduped(tmp_path, monkeypatch):
    """model_search_roots lists configured dir, default dir, repo models without duplicates."""
    import runtime_safety

    repo = tmp_path / "repo"
    repo_models = repo / "models"
    repo_models.mkdir(parents=True)
    user_models = tmp_path / "user_models"
    user_models.mkdir()
    custom = tmp_path / "custom"
    custom.mkdir()

    monkeypatch.setattr(runtime_safety, "REPO_ROOT", repo)
    monkeypatch.setattr(runtime_safety, "default_models_dir", lambda: user_models)

    cfg = {"models_dir": str(custom)}
    roots = runtime_safety.model_search_roots(cfg)
    assert roots == [custom.resolve(), user_models.resolve(), repo_models.resolve()]

    cfg_same = {"models_dir": str(user_models)}
    roots2 = runtime_safety.model_search_roots(cfg_same)
    assert roots2 == [user_models.resolve(), repo_models.resolve()]


def test_resolve_model_path_finds_basename_in_repo_models(tmp_path, monkeypatch):
    """When primary models_dir has no file, resolve_model_path uses repo models/ basename match."""
    import runtime_safety

    repo = tmp_path / "repo"
    repo_models = repo / "models"
    repo_models.mkdir(parents=True)
    gguf = repo_models / "weights.gguf"
    gguf.write_bytes(b"x")

    primary_dir = tmp_path / "primary_models"
    primary_dir.mkdir()

    monkeypatch.setattr(runtime_safety, "REPO_ROOT", repo)
    monkeypatch.setattr(runtime_safety, "default_models_dir", lambda: primary_dir)

    cfg = {"model_filename": "weights.gguf", "models_dir": str(primary_dir)}
    p = runtime_safety.resolve_model_path(cfg)
    assert p.resolve() == gguf.resolve()


def test_model_benchmark_stores_and_retrieves():
    """Benchmarks stored in ~/.layla/benchmarks.json can be retrieved."""
    from services.llm.model_benchmark import (
        BENCHMARKS_PATH,
        _benchmarks_path,
        get_all_benchmarks,
        get_benchmark,
    )

    # Was `assert BENCHMARKS_PATH == Path.home() / ".layla" / "benchmarks.json"`, which PINNED the
    # defect: it required the path to ignore LAYLA_DATA_DIR. Assert the property that matters instead.
    assert BENCHMARKS_PATH is None, "BENCHMARKS_PATH must default to None so it resolves per call"
    assert _benchmarks_path() == Path(os.environ["LAYLA_DATA_DIR"]).resolve() / ".layla" / "benchmarks.json"
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
    from services.llm.model_router import get_benchmark_for_model, get_fastest_benchmarked

    fastest = get_fastest_benchmarked()
    # May be None if no benchmarks
    assert fastest is None or isinstance(fastest, str)
    b = get_benchmark_for_model("nonexistent.gguf")
    assert b is None


def test_config_schema_and_settings_api():
    """Config schema and settings endpoints work correctly."""
    from config_schema import EDITABLE_SCHEMA, get_editable_keys, get_schema_for_api

    keys = get_editable_keys()
    assert len(keys) >= 10
    assert "model_filename" in keys
    assert "temperature" in keys

    schema = get_schema_for_api()
    assert "fields" in schema
    assert "categories" in schema
    assert "presets" in schema
    assert "potato" in schema["presets"]
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


def test_settings_preset_potato_writes_merged_config(tmp_path, monkeypatch):
    """POST /settings/preset merges potato keys without dropping unrelated config.

    C1b — WHY THIS TEST WAS REWRITTEN. It used to read

        assert body.get("ok") is True
        cfg = json.loads(fake.read_text(...))          # the FILE
        assert cfg["performance_mode"] == "low"

    …which is why 3736 tests were green while the endpoint reported the potato preset applied
    with three of its keys reverted. Both halves inspected the wrong thing: `ok` was returned
    unconditionally from the request's own intent, and reading runtime_config.json asks what
    was REQUESTED, not what is in force — exactly the inference this slice deletes. The file
    assertions stay (a preset really must not drop unrelated config), but the OUTCOME is now
    asserted against the effective config, which is the only place the answer lives.
    """
    import json

    import runtime_safety

    fake = tmp_path / "runtime_config.json"
    fake.write_text(json.dumps({"model_filename": "keep.gguf", "temperature": 0.5}), encoding="utf-8")
    monkeypatch.setattr(runtime_safety, "CONFIG_FILE", fake)
    runtime_safety.invalidate_config_cache()

    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    r = client.post("/settings/preset", json={"preset": "potato"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert body.get("preset") == "potato"

    # The write landed, and unrelated config survived it.
    cfg = json.loads(fake.read_text(encoding="utf-8"))
    assert cfg["model_filename"] == "keep.gguf"
    assert cfg["temperature"] == 0.5
    assert cfg["performance_mode"] == "low"
    # Potato keeps semantic memory ON now that model2vec + sqlite-vec make it cheap
    # (no torch); embedder_prefer_quality stays off so it uses the fast static embedder.
    assert cfg["use_chroma"] is True
    assert cfg["embedder_prefer_quality"] is False

    # THE OUTCOME, read back from what the running app sees.
    runtime_safety.invalidate_config_cache()
    effective = runtime_safety.load_config()
    report = body.get("report") or []
    assert report, "the preset must report per-key what happened, not just that it wrote"

    applied = body.get("applied") or []
    not_in_force = body.get("not_in_force") or []
    # `applied` means IN FORCE. Every key it names must actually hold in the effective config.
    for k in applied:
        row = next(r for r in report if r["key"] == k)
        assert effective.get(k) == row["requested"], (
            f"{k} is reported applied but the effective config says {effective.get(k)!r}"
        )
    # …and every key it does NOT name must be one the read-back caught, with a named owner.
    for k in not_in_force:
        row = next(r for r in report if r["key"] == k)
        assert effective.get(k) != row["requested"]
        assert row["owner"], f"{k} is not in force with no owner named"
        assert row["reason"]
    assert set(applied) & set(not_in_force) == set()
    assert body.get("in_force") is (not not_in_force)
    # Whatever the hardware tier does to the numeric keys, performance_mode itself has no
    # owner and must genuinely be in force — otherwise the preset did nothing at all.
    assert effective.get("performance_mode") == "low"
    assert "performance_mode" in applied


def test_settings_preset_reports_a_key_an_owner_reverts(tmp_path, monkeypatch):
    """C1, the regression that matters: a preset key an owner overwrites at load time must be
    reported as NOT in force — never counted as applied.

    Driven live before the fix, POST /settings/preset {"preset":"potato"} answered
    ok:true with applied=[16 keys] including n_batch (asked 256, in force 512),
    max_runtime_seconds (asked 20, in force 300) and completion_max_tokens (asked 256, in
    force 320). This installs an owner for one preset key and asserts the endpoint says so.
    """
    import json

    import runtime_safety
    from config_schema import SETTINGS_PRESETS

    fake = tmp_path / "runtime_config.json"
    fake.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runtime_safety, "CONFIG_FILE", fake)
    runtime_safety.invalidate_config_cache()

    victim = "max_tool_calls"
    assert victim in SETTINGS_PRESETS["potato"], "pick a key the potato preset actually sets"
    asked = SETTINGS_PRESETS["potato"][victim]

    real_load = runtime_safety.load_config

    def owned_load():
        cfg = dict(real_load())
        cfg[victim] = asked + 5  # an owner overwrites it on every load
        return cfg

    monkeypatch.setattr(runtime_safety, "load_config", owned_load)

    from fastapi.testclient import TestClient

    from main import app

    body = TestClient(app).post("/settings/preset", json={"preset": "potato"}).json()
    assert body["ok"] is True, "the write DID happen — ok reports the write"
    assert body["in_force"] is False
    assert victim in body["not_in_force"]
    assert victim not in body["applied"], "a key an owner reverted was counted as applied"
    row = next(r for r in body["report"] if r["key"] == victim)
    assert row["outcome"] == "overridden"
    assert row["effective"] == asked + 5
    # No probe claims this synthetic owner — the backstop must still refuse to report success.
    assert row["owner"] and row["reason"]
    assert "did NOT take effect" in row["reason"] or row["owner"] != "unknown"


def test_settings_preset_unknown_returns_400():
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    r = client.post("/settings/preset", json={"preset": "not_a_real_preset"})
    assert r.status_code == 400
    assert r.json().get("error") == "unknown_preset"


def test_installer_packs_include_e2e_voice_browser():
    from install.installer_cli import PACKS_DIR

    for name in ("e2e", "voice", "browser"):
        assert (PACKS_DIR / f"{name}.json").is_file()


def test_integrity_min_bytes_expected_fraction():
    """Truncated-but-large files fail: floor uses ~95% of declared size when set."""
    from install.model_downloader import _integrity_min_bytes

    assert _integrity_min_bytes({"expected_size_bytes": 2000}) >= int(2000 * 0.95)
    assert _integrity_min_bytes({"size_bytes": 4000}) >= int(4000 * 0.95)


def test_resume_partial_download_guard():
    """Resume safety: local .part larger than declared server total is corrupt / must restart."""
    from install.model_downloader import part_exceeds_server_total

    assert not part_exceeds_server_total(Path("/nonexistent/nope.part"), 1000)


def test_resume_partial_download_guard_oversized_part(tmp_path):
    from install.model_downloader import part_exceeds_server_total

    part = tmp_path / "model.gguf.part"
    part.write_bytes(b"x" * 5000)
    assert part_exceeds_server_total(part, 4000)
    assert not part_exceeds_server_total(part, 6000)
    assert not part_exceeds_server_total(part, None)


def test_model_selector_uses_vram_when_gpu_present():
    from install.model_selector import recommend_model

    h = {
        "ram_gb": 64.0,
        "vram_gb": 12.0,
        "acceleration_backend": "cuda",
        "gpu_name": "Test GPU",
    }
    rec = recommend_model(h)
    assert rec is not None
    assert float(rec.get("vram_required", 999)) <= 12.0 * 0.9 + 0.05


def test_model_selector_gpu_without_vram_falls_back_to_ram():
    from install.model_selector import recommend_model

    h = {
        "ram_gb": 16.0,
        "vram_gb": 0.0,
        "acceleration_backend": "cuda",
        "gpu_name": "Unknown",
    }
    rec = recommend_model(h)
    assert rec is not None
    assert float(rec.get("ram_required", 999)) <= 16.0 * 0.9 + 0.05


def test_meta_corruption_recovery(tmp_path):
    from install.model_downloader import try_load_part_meta

    bad = tmp_path / "x.gguf.part.meta"
    bad.write_text("{not-json", encoding="utf-8")
    assert try_load_part_meta(bad) is None
    bad.write_text('{"url": "https://example.com/f.bin"}', encoding="utf-8")
    assert try_load_part_meta(bad)["url"] == "https://example.com/f.bin"
