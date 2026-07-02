# Fix-the-lies plan — kill-or-wire before repaint (2026-07-03)

Order: lowest-risk → highest (see 00-SYNTHESIS §H). Each item: the fix + audit source.
Status: ⬜ todo · 🔧 in progress · ✅ done (verified) · ✂️ cut (removed honestly).

## Pass 1 — dead controls in the core chat loop  [01]
- ✅ **Plan-first** toggle → `send()` reads `#plan-mode-toggle` → `payload.plan_mode` (verified: payload=true).
- ✅ **Think-harder** → `send()` reads `#reasoning-effort` → `payload.reasoning_effort='high'` (verified).
- ✅ **Working-notes draft** → cleared after capture (+localStorage) (verified: cleared, still sent this turn).
- ✅ **Prompt-history ↑** → now `/history`, mapping `{prompts:[{prompt}]}` → strings (endpoint+shape fixed).
- ⬜ **Context-usage bar** → feed `ctx_pct` from the SSE stream into `#ctx-bar-fill` + label. *(next)*
- ⬜ **Pipeline-clarify** → render the server's `questions` into the panel + show it. *(next)*
- ✂️➡️ **Compact conv-scoping** → DEFERRED: server compacts one global `shared_state` buffer
  (`session.py:35` `sync_compact_history()` takes no id). Needs a conversation-aware history model —
  fold into the duplication cleanup (00-SYNTHESIS §D), not a half-fix now.
- ✂️➡️ **Rail "Load more"** → DEFERRED: server default `limit=200` already returns plenty; true
  pagination needs an `offset` param + DB support. Low impact; revisit if a user hits the cap.

## Pass 2 — broken endpoints (404s)  [03][06]
- ⬜ **Checkpoints panel** → `/memory/file_checkpoints` (not `/file_checkpoints`).
- ⬜ **Update-check** → `/update/check` (not `/version/check_update`).
- ⬜ **Potato preset** → POST `/settings/preset` with `{preset:"potato"}` in body (not path).
- ⬜ **Save appearance & lite** → correct DOM ids + real endpoint/keys, or cut if redundant.

## Pass 3 — wedge + silent-correctness bugs  [03]
- ⬜ **Potato preset keeps semantic memory** → stop forcing `use_chroma=False` (fallback exists for low-end).
- ⬜ **`min_adjusted_confidence`** slider → wire it into retrieval, or remove the control.
- ⬜ **Growth velocity + watcher widgets** → fix the dict-vs-array / field-name mismatch.

## Pass 4 — voice sliders (dead)  [02][05]
- ⬜ **Pitch/warmth/formality/speed** → pass to `/voice/speak`, or remove honestly.
- ⬜ **TTS volume** → add a GainNode, or remove the slider.

## Pass 5 — surface the flagship (backend-without-UI)  [03][04]
- ⬜ **Verify / learn loop** → a real UI for `/verify/next` + `/verify/answer` (the "it learns" promise).
- ⬜ **Autonomous toggle** → add `autonomous_mode` to the settings schema so the built loop is reachable.
- ⬜ (later) missions / spawn-agents surfacing — scope after the above land.

## Deferred to the repaint (G2–G6), tracked so they're not lost
- Collapse duplications: one aspect model, one onboarding, one governor, one deliberation, one skill registry, one plan store. [00-SYNTHESIS §D]
- Legible safety surface (bypass/approvals/safe-mode/governor). [00-SYNTHESIS §G5]
- Image→vision composer path; missions board; diagnostics surfacing. [01][04][06]
