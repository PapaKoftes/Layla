"""rebuild_lens_knowledge must not turn sources/README.md (folder docs) into a "README" lens."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_readme_is_not_a_lens(monkeypatch, tmp_path):
    from services.retrieval import lens_refresh as lr

    src = tmp_path / "sources"
    src.mkdir()
    (src / "README.md").write_text("How this folder works.", encoding="utf-8")
    (src / "carpenter.md").write_text("joinery " * 10, encoding="utf-8")
    monkeypatch.setattr(lr, "LENS_KNOWLEDGE_DIR", tmp_path)
    monkeypatch.setattr(lr, "SOURCES_DIR", src)
    lr.rebuild_lens_knowledge()
    assert (tmp_path / "carpenter.md").is_file(), "PROBE BROKEN: the rebuild produced nothing"
    assert not (tmp_path / "README.md").exists()
