# Fix-the-lies plan — kill-or-wire before repaint (2026-07-03)

Order: lowest-risk → highest (see 00-SYNTHESIS §H). Each item: the fix + audit source.
Status: ⬜ todo · 🔧 in progress · ✅ done (verified) · ✂️ cut (removed honestly).

## Pass 1 — dead controls in the core chat loop  [01]
- ✅ **Plan-first** toggle → `send()` reads `#plan-mode-toggle` → `payload.plan_mode` (verified: payload=true).
- ✅ **Think-harder** → `send()` reads `#reasoning-effort` → `payload.reasoning_effort='high'` (verified).
- ✅ **Working-notes draft** → cleared after capture (+localStorage) (verified: cleared, still sent this turn).
- ✅ **Prompt-history ↑** → now `/history`, mapping `{prompts:[{prompt}]}` → strings (endpoint+shape fixed).
- ✅ **Context-usage bar** → SSE `ctx_pct` → `#ctx-bar-fill` width + label + green/amber/red + hint
  (verified: mocked SSE ctx_pct:72 → width 72%, "Ctx: 72%").
- ✅ **Pipeline-clarify** → renders the server's `questions` into the panel + shows it, both SSE-done
  and JSON paths (verified: mocked pipeline_needs_input → panel visible with "1. …\n2. …").
- ✂️➡️ **Compact conv-scoping** → DEFERRED: server compacts one global `shared_state` buffer
  (`session.py:35` `sync_compact_history()` takes no id). Needs a conversation-aware history model —
  fold into the duplication cleanup (00-SYNTHESIS §D), not a half-fix now.
- ✂️➡️ **Rail "Load more"** → DEFERRED: server default `limit=200` already returns plenty; true
  pagination needs an `offset` param + DB support. Low impact; revisit if a user hits the cap.

## Pass 2 — broken endpoints (404s)  [03][06]
- ✅ **Checkpoints panel** → `/memory/file_checkpoints` (verified: GET /memory/file_checkpoints).
- ✅ **Update-check** → `/update/check` + read `latest_version` (verified: GET /update/check).
- ✅ **Potato preset** → POST `/settings/preset` body `{"preset":"potato"}` (verified: correct URL+body).
- ⬜ **Save appearance & lite** → DEFER: reads nonexistent `#app-font-size`/`#app-anim-level` +
  posts non-schema `ui_font_size`/`ui_animation_level`. Needs real appearance controls wired to
  `/settings/appearance` (a small feature, not a one-line fix). Fold into the settings redesign.

## Pass 3 — wedge + silent-correctness bugs  [03]
- ✂️➡️ **Potato + semantic memory** → RECLASSIFIED (not a simple bug): `use_chroma=False` on potato is
  a *defensible* tradeoff — embeddings cost CPU/RAM the target hardware lacks. The real fix is CHEAP
  embeddings (FastEmbed/model2vec, Phase 4) so potato can afford semantic memory. Keep the flag until then.
- ✅ **Growth velocity** → normalize the server `{week:count}` dict → array (verified: 10 bars render).
- ✅ **Growth watcher** → map real fields `watch_dirs[]`/`files_ingested`/`files_skipped` (verified:
  "● Running · 2 folders watched · 12 ingested · 2 skipped").
- ✅ **`min_adjusted_confidence`** → wired as a floor in `retrieve_relevant_memory` (services/retrieval),
  reading the config key nothing previously read; default 0.0 keeps behavior unchanged (py_compile OK).

## Pass 4 — voice sliders (dead)  [02][05]
- ✅ **Speed slider** → `speakText` sends `speed`; `/voice/speak` honors it over the aspect default
  (verified: body `speed:1.5`).
- ✅ **TTS volume** → `speakText` routes audio through a GainNode reading the 0..1 volume (was wired
  straight to destination). Client-only; audio-output not testable on the static preview.
- ✂️➡️ **Character-Lab pitch/warmth/formality** → DEFER: kokoro-onnx TTS has no pitch/warmth/formality
  params, so these can't drive TTS. Remove or repurpose them in the Character-Lab rework (repaint).

## Pass 5 — surface the flagship (backend-without-UI)  [03][04]
- ✅ **Verify / learn loop** → a working review flow in the Growth panel: "Review pending facts →"
  steps through `/verify/next` with True / Not-true → `/verify/answer`, refreshing stats. Verified end
  to end (open → fact shown → confirm → answer `{fact_id,confirmed:true}` → next → "all caught up").
  Minimal by design; the repaint gives it a fuller home.
- ⏸️ **Autonomous toggle** → HELD for your call. `autonomous_mode` isn't merely missing from the
  schema — it's **force-reset to False at startup** (runtime_safety.py:737) as a SAFETY gate. Enabling a
  bounded autonomous agent loop is a product/safety decision, not a fix to make silently. Surfaced, not flipped.
- ⬜ (later) missions / spawn-agents surfacing — repaint scope.

## Deferred to the repaint (G2–G6), tracked so they're not lost
- Collapse duplications: one aspect model, one onboarding, one governor, one deliberation, one skill registry, one plan store. [00-SYNTHESIS §D]
- Legible safety surface (bypass/approvals/safe-mode/governor). [00-SYNTHESIS §G5]
- Image→vision composer path; missions board; diagnostics surfacing. [01][04][06]
