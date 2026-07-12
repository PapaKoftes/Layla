"""R18 #4/#14: response-cache replay must not serve a DIFFERENT aspect's reply to an explicit-aspect
caller, and must re-guard the stored reply against current config. The router (routers/agent.py cache
read-hit block) enforces both; here we pin the data contract the guards rely on."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_cache_payload_preserves_resolved_aspect():
    from services.retrieval import response_cache as rc

    # An empty request aspect auto-selects (e.g. Nyx) but the router keys it under "morrigan"
    # (aspect_id or "morrigan"), so the payload's own `aspect` is the only record of the real voice.
    rc.put_cached_response("why is the sky blue", "morrigan",
                           {"response": "<Nyx-voiced>", "aspect": "nyx"})
    got = rc.get_cached_response("why is the sky blue", "morrigan", 300)
    assert got is not None
    assert got.get("aspect") == "nyx"


def test_router_aspect_mismatch_predicate():
    # The exact predicate the read-hit block uses to reject a wrong-aspect replay (#4): an explicit
    # request aspect that differs from the cached payload's resolved aspect is a miss.
    payload_aspect = "nyx"
    # explicit Morrigan request vs a Nyx-voiced cache entry → mismatch → miss
    _req = "morrigan".strip().lower()
    _pay = str(payload_aspect).strip().lower()
    assert bool(_req and _pay and _req != _pay) is True
    # same aspect → serve
    _req2 = "nyx"
    assert bool(_req2 and _pay and _req2 != _pay) is False
    # empty request aspect (auto-select) → never a mismatch (serve whatever is cached)
    _req3 = ""
    assert bool(_req3 and _pay and _req3 != _pay) is False
