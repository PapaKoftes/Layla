"""audit round-2 #13 + round-6 #13: the local llama_cpp non-stream timeout must
  (a) DETACH the hung worker (not JOIN it) so _llm_lock releases — an effective timeout; AND
  (b) FENCE the shared Llama instance before releasing the lock (invalidate the cache so the next caller
      builds a FRESH instance), or the detached worker's still-running native create_completion() races
      with the next caller on the same C context → heap corruption.
Round 2 fixed (a) but INTRODUCED the (b) race by explicitly NOT invalidating; round 6 caught it."""
import inspect
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_llama_cpp_timeout_detaches_and_fences_the_instance():
    from services.llm import inference_router as ir

    src = inspect.getsource(ir.run_completion_llama_cpp)
    # (a) The executor must NOT be a context manager (its __exit__ joins the worker under the lock).
    assert "ThreadPoolExecutor(max_workers=1) as " not in src
    assert "shutdown(wait=False, cancel_futures=True)" in src

    # Split on the OUTER except (the broadcast/shape handler), not the nested `except Exception: pass`
    # inside the fence's own try.
    timeout_branch = src.split("except _cf.TimeoutError:", 1)[1].split("except Exception as _fe:", 1)[0]
    # (b) The timeout branch MUST fence the poisoned instance before releasing the lock — invalidate the
    # cache so the next caller builds a fresh instance instead of racing on the worker's live one.
    assert "invalidate_llm_cache(already_locked=True)" in timeout_branch, \
        "timeout path must fence the Llama instance (invalidate cache) to avoid a native heap-corruption race"
    assert "timed out" in timeout_branch.lower()


def test_invalidate_llm_cache_supports_already_locked_fence():
    from services.llm import llm_gateway as g

    # The fence path calls invalidate with already_locked=True (skips re-acquiring _llm_lock to avoid a
    # non-reentrant deadlock); it must clear the module cache so _get_llm rebuilds.
    g._llm = object()
    g._llm_by_path = {"x": object()}
    g.invalidate_llm_cache(already_locked=True)
    assert g._llm is None and g._llm_by_path == {}


def test_llm_generation_lock_is_reentrant():
    # audit round-6 #12: in per-workspace mode this lock is held across a NESTED run_completion on the
    # same thread; a non-reentrant Lock self-deadlocked, wedging all local inference. It must be an RLock.
    import threading

    from services.llm.llm_gateway import llm_generation_lock

    assert isinstance(llm_generation_lock, type(threading.RLock()))
    # Re-acquire on the same thread must NOT block (a plain Lock would deadlock here).
    assert llm_generation_lock.acquire(timeout=2)
    try:
        assert llm_generation_lock.acquire(timeout=2), "llm_generation_lock is not reentrant (would deadlock)"
        llm_generation_lock.release()
    finally:
        llm_generation_lock.release()
