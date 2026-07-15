"""apply_deterministic_tool_verification is the post-tool gate that can downgrade a tool 'success' to a
failure (governs whether the decision loop retries or accepts a step). Was UNTESTED — a regression here
makes the agent accept broken results or spin. Locks the branch outcomes."""
import sys
from pathlib import Path
from unittest.mock import patch
AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
from services.agent.verification_engine import apply_deterministic_tool_verification as verify  # noqa: E402


def test_non_dict_result_passes_through():
    r, ok, reason = verify("shell", "plain string", workspace="/w", cfg={})
    assert ok is True and reason == "non_dict_result" and r == "plain string"


def test_tool_reported_failure_is_not_verified():
    r, ok, reason = verify("write_file", {"ok": False, "error": "boom"}, workspace="/w", cfg={})
    assert ok is False and reason == "tool_reported_failure"


def test_disabled_config_is_passthrough():
    r, ok, reason = verify("write_file", {"ok": True}, workspace="/w",
                           cfg={"deterministic_tool_verification_enabled": False})
    assert ok is True and reason == "disabled"


def test_failed_deterministic_verify_downgrades_success_to_failure():
    with patch("services.tools.tool_output_validator.deterministic_verify_tool_result",
               return_value={"ok": False, "reason": "file not written"}):
        r, ok, reason = verify("write_file", {"ok": True}, workspace="/w",
                               cfg={"deterministic_tool_verification_enabled": True})
    assert ok is False and r["ok"] is False and "file not written" in reason


def test_verifier_exception_fails_open_not_closed():
    with patch("services.tools.tool_output_validator.deterministic_verify_tool_result",
               side_effect=RuntimeError("verifier crashed")):
        r, ok, reason = verify("write_file", {"ok": True}, workspace="/w",
                               cfg={"deterministic_tool_verification_enabled": True})
    # a broken verifier must not block a genuinely-successful tool
    assert ok is True and reason == "verifier_unavailable"
