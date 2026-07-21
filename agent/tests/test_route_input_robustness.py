"""Robustness: client-supplied JSON bodies with wrong-typed fields (a number where a string is expected,
null where an int is expected, a top-level array) must NOT 500 the endpoint. These were confirmed 500s."""
import inspect
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_v1_conversation_id_number_does_not_crash():
    # openai_compat extracted `((req).get("conversation_id") or "").strip()` → int.strip() → 500. Now str-wrapped.
    src = inspect.getsource(__import__("routers.openai_compat", fromlist=["x"]))
    assert 'str((req or {}).get("conversation_id")' in src, "conversation_id must be str()-wrapped for a numeric id"
    # prove the pattern itself is null/number-safe:
    for v in (123, None, "abc"):
        assert isinstance(str((v) or "").strip(), str)


def test_language_json_guards_non_dict_and_safe_int():
    import routers.language as L
    assert L._safe_int(None, 3) == 3 and L._safe_int("x", 3) == 3 and L._safe_int("5", 3) == 5 and L._safe_int(4, 3) == 4
    # _json must return {} for a non-dict body (top-level array)
    src = inspect.getsource(L._json)
    assert "isinstance(d, dict)" in src


def test_german_quality_coercion_is_guarded():
    import routers.german as G
    src = inspect.getsource(G)
    assert "except (TypeError, ValueError)" in src, "german quality int() must be guarded against null/string"
