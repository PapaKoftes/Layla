# Phase 2 — Personality Expression Layer: Architecture Proposal

## Scope

- **Prompt-layer only**: no code self-modification, no autonomy, no change to tool/safety/approval/refusal.
- **Foundation**: existing aspect system (orchestrator + personalities/*.json + system_identity.txt).
- **New layer**: guidance style, thinking POV, internal narrative tone—injected only into prompt construction.

## Components

1. **system_identity.txt**  
   Unchanged as the single source of core identity. Optional: a second file (e.g. `personality_expression.txt`) holds the expression block so identity stays minimal and the expression layer can be toggled cleanly.

2. **personalities/*.json**  
   No structural change required. Optional later: add fields such as `core_guidance_mode`, `grounding_mode`, or `pov_reasoning_tags` per aspect if we want aspect-specific expression; for a first version, one global expression block is enough.

3. **Prompt builder (agent_loop._build_system_head)**  
   When feature flag is on, after identity and before/after personality:
   - Load the Personality Expression block (from a dedicated file or a marked section).
   - Append: core_guidance_mode (gentle but firm, organizing partner, forward push), grounding_mode (when to slow down / ground), and optionally pov_reasoning_tags (POV lenses as short cues).
   - Optional: internal thought snippets (e.g. "Consider: Will this hold? Can we make this easier? Is this done properly?") as a single short paragraph so the model can "think" through those lenses without outputting them.

4. **Feature flag**  
   `enable_personality_expression` in runtime_config.json (default false). When false, no expression block is loaded or appended; behaviour is identical to today.

## Data flow

```
load_config() → enable_personality_expression
                     ↓ (if true)
load_identity() + load_personality_expression() → expression_block
                     ↓
_build_system_head() → parts = [core, identity, (expression_block), content_policy?, personality, workspace, memories, learnings, knowledge]
                     ↓
build_standard_prompt() / build_deliberation_prompt()  (unchanged)
```

## Backwards compatibility

- Flag off: no new file read, no new text in prompt; existing behaviour preserved.
- No changes to orchestrator, refusal parsing, tool gating, approval flow, or loop mechanics.

## What is NOT in scope

- Changing how aspects are selected.
- Changing refusal format or logic.
- Any new tools or MCP behaviour.
- Any logic that runs outside prompt construction.
