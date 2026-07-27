"""Plan item 27 — effect-verifier coverage.

deterministic_verify_tool_result confirms the CONCRETE artifact of a successful
tool result, model-free, without re-running the tool. These tests exercise the
extended (risk-prioritized) verifier set: for a representative tool in each
category a known-GOOD result must verify ok, and a tampered/empty result must
fail. Pure-informational tools must stay no_verifier (never falsely "verified").
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from services.tools.tool_output_validator import (  # noqa: E402
    _EFFECT_VERIFIERS,
    deterministic_verify_tool_result,
)

# The original inline verifiers kept intact in deterministic_verify_tool_result.
_ORIGINAL_VERIFIERS = frozenset({
    "write_file", "replace_in_file", "apply_patch", "run_python", "shell",
    "read_file", "list_dir", "grep_code", "glob_files", "fetch_url",
    "search_replace", "rename_symbol",
})


def _verify(tool, result, ws=""):
    return deterministic_verify_tool_result(tool, result, workspace_root=ws)


# ---------------------------------------------------------------------------
# File / artifact writers
# ---------------------------------------------------------------------------

def test_write_csv_good_and_tampered(tmp_path: Path) -> None:
    p = tmp_path / "out.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    assert _verify("write_csv", {"ok": True, "path": str(p), "rows": 1}, str(tmp_path))["ok"]
    # tampered: names a file that was never written
    bad = _verify("write_csv", {"ok": True, "path": str(tmp_path / "nope.csv"), "rows": 1}, str(tmp_path))
    assert bad["ok"] is False and bad["reason"] == "artifact_missing"
    # tampered: no row count in the result
    assert _verify("write_csv", {"ok": True, "path": str(p)}, str(tmp_path))["ok"] is False


def test_create_svg_good_and_tampered(tmp_path: Path) -> None:
    p = tmp_path / "d.svg"
    p.write_text("<svg/>", encoding="utf-8")
    assert _verify("create_svg", {"ok": True, "path": str(p)}, str(tmp_path))["ok"]
    assert _verify("create_svg", {"ok": True, "path": ""}, str(tmp_path))["ok"] is False


def test_create_archive_good_and_tampered(tmp_path: Path) -> None:
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("member.txt", "hello")
    good = _verify("create_archive", {"ok": True, "output": str(z), "files": 1}, str(tmp_path))
    assert good["ok"] and good["details"]["members"] == 1
    # tampered: archive path missing
    bad = _verify("create_archive", {"ok": True, "output": str(tmp_path / "missing.zip"), "files": 1}, str(tmp_path))
    assert bad["ok"] is False


def test_db_backup_good_and_tampered(tmp_path: Path) -> None:
    b = tmp_path / "db.bak"
    b.write_text("x", encoding="utf-8")
    assert _verify("db_backup", {"ok": True, "source": "db.sqlite", "backup": str(b)}, str(tmp_path))["ok"]
    assert _verify("db_backup", {"ok": True, "source": "db.sqlite", "backup": str(tmp_path / "gone.bak")}, str(tmp_path))["ok"] is False


def test_notebook_edit_cell_good_and_tampered(tmp_path: Path) -> None:
    nb = tmp_path / "n.ipynb"
    nb.write_text("{}", encoding="utf-8")
    assert _verify("notebook_edit_cell", {"ok": True, "path": str(nb), "cell_index": 0, "written": True}, str(tmp_path))["ok"]
    # tampered: nothing was written
    assert _verify("notebook_edit_cell", {"ok": True, "path": str(nb), "cell_index": 0, "written": False}, str(tmp_path))["ok"] is False


def test_write_files_batch_good_and_tampered(tmp_path: Path) -> None:
    f1, f2 = tmp_path / "1.txt", tmp_path / "2.txt"
    f1.write_text("a", encoding="utf-8")
    f2.write_text("b", encoding="utf-8")
    assert _verify("write_files_batch", {"ok": True, "written": [str(f1), str(f2)], "count": 2}, str(tmp_path))["ok"]
    # tampered: claims a written file that does not exist
    bad = _verify("write_files_batch", {"ok": True, "written": [str(f1), str(tmp_path / "ghost.txt")], "count": 2}, str(tmp_path))
    assert bad["ok"] is False and bad["reason"] == "written_file_missing"
    # tampered: empty written list
    assert _verify("write_files_batch", {"ok": True, "written": [], "count": 0}, str(tmp_path))["ok"] is False


def test_generate_qr_good_and_tampered(tmp_path: Path) -> None:
    assert _verify("generate_qr", {"ok": True, "base64": "aGVsbG8="})["ok"]
    p = tmp_path / "qr.png"
    p.write_bytes(b"\x89PNG")
    assert _verify("generate_qr", {"ok": True, "output": str(p)}, str(tmp_path))["ok"]
    assert _verify("generate_qr", {"ok": True})["ok"] is False


# ---------------------------------------------------------------------------
# Structured-data producers
# ---------------------------------------------------------------------------

def test_json_query_key_presence_not_truthiness() -> None:
    # A queried value of None / 0 / False is still a real answer.
    assert _verify("json_query", {"ok": True, "result": None, "result_str": "None"})["ok"]
    assert _verify("json_query", {"ok": True, "data": "{...}"})["ok"]
    assert _verify("json_query", {"ok": True})["ok"] is False


def test_sql_query_good_and_tampered() -> None:
    good = {"ok": True, "columns": ["id"], "rows": [{"id": 1}, {"id": 2}], "row_count": 2}
    assert _verify("sql_query", good)["ok"]
    # tampered: row_count disagrees with the actual rows
    bad = _verify("sql_query", {"ok": True, "columns": ["id"], "rows": [], "row_count": 9})
    assert bad["ok"] is False and bad["reason"] == "row_count_mismatch"
    # tampered: no columns
    assert _verify("sql_query", {"ok": True, "rows": [], "row_count": 0})["ok"] is False
    # legitimate empty result set still verifies
    assert _verify("sql_query", {"ok": True, "columns": ["id"], "rows": [], "row_count": 0})["ok"]


def test_hash_file_good_and_tampered() -> None:
    good = {"ok": True, "algorithm": "sha256", "hash": "a" * 64}
    assert _verify("hash_file", good)["ok"]
    # tampered: wrong length for the declared algorithm
    assert _verify("hash_file", {"ok": True, "algorithm": "sha256", "hash": "abc"})["ok"] is False
    # tampered: not hex
    assert _verify("hash_file", {"ok": True, "algorithm": "md5", "hash": "z" * 32})["ok"] is False
    # tampered: missing hash
    assert _verify("hash_file", {"ok": True, "algorithm": "sha256"})["ok"] is False


def test_read_csv_good_and_tampered() -> None:
    assert _verify("read_csv", {"ok": True, "columns": ["a", "b"], "sample": [{"a": 1}]})["ok"]
    assert _verify("read_csv", {"ok": True, "sample": [{"a": 1}]})["ok"] is False


def test_dataset_summary_good_and_tampered() -> None:
    assert _verify("dataset_summary", {"ok": True, "shape": {"rows": 10, "columns": 3}})["ok"]
    assert _verify("dataset_summary", {"ok": True, "shape": {"rows": 10}})["ok"] is False


def test_schema_introspect_good_and_tampered() -> None:
    assert _verify("schema_introspect", {"ok": True, "tables": {"users": {}}})["ok"]
    assert _verify("schema_introspect", {"ok": True})["ok"] is False


# ---------------------------------------------------------------------------
# Git / exec / network effects
# ---------------------------------------------------------------------------

def test_git_commit_good_and_tampered() -> None:
    good = {"ok": True, "output": "[master 1a2b3c4] add feature\n 1 file changed, 2 insertions(+)"}
    assert _verify("git_commit", good)["ok"]
    # tampered: claims success but the commit produced no output
    assert _verify("git_commit", {"ok": True, "output": ""})["ok"] is False


def test_run_tests_good_and_tampered() -> None:
    assert _verify("run_tests", {"ok": True, "returncode": 0, "passed": 5, "failed": 0})["ok"]
    assert _verify("run_tests", {"ok": True, "returncode": 1, "passed": 4, "failed": 1})["ok"] is False
    # tampered: ok claimed but a test failed
    assert _verify("run_tests", {"ok": True, "returncode": 0, "failed": 2})["ok"] is False


def test_send_webhook_status_gate() -> None:
    assert _verify("send_webhook", {"ok": True, "status": 204, "response": ""})["ok"]
    # send_webhook returns ok even for a 5xx — the verifier catches non-delivery
    bad = _verify("send_webhook", {"ok": True, "status": 500, "response": "err"})
    assert bad["ok"] is False and bad["reason"] == "http_status_not_2xx"
    assert _verify("discord_send", {"ok": True, "status": 200})["ok"]


def test_github_pr_good_and_tampered() -> None:
    assert _verify("github_pr", {"ok": True, "number": 42, "url": "https://x/pr/42"})["ok"]
    assert _verify("github_pr", {"ok": True, "url": "https://x/pr/42"})["ok"] is False


def test_run_skill_pack_good_and_tampered() -> None:
    assert _verify("run_skill_pack", {"ok": True, "exit_code": 0, "timed_out": False})["ok"]
    assert _verify("run_skill_pack", {"ok": True, "exit_code": 1, "timed_out": False})["ok"] is False
    assert _verify("run_skill_pack", {"ok": True, "exit_code": 0, "timed_out": True})["ok"] is False


def test_mcp_tools_call_good_and_tampered() -> None:
    assert _verify("mcp_tools_call", {"ok": True, "mcp": {"content": []}, "server": "s", "tool": "t"})["ok"]
    assert _verify("mcp_tools_call", {"ok": True, "server": "s", "tool": "t"})["ok"] is False


def test_send_email_good_and_tampered() -> None:
    assert _verify("send_email", {"ok": True, "to": "a@b.c", "subject": "hi"})["ok"]
    assert _verify("send_email", {"ok": True, "subject": "hi"})["ok"] is False


# ---------------------------------------------------------------------------
# Memory persistence
# ---------------------------------------------------------------------------

def test_save_note_and_vector_store() -> None:
    assert _verify("save_note", {"ok": True, "saved": "a fact"})["ok"]
    assert _verify("save_note", {"ok": True, "saved": ""})["ok"] is False
    assert _verify("vector_store", {"ok": True, "stored": "chunk", "collection": "memories"})["ok"]
    assert _verify("vector_store", {"ok": True, "stored": ""})["ok"] is False


# ---------------------------------------------------------------------------
# Contract guards
# ---------------------------------------------------------------------------

def test_informational_tools_stay_no_verifier() -> None:
    informational = {
        "uuid_generate": {"ok": True, "uuids": ["x"]},
        "timestamp_convert": {"ok": True, "result": "2020-01-01"},
        "random_string": {"ok": True, "value": "abc"},
        "password_generate": {"ok": True, "password": "p", "length": 1},
        "base64_tool": {"ok": True, "result": "aGk=", "mode": "encode"},
        "string_transform": {"ok": True, "result": "HI"},
        "jwt_decode": {"ok": True, "header": {}, "payload": {}},
        "json_schema": {"ok": True, "schema": {}},
        # deliberately-excluded effectful tools with no result artifact to assert
        "git_add": {"ok": True, "output": ""},
        "docker_run": {"ok": True, "output": ""},
    }
    for tool, res in informational.items():
        v = _verify(tool, res)
        assert v["ok"] is True, tool
        assert v["reason"] == "no_verifier", f"{tool} should stay no_verifier, got {v['reason']}"


def test_failed_tool_is_never_verified() -> None:
    # A tool that reported failure must not be upgraded to verified by any branch.
    v = _verify("write_csv", {"ok": False, "error": "boom"})
    assert v["ok"] is False and v["reason"] == "tool_reported_failure"


def test_verifier_never_raises_on_garbage() -> None:
    # Non-dict result and empty dicts must degrade gracefully, never raise.
    assert deterministic_verify_tool_result("sql_query", "not-a-dict")["ok"] is False
    for tool in ("create_archive", "extract_frames", "hash_file", "git_commit"):
        out = _verify(tool, {"ok": True})
        assert isinstance(out, dict) and "ok" in out


def test_every_registered_verifier_targets_a_real_tool() -> None:
    from layla.tools.registry import TOOLS

    unknown = [name for name in _EFFECT_VERIFIERS if name not in TOOLS]
    assert not unknown, f"verifiers reference unregistered tools: {unknown}"


def test_has_verifier_count_report() -> None:
    covered = _ORIGINAL_VERIFIERS | set(_EFFECT_VERIFIERS)
    # no overlap: the extended set never redefines an original inline verifier
    assert not (_ORIGINAL_VERIFIERS & set(_EFFECT_VERIFIERS))
    total = len(covered)
    print(
        f"\n[effect-verifiers] tools with a deterministic verifier: {total} "
        f"(original={len(_ORIGINAL_VERIFIERS)}, extended={len(_EFFECT_VERIFIERS)})"
    )
    assert total == len(_ORIGINAL_VERIFIERS) + len(_EFFECT_VERIFIERS)
    assert total >= 45
