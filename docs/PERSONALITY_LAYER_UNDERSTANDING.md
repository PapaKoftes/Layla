# Phase 1 — Understanding Summary (Personality System)

## 1. Where personality is injected today

- **agent_loop.py** `_build_system_head(goal, aspect, workspace_root, sub_goals)` builds the system prompt. It loads:
  - `identity` via `runtime_safety.load_identity()` → [agent/system_identity.txt](agent/system_identity.txt)
  - `personality` from the **active aspect**: `name`, `title`, `role` or `voice` from personalities/*.json, formatted as third-person line; the aspect's `systemPromptAddition` is not injected here to avoid echo—only name/title/role. Fallback: `runtime_safety.load_personality()` → personality.json
- Order in head: core sentence → identity → content policy (if uncensored) → personality → workspace_context → aspect_memories → learnings → semantic → knowledge
- **orchestrator.py** `build_standard_prompt()` / `build_deliberation_prompt()` add the final user turn and "Reply as {name}... If you must refuse, start with [REFUSED: reason]."

## 2. How aspects are selected

- **orchestrator.select_aspect(message, force_aspect)**: If `force_aspect` is set, that aspect is returned. Otherwise, aspects are scored by trigger keyword matches in message; aspect name in message adds +5. Highest score wins; else default (Morrigan). Lilith may use her NSFW register when the message contains an nsfw_triggers keyword (e.g. intimate, nsfw).

## 3. How tone is constructed

- From the chosen aspect: `name`, `title`, `role` (or `voice`) → one line: "{Name}: {Title}; {Role}. Reply as her only." The full `systemPromptAddition` from JSON is not currently injected in _build_system_head to reduce instruction echo; the short role line sets tone. Fallback personality from personality.json can provide longer default text.

## 4. How refusal works

- Aspects may have `will_refuse` or `can_refuse`. After the model generates the reply in the reason path, agent_loop regex-matches `^\s*\[REFUSED:\s*(.+?)\]\s*` at the start of the reply; if matched, sets `state["refused"]` and `state["refusal_reason"]`, strips that block from visible text. Orchestrator prompts explicitly say: "If you must refuse, start with [REFUSED: reason]."

## 5. How prompts are built

- **Tool/decision path**: `_llm_decision()` builds a task-focused prompt (objective, steps, tools, JSON format); no aspect personality there.
- **Reason path**: `head = _build_system_head(...)` then either `build_deliberation_prompt(...)` or `build_standard_prompt(message, aspect, context, head, convo_block)`. Head contains identity + personality line + workspace + memories + knowledge; the standard/deliberation prompt adds "Reply as {name}...", [REFUSED]/[EARNED_TITLE] instructions, context, "User: {message}\n{name}:".

## 6. Where UX state / TTS connects

- **UX states**: agent_loop emits `ux_states` via `_emit_ux()` (thinking, verifying, changing_approach, reframing_objective). main.py includes them in JSON response and in SSE stream as `ux_state` events. UI (index.html) shows badges and updates typing label from these.
- **TTS**: UI-only; "Speak replies" checkbox, `TTS_VOICE_STYLES` per aspect, `speakReply(text, aspectId)` using browser SpeechSynthesis. No server-side TTS.

## 7. What MUST NEVER be modified

- **Approval flow**: require_approval(), _write_pending(), approval_id in responses, main.py /approve endpoint.
- **runtime_safety**: load_config(), require_approval(), is_protected(), sandbox, DANGEROUS_TOOLS, SAFE_TOOLS.
- **Refusal system**: [REFUSED: ...] parsing, will_refuse/can_refuse checks.
- **Sandbox**: inside_sandbox() in tools, sandbox_root.
- **Tool permissions**: allow_write / allow_run gating in agent_loop.
- **Loop mechanics**: depth limit, max_tool_calls, timeout, _llm_decision(), tool dispatch and verification.
