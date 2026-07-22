# Layla

## What This Is

A local-first AI companion and engineering agent that runs entirely on the operator's own hardware —
a local GGUF model via llama-cpp-python, no cloud, no API keys, nothing leaving the machine. She has
two halves that must both be real: a **companion** (persistent memory, six aspects with distinct
voices, knowledge of who you are) and an **engineering agent** (reads and edits your actual code,
runs tools, works in your repo). Built for one operator on a modest Windows box, with the explicit
intent that she can be anchored to a stronger machine or reached remotely when needed.

## Core Value

**She runs on your machine, and she does not lie to you about what she can see.**

Everything else — speed, features, personality — is negotiable. This is not. A local assistant that
invents the contents of your files is worse than no assistant, because the failure is invisible: a
fabrication and a correct answer are the same shape on the wire. Every prioritisation call resolves
toward "is it true?" before "is it impressive?".

## Requirements

### Validated

<!-- Shipped AND proven by live measurement, not by passing tests. -->

- ✓ Local inference with persistent memory across sessions — v1.5.0
- ✓ Six aspects with distinct voices and per-aspect episodic memory — P13-B1
- ✓ Conversation survives past the in-memory window (summaries + timeline + relationship memory) — P13-B2
- ✓ First token ~0.6s on a warm turn (was ~22.6s) — P13-A1
- ✓ She reads real files and answers from their contents — P13-E1/E2 (measured live, 5/6 grounding)
- ✓ When a tool cannot run she says so instead of inventing — P13-E3 *(non-streaming path only — see Active)*

### Active

<!-- Current scope. Hypotheses until shipped AND measured live. -->

- [ ] **Publishable release** — CI green, correct version, an installer that lands a working app
- [ ] **Fresh install works on day one** — a new user's file tools work without hand-editing JSON
- [ ] **The remote pillar** — anchor this box to a stronger machine; reach her from elsewhere
      (clustering offload, multi-device, phone, Discord)
- [ ] **Skill packs** — install a capability and have the agent actually be able to call it
- [ ] **Every advertised capability is real** — nothing claimed in README, UI, or in-chat that
      does not work

### Out of Scope

- **Cloud inference / hosted API** — the entire premise is local. Never add a default that phones home.
- **Distributed inference by model sharding** — ~2x worse decode for a model that already fits.
  Remote execution on a *stronger peer* is in scope; splitting one model across nodes is not.
- **Guaranteeing 3B answer quality** — comprehension errors on long documents are a property of the
  model, not a bug to fix in code. Grounding (did it read the file) is in scope; comprehension is not.
- **In-process Python sandboxing as a security boundary** — impossible on Windows without an OS
  boundary. The approval gate and url_guard are the real controls; the speed-bump is documented as
  non-binding and must never be advertised otherwise.

## Context

- **One operator, one box**: 4 physical cores, ~16GB RAM, no usable GPU. `auto_tune` classifies this
  as the `potato` tier and scales the whole pipeline to it.
- **The model is Qwen2.5-3B-Instruct-Q4_K_M.** It is weak at tool selection, imitates few-shot
  examples literally, and misreads long documents. Design around this rather than wishing it away.
- **The codebase's signature defect** is *"built well and never plugged in"* — callee sets one field,
  caller inspects another; or a complete, correct component has no caller. It has produced: 16 days
  of zero tool executions, 0 conversation summaries ever, all aspect memories filed under one
  hardcoded name, LAN clustering that moved no work, and an SRS algorithm nothing calls.
- **Tests are not evidence of product health here.** 4047 pass and every one mocks the model. A total
  product failure survived the entire suite *and* the product benchmark. Live measurement or it did
  not happen.

## Constraints

- **Tech stack**: Python 3.12, FastAPI, llama-cpp-python, SQLite, vanilla JS UI. No build step.
- **Performance**: CPU-only. Prefill is the floor. Any per-turn cost must be measured, not assumed —
  and measured with *alternating* run order (sequential order once reported +136% where truth was +12.7%).
- **Privacy**: local-first is the product. Any feature that transmits operator data must be
  off by default, explicit, and disclosed.
- **Security**: `sandbox_root` confines file access and this is correct — the defect is only ever the
  *default value*, never the confinement itself.
- **Solo maintainer**: prefer wiring what exists over building new. Prefer one owner over two copies.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Local-first, no cloud fallback | The entire value proposition; a cloud default would void it | ✓ Good |
| Maturity rank is a *mirror*, never a gate | It shows how much she's learned about you — locking features behind it punishes new users | ✓ Good |
| The remote pillar is WIRED, not deleted | Clustering/multi-device/phone/skill-packs/Discord are an unfinished pillar, not dead code | — Pending |
| Remote execution on a stronger peer, not model sharding | The "CUT distributed inference" verdict was about sharding; offloading to a GPU box is a genuine speedup | ✓ Good |
| Every slice ships a working product | No half-wired features. TRUTH BEFORE EXPOSURE — never surface in the UI before the data is real | ✓ Good |
| Concrete few-shot examples stay concrete | Abstracting them into placeholders destroyed tool selection (8 think steps, 0 tools). A weak model imitates; remove the thing to imitate and it stops acting | ✓ Good |
| Verify the probe before the result | Every measurement error in P13 was a broken probe, not broken code. Probes must assert their own preconditions and fail loudly | ✓ Good |
| One owner per rule, never two copies | Two implementations of the shell blocklist drifted; the weaker silently won. Delete the duplicate, do not fix it | ✓ Good |

---
*Last updated: 2026-07-22 after the adversarial release audit (31 surviving findings, 4 blockers) —
drafted by Claude, PENDING OPERATOR REVIEW.*
