"""Tests for companion intelligence subsystem."""


def test_relationship_memory_add_and_get():
    from layla.memory.db import add_relationship_memory, get_recent_relationship_memories, migrate
    migrate()
    add_relationship_memory("User asked about Python debugging. Resolved with breakpoint().")
    mems = get_recent_relationship_memories(n=3)
    assert len(mems) >= 1
    assert "user_event" in mems[0]
    assert "timestamp" in mems[0]
    assert "Python" in mems[0].get("user_event", "") or "debugging" in mems[0].get("user_event", "")


def test_style_profile_update_and_summary():
    from services.style_profile import get_profile_summary, update_profile_from_interactions
    update_profile_from_interactions([
        {"role": "user", "content": "Thanks! Can you fix this bug? The error says NoneType."},
        {"role": "user", "content": "Please explain how async works in Python."},
    ])
    profile = get_profile_summary()
    assert "response_style" in profile
    assert "topics" in profile


def test_style_profile_collaboration_hints_non_clinical():
    from layla.memory.db import get_style_profile, migrate
    from services.style_profile import get_profile_summary, update_profile_from_interactions

    migrate()
    update_profile_from_interactions([
        {"role": "user", "content": "be blunt — no sugarcoat. Tell me straight what's wrong with this design."},
        {"role": "user", "content": "i'm struggling a bit; please be gentle with the review."},
    ])
    profile = get_profile_summary()
    assert "collaboration" in profile
    row = get_style_profile("collaboration")
    assert row and "non-clinical" in (row.get("profile_snapshot") or "").lower()
    assert "dsm" in (row.get("profile_snapshot") or "").lower()


def test_conversation_summaries_still_work():
    from layla.memory.db import get_recent_conversation_summaries, migrate
    migrate()
    summaries = get_recent_conversation_summaries(n=5)
    assert isinstance(summaries, list)


def test_stt_detect_voice_mode():
    from services.stt import detect_voice_mode
    assert detect_voice_mode(b"") is False
    assert detect_voice_mode(b"x" * 100) is False
    # Short WAV-like bytes: RIFF header + minimal data
    wav = b"RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
    assert detect_voice_mode(wav) is False


def test_tts_get_voice_options():
    from services.tts import get_voice_options
    opts = get_voice_options()
    assert isinstance(opts, list)
    assert len(opts) >= 5
    assert any(v["id"] == "af_heart" for v in opts)
