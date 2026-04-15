from __future__ import annotations


def test_output_quality_strips_hedges_and_dedupes():
    from services.output_quality import clean_output

    t = "Sure, here's what I think.\n\nSure, here's what I think.\n\nAs an AI language model, I think this is fine."
    out = clean_output(t, cfg={})
    assert "As an AI" not in out
    # paragraph dedupe should remove identical para
    assert out.count("Sure") <= 1


def test_output_quality_preserves_code_fences():
    from services.output_quality import clean_output

    t = "```python\nprint('hi')\n```"
    assert clean_output(t, cfg={}).strip() == t


def test_output_polish_can_gate_with_cfg():
    from services.output_polish import polish_output

    cfg = {"output_quality_gate_enabled": True}
    out = polish_output("As an AI language model, I think ok.", cfg)
    assert "As an AI" not in out

