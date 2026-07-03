from __future__ import annotations


def test_output_quality_strips_hedges_and_dedupes():
    from services.infrastructure.output_quality import clean_output

    t = "Sure, here's what I think.\n\nSure, here's what I think.\n\nAs an AI language model, I think this is fine."
    out = clean_output(t, cfg={})
    assert "As an AI" not in out
    # paragraph dedupe should remove identical para
    assert out.count("Sure") <= 1


def test_output_quality_preserves_code_fences():
    from services.infrastructure.output_quality import clean_output

    t = "```python\nprint('hi')\n```"
    assert clean_output(t, cfg={}).strip() == t


def test_output_polish_can_gate_with_cfg():
    from services.infrastructure.output_polish import polish_output

    cfg = {"output_quality_gate_enabled": True}
    out = polish_output("As an AI language model, I think ok.", cfg)
    assert "As an AI" not in out


# --- advertised-vs-effective default: the gate must default ON when the key is absent ---
# (config_schema + runtime_safety DEFAULTS both declare True; the code fallbacks used to
# say False, silently disabling the gate on any partial/bypassed cfg.)


def test_output_polish_gates_by_default_when_key_absent():
    from services.infrastructure.output_polish import polish_output

    # cfg present but WITHOUT the gate key -> must behave as enabled (the DEFAULTS contract).
    out = polish_output("As an AI language model, I think ok.", {"unrelated": 1})
    assert "As an AI" not in out


def test_learning_quality_gate_defaults_on_when_key_absent(monkeypatch):
    import runtime_safety
    from layla.memory import distill

    # Simulate a config lacking the key (load_config bypassed / partial).
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {})
    ok, score = distill.passes_learning_quality_gate("hi")  # <12 chars -> score 0.2
    assert ok is False, "gate must default ON and reject low-quality content"
    assert score < 0.35


def test_learning_quality_gate_allows_quality_content_when_key_absent(monkeypatch):
    import runtime_safety
    from layla.memory import distill

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {})
    good = (
        "The intent router selects tools by task_type and workspace context; "
        "read-only inspection is preferred before writes when risk is high."
    )
    ok, score = distill.passes_learning_quality_gate(good)
    assert ok is True
    assert score >= 0.35

