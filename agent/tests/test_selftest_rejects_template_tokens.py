"""scripts/selftest.py's inference check must not pass a reply made of raw chat-template tokens.
The GPU setup's self-test printed "[ OK ] inference turn - model replied: ".<|end|><|start|>userWhat is the best"."""
import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("layla_selftest", ROOT / "scripts" / "selftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, monkeypatch, stdout):
    marks = []
    monkeypatch.setattr(mod, "_ok", lambda n, d="": marks.append(("ok", d)))
    monkeypatch.setattr(mod, "_warn", lambda n, d="": marks.append(("warn", d)))
    monkeypatch.setattr(mod, "_fail", lambda n, d="": marks.append(("fail", d)))
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=stdout, stderr=""))
    mod.check_inference(ROOT / "README.md")
    assert len(marks) == 1, f"PROBE BROKEN: {marks}"
    return marks[0][0]


def test_template_tokens_fail(monkeypatch):
    mod = _load()
    assert _run(mod, monkeypatch, "PROBE_OK:.<|end|><|start|>userWhat is the best\n") == "fail"


def test_a_real_reply_passes(monkeypatch):
    mod = _load()
    assert _run(mod, monkeypatch, "PROBE_OK:ok\n") == "ok"
