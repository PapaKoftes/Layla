"""audit round-3 #1: every memory_sections key build_system_head writes MUST be in MEMORY_SECTION_ORDER,
or the section is silently dropped before assembly (working_memory / answer_feedback / golden_examples
were dropped — the user-correction feedback loop was inert). #2: dedup must preserve memory precedence."""
import re
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_all_memory_section_keys_are_ordered():
    from services.context.context_merge_layers import MEMORY_SECTION_ORDER

    src = (AGENT_DIR / "services" / "prompts" / "system_head_builder.py").read_text(encoding="utf-8")
    written = set(re.findall(r"""memory_sections\[['"]([a-z_]+)['"]\]""", src))
    missing = written - set(MEMORY_SECTION_ORDER)
    assert not missing, f"memory_sections keys written but NOT in MEMORY_SECTION_ORDER (silently dropped): {missing}"
    # The three that regressed must specifically be present.
    for k in ("working_memory", "answer_feedback", "golden_examples"):
        assert k in MEMORY_SECTION_ORDER, k


def test_dedup_preserves_memory_before_knowledge():
    from services.context.context_manager import build_system_prompt

    sections = {
        "system_instructions": "SYS",
        "memory": "MEMBLOCK recalled facts about the user and project history here",
        "knowledge_graph": "GRAPH association edges between entities",
        "knowledge": "Reference docs: static documentation text as its own section",
    }
    out, _metrics = build_system_prompt(sections, n_ctx=8192)
    # memory content must appear BEFORE the Reference docs, even though a knowledge_graph block exists
    # (which triggers the dedup/merge path).
    assert "MEMBLOCK" in out and "Reference docs" in out
    assert out.index("MEMBLOCK") < out.index("Reference docs")
