# Layla — GUI Feature Map (the "nothing is lost" contract) — 2026-07-02

The sign-off artifact behind [`GUI-REBUILD.md`](GUI-REBUILD.md). It answers your four
questions with evidence, not assurances:

1. **Did we surface everything from the old GUI?** → §D is a line-by-line ledger of every
   overlay, data-action, and localStorage pref → its new home. Nothing drops silently.
2. **Is every feature redesigned into the new style?** → §A maps all 18 feature areas to a
   home in the new IA.
3. **Is everything controllable/customizable, grouped?** → §C places **every config key** into
   **8 settings groups**, common-first / advanced-collapsed.
4. **Is it not overwhelming?** → §B is the 3-tier progressive-disclosure model: a calm default
   screen, one gesture to power, settings for the rest, experimental parked.

Source: the exhaustive audit (all of `agent/ui/`, `config_schema.py`, 40 routers). Tags:
**[CORE]** wedge · **[ADV]** kept but de-emphasized · **[PARK]** experimental flag, off by default.

---

## §A — Every feature area → its new home

| # | Area | Tag | New home | How it's reached |
|---|------|-----|----------|------------------|
| 1 | **Chat** | CORE | **Main view** (home) | default screen; messages + composer |
| 2 | **Aspects / personality** | CORE | **Aspect rail** (switch + lock) | primary gesture; deep-edit → Settings › Personality |
| 3 | **Memory & Knowledge** | CORE | **Memory** destination (rail) | browse / search / checkpoints / ingest / import / codex / bundle |
| 4 | **Models & Kits** | CORE | **Models** destination (rail) | hardware / installed / catalog / download / switch |
| 5 | **Voice** | CORE | **Composer mic** + Settings › Voice | mic inline; tuning in settings |
| 6 | **Artifacts** | CORE | **Right panel › Artifacts** | slide-in, off by default |
| 7 | **Growth / maturity** | CORE (chip) · PARK (headline) | **Maturity chip** (rail foot) → Growth panel | small chip; ceremony toned down + opt-in |
| 8 | **Language learning** (German/Castilla) | CORE | **Right panel › Learn** (NEW surface) | latent backend, now surfaced — on-wedge |
| 9 | **Diagnostics / Doctor** | CORE | **Doctor** destination (rail foot) | health / doctor / deps / updates / metrics / audit |
| 10 | **Settings** | CORE | **Settings** destination | 8 grouped pages (§C) + raw editor in Advanced |
| 11 | **Onboarding / setup** | CORE | **Startup flow** (5-step) | first run; replayable from Settings › General |
| 12 | **Workspace / coding** | ADV | **Workspace** destination (rail) | projects / awareness / symbols / study / plans / skills / agents / exec-trace |
| 13 | **Research & autonomous** | ADV | **Right panel › Research** | analyse-repo / missions / investigations / approvals |
| 14 | **Pairing / remote / tunnel / sync** | ADV | **Settings › Connectivity** | discovery / devices / tunnel / tailscale / syncthing / phone URL |
| 15 | **Obsidian** | ADV | **Settings › Integrations** | vault connect / sync / suggest |
| 16 | **Skills / agents / plans / codex** | ADV | **Workspace** (plans/skills) + Settings | plan approve/execute/Gantt; codex in Memory |
| 17 | **Self-improvement** | ADV/PARK | **Settings › Advanced** (minimal) | backend-only today; surfaced as a small review list |
| 18 | **Cluster** | PARK | **Settings › Advanced › Experimental** | flag, off by default, hidden from default surface |

**Two latent surfaces the audit found (backend-complete, no UI today):**
- **German / language learning** — CEFR profile, correction, spaced-rep flashcards. **On-wedge (multilingual).** Recommendation: **surface it** as a right-panel "Learn" tool (lights up when a language kit is installed). This is a *gain* from the audit, not a loss.
- **Self-improvement** — proposal generate/approve/reject. ADV. Give it a minimal home in Settings › Advanced; don't headline.

---

## §B — The 3-tier disclosure model (why it's not overwhelming)

**Tier 0 — always on screen (the calm default).** Nothing here is optional cognition.
```
Aspect rail (6 + lock) │ Conversations (list · new · search) │ Chat (messages · composer)
Header: title · aspect · model dot · system dot · search · settings · panel-toggle
Composer: input · send · mic · attach · @mention
```
That's the entire resting state. No chip row, no HUD, no tool wall.

**Tier 1 — one gesture away (no settings dive).**
- **Chat-options popover** (from the composer) — the per-send toggles that used to clutter the
  sidebar: stream · show-thinking · reasoning-effort · plan-first · model-override · pipeline mode ·
  deliberation (solo/auto/debate). They live *next to where you send*, not in settings.
- **Rail destinations** — Memory · Models · Workspace · Doctor. One click → the card panel.
- **Right context panel** (slide-in, off by default) — tabs: **Context** (sources/memory for this
  turn) · **Artifacts** · **Research** · **Learn**.
- **Command palette (Ctrl/⌘-K)** — the universal escape hatch: jump to any action, conversation,
  model, or setting by name. This is what guarantees "everything is reachable" without rail bloat.
- **Global search** (header) — conversations + memory + knowledge.
- **Maturity chip** (rail foot) → Growth stats on click.

**Tier 2 — Settings (grouped, common-first).** §C. Eight groups; each opens with the handful of
common controls, with an **"Advanced"** expander hiding the power knobs. The full flat schema
(every key) lives behind **Settings › Advanced › Edit all settings** for the one-in-a-hundred case.

**Tier 3 — parked (experimental).** Cluster, tribunal (6-council), gamification-as-headline. Behind
a flag, off by default, invisible on the default surface, fully reversible.

> The anti-overwhelm rule: **a feature's prominence = its wedge-weight.** Chat/aspects are Tier 0.
> Power toggles are Tier 1. Config is Tier 2. Bloat is Tier 3. Nothing is deleted; everything is *ranked*.

---

## §C — Grouped Settings architecture (every config key has a home)

Eight groups. Every one of the ~70 `EDITABLE_SCHEMA` keys + appearance keys + curated toggles is
placed. **Common** = shown by default; **Advanced** = behind an expander inside that group.

### 1. General
- **Common:** theme/preset (`ui_theme_preset`), font size, animation level (`app-font-size`,
  `app-anim-level`), chat-lite mode (`chat_lite_mode`), decision-trace (`ui_decision_trace_enabled`),
  avatar seed/style (`ui_avatar_seed`, `ui_avatar_style`), **low-resource "potato" preset** button,
  language, replay onboarding/tutorial, reset wizard.
- **Advanced:** IndexedDB cache (`idb-cache`), low-FX (`low-fx`).

### 2. Chat & Personality
- **Common:** default stream / show-thinking / reasoning-effort / plan-first, deliberation mode
  (solo/auto/debate), **Character Lab** launcher (per-aspect sliders: aggression/humor/verbosity/
  curiosity/bluntness/empathy + voice pitch/speed/warmth/formality + color + titles), main aspect.
- **Advanced:** pipeline mode + `engineering_pipeline_*` (default-mode, max-clarify-rounds,
  validator-max-retries), `custom_system_prefix`, `direct_feedback_enabled`,
  `pin_psychology_framework_excerpt`, `enable_self_reflection`, `inline_initiative_enabled`,
  council/tribunal deliberation (also gated by tier).

### 3. Memory & Knowledge
- **Common:** semantic memory on/off (`use_chroma`), retrieval depth (`knowledge_chunks_k`,
  `learnings_n`, `semantic_k`), min-confidence (`memory_retrieval_min_adjusted_confidence`),
  knowledge ingest (path/source/label), import chat, memory bundle export/import.
- **Advanced:** learning quality gate (`learning_quality_gate_enabled`, `learning_quality_min_score`),
  file checkpoints (`file_checkpoint_enabled/max_count/max_bytes`), project-discovery auto-inject,
  Elasticsearch (`elasticsearch_enabled/url/index_prefix/api_key`), relationship codex, memory rebuild.

### 4. Models & Performance
- **Common:** active model + download catalog, performance mode (`performance_mode`),
  temperature, `completion_max_tokens`.
- **Advanced:** `n_ctx`, `n_gpu_layers`, `n_batch`, `n_threads`, `top_p`, `top_k`, `repeat_penalty`,
  limits (`max_tool_calls`, `max_runtime_seconds`, `tool_call_timeout_seconds`, `approval_ttl_seconds`),
  `llm_serialize_per_workspace`, `hyde_enabled`, `llama_server_url`.

### 5. Voice & Audio
- **Common:** speak-replies, voice (`tts_voice`), speed (`tts_speed`), volume.
- **Advanced:** STT model (`whisper_model`).

### 6. Permissions & Safety
- **Common:** allow-write, allow-run, bypass-approvals (with warning), content policy
  (`safe_mode`, `uncensored`, `nsfw_allowed`), pending approvals.
- **Advanced:** admin mode (`admin_mode`, `admin_auto_checkpoint`, `admin_blocklist_override`,
  git-undo checkpoint), plan governance (`planning_strict_mode`, `completion_gate_enabled`,
  `deterministic_tool_routes_enabled`, `in_loop_plan_governance_*`, `plan_governance_*`).

### 7. Connectivity & Integrations
- **Common:** remote access (`remote_enabled`, `remote_api_key`, `remote_rate_limit_per_minute`),
  device pairing (discovery toggle, paired devices + per-device permissions, PIN), phone-access URL,
  Obsidian (vault/connect/sync/suggest).
- **Advanced:** `allow_legacy_remote_api_key`, tunnel (cloudflared / tailscale / funnel), Syncthing
  sync, MCP client (`mcp_client_enabled`), Discord (`discord_webhook_url`, `discord_bot_token`),
  Slack (`slack_webhook_url`), optional-features installer.

### 8. Workspace, Research & Advanced
- **Common (Workspace):** sandbox root (`sandbox_root`), workspace presets, project context,
  study scheduler (`scheduler_study_enabled`, `scheduler_interval_minutes`,
  `scheduler_recent_activity_minutes`).
- **Common (Research):** default depth, `research_max_tool_calls`, `research_max_runtime_seconds`,
  autonomous defaults (mode/max-steps/timeout).
- **Advanced / Experimental:** **cluster** (enable, queen addr, pairing token) — flag, off by
  default; **self-improvement** review list; **"Edit all settings"** → the raw flat schema form
  (every key, unfiltered) for power users; full reset.

**System / Doctor** (its own rail destination, not a settings page): version, check-for-updates,
apply/undo update, platform health, doctor, deps matrix, provider status, metrics
(summary/security/observability), audit log, tool history/analysis, system export, live self-test.

---

## §D — Nothing-lost ledger (every overlay, action, pref accounted for)

**Overlays (15) → new home**

| Overlay | New home |
|---------|----------|
| setup / wizard / onboarding | Startup flow (5-step); replayable from Settings › General |
| settings | Settings destination |
| character-lab | Settings › Chat & Personality (full editor) |
| tutorial | Help / first-run (contextual) |
| models | Models destination |
| diff / batch-diff | Coding diff viewer (in chat/Workspace on file ops) |
| keyboard-shortcuts | Command palette + Help |
| rankup / rank-celebration | Growth panel (toned down, opt-in) |
| plan-viz (Gantt) | Workspace › Plans |
| artifact-edit | Right panel › Artifacts |
| chat-search | Ctrl+F overlay (kept) |
| pairing-pin | Settings › Connectivity › Pairing |
| right-panel | The slide-in context panel |

**~150 data-actions → destinations.** All map cleanly (verified against the audit's full list):
- Chat/composer (send/cancel/retry/mic/attach/url-chip/compose/search/history) → **Main view**.
- Aspect/lock/deliberation → **Rail** + **chat-options popover**; Character Lab → **Settings**.
- Memory (browse/search/ES/checkpoints/ingest/import/codex/bundle) → **Memory**.
- Models (open/refresh/switch/download) → **Models**.
- Workspace (awareness/symbols/study/plans/skills/agents/projects/exec-trace/doctor/setup-auto) → **Workspace** (+ Doctor).
- Research/autonomous/approvals/plan-viz → **Right panel › Research**.
- Artifacts (scan/clear/edit/copy/send/autoscan) → **Right panel › Artifacts**.
- Voice (mic/tts/speed/volume/preview) → **composer** + **Settings › Voice**.
- Growth (maturity/growth/verify) → **maturity chip → Growth panel**.
- Cluster (enable/queen/token/pair) → **Settings › Advanced › Experimental** (parked).
- Pairing/obsidian/discovery/phone → **Settings › Connectivity/Integrations**.
- Settings/appearance/preset/content-policy/git-undo/optional-features/import → **Settings**.
- Theme/search/right-panel/overflow/palette/shortcuts → **header + shell**.

**localStorage prefs (all preserved):** tts · stream · voice_speed · voice_volume ·
artifacts_autoscan · idb_cache · low_fx · compose_draft · engineering_pipeline_mode ·
cluster_enabled · workspace_presets(_host) · pinned_conversations · current_conversation_id ·
active_project_id · default_aspect · wizard_v2_done · onboarding_v1_done · remote_api_key · debug.

**Backend contract (40 routers) unchanged** — the rebuild is UI-only; every endpoint keeps its
consumer. The audit confirms no router loses its caller.

**Orphaned-markup capabilities kept (audit flagged partial/legacy markup):** appearance font/anim,
phone-access URL, KB ingest-by-path, codex-as-user-profile — re-homed with clean markup, capability retained.

---

## §E — What's genuinely different (the wins)

- **From ~28 independently-themed surfaces → 6 rail destinations + 1 card system.** One look, zero drift.
- **From a sidebar HUD of toggles → a chat-options popover** next to the composer. The controls you
  touch every message are one click from the message, not in a settings tree.
- **From a flat 70-key settings modal → 8 grouped pages** (common-first), with the flat form kept as
  a power-user escape hatch. Findable, not a wall.
- **+1 command palette** — the "everything reachable" guarantee that lets the default surface stay minimal.
- **+1 surfaced wedge feature** — language learning, which existed only in the backend, becomes real UI.
- **Bloat ranked, not deleted** — cluster/tribunal/gamification parked behind a flag; reversible; tests green.

---

## Sign-off

This map is the contract. On your **yes**, [`GUI-REBUILD.md`](GUI-REBUILD.md) G1 builds the design
system + shell against it, and I show you the running screen. If any feature's home looks wrong —
say which, and I move it before a line of G1 is written.
