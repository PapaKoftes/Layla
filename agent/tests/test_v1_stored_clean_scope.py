"""audit round-3 #8: the /v1 streaming TOKEN branch cleaned its stored/next-turn-context copy with
active_name_set(result), but `result` is unbound on that branch (it belongs to the autonomous
sub-branch), so a NameError was silently swallowed and RAW scaffolding was persisted + re-entered as
context. The clean must key off aspect_id (always in scope)."""
import inspect
import re
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_v1_token_branch_stored_clean_uses_aspect_id_not_unbound_result():
    from routers import openai_compat as oc

    src = inspect.getsource(oc.v1_chat_completions)
    # The stored-copy clean (the block that imports active_name_set as _ans_v1 and strip_junk as _sj_v1)
    # must feed it aspect_id, never `result` (which is unbound on the token branch → swallowed NameError).
    m = re.search(r"active_name_set as _ans_v1\b.*?_sj_v1\(response_text, active_names=_ans_v1\((\w+)\)\)",
                  src, re.DOTALL)
    assert m, "the /v1 token-branch stored-copy clean block was not found"
    assert m.group(1) == "aspect_id", f"stored-copy clean keys off `{m.group(1)}`, not aspect_id"
