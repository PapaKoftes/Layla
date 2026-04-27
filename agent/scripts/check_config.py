"""
check_config.py — Validate runtime_config.json for known bad values and structural issues.

Checks:
  - Duplicate JSON keys (Python's json module silently picks last; causes confusion)
  - Known dangerous defaults that have caused production bugs
  - Type mismatches (e.g. n_ctx should be int, not string)
  - n_ctx too small for typical Layla system prompts (< 2048)
  - speculative_decoding_enabled + scores mismatch (llama-cpp <=0.3.16 bug)
  - completion_gate_enabled=true (retry injections leak into responses)
  - Flash attention on systems where it causes crashes

Usage:
    python scripts/check_config.py [path/to/runtime_config.json]
    echo $?   # 0 = clean, 1 = issues found
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Duplicate key detector — stdlib json doesn't catch these
# ---------------------------------------------------------------------------

def find_duplicate_keys(text: str) -> list[tuple[str, int]]:
    """Return list of (key, count) for any key appearing more than once at any depth."""
    from collections import Counter
    import re
    # Simple regex: extract all "key": pairs (doesn't handle nested context but good enough)
    keys = re.findall(r'"([^"]+)"\s*:', text)
    c = Counter(keys)
    return [(k, n) for k, n in c.items() if n > 1]


def load_with_duplicate_check(path: Path) -> tuple[dict, list[str]]:
    """Load JSON and collect duplicate keys. Returns (config, warnings)."""
    text = path.read_text(encoding="utf-8")
    dupes = find_duplicate_keys(text)
    warnings = []
    for key, count in dupes:
        warnings.append(f"Duplicate key '{key}' appears {count}x — Python json keeps the LAST value; earlier ones silently ignored")
    cfg = json.loads(text)
    return cfg, warnings


# ---------------------------------------------------------------------------
# Config rules
# ---------------------------------------------------------------------------

class ConfigIssue:
    def __init__(self, severity: str, key: str, value, message: str):
        self.severity = severity  # ERROR or WARN
        self.key = key
        self.value = value
        self.message = message

    def __str__(self):
        val_str = repr(self.value) if self.value is not None else "(not set)"
        return f"  [{self.severity}] {self.key} = {val_str}\n    ^ {self.message}"


def check_config(cfg: dict) -> list[ConfigIssue]:
    issues = []

    def err(key, val, msg):
        issues.append(ConfigIssue("ERROR", key, val, msg))

    def warn(key, val, msg):
        issues.append(ConfigIssue("WARN", key, val, msg))

    # --- n_ctx ---
    n_ctx = cfg.get("n_ctx")
    if n_ctx is None:
        warn("n_ctx", None, "Not set; defaults to 4096 in llm_gateway.py. "
             "Layla system prompts are ~1800-2500 tokens; set to at least 4096.")
    elif not isinstance(n_ctx, int):
        err("n_ctx", n_ctx, f"Must be an integer, got {type(n_ctx).__name__}")
    elif n_ctx < 2048:
        err("n_ctx", n_ctx,
            "Too small — Layla system prompts alone can exceed 2048 tokens. "
            "Every request will crash with a broadcast ValueError. Set to 4096 minimum.")
    elif n_ctx < 4096:
        warn("n_ctx", n_ctx,
             "Low — system prompt + context can exceed this. Recommend 4096+.")

    # --- speculative_decoding_enabled ---
    spec = cfg.get("speculative_decoding_enabled")
    if spec is True:
        # Check if there's a guard in llm_gateway.py
        gw_path = Path(__file__).resolve().parent.parent / "services" / "llm_gateway.py"
        has_guard = False
        if gw_path.exists():
            src = gw_path.read_text(encoding="utf-8", errors="replace")
            has_guard = "_logits_all" in src and "scores" in src and "ndarray" in src
        if not has_guard:
            err("speculative_decoding_enabled", spec,
                "llama-cpp-python <=0.3.16: draft_model forces _logits_all=True but allocates scores "
                "as (n_batch, vocab) not (n_ctx, vocab). Every prompt > n_batch tokens crashes. "
                "Set to false OR ensure llm_gateway.py has the post-load scores resize guard.")
        else:
            warn("speculative_decoding_enabled", spec,
                 "Enabled. Post-init scores resize guard detected in llm_gateway.py — "
                 "should be safe, but test thoroughly on your llama-cpp version.")

    # --- completion_gate_enabled ---
    gate = cfg.get("completion_gate_enabled")
    if gate is True:
        err("completion_gate_enabled", gate,
            "When True, retry injection text ([System: Your last response...]) appends to the goal. "
            "If the model echoes it back, it appears verbatim in the user reply. "
            "Requires strip_junk_from_reply to clean it. Keep False unless output_quality.py is tuned.")

    # --- temperature ---
    temp = cfg.get("temperature")
    if temp is not None:
        if not isinstance(temp, (int, float)):
            err("temperature", temp, f"Must be float, got {type(temp).__name__}")
        elif temp > 1.5:
            warn("temperature", temp, "Very high temperature — responses will be incoherent. Typical: 0.1–0.7")
        elif temp == 0.0:
            warn("temperature", temp, "Zero temperature = greedy decoding. Fine for deterministic tasks, "
                 "poor for conversational quality.")

    # --- max_tokens / completion_max_tokens ---
    for key in ("completion_max_tokens", "max_tokens"):
        val = cfg.get(key)
        if val is not None and isinstance(val, int) and val < 64:
            warn(key, val, f"Very low max tokens ({val}) — responses will be truncated. Recommend 256+.")

    # --- n_batch ---
    n_batch = cfg.get("n_batch")
    if n_batch is not None and isinstance(n_batch, int) and n_batch > 2048:
        warn("n_batch", n_batch, "Unusually large batch size; may cause OOM on low-VRAM systems.")

    # --- flash_attn ---
    flash = cfg.get("flash_attn")
    if flash is True:
        warn("flash_attn", flash,
             "Flash attention requires CUDA/Metal. On CPU-only systems this silently falls back "
             "or may crash. Verify your build supports it.")

    # --- type_k / type_v (KV quantization) ---
    for key in ("type_k", "type_v"):
        val = cfg.get(key)
        if val is not None and isinstance(val, int) and val not in (0, 1, 2, 6, 7, 8):
            warn(key, val, f"Unusual GGML type value {val}. Common: 0=float32, 1=float16, 8=Q8_0. "
                 "Wrong value may crash or produce garbage.")

    # --- model_filename ---
    model = cfg.get("model_filename")
    if model:
        # Check if file exists relative to expected models dir
        model_path = Path(__file__).resolve().parent.parent / "models" / model
        if not model_path.exists():
            warn("model_filename", model,
                 f"Model file not found at models/{model}. "
                 "Server will fail to load at startup.")

    # --- stop_sequences override ---
    stop = cfg.get("stop_sequences")
    if isinstance(stop, list):
        has_section_stop = any("## " in s for s in stop)
        if not has_section_stop:
            warn("stop_sequences", stop,
                 "Custom stop_sequences override doesn't include '\\n## '. "
                 "Small models echo system prompt section headers (## CONTEXT, ## TASK). "
                 "Default get_stop_sequences() in llm_gateway.py handles this — "
                 "only a problem if you're overriding via config.")

    # --- max_tool_calls ---
    mtc = cfg.get("max_tool_calls")
    if mtc is not None and isinstance(mtc, int) and mtc > 20:
        warn("max_tool_calls", mtc,
             "High max_tool_calls can cause runaway tool loops. "
             "tool_loop_detection_enabled should be true if this is above 10.")

    # --- sandbox_root ---
    sandbox = cfg.get("sandbox_root")
    if sandbox:
        p = Path(sandbox)
        if not p.exists():
            warn("sandbox_root", sandbox, "Sandbox root directory does not exist. "
                 "File tools will fail permission checks.")

    return issues


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(config_path: Path):
    print("=" * 60)
    print("Layla Config Health Check")
    print(f"  {config_path}")
    print("=" * 60)

    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}")
        sys.exit(1)

    all_issues: list[str] = []
    error_count = 0

    # Duplicate key check
    try:
        cfg, dupe_warns = load_with_duplicate_check(config_path)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON — {e}")
        sys.exit(1)

    for w in dupe_warns:
        all_issues.append(f"  [ERROR] {w}")
        error_count += 1

    # Value checks
    value_issues = check_config(cfg)
    for iss in value_issues:
        all_issues.append(str(iss))
        if iss.severity == "ERROR":
            error_count += 1

    if all_issues:
        for line in all_issues:
            print(line)
        print()
        print(f"{'ERRORS' if error_count else 'WARNINGS'}: {len(all_issues)} issue(s), {error_count} error(s)")
        sys.exit(1 if error_count else 0)
    else:
        print("All checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    default = Path(__file__).resolve().parent.parent / "runtime_config.json"
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    run(path)
