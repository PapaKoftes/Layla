"""Plan-13 — Obsidian TWO-WAY sync + structured writeback.

Covers:
  (a) round-trip a note through _read_note/_write_note → byte-stable frontmatter
      + preserved body/wikilinks (and read→write idempotency);
  (b) edit-both-sides → conflict detected, neither side clobbered;
  (c) a Layla learning writes back as a well-formed frontmatter note;
  (d) degrades cleanly when python-frontmatter is absent (plain writer/parser).

All I/O is confined to tmp dirs; LAYLA_DATA_DIR is redirected so the sync-state
store never touches the operator's real data dir, and the vault is always a
throwaway tmp path — never a real vault.
"""
from pathlib import Path

import pytest

import services.infrastructure.obsidian_sync as obs


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect LAYLA_DATA_DIR to tmp and force the opt-in gate ON for the test."""
    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path / "data"))
    obs._vault_config.clear()
    # Reset the lazy-frontmatter cache so per-test monkeypatching is honoured.
    obs._FRONTMATTER_CHECKED = False
    obs._FRONTMATTER_MOD = None
    # Two-way sync + writeback are opt-in; a deliberate user opt-in is what the
    # tests represent, so enable the gate here rather than writing real config.
    monkeypatch.setattr(obs, "sync_enabled", lambda: True)
    yield
    obs._vault_config.clear()


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    return v


@pytest.fixture
def repo_root(tmp_path):
    return tmp_path / "repo"


# ── (a) round-trip: byte-stable frontmatter + preserved body/wikilinks ──────────

def test_read_write_note_byte_stable_and_wikilinks(tmp_path):
    if obs._load_frontmatter() is None:
        pytest.skip("python-frontmatter not installed; byte-stable case needs the real handler")

    meta = {"source": "layla", "type": "fact", "tags": ["alpha", "beta"], "layla_id": "42"}
    body = "# Title\n\nA paragraph that links [[Morrigan]] and [[The Vault]] together."

    # Author the note in canonical form, then round-trip it.
    canonical = obs._serialize_note(meta, body)
    src = tmp_path / "note.md"
    src.write_text(canonical, encoding="utf-8", newline="\n")

    doc = obs._read_note(src)
    assert doc["metadata"]["source"] == "layla"
    assert doc["metadata"]["tags"] == ["alpha", "beta"]
    assert "[[Morrigan]]" in doc["content"]
    assert "[[The Vault]]" in doc["content"]

    out = tmp_path / "out.md"
    obs._write_note(out, doc["metadata"], doc["content"])

    # Byte-stable: a canonically-authored note survives read→write unchanged.
    assert out.read_bytes() == src.read_bytes()
    # And key order is preserved (sort_keys=False), not alphabetised.
    text = out.read_text(encoding="utf-8")
    assert text.index("source:") < text.index("type:") < text.index("tags:") < text.index("layla_id:")


def test_read_write_note_idempotent(tmp_path):
    meta = {"source": "user", "created": "2026-07-24"}
    body = "Body with a [[Link]]."
    p = tmp_path / "n.md"
    p.write_text(obs._serialize_note(meta, body), encoding="utf-8", newline="\n")

    first = obs._read_note(p)
    obs._write_note(p, first["metadata"], first["content"])
    once = p.read_bytes()
    second = obs._read_note(p)
    obs._write_note(p, second["metadata"], second["content"])
    twice = p.read_bytes()
    assert once == twice  # read→write is a fixed point


# ── (b) edit-both-sides → conflict detected, not clobbered ──────────────────────

def test_two_way_detects_conflict_without_clobber(vault, repo_root, monkeypatch):
    obs.set_vault_path(str(vault))
    dest = obs.get_knowledge_vault_dir(repo_root)

    rel = "shared.md"
    original = obs._serialize_note({"source": "user"}, "original content")
    (vault / rel).write_text(original, encoding="utf-8", newline="\n")

    # First sync establishes the baseline state (import vault → mirror).
    r1 = obs.two_way_sync(repo_root)
    assert r1["ok"] is True
    assert rel in r1["imported"]
    assert (dest / rel).is_file()

    # Now edit BOTH sides to different content.
    vault_edit = obs._serialize_note({"source": "user"}, "VAULT side edit — the user's words")
    mirror_edit = obs._serialize_note({"source": "user"}, "MIRROR side edit — Layla's words")
    (vault / rel).write_text(vault_edit, encoding="utf-8", newline="\n")
    (dest / rel).write_text(mirror_edit, encoding="utf-8", newline="\n")

    r2 = obs.two_way_sync(repo_root)
    assert r2["ok"] is True
    # Conflict detected...
    assert any(c["file"] == rel for c in r2["conflicts"])
    assert rel not in r2["imported"]
    assert rel not in r2["exported"]
    # ...and NEITHER side was clobbered.
    assert (vault / rel).read_text(encoding="utf-8") == vault_edit
    assert (dest / rel).read_text(encoding="utf-8") == mirror_edit
    # Both versions survive: a conflict sidecar snapshot was kept on the mirror side.
    conflict_sidecars = list(dest.glob("shared.md.conflict-*.md"))
    assert conflict_sidecars, "expected a conflict snapshot to keep both versions"


def test_two_way_propagates_one_sided_edits(vault, repo_root):
    obs.set_vault_path(str(vault))
    dest = obs.get_knowledge_vault_dir(repo_root)
    rel = "one.md"
    (vault / rel).write_text(obs._serialize_note({"source": "user"}, "v1"), encoding="utf-8", newline="\n")
    obs.two_way_sync(repo_root)  # baseline

    # Edit only the mirror (Layla side) → should export back to the vault.
    (dest / rel).write_text(obs._serialize_note({"source": "user"}, "v2 from Layla"), encoding="utf-8", newline="\n")
    r = obs.two_way_sync(repo_root)
    assert rel in r["exported"]
    assert "v2 from Layla" in (vault / rel).read_text(encoding="utf-8")


# ── (c) a learning writes back as a well-formed structured note ─────────────────

def test_writeback_learning_produces_well_formed_note(vault, repo_root, monkeypatch):
    obs.set_vault_path(str(vault))
    monkeypatch.setattr(
        "layla.memory.db.get_top_learnings_for_planning",
        lambda limit, min_confidence: [
            {"id": "7", "content": "Always verify the probe before the result.",
             "type": "strategy", "confidence": 0.92, "entities": ["Probe", "Result"]},
        ],
    )

    r = obs.writeback_learnings(n=5, repo_root=repo_root)
    assert r["ok"] is True
    assert len(r["written"]) == 1

    note_path = vault / obs.LAYLA_WRITEBACK_SUBDIR / r["written"][0].split("/")[-1]
    assert note_path.is_file()

    doc = obs._read_note(note_path)
    assert doc["metadata"]["source"] == "layla"
    assert doc["metadata"]["type"] == "strategy"
    assert doc["metadata"]["layla_id"] == "7"
    assert "created" in doc["metadata"]
    assert "Always verify the probe" in doc["content"]
    # Wikilinks for known entities.
    assert "[[Probe]]" in doc["content"]
    assert "[[Result]]" in doc["content"]


def test_writeback_never_clobbers_user_note(vault, repo_root, monkeypatch):
    obs.set_vault_path(str(vault))
    content = "Always verify the probe before the result."
    monkeypatch.setattr(
        "layla.memory.db.get_top_learnings_for_planning",
        lambda limit, min_confidence: [
            {"id": "7", "content": content, "type": "strategy", "confidence": 0.92},
        ],
    )
    # Pre-place a USER note exactly where writeback would land.
    layla_dir = vault / obs.LAYLA_WRITEBACK_SUBDIR
    layla_dir.mkdir(parents=True)
    target = layla_dir / f"{obs._slugify(content)}.md"
    user_text = obs._serialize_note({"source": "user"}, "the user's own precious note")
    target.write_text(user_text, encoding="utf-8", newline="\n")

    r = obs.writeback_learnings(n=5, repo_root=repo_root)
    assert r["ok"] is True
    assert r["written"] == []
    assert any("user-authored" in s["reason"] for s in r["skipped"])
    # The user's note is byte-for-byte untouched.
    assert target.read_text(encoding="utf-8") == user_text


# ── (d) degrade cleanly when python-frontmatter is absent ───────────────────────

def test_degrades_without_frontmatter(tmp_path, monkeypatch):
    # Force the "not installed" path regardless of the real environment.
    monkeypatch.setattr(obs, "_load_frontmatter", lambda: None)

    meta = {"source": "layla", "created": "2026-07-24"}
    body = "# Heading\n\nBody with a [[WikiLink]] preserved."
    p = tmp_path / "plain.md"
    obs._write_note(p, meta, body)

    text = p.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "[[WikiLink]]" in text

    doc = obs._read_note(p)
    assert doc["metadata"]["source"] == "layla"
    assert doc["metadata"]["created"] == "2026-07-24"
    assert "[[WikiLink]]" in doc["content"]

    # Plain path is idempotent too.
    p2 = tmp_path / "plain2.md"
    obs._write_note(p2, doc["metadata"], doc["content"])
    assert p2.read_bytes() == p.read_bytes()


def test_two_way_and_writeback_gated_off(vault, repo_root, monkeypatch):
    """With the opt-in gate OFF, neither path touches the vault."""
    monkeypatch.setattr(obs, "sync_enabled", lambda: False)
    obs.set_vault_path(str(vault))
    r1 = obs.two_way_sync(repo_root)
    assert r1["ok"] is False and r1.get("disabled") is True
    r2 = obs.writeback_learnings(repo_root=repo_root)
    assert r2["ok"] is False and r2.get("disabled") is True
