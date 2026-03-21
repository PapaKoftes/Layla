"""Session IO limits, corruption, and isolation from execution."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fabrication_assist.assist.errors import InputValidationError, SessionIOError
from fabrication_assist.assist.layla_lite import assist
from fabrication_assist.assist.runner import StubRunner
from fabrication_assist.assist.schemas import MAX_USER_TEXT_CHARS
from fabrication_assist.assist.session import MAX_SESSION_BYTES, load_session
from fabrication_assist.assist.variants import load_knowledge_dir


def test_load_session_corrupt_json_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(SessionIOError) as ei:
        load_session(p)
    assert "invalid" in str(ei.value).lower() or "json" in str(ei.value).lower()


def test_load_session_too_large_raises(tmp_path: Path) -> None:
    p = tmp_path / "huge.json"
    # Single huge string field to exceed byte limit without deep JSON
    big = "x" * (MAX_SESSION_BYTES + 1)
    p.write_text(json.dumps({"history": [], "preferences": {"k": big}}), encoding="utf-8")
    with pytest.raises(SessionIOError) as ei:
        load_session(p)
    assert "large" in str(ei.value).lower() or "too" in str(ei.value).lower()


def test_user_text_over_max_raises() -> None:
    with pytest.raises(InputValidationError):
        assist("x" * (MAX_USER_TEXT_CHARS + 1), runner=StubRunner())


def test_poisoned_session_same_variant_configs(tmp_path: Path) -> None:
    """Preferences / stale variants in session file must not change run_build inputs."""

    class RecordingRunner:
        def __init__(self) -> None:
            self.configs: list[dict] = []

        def run_build(self, config: dict) -> dict:
            self.configs.append(dict(config))
            return StubRunner().run_build(config)

    poison = tmp_path / "poison.json"
    poison.write_text(
        json.dumps(
            {
                "preferences": {"inject": "evil", "units": "mm"},
                "variants": [{"id": "from_disk", "label": "should not be used"}],
                "outcomes": [{"variant_id": "ghost", "score": 999}],
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps({"history": [], "variants": [], "outcomes": [], "preferences": {}}), encoding="utf-8")

    rr1 = RecordingRunner()
    assist("CNC bracket for milling", session_path=poison, runner=rr1)
    rr2 = RecordingRunner()
    assist("CNC bracket for milling", session_path=clean, runner=rr2)

    assert len(rr1.configs) == len(rr2.configs) == 3
    for a, b in zip(rr1.configs, rr2.configs, strict=True):
        assert a == b


def test_assist_stub_fast_enough(tmp_path: Path) -> None:
    p = tmp_path / "perf.json"
    t0 = time.perf_counter()
    assist("bracket", session_path=p, runner=StubRunner())
    assert time.perf_counter() - t0 < 2.0


def test_unicode_user_text_ok(tmp_path: Path) -> None:
    p = tmp_path / "u.json"
    out = assist("café 日本語 \u0000 bracket", session_path=p, runner=StubRunner())
    assert len(out["variants"]) == 3


def test_malformed_yaml_in_knowledge_dir_skipped(tmp_path: Path) -> None:
    kd = tmp_path / "know"
    kd.mkdir()
    (kd / "broken.yaml").write_text("{\n  unclosed: ", encoding="utf-8")
    assert load_knowledge_dir(kd) == {}
