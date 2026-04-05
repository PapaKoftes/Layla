"""Chat export → knowledge/_ingested/chats Markdown."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def _patch_ingest_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import services.doc_ingestion as di

    kd = tmp_path / "knowledge"
    kd.mkdir()
    ing = kd / "_ingested"
    monkeypatch.setattr(di, "KNOWLEDGE_DIR", kd)
    monkeypatch.setattr(di, "INGEST_DIR", ing)


def test_ingest_chat_export_json_array(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _patch_ingest_dirs: None) -> None:
    import runtime_safety
    import services.doc_ingestion as di

    sandbox = tmp_path / "sand"
    sandbox.mkdir()
    exp = sandbox / "c.json"
    exp.write_text('[{"role":"user","content":"hello export"}]', encoding="utf-8")

    def lc() -> dict:
        return {
            "sandbox_root": str(sandbox),
            "knowledge_ingestion_enabled": True,
            "doc_injection_guard_enabled": False,
        }

    monkeypatch.setattr(runtime_safety, "load_config", lc)
    out = di.ingest_chat_export(str(exp), label="unit")
    assert out.get("ok") is True
    p = Path(out["path"])
    assert p.is_file()
    assert "hello export" in p.read_text(encoding="utf-8")


def test_ingest_rejects_outside_sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _patch_ingest_dirs: None) -> None:
    import runtime_safety
    import services.doc_ingestion as di

    sandbox = tmp_path / "sand"
    sandbox.mkdir()
    outside = tmp_path / "evil.json"
    outside.write_text("[]", encoding="utf-8")

    def lc() -> dict:
        return {"sandbox_root": str(sandbox), "knowledge_ingestion_enabled": True}

    monkeypatch.setattr(runtime_safety, "load_config", lc)
    out = di.ingest_chat_export(str(outside))
    assert out.get("ok") is False
