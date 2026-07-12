"""audit round-2 #13: the local llama_cpp non-stream timeout must not JOIN a hung worker while holding
llm_serialize_lock (which would stall every other LLM caller). The executor must be detached, not used
as a context manager (whose __exit__ shutdown(wait=True) joins)."""
import inspect
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_llama_cpp_timeout_detaches_hung_worker_not_joins():
    from services.llm import inference_router as ir

    src = inspect.getsource(ir.run_completion_llama_cpp)
    # The executor must NOT be a context manager (its __exit__ joins the worker under the lock).
    assert "ThreadPoolExecutor(max_workers=1) as " not in src
    # On timeout it must detach without waiting so the lock releases immediately.
    assert "shutdown(wait=False, cancel_futures=True)" in src
    # And it must NOT invalidate the llm cache on the TIMEOUT path (the hung worker still holds a live
    # reference to the instance). The timeout branch returns a plain retry message.
    timeout_branch = src.split("except _cf.TimeoutError:", 1)[1].split("except Exception", 1)[0]
    assert "invalidate_llm_cache()" not in timeout_branch  # the CALL (the comment mentioning it is fine)
    assert "timed out" in timeout_branch.lower()
