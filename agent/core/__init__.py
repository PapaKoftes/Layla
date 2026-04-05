"""
agent/core — deterministic 6-phase execution pipeline.

Phases:
  observe      → build stable context snapshot
  plan         → single LLM decision per iteration
  approve      → human gate for non-safe tools
  execute      → sandboxed tool call with timeout
  validate     → structural + injection checks on output
  update_state → atomic DB + history writes

Each module is independent and may be imported standalone.
agent_loop.py delegates to these; backward compatibility preserved.
"""
