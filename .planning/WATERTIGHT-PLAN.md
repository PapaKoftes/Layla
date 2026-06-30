# End-to-End Review → Watertight Installable Product

**Date:** 2026-06-30 · After the GSD codebase re-map (united + Castilla v1.4.0). Source of truth: `.planning/codebase/`. This is the *common-sense* path to a watertight, installable product with the Warframe-mystic GUI — **only what's necessary, nothing speculative.**

## State of the product (honest)
- **Solid:** trust-boundary security (REQ-10/11/12), copyleft guard, agent-loop decomposed (910 lines), 19-package services, ES-module UI, compiler-free install + hardware→kit recommender, dynamic ResourceGovernor wired into inference, Castilla Spanish (proven ~9 tok/s), **2143 tests green**, one-command installers.
- **Not yet watertight:** the *real* inference path isn't gated in CI; the GUI aesthetic + full control surface isn't applied to the (now-modular) UI; a couple of low-end traps.

## Do now (the only things that gate "watertight + installable + GUI")

### 1. Watertight gate — wire the real-inference CI smoke  *(HIGH; small)*
The seam exists (`LAYLA_TEST_REAL_LLM` in `conftest.py`) but **no CI job sets it**, so "a fresh install can load a model and complete a turn" is never verified automatically. Add a CI job (or scheduled) that downloads a tiny GGUF, sets `LAYLA_TEST_REAL_LLM=1`, runs a one-turn smoke + the benchmark. This is the single thing that makes the product *provably* installable-and-working on every change.

### 2. The GUI — **expand the existing modular UI** (do NOT rebuild) *(MEDIUM; the main build)*
The refactor already turned `agent/ui/` into ES modules (`core/` bus/state/actions + ~28 `components/`) with per-aspect re-theming. **Common sense: apply the locked Warframe-mystic aesthetic and a full see/control surface to *that*, not a from-scratch React `ui-next/`.** (This supersedes the earlier `ui-next` React idea — rebuilding modular code that already exists would be the "stupid" path.)
Scope = the control surfaces that matter, themed:
- **Shell + theme tokens** (near-black `#0a0008`, magenta `#c0006a`, per-aspect colors, `--wf-cut` panels, glyph/sigil SVGs) across the components.
- **See/control everything that's real:** chat (streaming, tools, diff) · **aspect switcher + creator** (the personalities) · **model/kit manager** (browse catalog, download, switch — `recommend_kit` already backs this) · **ResourceGovernor status + mode** (it exposes `to_dict()`; show WHISPER/BREATHE/SPRINT + let the user pin a cap) · **memory browser** · **settings** (typed) · **remote/connect** status.
- Skip until asked: the BG3 full character-creator and Fallout quiz (nice-to-have, not necessary for "see/control everything").

### 3. Low-end guardrails *(LOW; quick, prevents dumb failures)*
- Gate aspect→model by hardware tier so a low-end box never tries `eris`→11B (encode a `max_tier`/size in the personality/kit selection; today it's unenforced).
- Surface the governor + a "low-end mode" toggle in settings so she can see/control resource use.

## Deliberately deferred (safe debt — NOT now, by common sense)
- **~207 service shims** → incremental migration to canonical `services.<domain>` paths. Safe debt; cleanup, not a blocker.
- **Two config files** (`config.json` vs `runtime_config.json`) → consolidate later; document which is authoritative.
- Remaining god-modules (`vector_store`, `migrations`, `tool_dispatch`, MCP server), redundant inference backends audit, deprecated `remote_api_key` removal, root-entrypoint sprawl.
- Horizontal/multi-process inference (inherent single-process ceiling — out of scope).

## Definition of "watertight + installable" (acceptance)
1. `git clone` → `install\castilla.ps1` → working Spanish coding companion on a fresh 16GB/CPU box. *(installers built; need the CI smoke to keep it true)*
2. CI is green **including** a real one-turn inference smoke + benchmark. *(item 1 above)*
3. The GUI, in the Warframe-mystic style, lets her **see and control** chat, aspects, models/kits, resource governor, memory, and settings. *(item 2 above)*
4. No low-end footguns (no oversized model auto-selected; governor on by default). *(item 3 above)*
