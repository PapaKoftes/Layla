"""Regression: GET /file_intent must enforce sandbox containment.

The route passed the raw user-supplied `path` straight into analyze_file(),
which read_bytes() the file and returned content previews — a network-reachable
arbitrary file read that bypassed the sandbox its sibling /file_content enforces.
See audit finding #4.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _body(resp):
    raw = resp.body
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def test_file_intent_rejects_path_outside_sandbox(monkeypatch, tmp_path):
    import runtime_safety
    from routers import workspace

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "outside" / "notes.md"
    outside.parent.mkdir()
    outside.write_text("# secret heading\nconfidential body line\n" * 3, encoding="utf-8")

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"sandbox_root": str(sandbox)})

    resp = workspace.get_file_intent_api(path=str(outside))
    assert resp.status_code == 403
    body = _body(resp)
    assert body["ok"] is False
    assert "sandbox" in body["error"].lower()
    # The file's content preview must NOT have leaked.
    assert "confidential" not in json.dumps(body).lower()


def test_file_intent_allows_path_inside_sandbox(monkeypatch, tmp_path):
    import runtime_safety
    from routers import workspace

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    inside = sandbox / "notes.md"
    inside.write_text("# hello\nsome body\n", encoding="utf-8")

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"sandbox_root": str(sandbox)})

    result = workspace.get_file_intent_api(path=str(inside))
    # analyze_file returns a plain dict on success (not a 403 JSONResponse).
    assert isinstance(result, dict)
    assert result.get("format")


def test_file_intent_requires_configured_sandbox(monkeypatch, tmp_path):
    import runtime_safety
    from routers import workspace

    inside = tmp_path / "notes.md"
    inside.write_text("# hi\n", encoding="utf-8")
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"sandbox_root": ""})

    resp = workspace.get_file_intent_api(path=str(inside))
    assert resp.status_code == 403
