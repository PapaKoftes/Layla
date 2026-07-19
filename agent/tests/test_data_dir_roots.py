"""Every `.layla/` writer must resolve the SAME root, and must honour LAYLA_DATA_DIR.

R6. `Path(__file__).resolve().parent.parent` is correct only for a module sitting exactly one level below
the agent directory. Three modules used that idiom from two levels down and silently wrote to a shadow
`agent/services/.layla/` beside the real `agent/.layla/`:

  - services/prompts/prompt_builder.py      (fixed earlier: the manifest resolved to "" forever)
  - services/prompts/system_head_builder.py (same)
  - services/memory/working_memory.py       (this test)
  - services/personality/frame_modifier.py  (this test)

The failure is silent by construction — a wrong root yields a missing file, and every one of these call
sites treats a missing file as "no data yet". frame_modifier left TWO divergent layla_profile.json files on
disk for weeks. Counting parents by hand is the defect; this test is the guard.
"""
import json
import os
import sys
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

# (module path, resolver attribute) for every module that owns a `.layla/` file.
DATA_DIR_RESOLVERS = [
    ("services.memory.working_memory", "_wm_path"),
    ("services.personality.frame_modifier", "_profile_path"),
    # The fifth instance of the same defect, and the one this file's own shadow-directory assertion
    # was too dead to catch: `repo_indexer` sat in `services/workspace/` and counted two parents, so
    # it resolved to `agent/services/.layla/repo_index.db` and mkdir'd + connected to it ~50x a run.
    ("services.workspace.repo_indexer", "_default_db_path"),
]


def _resolve(modname, attr):
    import importlib

    mod = importlib.import_module(modname)
    return getattr(mod, attr)()


@pytest.mark.parametrize("modname,attr", DATA_DIR_RESOLVERS)
def test_data_path_defaults_to_the_agent_dir_not_a_shadow(modname, attr, monkeypatch):
    monkeypatch.delenv("LAYLA_DATA_DIR", raising=False)
    p = _resolve(modname, attr)

    assert p.parent == AGENT / ".layla", (
        f"{modname}.{attr}() resolves to {p.parent}, not {AGENT / '.layla'}. A parent chain counted by "
        f"hand is off by one, which creates a shadow data directory that nothing reads."
    )
    # The shadow directory, named explicitly.
    #
    # This assertion used to read:
    #     assert ".layla" not in str(AGENT / "services") or p.parent != AGENT / "services" / ".layla"
    # `str(AGENT / "services")` is ".../Layla/agent/services" — it contains "Layla", never ".layla" —
    # so the left operand was UNCONDITIONALLY True, the `or` short-circuited, and the right operand
    # was never evaluated. It could not fail. `repo_indexer` resolved to exactly this shadow path for
    # the entire time this test was green.
    shadow = AGENT / "services" / ".layla"
    assert p.parent != shadow, f"{modname}.{attr}() is writing to the shadow {shadow}"
    assert not shadow.exists(), (
        f"the shadow data directory {shadow} exists. Something resolved a data path with one too few "
        f"`.parent` calls and created it — see repo_indexer, which did exactly this ~50x per run."
    )


@pytest.mark.parametrize("modname,attr", DATA_DIR_RESOLVERS)
def test_data_path_honours_layla_data_dir(modname, attr, monkeypatch, tmp_path):
    """The installed layout puts user data outside the program directory. Ignoring LAYLA_DATA_DIR writes
    user state into Program Files, which is both wrong and often not writable."""
    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path))
    p = _resolve(modname, attr)

    assert p.parent == tmp_path / ".layla", (
        f"{modname}.{attr}() ignored LAYLA_DATA_DIR and resolved to {p.parent}"
    )


@pytest.mark.parametrize("modname,attr", DATA_DIR_RESOLVERS)
def test_data_path_is_resolved_per_call_not_frozen_at_import(modname, attr, monkeypatch, tmp_path):
    """These were module-level constants, so the path was frozen to whatever the environment held at
    import time — setting LAYLA_DATA_DIR after any transitive import silently did nothing."""
    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path / "first"))
    first = _resolve(modname, attr)
    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path / "second"))
    second = _resolve(modname, attr)

    assert first != second, (
        f"{modname}.{attr}() returned the same path after LAYLA_DATA_DIR changed — it is resolved once at "
        f"import rather than per call"
    )


def test_no_module_writes_a_shadow_layla_dir_under_services():
    """The concrete artefact this defect leaves behind, asserted directly."""
    import importlib

    shadow = AGENT / "services" / ".layla"
    for modname, attr in DATA_DIR_RESOLVERS:
        importlib.import_module(modname)
        p = _resolve(modname, attr)
        assert shadow not in p.parents and p.parent != shadow, (
            f"{modname}.{attr}() resolves inside {shadow}"
        )


# ---------------------------------------------------------------------------------------------
# A per-call path resolver in front of a process-global cache is the same defect wearing a hat.
# ---------------------------------------------------------------------------------------------

def test_working_memory_cache_is_keyed_by_data_dir(monkeypatch, tmp_path):
    """`_wm_path()` is resolved per call so LAYLA_DATA_DIR is honoured; `_cache` was keyed by NOTHING.

    So the content was process-global while the path was per-call:

        LAYLA_DATA_DIR=A  ->  remember a fact          (writes A, caches it)
        LAYLA_DATA_DIR=B  ->  read working memory      (cache hit -> returns A's fact)

    which silently contradicts the docstring the per-call resolver exists to satisfy, and would let a
    future test pass against a previous test's state.
    """
    import services.memory.working_memory as wm

    a, b = tmp_path / "A", tmp_path / "B"

    monkeypatch.setenv("LAYLA_DATA_DIR", str(a))
    wm._cache.clear()
    wm.add_to_working_memory("fact-from-A")
    assert "fact-from-A" in json.dumps(wm.get_working_memory())

    monkeypatch.setenv("LAYLA_DATA_DIR", str(b))
    under_b = json.dumps(wm.get_working_memory())
    assert "fact-from-A" not in under_b, (
        "reading working memory under data dir B returned data dir A's content — `_cache` is keyed by "
        "nothing, so it survives a LAYLA_DATA_DIR change that `_wm_path()` correctly follows"
    )

    wm.add_to_working_memory("fact-from-B")
    assert "fact-from-B" in json.dumps(wm.get_working_memory())

    # ...and going back to A must still see A, i.e. B did not simply clobber the single slot.
    monkeypatch.setenv("LAYLA_DATA_DIR", str(a))
    back_in_a = json.dumps(wm.get_working_memory())
    assert "fact-from-A" in back_in_a, "switching back to data dir A lost A's own content"
    assert "fact-from-B" not in back_in_a, "data dir A can see data dir B's facts"


def test_working_memory_reset_does_not_leave_another_data_dir_cached(monkeypatch, tmp_path):
    """reset() means forget. Leaving another data dir's entry behind is the same stale read."""
    import services.memory.working_memory as wm

    a, b = tmp_path / "A", tmp_path / "B"

    monkeypatch.setenv("LAYLA_DATA_DIR", str(a))
    wm._cache.clear()
    wm.add_to_working_memory("fact-from-A")

    monkeypatch.setenv("LAYLA_DATA_DIR", str(b))
    wm.add_to_working_memory("fact-from-B")
    wm.reset()

    assert not any("fact-from-A" in json.dumps(v) for v in wm._cache.values()), (
        "reset() left another data dir's document in the cache"
    )
