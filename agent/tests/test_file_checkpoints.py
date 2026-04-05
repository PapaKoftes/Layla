"""File checkpoint service: snapshot before write, list, restore."""

from __future__ import annotations

from pathlib import Path

from services import file_checkpoints as fc


def test_create_list_restore_roundtrip(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent_meta"
    ws = tmp_path / "ws"
    ws.mkdir()
    f = ws / "a.txt"
    f.write_text("v1", encoding="utf-8")
    r = fc.create_checkpoint(path=f, workspace_root=ws, agent_dir=agent_dir, tool_name="write_file")
    assert r.get("ok") is True
    cid = r.get("checkpoint_id")
    assert cid

    f.write_text("v2", encoding="utf-8")
    assert f.read_text() == "v2"

    listed = fc.list_checkpoints(workspace_root=ws, agent_dir=agent_dir, path_filter=str(f), limit=10)
    assert listed.get("ok") is True
    assert any(x.get("checkpoint_id") == cid for x in listed.get("checkpoints", []))

    rr = fc.restore_checkpoint(checkpoint_id=cid, workspace_root=ws, agent_dir=agent_dir, sandbox_root=ws)
    assert rr.get("ok") is True
    assert f.read_text() == "v1"


def test_retention_max_count(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent_meta"
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = {"file_checkpoint_max_count": 2, "file_checkpoint_max_bytes": 0}
    for i in range(4):
        f = ws / f"f{i}.txt"
        f.write_text("v", encoding="utf-8")
        fc.create_checkpoint(path=f, workspace_root=ws, agent_dir=agent_dir, tool_name="t", cfg=cfg)
    root = fc.checkpoint_root_for_workspace(ws, agent_dir)
    bundles = [d for d in root.iterdir() if d.is_dir() and (d / "meta.json").is_file()]
    assert len(bundles) <= 2


def test_restore_rejects_outside_sandbox(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent_meta"
    ws = tmp_path / "ws"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    secret = other / "secret.txt"
    secret.write_text("x", encoding="utf-8")
    r = fc.create_checkpoint(path=secret, workspace_root=ws, agent_dir=agent_dir, tool_name="t")
    assert r.get("ok") is True
    cid = r["checkpoint_id"]
    rr = fc.restore_checkpoint(
        checkpoint_id=cid,
        workspace_root=ws,
        agent_dir=agent_dir,
        sandbox_root=ws,
    )
    assert rr.get("ok") is False
    assert "sandbox" in (rr.get("error") or "").lower()
