"""BL-133/REQ-43: high-confidence secret-token scrubbing in log values + security-audit redaction."""
from __future__ import annotations

from services.safety.secret_filter import REDACTED, redact_payload, scrub_secret_tokens


def test_scrub_high_confidence_tokens():
    tokens = [
        "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWX1234",   # Anthropic
        "sk-ABCDEFGHIJKLMNOPQRSTUVWX",                  # OpenAI
        "xoxb-1234567890-ABCDEFGHIJKLM",                # Slack
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",     # GitHub PAT
        "AKIAIOSFODNN7EXAMPLE",                          # AWS key id
        "AIzaSyA1234567890B1234567890C1234567890",       # Google API key
    ]
    for t in tokens:
        out = scrub_secret_tokens(f"cmd --key {t} --other x")
        assert t not in out and REDACTED in out, t


def test_scrub_bearer_and_jwt():
    assert REDACTED in scrub_secret_tokens("Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345")
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcDEF123456"
    assert jwt not in scrub_secret_tokens(f"token={jwt}")


def test_scrub_leaves_normal_text_intact():
    # No false positives on ordinary diagnostic strings / flags / paths.
    for normal in [
        "python train.py --lr 0.001 --epochs 20 --model gpt-neo-1.3B",
        "C:/Users/mina/project/src/main.py",
        "git commit -m 'fix: handle empty input' && git push",
        "completion_max_tokens=4096 n_ctx=8192",
    ]:
        assert scrub_secret_tokens(normal) == normal


def test_redact_payload_scrubs_token_under_nonsecret_key():
    # args_preview is NOT a sensitive key name — value-scrubbing must still catch the token.
    p = {"tool": "shell", "args_preview": "curl -H 'Authorization: Bearer ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'"}
    out = redact_payload(p)
    assert "ghp_ABCDEF" not in str(out)
    assert REDACTED in out["args_preview"]
    assert out["tool"] == "shell"  # non-secret value preserved


def test_security_audit_event_is_redacted():
    from services.observability import security_audit as sa

    sa.log_dangerous_tool_usage(
        "shell",
        args_preview="export API=AKIAIOSFODNN7EXAMPLE && run",
        conversation_id="conv-xyz",
    )
    events = sa.get_recent_security_events(limit=10)
    blob = str(events)
    assert "AKIAIOSFODNN7EXAMPLE" not in blob   # secret scrubbed before it hit the ring buffer
    assert REDACTED in blob
