from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))


def test_deterministic_verify_write_file(tmp_path: Path) -> None:
    from services.tool_output_validator import deterministic_verify_tool_result

    p = tmp_path / "x.txt"
    p.write_text("hi", encoding="utf-8")
    r = deterministic_verify_tool_result("write_file", {"ok": True, "path": str(p)}, workspace_root=str(tmp_path))
    assert r["ok"] is True


def test_deterministic_verify_shell_returncode() -> None:
    from services.tool_output_validator import deterministic_verify_tool_result

    r = deterministic_verify_tool_result("shell", {"ok": True, "returncode": 1, "stderr": ""}, workspace_root="")
    assert r["ok"] is False
    assert r["reason"] == "nonzero_returncode"
