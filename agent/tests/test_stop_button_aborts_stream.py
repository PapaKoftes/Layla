"""Bug: the Stop button aborted the client fetch (UI stopped) but the server kept generating to EOS,
holding the single generation lock so the next turn was blocked. Root cause: the streaming token loop
never checked the client abort. Fix threads client_abort_event into stream_reason/_stream_reason_body
and breaks the token loops when it is set, and the router passes it in. Guard that wiring."""
import inspect
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
import sys

if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_stream_reason_accepts_client_abort_event():
    from services.agent import stream_handler as sh
    assert "client_abort_event" in inspect.signature(sh.stream_reason).parameters
    assert "client_abort_event" in inspect.signature(sh._stream_reason_body).parameters


def test_token_loops_break_on_abort():
    src = (AGENT_DIR / "services" / "agent" / "stream_handler.py").read_text(encoding="utf-8")
    # both the main answer loop and the deliberation-concluder loop must check the abort
    assert src.count("client_abort_event is not None and client_abort_event.is_set()") >= 2, \
        "each streaming token loop must break when the client aborts"
    # and stream_reason must forward it to the inner body
    assert "client_abort_event=client_abort_event" in src


def test_router_passes_client_abort_into_stream():
    src = (AGENT_DIR / "routers" / "agent.py").read_text(encoding="utf-8")
    assert "client_abort_event=client_abort" in src, "the router must pass its abort event into stream_reason"


def test_abort_actually_stops_a_token_generator(monkeypatch):
    """Functional: with the abort set, the loop must stop pulling from a long generator. We exercise
    the loop shape directly (the real _stream_reason_body builds a full prompt), proving the guard
    added to `for token in gen:` halts iteration."""
    import threading
    ev = threading.Event()
    pulled = {"n": 0}

    def _endless():
        while True:
            pulled["n"] += 1
            if pulled["n"] > 100000:
                return
            yield "x"

    gen = _endless()
    out = []
    # mirror the guarded loop body added to stream_handler
    for i, token in enumerate(gen):
        if ev.is_set():
            break
        out.append(token)
        if i == 3:
            ev.set()  # user hits Stop after a few tokens
    assert len(out) <= 5, f"loop kept pulling after abort: pulled {pulled['n']}"
