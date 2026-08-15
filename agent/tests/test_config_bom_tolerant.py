"""A runtime_config.json written with a UTF-8 BOM must still load.

Regression for the shipped "Service temporarily unavailable" bug: a Windows PowerShell
`Set-Content -Encoding UTF8` writes a BOM, and json.loads(read_text("utf-8")) rejects it, so the whole
config was silently dropped to defaults (model_filename -> "your-model.gguf") and the real model ignored.
The loader now reads utf-8-sig, which tolerates a BOM."""
import importlib
import json


def test_config_with_utf8_bom_still_loads(tmp_path, monkeypatch):
    cfg_file = tmp_path / "runtime_config.json"
    # Write WITH a BOM, exactly like PowerShell Set-Content -Encoding UTF8 does.
    cfg_file.write_text(json.dumps({"model_filename": "real-model.gguf", "temperature": 0.3}),
                        encoding="utf-8-sig")
    assert cfg_file.read_bytes().startswith(b"\xef\xbb\xbf"), "test setup: BOM must be present"

    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path))
    import runtime_safety
    importlib.reload(runtime_safety)
    try:
        runtime_safety.invalidate_config_cache()
    except Exception:
        pass
    cfg = runtime_safety.load_config()
    assert cfg.get("model_filename") == "real-model.gguf", "BOM must not drop the config to defaults"
    assert cfg.get("temperature") == 0.3
