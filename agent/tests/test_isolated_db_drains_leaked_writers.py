"""isolated_db must not inherit a PRIOR test's background memory writes.

Derived-memory writers (outcome-memory/reflection, auto-learn, title-synth, ...) are daemon threads that
resolve `_DB_PATH` at WRITE time. A slow one spawned by an earlier test used to finish after the next
test's isolated_db had patched the path, landing its rows in that fresh DB — the CI flake where
test_system_busy_turn_does_not_spawn_llm_learning saw two "Reflection (read the config...)" rows it never
wrote. The fixture now drains registered writers before patching.

Deterministic: the writer sleeps longer than fixture setup takes, so without the drain it ALWAYS observes
the isolated path (verified red with the drain removed).
"""
import sys
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_leaked_writer_never_sees_the_next_tests_db(request):
    import layla.memory.db_connection as dbc
    from services.agent.turn_commit import _spawn_derived

    seen: list = []

    def _slow_writer():
        time.sleep(1.0)
        seen.append(dbc._DB_PATH)  # the path a real save_learning would write to at this instant

    t = _spawn_derived(_slow_writer, name="outcome-memory")
    isolated = request.getfixturevalue("isolated_db")  # the "next test" starts while the writer is live
    t.join(timeout=5)

    assert len(seen) == 1, "PROBE BROKEN: the leaked writer never ran"
    assert Path(seen[0]) != Path(isolated), "a prior test's writer landed in this test's isolated DB"
