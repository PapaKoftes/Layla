"""Regression guards for the audit-loop Round-1 fixes: an out-of-the-box 500, an empty UI panel, a null
POST-body crash class, and four security-audit loggers that were defined but never wired."""
import inspect
import json
import sys
from pathlib import Path
from unittest.mock import patch

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _body(resp) -> dict:
    return json.loads(bytes(resp.body).decode("utf-8"))


def test_local_access_info_survives_null_remote_api_key():
    # Shipped example config has "remote_api_key": null; cfg.get(key,"") returns None → None.strip() 500'd.
    import routers.system as sysr
    fake = {"remote_api_key": None, "remote_enabled": False}
    with patch("runtime_safety.load_config", return_value=fake):
        resp = sysr.local_access_info() if hasattr(sysr, "local_access_info") else None
    # Either the function returns a response (no crash) — the point is no AttributeError.
    assert resp is not None


def test_operator_profile_serves_familiarity_not_unlocks():
    # INVERTED. This used to assert operator_profile populated maturity.unlocks via check_unlocks,
    # so growth.js could render an "Unlocked Abilities" list. Rank unlocks nothing — the ladder was
    # a capability claim derived from an activity counter — so the panel now renders familiarity
    # instead, and the endpoint must not resurrect the old shape.
    import routers.settings as settings_router
    src = inspect.getsource(settings_router.operator_profile)
    assert "get_familiarity" in src and 'prof["familiarity"]' in src, \
        "operator_profile must populate familiarity for the growth panel"
    for gone in ("check_unlocks", "all_unlocks", 'maturity["unlocks"]'):
        assert gone not in src, f"operator_profile still serves the removed unlock shape {gone!r}"


def test_null_post_body_hardening_no_attributeerror():
    # A client sending {"id": null} must not 500 with None.strip(); the hardened handlers coerce to "".
    import routers.approvals as appr
    # approve reads ((req or {}).get("id") or "").strip() — a null id yields "id required", not a crash.
    r = _body(appr.approve({"id": None}))  # the null must not raise AttributeError
    assert r.get("ok") is False and "id" in str(r.get("error", "")).lower()


def test_security_audit_loggers_are_wired():
    # The four loggers were defined but never called in production. Assert each now has a production caller.
    prod = ""
    for f in ("core/executor.py", "services/tools/tool_dispatch.py", "services/agent/approval_helpers.py"):
        prod += (AGENT_DIR / f).read_text(encoding="utf-8-sig")
    for name in ("log_dangerous_tool_usage", "log_approval_escalation", "log_sandbox_violation", "log_protected_file_attempt"):
        assert name in prod, f"{name} must be wired into a production guard path"
