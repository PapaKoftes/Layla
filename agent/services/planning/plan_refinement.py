"""Optional single-pass refinement for file-plan step outputs (bounded cost)."""
from __future__ import annotations


def refine_output_text(text: str, *, max_tokens: int = 256) -> str:
    """
    One LLM pass: tighten / fix the assistant text. Returns original on any failure.
    """
    t = (text or "").strip()
    if len(t) < 20:
        return text or ""
    try:
        import runtime_safety
        from services.llm_gateway import run_completion

        cfg = runtime_safety.load_config()
        if not cfg.get("file_plan_refinement_enabled", False):
            return text
        prompt = (
            "Improve the following assistant reply for clarity and correctness. "
            "Keep the same meaning; be concise. Output only the improved text, no preamble.\n\n"
            + t[:8000]
        )
        out = run_completion(prompt, max_tokens=max(64, min(512, int(max_tokens))), temperature=0.2, stream=False)
        if not isinstance(out, dict):
            return text
        msg = (out.get("choices") or [{}])[0].get("message") or {}
        improved = (msg.get("content") or "").strip()
        if not improved or len(improved) < 5:
            return text
        return improved
    except Exception:
        return text
